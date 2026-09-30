import io
import os
import uuid
import wave
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.services.audio_processing import preprocess_audio
from backend.services.tts_pipeline import InferenceQueueFullError, InferenceTimeoutError


@pytest.fixture
def auth_headers(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "voice@example.com",
            "password": "Password123!",
            "name": "Voice User",
        },
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "voice@example.com", "password": "Password123!"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_dummy_wav(seconds: float = 3.0) -> bytes:
    """Build a voiced (3 s, 220 Hz tone) 16 kHz mono WAV that passes M4's duration checks."""
    t = np.arange(int(16000 * seconds)) / 16000
    samples = (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())
    buf.seek(0)
    return buf.read()


def test_upload_valid_wav(client: TestClient, auth_headers):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    data = {"name": "My Voice", "consent_confirmed": "true"}

    response = client.post(
        "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["name"] == "My Voice"
    assert res_data["status"] == "ready"
    assert "id" in res_data
    assert "consent_confirmed_at" in res_data


def test_upload_rejects_missing_consent(client: TestClient, auth_headers):
    """Responsible-use safeguard: an upload with no consent field at all
    must be rejected before any file work, not silently defaulted."""
    files = {"file": ("test.wav", create_dummy_wav(), "audio/wav")}
    data = {"name": "No Consent Field"}

    with patch("backend.api.voice.save_upload") as save:
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )
    assert response.status_code == 422
    save.assert_not_called()


def test_upload_rejects_false_consent(client: TestClient, auth_headers):
    """An explicit consent_confirmed=false must be rejected, not accepted."""
    files = {"file": ("test.wav", create_dummy_wav(), "audio/wav")}
    data = {"name": "False Consent", "consent_confirmed": "false"}

    with patch("backend.api.voice.save_upload") as save:
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )
    assert response.status_code == 422
    assert "right to use" in response.json()["detail"]
    save.assert_not_called()


def test_upload_records_consent_timestamp(client: TestClient, auth_headers):
    """A confirmed consent must be persisted as an auditable timestamp."""
    files = {"file": ("test.wav", create_dummy_wav(), "audio/wav")}
    data = {"name": "Consented Voice", "consent_confirmed": "true"}

    response = client.post(
        "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 201
    assert response.json()["consent_confirmed_at"] is not None


def test_upload_persists_consent_timestamp_in_db(
    client: TestClient, auth_headers, db_session
):
    """The stored consent is a timezone-aware, current timestamp, and it is
    exactly what the API returns."""
    before = datetime.now(timezone.utc)
    files = {"file": ("test.wav", create_dummy_wav(), "audio/wav")}
    response = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "Audited Voice", "consent_confirmed": "true"},
        files=files,
    )
    after = datetime.now(timezone.utc)
    assert response.status_code == 201

    row = db_session.get(VoiceProfile, uuid.UUID(response.json()["id"]))
    stored = row.consent_confirmed_at
    if stored.tzinfo is None:  # SQLite drops tzinfo; the value is stored as UTC
        stored = stored.replace(tzinfo=timezone.utc)
    assert before <= stored <= after
    assert response.json()["consent_confirmed_at"].startswith(
        stored.strftime("%Y-%m-%dT%H:%M:%S")
    )


def test_rejected_consent_leaves_no_profile_row(client: TestClient, auth_headers):
    """A refused attestation must not create even a `failed` profile."""
    files = {"file": ("test.wav", create_dummy_wav(), "audio/wav")}
    response = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "Refused", "consent_confirmed": "false"},
        files=files,
    )
    assert response.status_code == 422
    assert client.get("/api/v1/voice/profiles", headers=auth_headers).json() == []


def test_failed_profile_also_records_consent(
    client: TestClient, auth_headers, db_session, tmp_path
):
    """The audit trail must cover failed uploads too: the file was received
    under the same attestation, so the `failed` row keeps the timestamp."""
    with patch("backend.core.config.settings.UPLOAD_DIR", str(tmp_path)), patch(
        "backend.api.voice.embed_speaker_async", side_effect=RuntimeError("boom")
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Failed Consent", "consent_confirmed": "true"},
            files={"file": ("f.wav", create_dummy_wav(), "audio/wav")},
        )
    assert response.status_code == 500

    row = db_session.query(VoiceProfile).filter_by(name="Failed Consent").one()
    assert row.status == "failed"
    assert row.consent_confirmed_at is not None


