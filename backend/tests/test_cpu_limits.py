"""Tests for cgroup-aware torch thread sizing (HARDENING_PLAN.md P2-L11)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.core.config import Settings
from backend.core.cpu_limits import detect_cpu_limit, resolve_thread_count
from backend.services import tts_pipeline

# ---- helpers: a fake cgroup filesystem ---------------------------------------


def _fs(tmp_path: Path, proc: str, files: dict) -> tuple:
    """Write a fake /proc/self/cgroup and cgroup tree; return (root, proc_path)."""
    # a fresh tree per call, so one test can build several
    root = tmp_path / f"cgroup{len(list(tmp_path.iterdir()))}"
    root.mkdir()
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    proc_file = root.parent / f"{root.name}_proc"
    proc_file.write_text(proc)
    return str(root), str(proc_file)


def _detect(tmp_path: Path, proc: str, files: dict):
    root, proc_file = _fs(tmp_path, proc, files)
    return detect_cpu_limit(root, proc_file)


# ---- cgroup v2 ---------------------------------------------------------------


def test_v2_two_cpu_quota(tmp_path) -> None:
    files = {"a/b.scope/cpu.max": "200000 100000\n"}
    assert _detect(tmp_path, "0::/a/b.scope\n", files) == 2.0


def test_v2_fractional_quota(tmp_path) -> None:
    assert _detect(tmp_path, "0::/x\n", {"x/cpu.max": "150000 100000"}) == 1.5


def test_v2_max_means_unlimited(tmp_path) -> None:
    assert _detect(tmp_path, "0::/x\n", {"x/cpu.max": "max 100000"}) is None


def test_v2_container_root_cgroup(tmp_path) -> None:
    """Inside a container's cgroup namespace the path is "/" and cpu.max is at the root."""
    assert _detect(tmp_path, "0::/\n", {"cpu.max": "400000 100000"}) == 4.0


def test_v2_tightest_limit_among_parents_wins(tmp_path) -> None:
    files = {
        "a/cpu.max": "100000 100000",  # pod-level limit: 1 CPU
        "a/b/cpu.max": "400000 100000",  # container asks for 4
        "a/b/c/cpu.max": "max 100000",
    }
    assert _detect(tmp_path, "0::/a/b/c\n", files) == 1.0


def test_v2_parent_limit_applies_when_child_is_unlimited(tmp_path) -> None:
    files = {"a/cpu.max": "300000 100000", "a/b/cpu.max": "max 100000"}
    assert _detect(tmp_path, "0::/a/b\n", files) == 3.0


# ---- cgroup v1 ---------------------------------------------------------------


def test_v1_quota_and_period(tmp_path) -> None:
    files = {
        "cpu/docker/x/cpu.cfs_quota_us": "200000",
        "cpu/docker/x/cpu.cfs_period_us": "100000",
    }
    assert _detect(tmp_path, "4:cpu,cpuacct:/docker/x\n", files) == 2.0


def test_v1_minus_one_means_unlimited(tmp_path) -> None:
    files = {
        "cpu/cpu.cfs_quota_us": "-1",
        "cpu/cpu.cfs_period_us": "100000",
    }
    assert _detect(tmp_path, "4:cpu:/\n", files) is None


def test_v1_combined_controller_mount_name(tmp_path) -> None:
    files = {
        "cpu,cpuacct/cpu.cfs_quota_us": "100000",
        "cpu,cpuacct/cpu.cfs_period_us": "100000",
    }
    assert _detect(tmp_path, "3:cpu,cpuacct:/\n", files) == 1.0


def test_v1_ignores_other_controllers(tmp_path) -> None:
    files = {"memory/cpu.cfs_quota_us": "100000", "memory/cpu.cfs_period_us": "100000"}
    assert _detect(tmp_path, "5:memory:/\n", files) is None


# ---- robustness --------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "garbage", "abc def", "100000", "0 100000"])
def test_malformed_cpu_max_is_treated_as_unlimited(tmp_path, bad) -> None:
    assert _detect(tmp_path, "0::/x\n", {"x/cpu.max": bad}) is None


def test_missing_files_mean_unlimited(tmp_path) -> None:
    assert _detect(tmp_path, "0::/nowhere\n", {}) is None


