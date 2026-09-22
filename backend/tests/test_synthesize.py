"""Integration tests for the /api/v1/synthesize endpoint."""

import io
import uuid
import wave
from unittest.mock import patch

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient

from backend.services.tts_pipeline import (InferenceQueueFullError,
                                           InferenceTimeoutError,
                                           load_mock_models)


@pytest.fixture(scope="module", autouse=True)
def setup_models_for_synthesize():
    """Inject lightweight mock models once for the entire synthesis test module."""
    load_mock_models("cpu")


@pytest.fixture
def auth_headers_syn(client: TestClient):
    """Create and authenticate a test user for synthesis tests."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "syn@example.com",
            "password": "Password123!",
            "name": "Syn User",
        },
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "syn@example.com", "password": "Password123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


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


def upload_profile(client: TestClient, headers: dict) -> str:
    """Helper: upload a dummy WAV and return the new voice profile id."""
    wav_data = create_dummy_wav()
    files = {"file": ("test.wav", wav_data, "audio/wav")}
    up_res = client.post(
        "/api/v1/voice/upload", headers=headers, data={"name": "Syn Voice"}, files=files
    )
    return up_res.json()["id"]


def test_synthesize_success(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Hello world!"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"


def test_synthesize_creates_db_row(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Row Test"},
    )

    res = client.get("/api/v1/synthesize/history", headers=auth_headers_syn)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_synthesize_invalid_profile(client: TestClient, auth_headers_syn):
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": str(uuid.uuid4()), "text": "Hello"},
    )
    assert res.status_code == 404


def test_synthesize_wrong_user_profile(client: TestClient, auth_headers_syn):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "other@example.com",
            "password": "Password123!",
            "name": "Other User",
        },
    )
    token2 = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "Password123!"},
    ).json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    profile_id = upload_profile(client, headers2)

    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Hello"},
    )
    assert res.status_code == 403


def test_synthesize_empty_text(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": ""},
    )
    assert res.status_code == 422


def test_synthesize_text_too_long(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    long_text = "a" * 501
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": long_text},
    )
    assert res.status_code == 422


def test_synthesize_unauthenticated(client: TestClient):
    res = client.post(
        "/api/v1/synthesize",
        json={"voice_profile_id": str(uuid.uuid4()), "text": "Hello"},
    )
    assert res.status_code == 401


def test_history_empty(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "history@example.com",
            "password": "Password123!",
            "name": "Hist User",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "history@example.com", "password": "Password123!"},
    ).json()["access_token"]

    res = client.get(
        "/api/v1/synthesize/history", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert len(res.json()) == 0


def test_history_after_synthesis(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Hist"},
    )

    res = client.get("/api/v1/synthesize/history", headers=auth_headers_syn)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_history_pagination(client: TestClient, auth_headers_syn):
    res = client.get("/api/v1/synthesize/history?limit=100", headers=auth_headers_syn)
    assert res.status_code == 200
    assert len(res.json()) <= 50


@pytest.mark.parametrize("query", ["limit=-1", "limit=0", "offset=-1"])
def test_history_rejects_out_of_bounds_pagination(
    client: TestClient, auth_headers_syn, query
):
    """L3: negative limit/offset (or limit=0) is a 422, not a 500 from the DB layer."""
    res = client.get(f"/api/v1/synthesize/history?{query}", headers=auth_headers_syn)
    assert res.status_code == 422


def test_history_accepts_boundary_pagination_values(
    client: TestClient, auth_headers_syn
):
    """limit=1 and offset=0 are the lowest valid values and must still succeed."""
    res = client.get(
        "/api/v1/synthesize/history?limit=1&offset=0", headers=auth_headers_syn
    )
    assert res.status_code == 200


def test_history_excludes_soft_deleted(client: TestClient, auth_headers_syn):
    profile_id = upload_profile(client, auth_headers_syn)
    client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": "Soft delete test"},
    )

    res = client.get("/api/v1/synthesize/history", headers=auth_headers_syn)
    assert len(res.json()) >= 1

    res_del = client.delete(
        f"/api/v1/voice/profiles/{profile_id}", headers=auth_headers_syn
    )
    assert res_del.status_code == 200

    res_after = client.get("/api/v1/synthesize/history", headers=auth_headers_syn)
    assert all(gen["voice_profile_id"] != profile_id for gen in res_after.json())


def test_synthesize_cuda_oom_returns_503_and_records_failed_generation(
    client: TestClient, auth_headers_syn
):
    """HARDENING_PLAN.md H3: CUDA OOM during inference maps to 503, not a
    bare 500, and leaves a `status="failed"` audit row instead of no row."""
    profile_id = upload_profile(client, auth_headers_syn)

    with patch(
        "backend.api.synthesize.run_inference_pipeline",
        side_effect=torch.cuda.OutOfMemoryError("simulated CUDA OOM"),
    ), patch("backend.api.synthesize.free_gpu_memory") as mock_free:
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers_syn,
            json={"voice_profile_id": profile_id, "text": "OOM test"},
        )

    assert res.status_code == 503
    mock_free.assert_called_once()

    history = client.get("/api/v1/synthesize/history", headers=auth_headers_syn).json()
    failed = [g for g in history if g["input_text"] == "OOM test"]
    assert len(failed) == 1
    assert failed[0]["output_filename"] == ""
    assert failed[0]["duration_seconds"] is None


def test_synthesize_queue_full_returns_429_without_failed_generation(
    client: TestClient, auth_headers_syn
):
    """HARDENING_PLAN.md H6: a full inference queue maps to 429, and — since
    no inference was ever attempted — must not leave a failed audit row."""
    profile_id = upload_profile(client, auth_headers_syn)

    with patch(
        "backend.api.synthesize.run_inference_pipeline",
        side_effect=InferenceQueueFullError("simulated full queue"),
    ):
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers_syn,
            json={"voice_profile_id": profile_id, "text": "Queue full test"},
        )

    assert res.status_code == 429

    history = client.get("/api/v1/synthesize/history", headers=auth_headers_syn).json()
    failed = [g for g in history if g["input_text"] == "Queue full test"]
    assert len(failed) == 0


def test_synthesize_timeout_returns_503_and_records_failed_generation(
    client: TestClient, auth_headers_syn
):
    """HARDENING_PLAN.md H6: an inference acquisition/forward-pass timeout
    maps to 503 and leaves a `status="failed"` audit row, same as OOM."""
    profile_id = upload_profile(client, auth_headers_syn)

    with patch(
        "backend.api.synthesize.run_inference_pipeline",
        side_effect=InferenceTimeoutError("simulated inference timeout"),
    ), patch("backend.api.synthesize.free_gpu_memory") as mock_free:
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers_syn,
            json={"voice_profile_id": profile_id, "text": "Timeout test"},
        )

    assert res.status_code == 503
    mock_free.assert_called_once()

    history = client.get("/api/v1/synthesize/history", headers=auth_headers_syn).json()
    failed = [g for g in history if g["input_text"] == "Timeout test"]
    assert len(failed) == 1
    assert failed[0]["output_filename"] == ""
    assert failed[0]["duration_seconds"] is None


def test_synthesize_model_error_returns_500_and_records_failed_generation(
    client: TestClient, auth_headers_syn
):
    """HARDENING_PLAN.md H3: a non-OOM inference failure maps to 500 with a
    controlled detail message, and also leaves a `status="failed"` row."""
    profile_id = upload_profile(client, auth_headers_syn)

    with patch(
        "backend.api.synthesize.run_inference_pipeline",
        side_effect=RuntimeError("simulated model failure with sensitive internals"),
    ), patch("backend.api.synthesize.free_gpu_memory") as mock_free:
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers_syn,
            json={"voice_profile_id": profile_id, "text": "Model error test"},
        )

    assert res.status_code == 500
    assert "sensitive internals" not in res.json()["detail"]
    mock_free.assert_called_once()

    history = client.get("/api/v1/synthesize/history", headers=auth_headers_syn).json()
    failed = [g for g in history if g["input_text"] == "Model error test"]
    assert len(failed) == 1
    assert failed[0]["output_filename"] == ""
    assert failed[0]["duration_seconds"] is None


@pytest.mark.parametrize("profile_status", ["failed", "processing"])
def test_synthesize_non_ready_profile_returns_409(
    client: TestClient, auth_headers_syn, db_session, profile_status
):
    """A non-`ready` profile is a 409 (not a 500), runs no inference, adds no row."""
    from backend.models.voice_profile import VoiceProfile

    profile_id = upload_profile(client, auth_headers_syn)
    profile = db_session.query(VoiceProfile).filter_by(id=uuid.UUID(profile_id)).one()
    profile.status = profile_status
    profile.embedding_path = ""
    db_session.commit()

    with patch("backend.api.synthesize.run_inference_pipeline") as mock_run:
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers_syn,
            json={"voice_profile_id": profile_id, "text": "Hello"},
        )

    assert res.status_code == 409
    assert "not ready" in res.json()["detail"]
    mock_run.assert_not_called()
    history = client.get("/api/v1/synthesize/history", headers=auth_headers_syn)
    assert history.json() == []


def test_synthesize_other_users_non_ready_profile_still_403(
    client: TestClient, auth_headers_syn, db_session
):
    """Ownership is checked before status, so a foreign failed profile stays a 403."""
    from backend.models.user import User
    from backend.models.voice_profile import VoiceProfile

    other = User(email="own2@example.com", name="Own", provider="local")
    db_session.add(other)
    db_session.commit()
    profile = VoiceProfile(
        user_id=other.id,
        name="x",
        audio_sample_path="",
        embedding_path="",
        status="failed",
    )
    db_session.add(profile)
    db_session.commit()

    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": str(profile.id), "text": "Hello"},
    )
    assert res.status_code == 403
