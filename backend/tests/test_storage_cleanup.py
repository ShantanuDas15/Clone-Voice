"""Unit tests for the storage cleanup background job (HARDENING_PLAN Phase 2,
Critical finding C1)."""

import asyncio
import os
import time
import uuid

from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.services.storage_cleanup import (cleanup_stale_files,
                                              get_protected_paths,
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


def test_cleanup_skips_protected_files_regardless_of_age(tmp_path):
    """A file referenced by an active DB row must survive pruning (C1)."""
    upload_dir = tmp_path / "uploads" / "user-1"
    upload_dir.mkdir(parents=True)

    protected_file = upload_dir / "profile.wav"
    unprotected_file = upload_dir / "orphan.wav"
    _touch(str(protected_file), age_hours=999)
    _touch(str(unprotected_file), age_hours=999)

    deleted = cleanup_stale_files(
        [str(tmp_path / "uploads")],
        max_age_hours=24,
        protected_paths={os.path.abspath(str(protected_file))},
    )

    assert deleted == 1
    assert protected_file.exists()
    assert not unprotected_file.exists()


def test_cleanup_leaves_directory_when_only_protected_files_remain(tmp_path):
    user_dir = tmp_path / "uploads" / "user-1"
    user_dir.mkdir(parents=True)
    protected_file = user_dir / "profile.wav"
    _touch(str(protected_file), age_hours=999)

    cleanup_stale_files(
        [str(tmp_path / "uploads")],
        max_age_hours=24,
        protected_paths={os.path.abspath(str(protected_file))},
    )

    assert user_dir.exists()
    assert protected_file.exists()


def _make_user(db_session) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        name="Storage Cleanup Test User",
        provider="local",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_get_protected_paths_includes_active_voice_profile_files(db_session):
    user = _make_user(db_session)
    profile = VoiceProfile(
        user_id=user.id,
        name="voice",
        audio_sample_path="/data/uploads/u1/a.wav",
        embedding_path="/data/uploads/u1/a_embed.npy",
        status="ready",
    )
    db_session.add(profile)
    db_session.commit()

    protected = get_protected_paths(db_session)

    assert os.path.abspath("/data/uploads/u1/a.wav") in protected
    assert os.path.abspath("/data/uploads/u1/a_embed.npy") in protected


def test_get_protected_paths_excludes_soft_deleted_voice_profile(db_session):
    from sqlalchemy.sql import func

    user = _make_user(db_session)
    profile = VoiceProfile(
        user_id=user.id,
        name="deleted-voice",
        audio_sample_path="/data/uploads/u1/deleted.wav",
        embedding_path="/data/uploads/u1/deleted_embed.npy",
        status="ready",
        deleted_at=func.now(),
    )
    db_session.add(profile)
    db_session.commit()

    protected = get_protected_paths(db_session)

    assert os.path.abspath("/data/uploads/u1/deleted.wav") not in protected
    assert os.path.abspath("/data/uploads/u1/deleted_embed.npy") not in protected


def test_get_protected_paths_skips_blank_embedding_path(db_session):
    """A failed upload persists `embedding_path=""` (api/voice.py) — must not
    be treated as a protected path."""
    user = _make_user(db_session)
    profile = VoiceProfile(
        user_id=user.id,
        name="failed-voice",
        audio_sample_path="/data/uploads/u1/failed.wav",
        embedding_path="",
        status="failed",
    )
    db_session.add(profile)
    db_session.commit()

    protected = get_protected_paths(db_session)

    assert "" not in protected
    assert os.path.abspath("") not in protected
    assert os.path.abspath("/data/uploads/u1/failed.wav") in protected


def test_get_protected_paths_includes_generation_output_files(db_session):
    user = _make_user(db_session)
    profile = VoiceProfile(
        user_id=user.id,
        name="voice",
        audio_sample_path="/data/uploads/u1/a.wav",
        embedding_path="/data/uploads/u1/a_embed.npy",
        status="ready",
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    generation = Generation(
        user_id=user.id,
        voice_profile_id=profile.id,
        input_text="hello",
        output_audio_path="/data/outputs/u1/out.wav",
        status="completed",
    )
    db_session.add(generation)
    db_session.commit()

    protected = get_protected_paths(db_session)

    assert os.path.abspath("/data/outputs/u1/out.wav") in protected


def test_periodic_cleanup_runs_repeatedly_and_stops_on_cancel(tmp_path, monkeypatch):
    call_count = {"n": 0}

    def fake_cleanup(directories, max_age_hours, protected_paths=()):
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


def test_periodic_cleanup_protects_files_referenced_via_session_factory(
    tmp_path, db_session, monkeypatch
):
    """End-to-end: a file referenced by an active voice profile survives a
    periodic_cleanup pass when a `session_factory` is supplied (C1 fix)."""
    upload_dir = tmp_path / "uploads" / "u1"
    upload_dir.mkdir(parents=True)
    protected_file = upload_dir / "a.wav"
    orphan_file = upload_dir / "orphan.wav"
    _touch(str(protected_file), age_hours=999)
    _touch(str(orphan_file), age_hours=999)

    user = _make_user(db_session)
    profile = VoiceProfile(
        user_id=user.id,
        name="voice",
        audio_sample_path=str(protected_file),
        embedding_path=str(protected_file),
        status="ready",
    )
    db_session.add(profile)
    db_session.commit()

    async def runner():
        task = asyncio.create_task(
            periodic_cleanup(
                directories=[str(tmp_path / "uploads")],
                interval_seconds=0.01,
                max_age_hours=24,
                session_factory=lambda: db_session,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())

    assert protected_file.exists()
    assert not orphan_file.exists()
