"""Unit tests for the storage cleanup background job (HARDENING_PLAN Phase 2)."""

import asyncio
import os
import time

from backend.services.storage_cleanup import (cleanup_stale_files,
                                              periodic_cleanup)


def _touch(path: str, age_hours: float) -> None:
    """Create a file at `path` and backdate its mtime by `age_hours`."""
    with open(path, "wb") as f:
        f.write(b"data")
    stale_time = time.time() - (age_hours * 3600)
    os.utime(path, (stale_time, stale_time))


def test_cleanup_removes_only_stale_files(tmp_path):
    upload_dir = tmp_path / "uploads" / "user-1"
    upload_dir.mkdir(parents=True)

    stale_file = upload_dir / "old.wav"
    fresh_file = upload_dir / "new.wav"
    _touch(str(stale_file), age_hours=25)
    _touch(str(fresh_file), age_hours=1)

    deleted = cleanup_stale_files([str(tmp_path / "uploads")], max_age_hours=24)

    assert deleted == 1
    assert not stale_file.exists()
    assert fresh_file.exists()


def test_cleanup_removes_now_empty_subdirectories(tmp_path):
    user_dir = tmp_path / "uploads" / "user-2"
    user_dir.mkdir(parents=True)
    _touch(str(user_dir / "old.wav"), age_hours=48)

    cleanup_stale_files([str(tmp_path / "uploads")], max_age_hours=24)

    assert not user_dir.exists()


def test_cleanup_scans_multiple_directories(tmp_path):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    uploads.mkdir()
    outputs.mkdir()
    _touch(str(uploads / "old_upload.wav"), age_hours=48)
    _touch(str(outputs / "old_output.wav"), age_hours=48)

    deleted = cleanup_stale_files([str(uploads), str(outputs)], max_age_hours=24)

    assert deleted == 2


def test_cleanup_ignores_missing_directory(tmp_path):
    missing = tmp_path / "does-not-exist"

    deleted = cleanup_stale_files([str(missing)], max_age_hours=24)

    assert deleted == 0


def test_cleanup_no_files_returns_zero(tmp_path):
    empty_dir = tmp_path / "uploads"
    empty_dir.mkdir()

    deleted = cleanup_stale_files([str(empty_dir)], max_age_hours=24)

    assert deleted == 0


def test_periodic_cleanup_runs_repeatedly_and_stops_on_cancel(tmp_path, monkeypatch):
    call_count = {"n": 0}

    def fake_cleanup(directories, max_age_hours):
        call_count["n"] += 1
        return 0

    monkeypatch.setattr(
        "backend.services.storage_cleanup.cleanup_stale_files", fake_cleanup
    )

    async def runner():
        task = asyncio.create_task(
            periodic_cleanup(
                directories=[str(tmp_path)],
                interval_seconds=0.01,
                max_age_hours=24,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())

    assert call_count["n"] >= 1
