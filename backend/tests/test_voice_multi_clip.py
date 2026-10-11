"""Multi-clip voice profiles (SPEECH_QUALITY_PLAN.md S2.1b)."""

import io
import os
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings, settings
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.models.voice_profile_sample import VoiceProfileSample
from backend.services.erasure import erase_voice_profile, remove_files
from backend.services.storage_cleanup import get_protected_paths

SR = 16000


@pytest.fixture
def auth_headers(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "multi@example.com", "password": "Password123!", "name": "M"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "multi@example.com", "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


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
    """A 256-d unit embedding whose first coordinates are ``values`` (rest zero-padded)."""
    v = np.zeros(256, dtype=np.float32)
    v[: len(values)] = values
    return v / np.linalg.norm(v)


def _post(client, headers, embeddings=None, count=3, *, field="files", extra=None):
    """Upload ``count`` clips under ``field``, optionally with a fixed embedding per clip."""
    files = [(field, (f"c{i}.wav", _wav(), "audio/wav")) for i in range(count)]
    data = {"name": "Multi", "consent_confirmed": "true", **(extra or {})}
    if embeddings is None:
        return client.post(
            "/api/v1/voice/upload", headers=headers, data=data, files=files
        )
    with patch("backend.api.voice.embed_speaker_async", side_effect=embeddings):
        return client.post(
            "/api/v1/voice/upload", headers=headers, data=data, files=files
        )


def _tree_files(root: str) -> list:
    return [p for p in Path(root).rglob("*") if p.is_file()]


# --- success ----------------------------------------------------------------


def test_several_clips_make_one_profile_with_one_sample_row_each(
    client, auth_headers, db_session
):
    emb = [_unit(1, 0.1), _unit(1, -0.1), _unit(1, 0.05)]
    response = _post(client, auth_headers, emb)
    assert response.status_code == 201
    body = response.json()
    assert [s["position"] for s in body["samples"]] == [0, 1, 2]
    assert not any(s["mismatch"] for s in body["samples"])

    profiles = db_session.query(VoiceProfile).all()
    assert len(profiles) == 1
    rows = db_session.query(VoiceProfileSample).order_by(VoiceProfileSample.position)
    assert [r.position for r in rows] == [0, 1, 2]
    assert all(
        os.path.exists(r.audio_path) and os.path.exists(r.embedding_path) for r in rows
    )
    assert profiles[0].audio_sample_path == rows[0].audio_path


def test_the_profile_embedding_is_the_unit_mean_of_the_clips(
    client, auth_headers, db_session
):
    emb = [_unit(1, 0.2), _unit(1, -0.2), _unit(1, 0.0)]
    _post(client, auth_headers, emb)
    profile = db_session.query(VoiceProfile).one()
    stored = np.load(profile.embedding_path)
    expected = sum(emb) / np.linalg.norm(sum(emb))
    assert np.allclose(stored, expected, atol=1e-6)
    assert float(np.linalg.norm(stored)) == pytest.approx(1.0, abs=1e-5)


def test_the_profile_embedding_does_not_depend_on_upload_order(client, auth_headers):
    emb = [_unit(1, 0.3), _unit(1, -0.2), _unit(1, 0.1)]
    first = _post(client, auth_headers, emb)
    second = _post(client, auth_headers, list(reversed(emb)))
    assert first.status_code == second.status_code == 201


def test_one_clip_through_files_or_file_is_the_old_single_clip_profile(
    client, auth_headers, db_session
):
    emb = _unit(1, 0.4)
    for field in ("file", "files"):
        assert _post(client, auth_headers, [emb], 1, field=field).status_code == 201
    for profile in db_session.query(VoiceProfile).all():
        # The clip's own embedding file *is* the profile embedding, as before S2.1b.
        sample = profile.samples[0]
        assert profile.embedding_path == sample.embedding_path
        assert np.array_equal(np.load(profile.embedding_path), emb)
        assert sample.agreement == 1.0


def test_file_and_files_can_be_combined(client, auth_headers, db_session):
    files = [
        ("file", ("a.wav", _wav(), "audio/wav")),
        ("files", ("b.wav", _wav(), "audio/wav")),
    ]
    with patch(
        "backend.api.voice.embed_speaker_async",
        side_effect=[_unit(1, 0.1), _unit(1, -0.1)],
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Mixed", "consent_confirmed": "true"},
            files=files,
        )
    assert response.status_code == 201
    assert len(response.json()["samples"]) == 2


def test_a_clip_from_another_speaker_is_flagged_not_rejected(client, auth_headers):
    # Three consistent clips and one orthogonal one: with fewer clips the outlier drags
    # a good clip below the threshold too (SPEECH_QUALITY_STUDY.md, S2.1a).
    emb = [_unit(1, 0.1), _unit(1, -0.1), _unit(1, 0.05), _unit(0, 1)]
    response = _post(client, auth_headers, emb, 4)
    assert response.status_code == 201
    samples = response.json()["samples"]
    assert [s["mismatch"] for s in samples] == [False, False, False, True]
    assert samples[3]["agreement"] < 0.75


def test_two_clips_are_never_flagged(client, auth_headers):
    response = _post(client, auth_headers, [_unit(1, 0), _unit(0, 1)], 2)
    assert response.status_code == 201
    assert not any(s["mismatch"] for s in response.json()["samples"])


def test_the_response_reports_the_lowest_rated_clip_as_quality(client, auth_headers):
    from backend.schemas.voice import QualityOut

    def q(rating):
        return QualityOut(
            rating=rating,
            hints=[],
            measures=dict(
                voiced_seconds=1,
                snr_db=1,
                clipping_ratio=0,
                high_band_db=0,
                level_dbfs=0,
            ),
        )

    ratings = iter(["good", "poor", "fair"])

    async def fake(_path):
        return q(next(ratings))

    with patch("backend.api.voice._assess_quality_quietly", side_effect=fake):
        response = _post(client, auth_headers, [_unit(1, 0.1)] * 3)
    body = response.json()
    assert body["quality"]["rating"] == "poor"
    assert [s["quality"]["rating"] for s in body["samples"]] == ["good", "poor", "fair"]


# --- limits and failures ---------------------------------------------------


def test_no_clip_at_all_is_a_422(client, auth_headers):
    response = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "None", "consent_confirmed": "true"},
    )
    assert response.status_code == 422
    assert "at least one" in response.json()["detail"]


