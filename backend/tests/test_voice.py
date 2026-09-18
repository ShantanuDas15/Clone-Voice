import io
import os
import uuid
import wave
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.services.audio_processing import preprocess_audio
from backend.services.tts_pipeline import (InferenceQueueFullError,
                                           InferenceTimeoutError)


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


def create_dummy_wav(size_bytes=1000):

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00" * size_bytes)
    buf.seek(0)
    return buf.read()


def test_upload_valid_wav(client: TestClient, auth_headers):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    data = {"name": "My Voice"}

    response = client.post(
        "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["name"] == "My Voice"
    assert res_data["status"] == "ready"
    assert "id" in res_data


def test_upload_valid_mp3(client: TestClient, auth_headers):

    with patch("backend.api.voice.preprocess_audio") as mock_pre:
        mock_pre.return_value = None
        files = {"file": ("test.mp3", b"ID3 dummy mp3 data", "audio/mp3")}
        data = {"name": "MP3 Voice"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )
        assert response.status_code == 201


def test_upload_invalid_format_txt(client: TestClient, auth_headers):
    files = {"file": ("test.txt", b"hello text", "text/plain")}
    data = {"name": "Text Voice"}
    response = client.post(
        "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 422
    assert "Invalid audio format" in response.json()["detail"]


def test_upload_oversized_file(client: TestClient, auth_headers):

    with patch("backend.core.config.settings.MAX_AUDIO_SIZE_MB", 0.0001):
        wav_data = create_dummy_wav(size_bytes=500)
        files = {"file": ("test.wav", wav_data, "audio/wav")}
        data = {"name": "Big Voice"}
        response = client.post(
            "/api/v1/voice/upload", headers=auth_headers, data=data, files=files
        )
        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]


def test_upload_empty_file(client: TestClient, auth_headers):
    files = {"file": ("test.wav", b"", "audio/wav")}
    data = {"name": "Empty Voice"}
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
        data = {"name": "Fail Voice"}
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
        data = {"name": "Busy Voice"}
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
        data = {"name": "Slow Voice"}
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
        data = {"name": "Mismatched Voice"}
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
    data = {"name": "No Auth"}
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
        data={"name": "My Voice"},
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
        "/api/v1/voice/upload", headers=auth_headers, data={"name": "Del"}, files=files
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
        data={"name": "Owner Voice"},
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
    """preprocess_audio must return a 1D float32 array normalized to [-1.0, 1.0]."""

    audio = preprocess_audio("backend/tests/fixtures/sample_5sec.wav")
    assert audio is not None, "preprocess_audio returned None for a valid WAV"
    assert audio.ndim == 1, f"Expected 1D array, got {audio.ndim}D"
    assert audio.dtype == np.float32, f"Expected float32, got {audio.dtype}"
    assert np.max(np.abs(audio)) <= 1.0, "Audio samples exceed normalized [-1, 1] range"
