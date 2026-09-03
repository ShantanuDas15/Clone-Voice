import io
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_headers(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "voice@example.com",
            "password": "Password123!",
            "name": "Voice User",
        },
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "voice@example.com", "password": "Password123!"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_dummy_wav(size_bytes=1000):
    import wave

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
        "/api/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 201
    res_data = response.json()
    assert res_data["name"] == "My Voice"
    assert res_data["status"] == "ready"
    assert "id" in res_data


def test_upload_valid_mp3(client: TestClient, auth_headers):
    from unittest.mock import patch

    with patch("backend.api.voice.preprocess_audio") as mock_pre:
        mock_pre.return_value = None
        files = {"file": ("test.mp3", b"dummy mp3 data", "audio/mp3")}
        data = {"name": "MP3 Voice"}
        response = client.post(
            "/api/voice/upload", headers=auth_headers, data=data, files=files
        )
        assert response.status_code == 201


def test_upload_invalid_format_txt(client: TestClient, auth_headers):
    files = {"file": ("test.txt", b"hello text", "text/plain")}
    data = {"name": "Text Voice"}
    response = client.post(
        "/api/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 422
    assert "Invalid audio format" in response.json()["detail"]


def test_upload_oversized_file(client: TestClient, auth_headers):
    from unittest.mock import patch

    with patch("backend.core.config.settings.MAX_AUDIO_SIZE_MB", 0.0001):
        wav_data = create_dummy_wav(size_bytes=500)
        files = {"file": ("test.wav", wav_data, "audio/wav")}
        data = {"name": "Big Voice"}
        response = client.post(
            "/api/voice/upload", headers=auth_headers, data=data, files=files
        )
        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]


def test_upload_empty_file(client: TestClient, auth_headers):
    files = {"file": ("test.wav", b"", "audio/wav")}
    data = {"name": "Empty Voice"}
    response = client.post(
        "/api/voice/upload", headers=auth_headers, data=data, files=files
    )
    assert response.status_code == 422
    assert "Empty file" in response.json()["detail"]


def test_upload_unauthenticated(client: TestClient):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    data = {"name": "No Auth"}
    response = client.post("/api/voice/upload", data=data, files=files)
    assert response.status_code == 401


def test_list_profiles_empty(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "empty@example.com",
            "password": "Password123!",
            "name": "Empty",
        },
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "empty@example.com", "password": "Password123!"},
    ).json()["access_token"]

    response = client.get(
        "/api/voice/profiles", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json() == []


def test_list_profiles_after_upload(client: TestClient, auth_headers):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    client.post(
        "/api/voice/upload",
        headers=auth_headers,
        data={"name": "My Voice"},
        files=files,
    )

    response = client.get("/api/voice/profiles", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "id" in data[0]


def test_delete_profile_success(client: TestClient, auth_headers):
    wav_data = create_dummy_wav()
    files = {"file": ("delete_test.wav", wav_data, "audio/wav")}
    up_res = client.post(
        "/api/voice/upload", headers=auth_headers, data={"name": "Del"}, files=files
    )
    profile_id = up_res.json()["id"]

    del_res = client.delete(f"/api/voice/profiles/{profile_id}", headers=auth_headers)
    assert del_res.status_code == 200

    list_res = client.get("/api/voice/profiles", headers=auth_headers)
    ids = [p["id"] for p in list_res.json()]
    assert profile_id not in ids


def test_delete_profile_not_found(client: TestClient, auth_headers):
    import uuid

    del_res = client.delete(f"/api/voice/profiles/{uuid.uuid4()}", headers=auth_headers)
    assert del_res.status_code == 404