def test_more_than_the_limit_is_a_422_and_stores_nothing(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "VOICE_MAX_SAMPLES", 2)
    response = _post(client, auth_headers, count=3)
    assert response.status_code == 422
    assert not _tree_files(settings.UPLOAD_DIR)


def test_exactly_the_limit_is_accepted(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_MAX_SAMPLES", 3)
    assert _post(client, auth_headers, [_unit(1, 0.1)] * 3).status_code == 201


def test_one_bad_clip_leaves_no_profile_and_no_files(client, auth_headers, db_session):
    files = [
        ("files", ("a.wav", _wav(), "audio/wav")),
        ("files", ("b.wav", _wav(), "audio/wav")),
        ("files", ("c.wav", b"not audio at all", "audio/wav")),
    ]
    with patch(
        "backend.api.voice.embed_speaker_async",
        side_effect=[_unit(1, 0.1), _unit(1, 0.2)],
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Bad", "consent_confirmed": "true"},
            files=files,
        )
    assert response.status_code == 422
    assert db_session.query(VoiceProfile).count() == 0
    assert db_session.query(VoiceProfileSample).count() == 0
    assert not _tree_files(settings.UPLOAD_DIR)


def test_a_blank_embedding_on_a_later_clip_leaves_nothing_behind(
    client, auth_headers, db_session
):
    response = _post(
        client, auth_headers, [_unit(1, 0.1), np.zeros(256, dtype=np.float32)], 2
    )
    assert response.status_code == 422
    assert db_session.query(VoiceProfile).count() == 0
    assert not _tree_files(settings.UPLOAD_DIR)


def test_an_embedding_crash_on_a_later_clip_records_one_failed_profile(
    client, auth_headers, db_session
):
    response = _post(client, auth_headers, [_unit(1, 0.1), RuntimeError("boom")], 2)
    assert response.status_code == 500
    profiles = db_session.query(VoiceProfile).all()
    assert [p.status for p in profiles] == ["failed"]
    assert db_session.query(VoiceProfileSample).count() == 0
    assert not _tree_files(settings.UPLOAD_DIR)


def test_a_database_failure_removes_every_file(client, auth_headers, db_session):
    from sqlalchemy.exc import IntegrityError

    err = IntegrityError("x", {}, Exception("boom"))
    with patch("backend.api.voice._persist_profile", side_effect=err):
        response = _post(client, auth_headers, [_unit(1, 0.1)] * 3)
    assert response.status_code == 500
    assert not _tree_files(settings.UPLOAD_DIR)


# --- erasure and cleanup ----------------------------------------------------


def _multi_profile(client, auth_headers, db_session):
    _post(client, auth_headers, [_unit(1, 0.1), _unit(1, -0.1), _unit(1, 0.0)])
    return db_session.query(VoiceProfile).one()


def test_deleting_a_profile_removes_every_clip_and_its_embeddings(
    client, auth_headers, db_session
):
    profile = _multi_profile(client, auth_headers, db_session)
    assert (
        len(_tree_files(settings.UPLOAD_DIR)) == 7
    )  # 3 clips + 3 embeddings + profile
    response = client.delete(
        f"/api/v1/voice/profiles/{profile.id}", headers=auth_headers
    )
    assert response.status_code == 200
    assert not _tree_files(settings.UPLOAD_DIR)
    db_session.expire_all()
    assert all(
        r.deleted_at is not None for r in db_session.query(VoiceProfileSample).all()
    )


def test_erase_voice_profile_lists_every_clip_path(client, auth_headers, db_session):
    profile = _multi_profile(client, auth_headers, db_session)
    paths = erase_voice_profile(db_session, profile)
    db_session.commit()
    on_disk = {str(p) for p in _tree_files(settings.UPLOAD_DIR)}
    assert on_disk <= set(paths)
    assert remove_files(paths) == len(on_disk)


def test_account_erasure_removes_every_clip(client, auth_headers, db_session):
    _multi_profile(client, auth_headers, db_session)
    response = client.request(
        "DELETE",
        "/api/v1/auth/me",
        headers=auth_headers,
        json={"password": "Password123!"},
    )
    assert response.status_code in (200, 204)
    assert not _tree_files(settings.UPLOAD_DIR)


def test_cleanup_protects_every_clip_of_an_active_profile_only(
    client, auth_headers, db_session
):
    profile = _multi_profile(client, auth_headers, db_session)
    clip_paths = {
        os.path.abspath(p)
        for r in profile.samples
        for p in (r.audio_path, r.embedding_path)
    }
    assert clip_paths <= get_protected_paths(db_session, 30)
    assert os.path.abspath(profile.embedding_path) in get_protected_paths(
        db_session, 30
    )

    erase_voice_profile(db_session, profile)
    db_session.commit()
    assert not clip_paths & get_protected_paths(db_session, 30)


def test_a_profile_without_samples_still_works(client, auth_headers, db_session):
    """Profiles from before S2.1b have no sample rows and must keep behaving."""
    from datetime import datetime, timezone

    user = db_session.query(User).one()
    sample = os.path.join(settings.UPLOAD_DIR, "old.wav")
    embed = os.path.join(settings.UPLOAD_DIR, "old_embed.npy")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    for p in (sample, embed):
        Path(p).write_bytes(b"x")
    profile = VoiceProfile(
        user_id=user.id,
        name="old",
        audio_sample_path=sample,
        embedding_path=embed,
        status="ready",
        consent_confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add(profile)
    db_session.commit()
    assert {os.path.abspath(sample), os.path.abspath(embed)} <= get_protected_paths(
        db_session, 30
    )
    assert (
        client.delete(
            f"/api/v1/voice/profiles/{profile.id}", headers=auth_headers
        ).status_code
        == 200
    )
    assert not os.path.exists(sample) and not os.path.exists(embed)


def test_deleting_a_profile_row_cascades_to_its_samples(
    client, auth_headers, db_session
):
    profile = _multi_profile(client, auth_headers, db_session)
    profile.samples.clear()
    db_session.commit()
    assert db_session.query(VoiceProfileSample).count() == 0


# --- synthesis uses the aggregated embedding --------------------------------


def test_synthesis_conditions_on_the_aggregated_embedding(
    client, auth_headers, db_session
):
    emb = [_unit(1, 0.2), _unit(1, -0.2), _unit(1, 0.0)]
    profile_id = _post(client, auth_headers, emb).json()["id"]
    seen = {}

    async def fake_pipeline(text, embedding, user_id):
        seen["embedding"] = embedding
        raise RuntimeError("stop here")

    with patch(
        "backend.api.synthesize.run_inference_pipeline", side_effect=fake_pipeline
    ):
        client.post(
            "/api/v1/synthesize",
            headers=auth_headers,
            json={"text": "Hello there.", "voice_profile_id": profile_id},
        )
    expected = sum(emb) / np.linalg.norm(sum(emb))
    assert np.allclose(seen["embedding"], expected, atol=1e-6)


# --- settings ---------------------------------------------------------------


def test_the_default_limit_and_its_bounds():
    assert settings.VOICE_MAX_SAMPLES == 10
    for bad in (0, 21):
        with pytest.raises(Exception):
            Settings(VOICE_MAX_SAMPLES=bad)
