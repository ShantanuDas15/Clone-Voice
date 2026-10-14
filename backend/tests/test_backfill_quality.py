"""Backfilling stored quality reports for older clips (SPEECH_QUALITY_PLAN.md S2.2d)."""

import os
from datetime import datetime, timezone

import numpy as np
import pytest
import soundfile as sf

from backend import backfill_quality as bq
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.models.voice_profile_sample import VoiceProfileSample

SR = 16000
KEPT = {"rating": "good", "hints": [], "measures": {}}  # a sentinel, never overwritten


@pytest.fixture
def user(db_session) -> User:
    row = User(email="backfill@example.com", name="B", hashed_password="x")
    db_session.add(row)
    db_session.commit()
    return row


def _clip(directory, name, seconds=3.0) -> str:
    t = np.arange(int(SR * seconds)) / SR
    path = os.path.join(directory, name)
    sf.write(path, 0.4 * np.sin(2 * np.pi * 220 * t), SR)
    return path


def _profile(db, user, tmp_path, qualities, *, status="ready", deleted=False):
    """A profile with one clip per entry of ``qualities`` (None = no stored report)."""
    samples = [
        VoiceProfileSample(
            position=i,
            audio_path=_clip(
                str(tmp_path), f"{user.id}-{status}-{i}-{id(qualities)}.wav"
            ),
            embedding_path="e",
            agreement=1.0,
            quality=q,
        )
        for i, q in enumerate(qualities)
    ]
    profile = VoiceProfile(
        user_id=user.id,
        name="p",
        audio_sample_path=samples[0].audio_path,
        embedding_path="e",
        status=status,
        consent_confirmed_at=datetime.now(timezone.utc),
        deleted_at=datetime.now(timezone.utc) if deleted else None,
        samples=samples,
    )
    db.add(profile)
    db.commit()
    return profile


def _statuses(outcomes):
    return [(o.position, o.status) for o in outcomes]


def test_a_dry_run_reports_and_writes_nothing(db_session, user, tmp_path):
    profile = _profile(db_session, user, tmp_path, [None, None])
    outcomes = bq.backfill_all(db_session, apply=False)
    assert _statuses(outcomes) == [(0, "would_fill"), (1, "would_fill")]
    db_session.expire_all()
    assert all(s.quality is None for s in profile.samples)


def test_apply_fills_only_the_missing_reports(db_session, user, tmp_path):
    profile = _profile(db_session, user, tmp_path, [KEPT, None])
    outcomes = bq.backfill_all(db_session, apply=True)
    assert _statuses(outcomes) == [(1, "filled")]
    db_session.expire_all()
    first, second = profile.samples
    assert first.quality == KEPT  # never overwritten
    assert second.quality["rating"] in ("good", "fair", "poor")
    assert {"hints", "measures"} <= set(second.quality)


def test_running_twice_does_nothing_the_second_time(db_session, user, tmp_path):
    _profile(db_session, user, tmp_path, [None])
    assert _statuses(bq.backfill_all(db_session, apply=True)) == [(0, "filled")]
    assert bq.backfill_all(db_session, apply=True) == []


def test_a_missing_file_is_skipped_and_the_other_clips_still_filled(
    db_session, user, tmp_path
):
    profile = _profile(db_session, user, tmp_path, [None, None, None])
    os.remove(profile.samples[1].audio_path)
    outcomes = bq.backfill_all(db_session, apply=True)
    assert sorted(_statuses(outcomes)) == [(0, "filled"), (1, "skipped"), (2, "filled")]
    db_session.expire_all()
    assert [s.quality is not None for s in profile.samples] == [True, False, True]


def test_a_clip_that_cannot_be_assessed_is_skipped_with_the_reason(
    db_session, user, tmp_path
):
    profile = _profile(db_session, user, tmp_path, [None])

    def boom(_path):
        raise ValueError("undecodable")

    outcomes = bq.backfill_all(db_session, apply=True, assess=boom)
    assert _statuses(outcomes) == [(0, "skipped")]
    assert "ValueError: undecodable" in outcomes[0].detail
    db_session.expire_all()
    assert profile.samples[0].quality is None


def test_deleted_and_failed_profiles_are_left_alone(db_session, user, tmp_path):
    gone = _profile(db_session, user, tmp_path, [None], deleted=True)
    failed = _profile(db_session, user, tmp_path, [None], status="failed")
    assert bq.backfill_all(db_session, apply=True) == []
    db_session.expire_all()
    assert gone.samples[0].quality is None and failed.samples[0].quality is None


def test_a_profile_with_no_sample_rows_is_ignored(db_session, user, tmp_path):
    profile = _profile(db_session, user, tmp_path, [None])
    for row in list(profile.samples):
        db_session.delete(row)
    db_session.commit()
    assert bq.backfill_all(db_session, apply=True) == []


def test_a_failed_commit_reports_the_clips_as_skipped(
    db_session, user, tmp_path, monkeypatch
):
    _profile(db_session, user, tmp_path, [None])

    def fail():
        raise RuntimeError("disk full")

    monkeypatch.setattr(db_session, "commit", fail)
    monkeypatch.setattr(db_session, "rollback", lambda: None)
    outcomes = bq.backfill_all(db_session, apply=True)
    assert _statuses(outcomes) == [(0, "skipped")]
    assert "database update failed" in outcomes[0].detail


def test_main_exit_code_and_summary(db_session, user, tmp_path, monkeypatch, capsys):
    _profile(db_session, user, tmp_path, [None])
    monkeypatch.setattr("backend.core.database.SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    assert bq.main([]) == 0
    assert "1 would_fill" in capsys.readouterr().out
    assert bq.main(["--apply"]) == 0
    assert "1 filled" in capsys.readouterr().out