def test_upload_records_terms_version(client: TestClient, auth_headers, db_session):
    """The consent is stored with the terms version in force, and returned."""
    with patch("backend.core.config.settings.TERMS_VERSION", "2099-01-01"):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Versioned Voice", "consent_confirmed": "true"},
            files={"file": ("test.wav", create_dummy_wav(), "audio/wav")},
        )
    assert response.status_code == 201
    assert response.json()["terms_version"] == "2099-01-01"
    row = db_session.get(VoiceProfile, uuid.UUID(response.json()["id"]))
    assert row.terms_version == "2099-01-01"


def test_failed_profile_also_records_terms_version(
    client: TestClient, auth_headers, db_session, tmp_path
):
    """A failed upload was received under the same terms, so it keeps them."""
    with patch("backend.core.config.settings.UPLOAD_DIR", str(tmp_path)), patch(
        "backend.api.voice.embed_speaker_async", side_effect=RuntimeError("boom")
    ):
        client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Failed Terms", "consent_confirmed": "true"},
            files={"file": ("f.wav", create_dummy_wav(), "audio/wav")},
        )
    row = db_session.query(VoiceProfile).filter_by(name="Failed Terms").one()
    assert row.terms_version


def test_rejected_consent_does_not_record_terms(
    client: TestClient, auth_headers, db_session
):
    """No consent, no row: a terms version is never stored on its own."""
    client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "No Terms", "consent_confirmed": "false"},
        files={"file": ("t.wav", create_dummy_wav(), "audio/wav")},
    )
    assert db_session.query(VoiceProfile).filter_by(name="No Terms").count() == 0


def test_voice_profile_consent_is_not_nullable(db_session):
    """The schema, not just the API, refuses a profile with no consent."""
    user = User(email="nc@example.com", name="NC", provider="local")
    db_session.add(user)
    db_session.flush()
    with pytest.raises(IntegrityError):
        # A savepoint keeps the failed flush from poisoning the outer
        # per-test transaction that the fixture rolls back.
        with db_session.begin_nested():
            db_session.add(
                VoiceProfile(
                    user_id=user.id,
                    name="No Consent",
                    audio_sample_path="a.wav",
                    embedding_path="a.npy",
                )
            )