def test_missing_proc_file_means_unlimited(tmp_path) -> None:
    root, _ = _fs(tmp_path, "", {})
    assert detect_cpu_limit(root, str(tmp_path / "does-not-exist")) is None


def test_real_host_call_never_raises() -> None:
    """Whatever this machine's cgroup looks like, detection returns a number or None."""
    limit = detect_cpu_limit()
    assert limit is None or limit > 0


# ---- resolve_thread_count ----------------------------------------------------


def _resolve(tmp_path, quota_file: str, cores: int, configured=0, env=None):
    root, proc = _fs(tmp_path, "0::/x\n", {"x/cpu.max": quota_file})
    return resolve_thread_count(
        configured,
        env={} if env is None else env,
        cgroup_root=root,
        proc_cgroup=proc,
        cores=cores,
    )


def test_explicit_setting_wins_over_everything(tmp_path) -> None:
    assert _resolve(tmp_path, "200000 100000", 24, configured=6) == 6
    assert (
        _resolve(
            tmp_path, "200000 100000", 24, configured=6, env={"OMP_NUM_THREADS": "3"}
        )
        == 6
    )


def test_operators_omp_num_threads_is_respected(tmp_path) -> None:
    assert _resolve(tmp_path, "200000 100000", 24, env={"OMP_NUM_THREADS": "8"}) is None


def test_limit_tighter_than_cores_sets_the_thread_count(tmp_path) -> None:
    assert _resolve(tmp_path, "200000 100000", 24) == 2


def test_fractional_limit_rounds_up(tmp_path) -> None:
    assert _resolve(tmp_path, "150000 100000", 24) == 2


def test_sub_one_cpu_limit_still_gets_one_thread(tmp_path) -> None:
    assert _resolve(tmp_path, "50000 100000", 24) == 1


def test_limit_not_tighter_than_cores_changes_nothing(tmp_path) -> None:
    assert _resolve(tmp_path, "800000 100000", 8) is None
    assert _resolve(tmp_path, "1600000 100000", 8) is None


def test_unlimited_changes_nothing(tmp_path) -> None:
    assert _resolve(tmp_path, "max 100000", 24) is None


# ---- wiring into the pipeline and settings -----------------------------------


def test_configure_torch_threads_applies_the_resolved_count() -> None:
    with patch.object(tts_pipeline, "resolve_thread_count", return_value=3), patch(
        "backend.services.tts_pipeline.torch.set_num_threads"
    ) as setter:
        tts_pipeline._configure_torch_threads()
    setter.assert_called_once_with(3)


def test_configure_torch_threads_leaves_torch_alone_when_unresolved() -> None:
    with patch.object(tts_pipeline, "resolve_thread_count", return_value=None), patch(
        "backend.services.tts_pipeline.torch.set_num_threads"
    ) as setter:
        tts_pipeline._configure_torch_threads()
    setter.assert_not_called()


def test_configure_torch_threads_passes_the_setting_through(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(tts_pipeline.settings, "TORCH_NUM_THREADS", 5)
    monkeypatch.setattr(
        tts_pipeline, "resolve_thread_count", lambda configured: seen.append(configured)
    )
    tts_pipeline._configure_torch_threads()
    assert seen == [5]


def test_load_models_configures_threads_before_loading() -> None:
    """The real loader calls it (needs the provisioned checkpoints)."""
    from backend.core.config import settings

    weights = [
        os.path.join(settings.WEIGHTS_DIR, name)
        for name in ("synthesizer.pt", "vocoder.pt")
    ]
    if not all(os.path.exists(path) for path in weights):
        pytest.skip("real checkpoints not provisioned")
    with patch.object(tts_pipeline, "_configure_torch_threads") as configure:
        tts_pipeline.load_models("cpu")
    assert configure.call_count == 1
    tts_pipeline.load_mock_models("cpu")  # restore the suite's mock models


_REQUIRED = {"DATABASE_URL": "sqlite://", "JWT_SECRET_KEY": "k" * 40}


def test_torch_num_threads_defaults_to_auto() -> None:
    assert Settings(_env_file=None, **_REQUIRED).TORCH_NUM_THREADS == 0


def test_negative_torch_num_threads_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, TORCH_NUM_THREADS=-1, **_REQUIRED)
