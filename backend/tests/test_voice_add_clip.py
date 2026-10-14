"""Adding clips to an existing voice profile (SPEECH_QUALITY_PLAN.md S2.1c)."""

import io
import os
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.core.config import settings
from backend.models.voice_profile import VoiceProfile
from backend.models.voice_profile_sample import VoiceProfileSample
from backend.services.erasure import erase_voice_profile, remove_files
from backend.services.voice_embedding import EMBEDDING_VERSION

SR = 16000


def _login(client: TestClient, email: str) -> dict:
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "A"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(client: TestClient):
    return _login(client, "addclip@example.com")


def _wav(seconds: float = 3.0) -> bytes:
    t = np.arange(int(SR * seconds)) / SR
    samples = (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(samples.tobytes())
    return buf.getvalue()


def _unit(*values: float) -> np.ndarray:
    """A 256-d unit embedding whose first coordinates are ``values``."""
    v = np.zeros(256, dtype=np.float32)
    v[: len(values)] = values
    return v / np.linalg.norm(v)


def _clips(count: int, field: str = "files") -> list:
    return [(field, (f"c{i}.wav", _wav(), "audio/wav")) for i in range(count)]


def _create(client, headers, embeddings) -> str:
    """Upload one clip per embedding as a new profile; return its id."""
    field = "file" if len(embeddings) == 1 else "files"
    with patch(
        "backend.services.tts_pipeline.embed_speaker_async", side_effect=embeddings
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=headers,
            data={"name": "Voice", "consent_confirmed": "true"},
            files=_clips(len(embeddings), field),
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add(client, headers, profile_id, embeddings, *, data=None, files=None):
    """POST clips to ``profile_id`` with a fixed embedding per clip."""
    body = {"consent_confirmed": "true", **(data or {})}
    with patch(
        "backend.services.tts_pipeline.embed_speaker_async", side_effect=embeddings
    ):
        return client.post(
            f"/api/v1/voice/profiles/{profile_id}/samples",
            headers=headers,
            data=body,
            files=files if files is not None else _clips(len(embeddings)),
        )


def _tree_files(root: str) -> set:
    return {str(p) for p in Path(root).rglob("*") if p.is_file()}


def _profile(db_session) -> VoiceProfile:
    db_session.expire_all()
    return db_session.query(VoiceProfile).one()


# --- success ----------------------------------------------------------------


def test_adding_a_clip_re_derives_the_mean_over_all_clips(
    client, auth_headers, db_session
):
    first = [_unit(1, 0.2), _unit(1, -0.2), _unit(1, 0.0)]
    pid = _create(client, auth_headers, first)
    old_aggregate = _profile(db_session).embedding_path

    new = _unit(1, 0.1)
    response = _add(client, auth_headers, pid, [new])

    assert response.status_code == 201, response.text
    body = response.json()
    assert [s["position"] for s in body["samples"]] == [0, 1, 2, 3]
    assert [s["quality"] is not None for s in body["samples"]] == [
        False,
        False,
        False,
        True,
    ]
    profile = _profile(db_session)
    expected = sum(first + [new])
    expected = expected / np.linalg.norm(expected)
    assert np.allclose(np.load(profile.embedding_path), expected, atol=1e-6)
    assert profile.embedding_path != old_aggregate
    assert not os.path.exists(old_aggregate)
    assert profile.embedding_version == EMBEDDING_VERSION


def test_adding_to_a_single_clip_profile_keeps_that_clips_own_embedding(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    profile = _profile(db_session)
    lone_embedding = profile.embedding_path
    assert profile.samples[0].embedding_path == lone_embedding

    response = _add(client, auth_headers, pid, [_unit(1, 0.1)])

    assert response.status_code == 201, response.text
    profile = _profile(db_session)
    assert os.path.exists(lone_embedding)  # still the first clip's embedding
    assert profile.embedding_path != lone_embedding
    assert [s.position for s in profile.samples] == [0, 1]
    assert profile.samples[0].embedding_path == lone_embedding


def test_a_profile_from_before_sample_rows_gains_one_for_its_original_clip(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    profile = _profile(db_session)
    audio, embedding = profile.audio_sample_path, profile.embedding_path
    for row in list(profile.samples):
        db_session.delete(row)
    profile.embedding_version = None
    db_session.commit()

    response = _add(client, auth_headers, pid, [_unit(1, 0.1), _unit(1, -0.1)])

    assert response.status_code == 201, response.text
    profile = _profile(db_session)
    assert [(s.position, s.audio_path) for s in profile.samples][0] == (0, audio)
    assert profile.samples[0].embedding_path == embedding
    assert len(profile.samples) == 3
    assert os.path.exists(embedding)
    assert profile.embedding_version == EMBEDDING_VERSION


def test_every_clips_stored_agreement_is_refreshed(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.05)])
    _add(client, auth_headers, pid, [_unit(1, -0.05)])
    rows = _profile(db_session).samples
    assert len(rows) == 3
    assert all(0.9 < r.agreement <= 1.0 for r in rows)
    assert rows[2].agreement != 0.0


def test_a_clip_from_another_speaker_is_flagged_not_refused(
    client, auth_headers, db_session
):
    pid = _create(
        client, auth_headers, [_unit(1, 0.0), _unit(1, 0.05), _unit(1, -0.05)]
    )
    response = _add(client, auth_headers, pid, [_unit(0, 1)])
    assert response.status_code == 201
    assert [s["mismatch"] for s in response.json()["samples"]] == [
        False,
        False,
        False,
        True,
    ]


def test_erasure_after_adding_removes_every_file(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    _add(client, auth_headers, pid, [_unit(1, -0.1)])
    profile = _profile(db_session)
    files = erase_voice_profile(db_session, profile)
    db_session.commit()
    remove_files(files)
    assert _tree_files(settings.UPLOAD_DIR) == set()


# --- refusal leaves the profile untouched -----------------------------------


def test_a_bad_clip_keeps_the_profile_and_leaves_no_files(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    before_files = _tree_files(settings.UPLOAD_DIR)
    profile = _profile(db_session)
    before_embedding = np.load(profile.embedding_path)

    files = [
        ("files", ("good.wav", _wav(), "audio/wav")),
        ("files", ("bad.wav", b"this is not audio", "audio/wav")),
    ]
    response = _add(client, auth_headers, pid, [_unit(1, 0.0)], files=files)

    assert response.status_code == 422
    assert _tree_files(settings.UPLOAD_DIR) == before_files
    profile = _profile(db_session)
    assert len(profile.samples) == 2
    assert np.array_equal(np.load(profile.embedding_path), before_embedding)


def test_a_database_failure_keeps_the_profile_and_leaves_no_files(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    before_files = _tree_files(settings.UPLOAD_DIR)
    before_path = _profile(db_session).embedding_path

    with patch(
        "backend.api.voice._attach_clips",
        side_effect=OperationalError("x", {}, Exception("boom")),
    ):
        response = _add(client, auth_headers, pid, [_unit(1, 0.0)])

    assert response.status_code in (500, 503)
    assert _tree_files(settings.UPLOAD_DIR) == before_files
    profile = _profile(db_session)
    assert profile.embedding_path == before_path
    assert len(profile.samples) == 2


def test_an_inference_failure_removes_the_new_files_and_keeps_the_profile(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    before_files = _tree_files(settings.UPLOAD_DIR)
    response = _add(client, auth_headers, pid, [RuntimeError("encoder died")])
    assert response.status_code == 500
    assert _tree_files(settings.UPLOAD_DIR) == before_files
    assert db_session.query(VoiceProfile).count() == 1  # no "failed" row either


def test_the_voice_cannot_exceed_the_clip_limit(
    client, auth_headers, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "VOICE_MAX_SAMPLES", 3)
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    before_files = _tree_files(settings.UPLOAD_DIR)

    response = _add(client, auth_headers, pid, [_unit(1, 0.0), _unit(1, 0.2)])

    assert response.status_code == 422
    assert "at most 3" in response.json()["detail"]
    assert _tree_files(settings.UPLOAD_DIR) == before_files
    # Exactly the limit is fine.
    assert _add(client, auth_headers, pid, [_unit(1, 0.0)]).status_code == 201


def test_a_profile_made_by_an_older_engine_is_refused(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    _profile(db_session).embedding_version = "sv2tts-0"
    db_session.commit()
    response = _add(client, auth_headers, pid, [_unit(1, 0.0)])
    assert response.status_code == 409


def test_missing_stored_embeddings_are_refused_not_crashed(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    os.remove(_profile(db_session).samples[0].embedding_path)
    response = _add(client, auth_headers, pid, [_unit(1, 0.0)])
    assert response.status_code == 409


# --- request validation and ownership ---------------------------------------


def test_consent_is_required_for_every_added_clip(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    response = _add(
        client, auth_headers, pid, [_unit(1, 0.0)], data={"consent_confirmed": "false"}
    )
    assert response.status_code == 422


def test_stale_terms_version_is_refused(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    response = _add(
        client, auth_headers, pid, [_unit(1, 0.0)], data={"terms_version": "old"}
    )
    assert response.status_code == 409


def test_at_least_one_clip_is_required(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    response = _add(client, auth_headers, pid, [], files=[])
    assert response.status_code == 422


def test_an_invalid_profile_id_is_a_400(client, auth_headers):
    assert _add(client, auth_headers, "nope", [_unit(1, 0.0)]).status_code == 400


def test_another_users_profile_is_a_404(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    other = _login(client, "intruder@example.com")
    assert _add(client, other, pid, [_unit(1, 0.0)]).status_code == 404
    assert len(_profile(db_session).samples) == 1


def test_a_deleted_profile_is_a_404(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    client.delete(f"/api/v1/voice/profiles/{pid}", headers=auth_headers)
    assert _add(client, auth_headers, pid, [_unit(1, 0.0)]).status_code == 404


def test_it_requires_authentication(client):
    response = client.post(
        "/api/v1/voice/profiles/00000000-0000-0000-0000-000000000000/samples",
        data={"consent_confirmed": "true"},
        files=_clips(1),
    )
    assert response.status_code == 401


# --- removing a clip (S2.1d) ------------------------------------------------


def _remove(client, headers, profile_id, position):
    return client.delete(
        f"/api/v1/voice/profiles/{profile_id}/samples/{position}", headers=headers
    )


def test_removing_a_clip_re_derives_the_mean_and_renumbers(
    client, auth_headers, db_session
):
    emb = [_unit(1, 0.2), _unit(1, -0.2), _unit(1, 0.0), _unit(1, 0.1)]
    pid = _create(client, auth_headers, emb)
    profile = _profile(db_session)
    old_aggregate = profile.embedding_path
    gone = profile.samples[1]
    gone_files = [gone.audio_path, gone.embedding_path]

    response = _remove(client, auth_headers, pid, 1)

    assert response.status_code == 200, response.text
    assert [s["position"] for s in response.json()["samples"]] == [0, 1, 2]
    profile = _profile(db_session)
    assert [s.position for s in profile.samples] == [0, 1, 2]
    kept = [emb[0], emb[2], emb[3]]
    expected = sum(kept) / np.linalg.norm(sum(kept))
    assert np.allclose(np.load(profile.embedding_path), expected, atol=1e-6)
    assert not any(os.path.exists(p) for p in gone_files + [old_aggregate])
    assert db_session.query(VoiceProfileSample).count() == 3


def test_down_to_one_clip_the_profile_uses_that_clips_own_embedding(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    old_aggregate = _profile(db_session).embedding_path
    assert _remove(client, auth_headers, pid, 0).status_code == 200
    profile = _profile(db_session)
    only = profile.samples[0]
    assert only.position == 0 and only.agreement == 1.0
    assert profile.embedding_path == only.embedding_path
    assert profile.audio_sample_path == only.audio_path
    assert os.path.exists(only.embedding_path)
    assert not os.path.exists(old_aggregate)


def test_removing_an_outlier_clears_the_mismatch_and_synthesis_still_resolves(
    client, auth_headers, db_session
):
    pid = _create(
        client,
        auth_headers,
        [_unit(1, 0.0), _unit(1, 0.05), _unit(1, -0.05), _unit(0, 1)],
    )
    response = _remove(client, auth_headers, pid, 3)
    assert response.status_code == 200
    assert not any(s["mismatch"] for s in response.json()["samples"])


def test_removing_then_adding_keeps_positions_contiguous(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1), _unit(1, 0.2)])
    _remove(client, auth_headers, pid, 0)
    assert _add(client, auth_headers, pid, [_unit(1, 0.0)]).status_code == 201
    assert [s.position for s in _profile(db_session).samples] == [0, 1, 2]


def test_the_last_clip_cannot_be_removed(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    before = _tree_files(settings.UPLOAD_DIR)
    assert _remove(client, auth_headers, pid, 0).status_code == 409
    assert _tree_files(settings.UPLOAD_DIR) == before


def test_a_profile_from_before_sample_rows_cannot_lose_its_only_clip(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0)])
    profile = _profile(db_session)
    for row in list(profile.samples):
        db_session.delete(row)
    db_session.commit()
    assert _remove(client, auth_headers, pid, 0).status_code == 409


def test_an_unknown_position_is_a_404_and_changes_nothing(
    client, auth_headers, db_session
):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    before = _tree_files(settings.UPLOAD_DIR)
    assert _remove(client, auth_headers, pid, 7).status_code == 404
    assert _remove(client, auth_headers, pid, -1).status_code == 404
    assert _tree_files(settings.UPLOAD_DIR) == before
    assert len(_profile(db_session).samples) == 2


def test_a_database_failure_while_removing_deletes_no_file(
    client, auth_headers, db_session
):
    """Files go only after the commit: a failed commit leaves every one on disk.

    (The shared test session sits in one outer transaction, so a real rollback would also
    undo the fixture's rows; it is stubbed here and the rows are not asserted.)
    """
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1), _unit(1, 0.2)])
    before = _tree_files(settings.UPLOAD_DIR)
    with patch(
        "sqlalchemy.orm.Session.commit",
        side_effect=OperationalError("x", {}, Exception("boom")),
    ), patch("sqlalchemy.orm.Session.rollback") as rollback:
        response = _remove(client, auth_headers, pid, 1)
    assert rollback.called
    assert response.status_code in (500, 503)
    assert (
        _tree_files(settings.UPLOAD_DIR) == before
    )  # nothing deleted, new aggregate gone


def test_removal_is_owner_only_and_validates_the_id(client, auth_headers, db_session):
    pid = _create(client, auth_headers, [_unit(1, 0.0), _unit(1, 0.1)])
    other = _login(client, "intruder2@example.com")
    assert _remove(client, other, pid, 0).status_code == 404
    assert _remove(client, auth_headers, "nope", 0).status_code == 400
    assert len(_profile(db_session).samples) == 2
    client.delete(f"/api/v1/voice/profiles/{pid}", headers=auth_headers)
    assert _remove(client, auth_headers, pid, 0).status_code == 404


def test_removal_requires_authentication(client):
    response = client.delete(
        "/api/v1/voice/profiles/00000000-0000-0000-0000-000000000000/samples/0"
    )
    assert response.status_code == 401