def test_upload_valid_mp3(client: TestClient, auth_headers):

    with patch("backend.api.voice.preprocess_audio") as mock_pre:
        mock_pre.return_value = np.random.randn(32000).astype(np.float32)
        files = {"file": ("test.mp3", b"ID3 dummy mp3 data", "audio/mp3")}
        data = {"name": "MP3 Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )
        assert response.status_code == 201


def test_upload_acquires_preprocess_semaphore(client: TestClient, auth_headers):
    """HARDENING_PLAN.md P2-L10: the upload route must acquire
    preprocess_semaphore around the decode/resample call, not just leave it
    defined and unused in audio_processing.py."""

    class _TrackingSemaphore:
        def __init__(self):
            self.entered = False

        async def __aenter__(self):
            self.entered = True

        async def __aexit__(self, *exc_info):
            return False

    tracker = _TrackingSemaphore()

    with patch("backend.api.voice.preprocess_semaphore", tracker):
        wav_data = create_dummy_wav()
        files = {"file": ("test.wav", wav_data, "audio/wav")}
        data = {"name": "Tracked Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )

    assert response.status_code == 201
    assert tracker.entered, "Upload did not acquire preprocess_semaphore"


def test_upload_invalid_format_txt(client: TestClient, auth_headers):
    files = {"file": ("test.txt", b"hello text", "text/plain")}
    data = {"name": "Text Voice", "consent_confirmed": "true"}
    response = client.post(
        "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 422
    assert "Invalid audio format" in response.json()["detail"]


def test_upload_oversized_file(client: TestClient, auth_headers):

    with patch("backend.core.config.settings.MAX_AUDIO_SIZE_MB", 0.0001):
        wav_data = create_dummy_wav()
        files = {"file": ("test.wav", wav_data, "audio/wav")}
        data = {"name": "Big Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )
        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]


def test_upload_empty_file(client: TestClient, auth_headers):
    files = {"file": ("test.wav", b"", "audio/wav")}
    data = {"name": "Empty Voice", "consent_confirmed": "true"}
    response = client.post(
        "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 422
    assert "Empty file" in response.json()["detail"]


def test_upload_embedding_failure_deletes_orphaned_file(
    client: TestClient, auth_headers, tmp_path
):
    """A failed embedding extraction must not leave the uploaded file on disk."""
    with patch("backend.core.config.settings.UPLOAD_DIR", str(tmp_path)), patch(
        "backend.api.voice.embed_speaker_async", side_effect=RuntimeError("boom")
    ):
        wav_data = create_dummy_wav()
        files = {"file": ("fail.wav", wav_data, "audio/wav")}
        data = {"name": "Fail Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )

    assert response.status_code == 500
    remaining_files = list(tmp_path.rglob("*.wav"))
    assert remaining_files == [], f"Orphaned upload(s) left on disk: {remaining_files}"

    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    failed = [p for p in profiles if p["name"] == "Fail Voice"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"


def test_upload_queue_full_returns_429_and_deletes_orphaned_file(
    client: TestClient, auth_headers, tmp_path
):
    """HARDENING_PLAN.md H6: a full inference queue during embedding
    extraction maps to 429 and still cleans up the orphaned upload."""
    with patch("backend.core.config.settings.UPLOAD_DIR", str(tmp_path)), patch(
        "backend.api.voice.embed_speaker_async",
        side_effect=InferenceQueueFullError("simulated full queue"),
    ):
        wav_data = create_dummy_wav()
        files = {"file": ("busy.wav", wav_data, "audio/wav")}
        data = {"name": "Busy Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )

    assert response.status_code == 429
    remaining_files = list(tmp_path.rglob("*.wav"))
    assert remaining_files == [], f"Orphaned upload(s) left on disk: {remaining_files}"

    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    failed = [p for p in profiles if p["name"] == "Busy Voice"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"


def test_upload_timeout_returns_503_and_deletes_orphaned_file(
    client: TestClient, auth_headers, tmp_path
):
    """HARDENING_PLAN.md H6: an embedding-extraction timeout maps to 503
    and still cleans up the orphaned upload."""
    with patch("backend.core.config.settings.UPLOAD_DIR", str(tmp_path)), patch(
        "backend.api.voice.embed_speaker_async",
        side_effect=InferenceTimeoutError("simulated inference timeout"),
    ):
        wav_data = create_dummy_wav()
        files = {"file": ("slow.wav", wav_data, "audio/wav")}
        data = {"name": "Slow Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )

    assert response.status_code == 503
    remaining_files = list(tmp_path.rglob("*.wav"))
    assert remaining_files == [], f"Orphaned upload(s) left on disk: {remaining_files}"

    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    failed = [p for p in profiles if p["name"] == "Slow Voice"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"


def test_upload_extension_derived_from_magic_bytes_not_filename(
    client: TestClient, auth_headers, tmp_path
):
    """A client filename extension that disagrees with the real audio format
    (e.g. real WAV bytes under a ".mp3" name, or mixed-case ".WAV") must not
    dictate the stored extension — the magic bytes must, so the saved file and
    its embedding stay loadable via `np.load`."""
    with patch("backend.core.config.settings.UPLOAD_DIR", str(tmp_path)):
        wav_data = create_dummy_wav()
        files = {"file": ("voice.MP3", wav_data, "audio/wav")}
        data = {"name": "Mismatched Voice", "consent_confirmed": "true"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )

    assert response.status_code == 201
    assert response.json()["status"] == "ready"

    saved_files = list(tmp_path.rglob("*"))
    audio_files = [f for f in saved_files if f.suffix == ".wav" and f.is_file()]
    embed_files = [f for f in saved_files if f.name.endswith("_embed.npy")]
    assert len(audio_files) == 1, f"Expected one .wav file, found: {saved_files}"
    assert len(embed_files) == 1, f"Expected one _embed.npy file, found: {saved_files}"
    assert embed_files[0].name == audio_files[0].stem + "_embed.npy"
    assert not any(f.suffix == ".mp3" for f in saved_files)


def test_validate_audio_file_returns_extension_from_magic_bytes():
    """`validate_audio_file` must return the extension implied by the magic
    bytes, ignoring the client-supplied filename entirely."""
    from io import BytesIO

    from starlette.datastructures import UploadFile as StarletteUploadFile

    from backend.services.audio_processing import validate_audio_file

    wav_bytes = create_dummy_wav()
    upload = StarletteUploadFile(file=BytesIO(wav_bytes), filename="not_actually.mp3")
    upload.headers = {"content-type": "audio/wav"}

    assert validate_audio_file(upload) == ".wav"


def test_upload_unauthenticated(client: TestClient):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    data = {"name": "No Auth", "consent_confirmed": "true"}
    response = client.post("/api/v1/voice/upload", data=data, files=files)
    assert response.status_code == 401


def test_list_profiles_empty(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "empty@example.com",
            "password": "Password123!",
            "name": "Empty",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "empty@example.com", "password": "Password123!"},
    ).json()["access_token"]

    response = client.get(
        "/api/v1/voice/profiles", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == []


def test_list_profiles_after_upload(client: TestClient, auth_headers):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "My Voice", "consent_confirmed": "true"},
        files=files,
    )

    response = client.get("/api/v1/voice/profiles", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "id" in data[0]


def test_delete_profile_success(client: TestClient, auth_headers):
    wav_data = create_dummy_wav()
    files = {"file": ("delete_test.wav", wav_data, "audio/wav")}
    up_res = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "Del", "consent_confirmed": "true"},
        files=files,
    )
    profile_id = up_res.json()["id"]

    del_res = client.delete(
        f"/api/v1/voice/profiles/{profile_id}", headers=auth_headers
    )
    assert del_res.status_code == 200

    list_res = client.get("/api/v1/voice/profiles", headers=auth_headers)
    ids = [p["id"] for p in list_res.json()]
    assert profile_id not in ids


def test_delete_profile_not_found(client: TestClient, auth_headers):

    del_res = client.delete(
        f"/api/v1/voice/profiles/{uuid.uuid4()}", headers=auth_headers
    )
    assert del_res.status_code == 404


def test_delete_profile_wrong_user(client: TestClient, auth_headers):
    """User B must receive 404 when attempting to delete User A's profile."""
    # User A (auth_headers) creates a profile
    wav_data = create_dummy_wav()
    files = {"file": ("owner.wav", wav_data, "audio/wav")}
    up_res = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "Owner Voice", "consent_confirmed": "true"},
        files=files,
    )
    profile_id = up_res.json()["id"]

    # User B signs up and logs in
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "intruder@example.com",
            "password": "Password123!",
            "name": "Intruder",
        },
    )
    token_b = client.post(
        "/api/v1/auth/login",
        json={"email": "intruder@example.com", "password": "Password123!"},
    ).json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B attempts to delete User A's profile — must be rejected
    del_res = client.delete(f"/api/v1/voice/profiles/{profile_id}", headers=headers_b)
    assert del_res.status_code == 404

    # Confirm profile still belongs to User A and is intact
    list_res = client.get("/api/v1/voice/profiles", headers=auth_headers)
    ids = [p["id"] for p in list_res.json()]
    assert profile_id in ids


def test_librosa_preprocess_shape():
    """preprocess_audio must return a 1D float32 array at the encoder's level."""

    audio = preprocess_audio("backend/tests/fixtures/sample_5sec.wav")
    assert audio is not None, "preprocess_audio returned None for a valid WAV"
    assert audio.ndim == 1, f"Expected 1D array, got {audio.ndim}D"
    assert audio.dtype == np.float32, f"Expected float32, got {audio.dtype}"
    # A loud fixture is left at its own level, not scaled to full scale.
    assert np.max(np.abs(audio)) <= 1.0, "Audio samples exceed the [-1, 1] range"


# ---------------------------------------------------------------------------
# HARDENING_PLAN.md finding M4: duration bounds and blank-embedding rejection
# ---------------------------------------------------------------------------


def _wav_file(tmp_path, tone_seconds: float, silence_seconds: float = 0.0) -> str:
    """Write a 16 kHz mono WAV (tone then silence) and return its path."""
    t = np.arange(int(16000 * tone_seconds)) / 16000
    tone = (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    silence = np.zeros(int(16000 * silence_seconds), dtype="<i2")
    path = tmp_path / f"{uuid.uuid4()}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(np.concatenate([tone, silence]).tobytes())
    return str(path)


@pytest.mark.parametrize(
    "tone, silence",
    [
        (0.5, 0.0),  # too short
        (0.0, 5.0),  # entirely silent → trims to nothing
        (1.0, 10.0),  # long file, but under 2 s of actual speech
    ],
)
def test_preprocess_rejects_too_little_voiced_audio(tmp_path, tone, silence):
    """Audio with < MIN_VOICED_DURATION_SECONDS after trimming is a 422."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        preprocess_audio(_wav_file(tmp_path, tone, silence))
    assert exc.value.status_code == 422
    assert "too little speech" in exc.value.detail


def test_preprocess_accepts_audio_at_minimum_voiced_duration(tmp_path):
    """Just over the minimum passes, and a loud input keeps its own level."""
    audio = preprocess_audio(_wav_file(tmp_path, 2.5, 3.0))
    assert audio.ndim == 1 and len(audio) >= 2.0 * 16000
    # The fixture tone peaks at 0.5 (about -9 dBFS RMS), louder than the
    # encoder's -30 dBFS, so it is not touched: no peak normalisation.
    assert np.isclose(np.max(np.abs(audio)), 0.5, atol=0.01)


def test_preprocess_rejects_over_max_duration_before_decoding(tmp_path):
    """The cap uses the cheap header duration and never decodes an over-long file."""
    from fastapi import HTTPException

    path = _wav_file(tmp_path, 3.0)
    with patch("backend.core.config.settings.MAX_AUDIO_DURATION_SECONDS", 1.0), patch(
        "backend.services.audio_processing.librosa.load"
    ) as load:
        with pytest.raises(HTTPException) as exc:
            preprocess_audio(path)
    assert exc.value.status_code == 422
    assert "too long" in exc.value.detail
    load.assert_not_called()


@pytest.mark.parametrize("tone, silence", [(0.5, 0.0), (0.0, 5.0)])
def test_upload_rejects_unusable_audio_and_leaves_no_trace(
    client: TestClient, auth_headers, tmp_path, tone, silence
):
    """Short/silent uploads: 422, no profile row, and no audio kept on disk."""
    wav = open(_wav_file(tmp_path, tone, silence), "rb").read()
    upload_dir = tmp_path / "uploads"
    with patch("backend.core.config.settings.UPLOAD_DIR", str(upload_dir)):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Bad", "consent_confirmed": "true"},
            files={"file": ("v.wav", wav, "audio/wav")},
        )
    assert response.status_code == 422
    assert "too little speech" in response.json()["detail"]
    assert [p for p in upload_dir.rglob("*") if p.is_file()] == []
    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    assert profiles == []


@pytest.mark.parametrize(
    "bad_embedding",
    [
        np.zeros(256, dtype=np.float32),
        np.full(256, np.nan, dtype=np.float32),
        np.array([], dtype=np.float32),
    ],
    ids=["zeros", "nan", "empty"],
)
def test_upload_never_persists_blank_embedding_as_ready(
    client: TestClient, auth_headers, tmp_path, bad_embedding
):
    """A zero/NaN/empty embedding is a 422: no ready profile, no files kept."""
    upload_dir = tmp_path / "uploads"
    with patch("backend.core.config.settings.UPLOAD_DIR", str(upload_dir)), patch(
        "backend.api.voice.embed_speaker_async", return_value=bad_embedding
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Blank", "consent_confirmed": "true"},
            files={"file": ("v.wav", create_dummy_wav(), "audio/wav")},
        )
    assert response.status_code == 422
    assert "Could not extract a voice" in response.json()["detail"]
    assert [p for p in upload_dir.rglob("*") if p.is_file()] == []
    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    assert all(p["status"] != "ready" for p in profiles)
    assert profiles == []


def test_preprocess_failure_returns_generic_detail(tmp_path):
    """Undecodable audio: 422 with a generic detail, never the raw library error."""
    from fastapi import HTTPException

    secret = "/internal/path/codec-secret-xyz"
    with patch(
        "backend.services.audio_processing.librosa.get_duration",
        side_effect=RuntimeError(secret),
    ):
        with pytest.raises(HTTPException) as exc:
            preprocess_audio(str(tmp_path / "x.wav"))
    assert exc.value.status_code == 422
    assert secret not in exc.value.detail
    assert "RuntimeError" not in exc.value.detail


def test_upload_decode_failure_leaks_nothing_and_leaves_no_orphan(
    client: TestClient, auth_headers, tmp_path
):
    """API level: decode error -> generic 422, upload deleted, no profile row."""
    secret = "libsndfile-secret-error-abc"
    wav = open(_wav_file(tmp_path, 3.0, 0.0), "rb").read()
    upload_dir = tmp_path / "uploads"
    with patch("backend.core.config.settings.UPLOAD_DIR", str(upload_dir)), patch(
        "backend.services.audio_processing.librosa.load",
        side_effect=RuntimeError(secret),
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Broken", "consent_confirmed": "true"},
            files={"file": ("v.wav", wav, "audio/wav")},
        )
    assert response.status_code == 422
    assert secret not in response.text
    assert [p for p in upload_dir.rglob("*") if p.is_file()] == []
    assert client.get("/api/v1/voice/profiles", headers=auth_headers).json() == []
