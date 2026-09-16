"""Repo-hygiene regression test for HARDENING_PLAN Critical finding C3:
committed user audio must never re-enter the git index."""

import subprocess

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def _tracked_files(pathspec: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", REPO_ROOT, "ls-files", pathspec],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_uploads_and_outputs_are_not_tracked() -> None:
    assert _tracked_files("uploads") == []
    assert _tracked_files("outputs") == []


def test_test_output_wav_is_not_tracked() -> None:
    assert _tracked_files("test_output.wav") == []


def test_gitignore_covers_audio_paths() -> None:
    with open(f"{REPO_ROOT}/.gitignore", encoding="utf-8") as f:
        contents = f.read()
    for pattern in ("uploads/", "outputs/", "test_output.wav"):
        assert pattern in contents, f"{pattern!r} missing from .gitignore"
