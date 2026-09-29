"""HARDENING_PLAN.md P2-L2: DB failures after inference never leak orphans or mask status codes."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.core.db_errors import (DB_RETRY_AFTER_SECONDS,
                                    DB_UNAVAILABLE_DETAIL)
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


def _integrity_error(*_args, **_kwargs):
    """Raise a non-transient DB error: retrying will not help."""
    raise IntegrityError("stmt", {}, Exception("constraint"))


def _synthesize(client: TestClient, headers: dict, profile_id: str, text: str):
    """POST a synthesis request."""
    return client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile_id, "text": text},
    )


def test_synthesize_persist_outage_returns_503_and_removes_output(
    client: TestClient, auth_headers_syn, tmp_path  # noqa: F811
):
    """A database outage while saving the result is a retryable 503, and the
    synthesized WAV that no row will reference is deleted."""
    profile_id = upload_profile(client, auth_headers_syn)
    with patch("backend.api.synthesize._persist_generation", side_effect=_db_error):
        res = _synthesize(client, auth_headers_syn, profile_id, "persist fails")
    assert res.status_code == 503
    assert res.headers["Retry-After"] == str(DB_RETRY_AFTER_SECONDS)
    assert res.json()["detail"] == DB_UNAVAILABLE_DETAIL
    outputs = tmp_path / "outputs"
    assert list(outputs.rglob("*.wav")) == []


def test_synthesize_persist_non_transient_error_stays_500_and_removes_output(
    client: TestClient, auth_headers_syn, tmp_path  # noqa: F811
):
    """A constraint error will not go away on retry, so it is not a 503."""
    profile_id = upload_profile(client, auth_headers_syn)
    with patch(
        "backend.api.synthesize._persist_generation", side_effect=_integrity_error
    ):
        res = _synthesize(client, auth_headers_syn, profile_id, "persist fails")
    assert res.status_code == 500
    assert res.json()["detail"] == "Failed to save the synthesized audio"
    assert "Retry-After" not in res.headers
    assert list((tmp_path / "outputs").rglob("*.wav")) == []


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


@pytest.mark.parametrize(
    "error, status, detail",
    [
        (_db_error, 503, DB_UNAVAILABLE_DETAIL),
        (_integrity_error, 500, "Failed to save voice profile"),
    ],
)
def test_upload_persist_failure_status_and_cleanup(
    client: TestClient, auth_headers_syn, tmp_path, error, status, detail  # noqa: F811
):
    """A failed ready-profile insert removes the WAV and embedding; an outage
    is a retryable 503, any other database error a 500."""
    files = {"file": ("t.wav", create_dummy_wav(), "audio/wav")}
    with patch("backend.api.voice._persist_profile", side_effect=error):
        res = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers_syn,
            data={"name": "Persist Fail", "consent_confirmed": "true"},
            files=files,
        )
    assert res.status_code == status
    assert res.json()["detail"] == detail
    assert ("Retry-After" in res.headers) is (status == 503)
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
            data={"name": "Mask", "consent_confirmed": "true"},
            files=files,
        )
    assert res.status_code == expected
