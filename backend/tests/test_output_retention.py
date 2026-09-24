"""Tests for generation-output retention (HARDENING_PLAN.md finding P2-M5)."""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.core.config import settings
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.services.storage_cleanup import _run_cleanup_pass, get_protected_paths


def _touch(path: str, age_hours: float) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"RIFF")
    old = time.time() - age_hours * 3600
    os.utime(path, (old, old))


@pytest.fixture
def profile(db_session):
    user = User(email=f"{uuid.uuid4()}@example.com", name="Ret", provider="local")
    db_session.add(user)
    db_session.commit()
    p = VoiceProfile(
        user_id=user.id,
        name="v",
        audio_sample_path="/nonexistent/a.wav",
        embedding_path="/nonexistent/a.npy",
        status="ready",
    )
    db_session.add(p)
    db_session.commit()
    return p


def _generation(db, profile, path, age_days=0.0, deleted=False) -> Generation:
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    g = Generation(
        user_id=profile.user_id,
        voice_profile_id=profile.id,
        input_text="hi",
        output_audio_path=path,
        status="completed",
        created_at=created,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(g)
    db.commit()
    return g


def test_default_retention_is_finite() -> None:
    assert settings.OUTPUT_RETENTION_DAYS > 0


def test_recent_output_is_protected(db_session, profile) -> None:
    _generation(db_session, profile, "/o/new.wav", age_days=1)
    assert os.path.abspath("/o/new.wav") in get_protected_paths(db_session, 30)


def test_output_older_than_retention_is_unprotected(db_session, profile) -> None:
    _generation(db_session, profile, "/o/old.wav", age_days=31)
    assert os.path.abspath("/o/old.wav") not in get_protected_paths(db_session, 30)


def test_retention_boundary(db_session, profile) -> None:
    _generation(db_session, profile, "/o/inside.wav", age_days=29.9)
    _generation(db_session, profile, "/o/outside.wav", age_days=30.1)
    protected = get_protected_paths(db_session, 30)
    assert os.path.abspath("/o/inside.wav") in protected
    assert os.path.abspath("/o/outside.wav") not in protected


def test_soft_deleted_generation_output_is_unprotected(db_session, profile) -> None:
    _generation(db_session, profile, "/o/gone.wav", age_days=0, deleted=True)
    assert os.path.abspath("/o/gone.wav") not in get_protected_paths(db_session, 30)


@pytest.mark.parametrize("days", [0, -1])
def test_non_positive_retention_keeps_everything(db_session, profile, days) -> None:
    _generation(db_session, profile, "/o/ancient.wav", age_days=9999)
    _generation(db_session, profile, "/o/deleted.wav", deleted=True)
    protected = get_protected_paths(db_session, days)
    assert os.path.abspath("/o/ancient.wav") in protected
    assert os.path.abspath("/o/deleted.wav") in protected


def test_setting_is_used_when_no_override(db_session, profile, monkeypatch) -> None:
    _generation(db_session, profile, "/o/mid.wav", age_days=10)
    monkeypatch.setattr(settings, "OUTPUT_RETENTION_DAYS", 5)
    assert os.path.abspath("/o/mid.wav") not in get_protected_paths(db_session)
    monkeypatch.setattr(settings, "OUTPUT_RETENTION_DAYS", 20)
    assert os.path.abspath("/o/mid.wav") in get_protected_paths(db_session)


def test_profile_files_unaffected_by_output_retention(db_session, profile) -> None:
    protected = get_protected_paths(db_session, 0.0001)
    assert os.path.abspath("/nonexistent/a.wav") in protected
    assert os.path.abspath("/nonexistent/a.npy") in protected


def test_cleanup_pass_deletes_expired_output_and_keeps_recent(
    db_session, profile, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "OUTPUT_RETENTION_DAYS", 30)
    out = tmp_path / "outputs" / "u"
    fresh, expired = str(out / "fresh.wav"), str(out / "expired.wav")
    _touch(fresh, age_hours=48)
    _touch(expired, age_hours=48)
    fresh_id = _generation(db_session, profile, fresh, age_days=2).id
    expired_id = _generation(db_session, profile, expired, age_days=40).id

    deleted = _run_cleanup_pass([str(tmp_path / "outputs")], 24, lambda: db_session)

    assert deleted == 1
    assert os.path.exists(fresh)
    assert not os.path.exists(expired)
    # the audit rows survive; only the file expired
    assert db_session.get(Generation, fresh_id) is not None
    assert db_session.get(Generation, expired_id) is not None
