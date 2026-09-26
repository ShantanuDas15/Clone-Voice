"""HARDENING_PLAN.md P2-L2: DB failures after inference never leak orphans or mask status codes."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.services.tts_pipeline import (InferenceQueueFullError,
                                           InferenceTimeoutError,
                                           load_mock_models)
from backend.tests.test_synthesize import auth_headers_syn  # noqa: F401
from backend.tests.test_synthesize import create_dummy_wav, upload_profile


@pytest.fixture(scope="module", autouse=True)
def _mock_models():
    """Inject lightweight mock models for this module."""
    load_mock_models("cpu")


def _db_error(*_args, **_kwargs):
    """Raise the DB error a dropped connection produces."""
    raise OperationalError("stmt", {}, Exception("db down"))


def _synthesize(client: TestClient, headers: dict, profile_id: str, text: str):
    """POST a synthesis request."""
    return client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile_id, "text": text},
    )


def test_synthesize_persist_failure_returns_500_and_removes_output(
    client: TestClient, auth_headers_syn, tmp_path  # noqa: F811
):
    """A failed completed-row insert returns 500 and deletes the synthesized WAV."""
    profile_id = upload_profile(client, auth_headers_syn)
    with patch("backend.api.synthesize._persist_generation", side_effect=_db_error):
        res = _synthesize(client, auth_headers_syn, profile_id, "persist fails")
    assert res.status_code == 500
    assert res.json()["detail"] == "Failed to save the synthesized audio"
    outputs = tmp_path / "outputs"
    assert list(outputs.rglob("*.wav")) == []


@pytest.mark.parametrize(
    "exc,expected",
    [
        (InferenceTimeoutError("t"), 503),
        (RuntimeError("boom"), 500),
    ],
)
def test_failed_generation_db_error_does_not_mask_status(
    client: TestClient, auth_headers_syn, exc, expected  # noqa: F811
):
    """A DB error while recording the failure keeps the original 503/500."""
    profile_id = upload_profile(client, auth_headers_syn)
    with patch("backend.api.synthesize.run_inference_pipeline", side_effect=exc), patch(
        "backend.api.synthesize.free_gpu_memory"
    ) as mock_free, patch("sqlalchemy.orm.Session.commit", side_effect=_db_error):
        res = _synthesize(client, auth_headers_syn, profile_id, "mask test")
    assert res.status_code == expected
    mock_free.assert_called_once()


def test_upload_persist_failure_returns_500_and_removes_files(
    client: TestClient, auth_headers_syn, tmp_path  # noqa: F811
):
    """A failed ready-profile insert returns 500 and removes the WAV and embedding."""
    files = {"file": ("t.wav", create_dummy_wav(), "audio/wav")}
    with patch("backend.api.voice._persist_profile", side_effect=_db_error):
        res = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers_syn,
            data={"name": "Persist Fail"},
            files=files,
        )
    assert res.status_code == 500
    assert res.json()["detail"] == "Failed to save voice profile"
    uploads = tmp_path / "uploads"
    assert list(uploads.rglob("*")) == [] or all(p.is_dir() for p in uploads.rglob("*"))


@pytest.mark.parametrize(
    "exc,expected",
    [
        (InferenceQueueFullError("q"), 429),
        (InferenceTimeoutError("t"), 503),
        (RuntimeError("boom"), 500),
    ],
)
def test_upload_failed_profile_db_error_does_not_mask_status(
    client: TestClient, auth_headers_syn, exc, expected  # noqa: F811
):
    """A DB error while recording the failed profile keeps the original 429/503/500."""
    files = {"file": ("t.wav", create_dummy_wav(), "audio/wav")}
    with patch("backend.api.voice.embed_speaker_async", side_effect=exc), patch(
        "backend.api.voice._persist_profile", side_effect=_db_error
    ):
        res = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers_syn,
            data={"name": "Mask"},
            files=files,
        )
    assert res.status_code == expected
