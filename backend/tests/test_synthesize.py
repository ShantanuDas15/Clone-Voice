import io
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.services.tts_pipeline import (embed_speaker, load_models,
                                           save_output, synthesize_speech,
                                           vocode)


@pytest.fixture(scope="module", autouse=True)
def setup_models():
    load_models("cpu")


def test_embed_speaker_output_shape():
    audio = np.random.randn(16000).astype(np.float32)
    emb = embed_speaker(audio)
    assert emb.shape == (256,)


def test_save_output_creates_file():
    wav = np.random.randn(16000).astype(np.float32)
    path, duration = save_output(wav, 16000, "test_user")

    assert os.path.exists(path)
    assert duration == 1.0
    os.remove(path)


def test_save_output_returns_duration():
    wav = np.random.randn(8000).astype(np.float32)
    path, duration = save_output(wav, 16000, "test_user")

    assert duration == 0.5
    os.remove(path)


# --- Integration Tests ---


@pytest.fixture
def auth_headers_syn(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "syn@example.com",
            "password": "Password123!",
            "name": "Syn User",
        },
    )
    resp = client.post(
        "/api/auth/login", json={"email": "syn@example.com", "password": "Password123!"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


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


def upload_profile(client, headers):
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    up_res = client.post(
        "/api/voice/upload", headers=headers, data={"name": "Syn Voice"}, files=files
    )
    return up_res.json()["id"]


def test_synthesize_success(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    res = client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Hello world!"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"


def test_synthesize_creates_db_row(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Row Test"},
    )

    res = client.get("/api/synthesize/history", headers=auth_headers_syn)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_synthesize_invalid_profile(client: TestClient, auth_headers_syn):
    import uuid

    res = client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": str(uuid.uuid4()), "text": "Hello"},
    )
    assert res.status_code == 404


def test_synthesize_wrong_user_profile(client: TestClient, auth_headers_syn):
    client.post(
        "/api/auth/signup",
        json={
            "email": "other@example.com",
            "password": "Password123!",
            "name": "Other User",
        },
    )
    token2 = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "Password123!"},
    ).json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    profile_id = upload_profile(client, headers2)

    res = client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Hello"},
    )
    assert res.status_code == 403


def test_synthesize_empty_text(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    res = client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": ""},
    )
    assert res.status_code == 422


def test_synthesize_text_too_long(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    long_text = "a" * 501
    res = client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": long_text},
    )
    assert res.status_code == 422


def test_synthesize_unauthenticated(client: TestClient):
    import uuid

    res = client.post(
        "/api/synthesize", json={"voice_profile_id": str(uuid.uuid4()), "text": "Hello"}
    )
    assert res.status_code == 401


def test_history_empty(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "history@example.com",
            "password": "Password123!",
            "name": "Hist User",
        },
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "history@example.com", "password": "Password123!"},
    ).json()["access_token"]

    res = client.get(
        "/api/synthesize/history", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert len(res.json()) == 0


def test_history_after_synthesis(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Hist"},
    )

    res = client.get("/api/synthesize/history", headers=auth_headers_syn)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_history_pagination(client: TestClient, auth_headers_syn):
    res = client.get("/api/synthesize/history?limit=100", headers=auth_headers_syn)
    assert res.status_code == 200
    assert len(res.json()) <= 50


def test_history_excludes_soft_deleted(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    client.post(
        "/api/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Soft delete test"},
    )

    # Verify it exists in history
    res = client.get("/api/synthesize/history", headers=auth_headers_syn)
    assert len(res.json()) >= 1

    # Soft delete profile
    res_del = client.delete(
        f"/api/voice/profiles/{profile_id}", headers=auth_headers_syn
    )
    assert res_del.status_code == 200

    # Verify it is removed from history
    res_after = client.get("/api/synthesize/history", headers=auth_headers_syn)
    assert all(gen["voice_profile_id"] != profile_id for gen in res_after.json())
