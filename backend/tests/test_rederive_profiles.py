"""Re-deriving profile embeddings from the stored clips (SPEECH_QUALITY_PLAN.md S4.5b)."""

import os
import uuid

import numpy as np
import pytest

from backend import rederive_profiles as rp
from backend.models.voice_profile import VoiceProfile
from backend.services.voice_embedding import EMBEDDING_VERSION
from backend.tests.test_chatterbox_engine import _tone, _wav
from backend.tests.test_style_override import auth, profile  # noqa: F401

NEW = np.zeros(256, np.float32)
NEW[3] = 1.0


def _embed(_audio):
    return NEW.copy()


def _upload_clips(client, auth, count):  # noqa: F811
    files = [
        (
            "files",
            (f"c{i}.wav", _wav(_tone(4.0, freq=150 + 20 * i, amp=0.5)), "audio/wav"),
        )
        for i in range(count)
    ]
    response = client.post(
        "/api/v1/voice/upload",
        headers=auth,
        data={"name": "multi", "consent_confirmed": "true"},
        files=files,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _row(db, pid=None):
    db.expire_all()
    q = db.query(VoiceProfile)
    return q.filter(VoiceProfile.id == uuid.UUID(pid)).one() if pid else q.one()


def _files(row):
    paths = {row.embedding_path}
    paths.update(s.embedding_path for s in row.samples)
    return {p: open(p, "rb").read() for p in paths}


def _stray(row):
    return [
        f
        for f in os.listdir(os.path.dirname(row.embedding_path))
        if f.startswith(".rederive-")
    ]


def test_a_dry_run_changes_nothing(client, auth, profile, db_session):  # noqa: F811
    row = _row(db_session)
    row.embedding_version = None
    db_session.commit()
    before = _files(row)
    (outcome,) = rp.rederive_all(db_session, _embed, apply=False)
    assert outcome.status == "would_update" and outcome.similarity is not None
    assert _files(_row(db_session)) == before
    assert _row(db_session).embedding_version is None


def test_apply_rewrites_the_embedding_and_stamps_the_version(
    client, auth, profile, db_session  # noqa: F811
):
    row = _row(db_session)
    row.embedding_version = None
    db_session.commit()
    (outcome,) = rp.rederive_all(db_session, _embed, apply=True)
    row = _row(db_session)
    assert outcome.status == "updated"
    assert row.embedding_version == EMBEDDING_VERSION
    assert np.array_equal(np.load(row.embedding_path), NEW)
    assert _stray(row) == []


def test_a_multi_clip_profile_gets_every_clip_and_the_aggregate(
    client, auth, db_session  # noqa: F811
):
    pid = _upload_clips(client, auth, 3)
    row = _row(db_session, pid)
    assert len(row.samples) == 3
    rp.rederive_all(db_session, _embed, apply=True)
    row = _row(db_session, pid)
    for sample in row.samples:
        assert np.array_equal(np.load(sample.embedding_path), NEW)
    assert np.allclose(np.load(row.embedding_path), NEW)
    assert _stray(row) == []


def test_a_missing_clip_skips_the_profile_and_changes_nothing(
    client, auth, profile, db_session  # noqa: F811
):
    row = _row(db_session)
    before = _files(row)
    os.remove(row.audio_sample_path)
    (outcome,) = rp.rederive_all(db_session, _embed, apply=True)
    assert outcome.status == "skipped" and "missing" in outcome.detail
    assert _files(_row(db_session)) == before


def test_an_unusable_embedding_skips_the_profile(
    client, auth, profile, db_session
):  # noqa: F811
    before = _files(_row(db_session))
    (outcome,) = rp.rederive_all(
        db_session, lambda a: np.zeros(256, np.float32), apply=True
    )
    assert outcome.status == "skipped" and "unusable" in outcome.detail
    assert _files(_row(db_session)) == before


def test_one_bad_profile_does_not_stop_the_rest(client, auth, db_session):  # noqa: F811
    first = _upload_clips(client, auth, 1)
    second = _upload_clips(client, auth, 2)
    os.remove(_row(db_session, first).audio_sample_path)
    outcomes = {
        o.profile_id: o.status for o in rp.rederive_all(db_session, _embed, apply=True)
    }
    assert outcomes[first] == "skipped" and outcomes[second] == "updated"


def test_a_failed_write_leaves_the_old_files_and_no_temporaries(
    client, auth, db_session, monkeypatch  # noqa: F811
):
    pid = _upload_clips(client, auth, 2)
    row = _row(db_session, pid)
    before = _files(row)
    real, calls = rp._write_npy, []

    def flaky(path, array):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(path, array)

    monkeypatch.setattr(rp, "_write_npy", flaky)
    (outcome,) = rp.rederive_all(db_session, _embed, apply=True)
    assert outcome.status == "skipped" and "write failed" in outcome.detail
    row = _row(db_session, pid)
    assert _files(row) == before and _stray(row) == []


def test_only_outdated_skips_profiles_already_current(
    client, auth, profile, db_session
):  # noqa: F811
    (outcome,) = rp.rederive_all(db_session, _embed, apply=True, only_outdated=True)
    assert outcome.status == "current"
    row = _row(db_session)
    row.embedding_version = "ecapa-1"
    db_session.commit()
    (outcome,) = rp.rederive_all(db_session, _embed, apply=False, only_outdated=True)
    assert outcome.status == "would_update"


def test_a_deleted_profile_is_ignored(client, auth, profile, db_session):  # noqa: F811
    from datetime import datetime, timezone

    row = _row(db_session)
    row.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    assert rp.rederive_all(db_session, _embed, apply=True) == []


@pytest.mark.parametrize(
    "a,b,expected",
    [([1, 0], [1, 0], 1.0), ([1, 0], [0, 1], 0.0), ([0, 0], [1, 0], 0.0)],
)
def test_cosine(a, b, expected):
    assert rp._cosine(np.array(a, float), np.array(b, float)) == pytest.approx(expected)
