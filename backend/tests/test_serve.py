"""Container entrypoint (backend/serve.py) and the DATA_DIR / weights settings
it relies on (HARDENING_PLAN.md R1).

Nothing here needs root or the network: privilege and ownership calls are
patched, and the weights download is a mock.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from backend import serve
from backend.core.config import Settings, settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cfg(**overrides) -> Settings:
    return Settings(
        _env_file=None, DATABASE_URL="sqlite://", JWT_SECRET_KEY="x" * 40, **overrides
    )


# --- Port --------------------------------------------------------------------


@pytest.mark.parametrize(
    "environ, expected",
    [
        ({}, 8000),
        ({"PORT": ""}, 8000),
        ({"PORT": "  "}, 8000),
        ({"PORT": "9001"}, 9001),
    ],
)
def test_resolve_port(environ, expected):
    assert serve.resolve_port(environ) == expected


@pytest.mark.parametrize("bad", ["abc", "80.5", "0", "-1", "65536"])
def test_resolve_port_rejects_bad_values(bad):
    with pytest.raises(ValueError, match="PORT"):
        serve.resolve_port({"PORT": bad})


def test_uvicorn_command_shape():
    command = serve.uvicorn_command(9001)
    # The same interpreter as the entrypoint, never a PATH lookup that could
    # find another environment's uvicorn.
    assert command[:4] == [sys.executable, "-m", "uvicorn", "backend.main:app"]
    assert command[command.index("--port") + 1] == "9001"
    assert command[command.index("--host") + 1] == "0.0.0.0"
    # One process: the semaphore and rate limiter are process-local.
    assert command[command.index("--workers") + 1] == "1"
    assert command.count("--workers") == 1
    assert (
        int(command[command.index("--timeout-graceful-shutdown") + 1])
        == serve.GRACEFUL_SHUTDOWN_SECONDS
    )


def test_app_user_matches_the_dockerfile():
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    assert f"--uid {serve.APP_UID} appuser" in dockerfile
    assert serve.APP_HOME == "/home/appuser"


# --- Storage ownership -------------------------------------------------------


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A DATA_DIR with the three storage directories and some content."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    dirs = [str(tmp_path / n) for n in ("uploads", "outputs", "weights")]
    (tmp_path / "uploads" / "u1").mkdir(parents=True)
    (tmp_path / "uploads" / "u1" / "a.wav").write_bytes(b"x")
    (tmp_path / "outputs").mkdir()
    (tmp_path / "weights").mkdir()
    (tmp_path / "outside.txt").write_text("not ours")
    (tmp_path / "uploads" / "link").symlink_to(tmp_path / "outside.txt")
    return tmp_path, dirs


def test_chown_storage_hands_everything_to_the_app_user(tree):
    root, dirs = tree
    other = os.getuid() + 1  # differs from the owner, so every entry needs a chown
    with patch("backend.serve.os.lchown") as lchown:
        serve.chown_storage(dirs, uid=other, gid=other)
    chowned = {call.args[0] for call in lchown.call_args_list}
    assert str(root) in chowned  # the volume mount point itself
    assert set(dirs) <= chowned
    assert str(root / "uploads" / "u1" / "a.wav") in chowned
    # A symlink is re-owned itself; its target outside storage is left alone.
    assert str(root / "uploads" / "link") in chowned
    assert str(root / "outside.txt") not in chowned
    assert all(call.args[1:] == (other, other) for call in lchown.call_args_list)


def test_chown_storage_is_a_no_op_when_already_owned(tree):
    _, dirs = tree
    with patch("backend.serve.os.lchown") as lchown:
        serve.chown_storage(dirs, uid=os.getuid(), gid=os.getgid())
    lchown.assert_not_called()


def test_chown_storage_creates_missing_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", "")
    dirs = [str(tmp_path / "a" / "b"), str(tmp_path / "c")]
    serve.chown_storage(dirs, uid=os.getuid(), gid=os.getgid())
    assert all(os.path.isdir(d) for d in dirs)


def test_drop_privileges_sets_group_before_user_and_clears_groups(monkeypatch):
    calls = []
    monkeypatch.setattr(serve.os, "setgroups", lambda g: calls.append(("groups", g)))
    monkeypatch.setattr(serve.os, "setgid", lambda g: calls.append(("gid", g)))
    monkeypatch.setattr(serve.os, "setuid", lambda u: calls.append(("uid", u)))
    monkeypatch.setattr(serve.os, "geteuid", lambda: serve.APP_UID)
    monkeypatch.delenv("HOME", raising=False)

    serve.drop_privileges()

    # Group first: once the uid is dropped, changing groups is no longer allowed.
    assert calls == [("groups", []), ("gid", serve.APP_GID), ("uid", serve.APP_UID)]
    assert os.environ["HOME"] == serve.APP_HOME
    monkeypatch.delenv("HOME")
    monkeypatch.delenv("USER", raising=False)


def test_drop_privileges_fails_loudly_if_still_root(monkeypatch):
    monkeypatch.setattr(serve.os, "setgroups", lambda g: None)
    monkeypatch.setattr(serve.os, "setgid", lambda g: None)
    monkeypatch.setattr(serve.os, "setuid", lambda u: None)
    monkeypatch.setattr(serve.os, "geteuid", lambda: 0)
    with pytest.raises(RuntimeError, match="drop root"):
        serve.drop_privileges()


# --- Writability -------------------------------------------------------------


def test_ensure_writable_creates_and_accepts_directories(tmp_path):
    target = tmp_path / "new" / "dir"
    serve.ensure_writable([str(target)])
    assert target.is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_ensure_writable_explains_the_railway_fix(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(PermissionError, match="RAILWAY_RUN_UID=0"):
            serve.ensure_writable([str(locked)])
    finally:
        locked.chmod(0o700)


# --- Weights -----------------------------------------------------------------


def test_weights_are_not_fetched_unless_enabled(monkeypatch):
    monkeypatch.setattr(settings, "FETCH_WEIGHTS_ON_START", False)
    with patch("backend.download_weights.fetch_and_verify_checkpoints") as fetch:
        assert serve.provision_weights() is True
    fetch.assert_not_called()


@pytest.mark.parametrize("ok", [True, False])
def test_weights_are_fetched_into_weights_dir_when_enabled(monkeypatch, ok):
    monkeypatch.setattr(settings, "FETCH_WEIGHTS_ON_START", True)
    with patch(
        "backend.download_weights.fetch_and_verify_checkpoints", return_value=ok
    ) as fetch:
        assert serve.provision_weights() is ok
    fetch.assert_called_once_with(settings.WEIGHTS_DIR)


# --- prepare / main ----------------------------------------------------------


def _recorder(monkeypatch, euid: int) -> list:
    calls: list = []
    monkeypatch.setattr(serve.os, "geteuid", lambda: euid)
    monkeypatch.setattr(serve, "chown_storage", lambda d: calls.append("chown"))
    monkeypatch.setattr(serve, "drop_privileges", lambda: calls.append("drop"))
    monkeypatch.setattr(serve, "ensure_writable", lambda d: calls.append("writable"))
    monkeypatch.setattr(
        serve, "provision_weights", lambda: calls.append("weights") or True
    )
    return calls


def test_prepare_as_root_chowns_then_drops_then_fetches(monkeypatch):
    calls = _recorder(monkeypatch, euid=0)
    serve.prepare(["/x"])
    # Weights must be fetched AFTER the drop so the files belong to the app user.
    assert calls == ["chown", "drop", "writable", "weights"]


def test_prepare_as_app_user_never_touches_ownership(monkeypatch):
    calls = _recorder(monkeypatch, euid=serve.APP_UID)
    serve.prepare(["/x"])
    assert calls == ["writable", "weights"]


def test_prepare_fails_when_weights_cannot_be_provisioned(monkeypatch):
    _recorder(monkeypatch, euid=serve.APP_UID)
    monkeypatch.setattr(serve, "provision_weights", lambda: False)
    with pytest.raises(RuntimeError, match="weights"):
        serve.prepare(["/x"])


def test_main_execs_uvicorn_on_the_platform_port(monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setattr(serve, "prepare", lambda: None)
    with patch("backend.serve.os.execvp") as execvp:
        serve.main([])
    command = serve.uvicorn_command(9001)
    execvp.assert_called_once_with(command[0], command)


def test_main_dry_run_prints_the_command_and_does_not_exec(monkeypatch, capsys):
    monkeypatch.setenv("PORT", "9002")
    monkeypatch.setattr(serve, "prepare", lambda: None)
    with patch("backend.serve.os.execvp") as execvp:
        assert serve.main(["--dry-run"]) == 0
    execvp.assert_not_called()
    assert "--port 9002" in capsys.readouterr().out


def test_main_reports_a_bad_port_without_starting(monkeypatch, caplog):
    monkeypatch.setenv("PORT", "nope")
    prepare = MagicMock()
    monkeypatch.setattr(serve, "prepare", prepare)
    with patch("backend.serve.os.execvp") as execvp:
        assert serve.main([]) == 1
    execvp.assert_not_called()
    prepare.assert_not_called()
    assert "PORT" in caplog.text


def test_main_reports_a_preparation_failure_without_starting(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(
        serve, "prepare", MagicMock(side_effect=PermissionError("not writable"))
    )
    with patch("backend.serve.os.execvp") as execvp:
        assert serve.main([]) == 1
    execvp.assert_not_called()


def test_module_entrypoint_runs_end_to_end(tmp_path):
    """`python -m backend.serve --dry-run` in a clean process: real settings
    import, real directory creation, real argv on stdout."""
    env = {
        **os.environ,
        "PORT": "9123",
        # Explicit per-directory values: hermetic even when a developer's own
        # backend/.env sets UPLOAD_DIR/OUTPUT_DIR (an explicit value beats DATA_DIR).
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "OUTPUT_DIR": str(tmp_path / "outputs"),
        "WEIGHTS_DIR": str(tmp_path / "weights"),
        "DATABASE_URL": "sqlite://",
        "JWT_SECRET_KEY": "x" * 40,
        "FETCH_WEIGHTS_ON_START": "false",
    }
    result = subprocess.run(
        [sys.executable, "-m", "backend.serve", "--dry-run"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--port 9123" in result.stdout
    for name in ("uploads", "outputs", "weights"):
        assert (tmp_path / name).is_dir()


# --- DATA_DIR and FETCH_WEIGHTS_ON_START settings ----------------------------


def test_data_dir_places_all_three_directories_under_it():
    cfg = _cfg(DATA_DIR="/data")
    assert cfg.UPLOAD_DIR == "/data/uploads"
    assert cfg.OUTPUT_DIR == "/data/outputs"
    assert cfg.WEIGHTS_DIR == "/data/weights"


def test_explicit_directory_wins_over_data_dir():
    cfg = _cfg(DATA_DIR="/data", WEIGHTS_DIR="/models")
    assert cfg.WEIGHTS_DIR == "/models"
    assert cfg.UPLOAD_DIR == "/data/uploads"


def test_blank_data_dir_leaves_the_defaults_alone():
    base, cfg = _cfg(), _cfg(DATA_DIR="  ")
    assert (cfg.UPLOAD_DIR, cfg.OUTPUT_DIR, cfg.WEIGHTS_DIR) == (
        base.UPLOAD_DIR,
        base.OUTPUT_DIR,
        base.WEIGHTS_DIR,
    )


def test_relative_data_dir_is_rejected():
    with pytest.raises(ValidationError, match="absolute"):
        _cfg(DATA_DIR="data")


def test_weights_are_not_fetched_by_default():
    assert _cfg().FETCH_WEIGHTS_ON_START is False


# --- Log format --------------------------------------------------------------


def test_entrypoint_log_lines_are_json_like_the_apps():
    handler = serve.json_log_handler()
    record = logging.LogRecord(
        "backend.serve", logging.INFO, __file__, 0, "Starting: %s", ("uvicorn",), None
    )
    payload = json.loads(handler.format(record))
    assert payload["message"] == "Starting: uvicorn"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "backend.serve"
    assert "timestamp" in payload


def test_entrypoint_errors_reach_stderr_as_json():
    """In a clean process: a bad PORT exits 1 and says so as one JSON line."""
    env = {
        **os.environ,
        "PORT": "nope",
        "DATABASE_URL": "sqlite://",
        "JWT_SECRET_KEY": "x" * 40,
    }
    result = subprocess.run(
        [sys.executable, "-m", "backend.serve", "--dry-run"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["level"] == "ERROR"
    assert "PORT" in payload["message"]
