"""HARDENING_PLAN.md finding P2-M1: no DB transaction is held during inference."""

from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.tests.test_synthesize import create_dummy_wav, upload_profile


@pytest.fixture
def auth_headers(client: TestClient):
    """Sign up and log in a throwaway user, returning bearer headers."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": "m1@example.com", "password": "Password123!", "name": "M1"},
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "m1@example.com", "password": "Password123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_synthesize_holds_no_transaction_during_inference(
    client: TestClient, db_session, auth_headers, tmp_path
):
    """The session must be out of its transaction while inference runs, and
    still persist the completed generation afterwards."""
    profile_id = upload_profile(client, auth_headers)
    out_path = tmp_path / "out.wav"
    sf.write(str(out_path), np.zeros(1600, dtype="float32"), 16000)
    seen = {}

    async def fake_inference(text, embedding, user_id):
        seen["in_transaction"] = db_session.in_transaction()
        return str(out_path), 0.1

    with patch("backend.api.synthesize.run_inference_pipeline", fake_inference):
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers,
            json={"voice_profile_id": profile_id, "text": "release the connection"},
        )

    assert res.status_code == 200
    assert seen["in_transaction"] is False
    history = client.get("/api/v1/synthesize/history", headers=auth_headers).json()
    assert [g["input_text"] for g in history] == ["release the connection"]


def test_synthesize_failure_path_still_records_failed_generation(
    client: TestClient, db_session, auth_headers
):
    """Releasing the connection early must not break the error-path audit row."""
    profile_id = upload_profile(client, auth_headers)
    seen = {}

    async def failing_inference(text, embedding, user_id):
        seen["in_transaction"] = db_session.in_transaction()
        raise RuntimeError("boom")

    with patch("backend.api.synthesize.run_inference_pipeline", failing_inference):
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers,
            json={"voice_profile_id": profile_id, "text": "will fail"},
        )

    assert res.status_code == 500
    assert seen["in_transaction"] is False
    history = client.get("/api/v1/synthesize/history", headers=auth_headers).json()
    assert [g["input_text"] for g in history] == ["will fail"]


def test_upload_holds_no_transaction_during_embedding(
    client: TestClient, db_session, auth_headers
):
    """/voice/upload must release the connection before the embedding runs
    and still persist the profile afterwards."""
    seen = {}

    async def fake_embed(audio):
        seen["in_transaction"] = db_session.in_transaction()
        return np.ones(256, dtype=np.float32)

    with patch("backend.api.voice.embed_speaker_async", fake_embed):
        res = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Release Voice"},
            files={"file": ("test.wav", create_dummy_wav(), "audio/wav")},
        )

    assert res.status_code == 201
    assert seen["in_transaction"] is False
    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    assert [p["name"] for p in profiles] == ["Release Voice"]
