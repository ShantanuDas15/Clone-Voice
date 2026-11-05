"""Each generation records which engine spoke, and says so (SPEECH_QUALITY_PLAN.md S7.1)."""

import asyncio
import io
import uuid
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.models.generation import Generation
from backend.services import tts_engine, tts_pipeline
from backend.services.tts_engine import EngineUnavailableError
from backend.services.tts_pipeline import InferenceResult
from backend.tests.test_chatterbox_engine import (TOKEN, _Model, _Server,
                                                  _tone, _wav)
from backend.tests.test_engine_fallback import PRIMARY, _FlakyEngine

EMB = np.ones(256, np.float32) / 16.0


@pytest.fixture
def headers(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "eng@example.com", "password": "Password123!", "name": "E"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "eng@example.com", "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def profile(client, headers) -> str:
    tts_pipeline.load_mock_models("cpu")
    return client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "E", "consent_confirmed": "true"},
        files={"file": ("a.wav", _wav(_tone(4.0, amp=0.5)), "audio/wav")},
    ).json()["id"]


def _synth(client, headers, profile, text="Hello there."):
    return client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile, "text": text},
    )


def _row(db, text):
    db.expire_all()
    return db.query(Generation).filter(Generation.input_text == text).one()


# --- the pipeline result -----------------------------------------------------


def test_the_result_still_unpacks_as_a_pair_and_carries_the_engine():
    result = InferenceResult("/a.wav", 1.5, "sv2tts", "1", None)
    path, duration = result
    assert (path, duration) == ("/a.wav", 1.5) and len(result) == 2
    assert (result.engine, result.engine_version, result.engine_fallback_from) == (
        "sv2tts",
        "1",
        None,
    )


def test_the_pipeline_names_sv2tts_when_it_spoke():
    tts_pipeline.load_mock_models("cpu")
    result = asyncio.run(tts_pipeline.run_inference_pipeline("Hello.", EMB, "who"))
    assert (result.engine, result.engine_version, result.engine_fallback_from) == (
        "sv2tts",
        "1",
        None,
    )


def test_the_pipeline_names_the_fallback_and_what_it_replaced(monkeypatch):
    tts_pipeline.load_mock_models("cpu")
    monkeypatch.setattr(
        tts_engine, "get_engine", lambda: _FlakyEngine(EngineUnavailableError("down"))
    )
    result = asyncio.run(tts_pipeline.run_inference_pipeline("Hello.", EMB, "who"))
    assert (result.engine, result.engine_fallback_from) == ("sv2tts", PRIMARY)


def test_the_pipeline_names_a_worker_engine(monkeypatch, tmp_path):
    server = _Server(_Model())
    monkeypatch.setattr(settings, "TTS_ENGINE", PRIMARY)
    monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), _tone(6.0), 16000)
    try:
        result = asyncio.run(
            tts_pipeline.run_inference_pipeline(
                "Hello.", EMB, "who", reference_audio_path=str(ref)
            )
        )
    finally:
        server.stop()
    assert (result.engine, result.engine_version, result.engine_fallback_from) == (
        PRIMARY,
        "1",
        None,
    )


# --- the API ----------------------------------------------------------------


def test_a_completed_generation_records_the_engine_and_says_so(
    client, headers, profile, db_session
):
    response = _synth(client, headers, profile, "Recorded engine")
    assert response.status_code == 200
    assert response.headers["X-Voice-Engine"] == "sv2tts"
    assert "X-Voice-Engine-Fallback" not in response.headers
    row = _row(db_session, "Recorded engine")
    assert (row.engine, row.engine_version, row.engine_fallback_from) == (
        "sv2tts",
        "1",
        None,
    )


def test_a_fallback_is_recorded_and_visible(
    client, headers, profile, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_ENGINE", PRIMARY)
    monkeypatch.setattr(
        settings, "TTS_WORKER_URL", "http://127.0.0.1:9"
    )  # nothing listens
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    response = _synth(client, headers, profile, "Backup voice")
    assert response.status_code == 200
    assert response.headers["X-Voice-Engine"] == "sv2tts"
    assert response.headers["X-Voice-Engine-Fallback"] == PRIMARY
    assert (
        sf.info(io.BytesIO(response.content)).samplerate == settings.VOCODER_SAMPLE_RATE
    )
    row = _row(db_session, "Backup voice")
    assert (row.engine, row.engine_fallback_from) == ("sv2tts", PRIMARY)


def test_history_shows_which_engine_spoke(client, headers, profile, monkeypatch):
    _synth(client, headers, profile, "Normal one")
    monkeypatch.setattr(settings, "TTS_ENGINE", PRIMARY)
    monkeypatch.setattr(settings, "TTS_WORKER_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    _synth(client, headers, profile, "Backup one")
    rows = {
        r["input_text"]: r
        for r in client.get("/api/v1/synthesize/history", headers=headers).json()
    }
    assert (
        rows["Normal one"]["engine"],
        rows["Normal one"]["engine_fallback_from"],
    ) == ("sv2tts", None)
    assert (
        rows["Backup one"]["engine"],
        rows["Backup one"]["engine_fallback_from"],
    ) == ("sv2tts", PRIMARY)


def test_a_failed_generation_records_the_engine_that_was_asked(
    client, headers, profile, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_ENGINE", PRIMARY)
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "none")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    assert _synth(client, headers, profile, "Asked and failed").status_code == 503
    row = _row(db_session, "Asked and failed")
    assert (row.status, row.engine, row.engine_version) == ("failed", PRIMARY, None)


def test_a_pipeline_double_that_returns_a_plain_pair_leaves_the_columns_empty(
    client, headers, profile, db_session, tmp_path
):
    out = tmp_path / "outputs" / "x.wav"
    out.parent.mkdir(parents=True)
    sf.write(str(out), _tone(1.0), 16000)

    async def plain(*args, **kwargs):
        return str(out), 1.0

    with patch("backend.api.synthesize.run_inference_pipeline", plain):
        response = _synth(client, headers, profile, "Plain pair")
    assert response.status_code == 200 and "X-Voice-Engine" not in response.headers
    row = _row(db_session, "Plain pair")
    assert (row.engine, row.engine_version, row.engine_fallback_from) == (
        None,
        None,
        None,
    )


def test_old_rows_without_an_engine_show_null_in_history(
    client, headers, profile, db_session
):
    from backend.models.user import User

    user = db_session.query(User).one()
    db_session.add(
        Generation(
            user_id=user.id,
            voice_profile_id=uuid.UUID(profile),
            input_text="Before engines",
            status="completed",
        )
    )
    db_session.commit()
    rows = {
        r["input_text"]: r
        for r in client.get("/api/v1/synthesize/history", headers=headers).json()
    }
    assert (
        rows["Before engines"]["engine"] is None
        and rows["Before engines"]["engine_fallback_from"] is None
    )


def test_the_browser_may_read_the_engine_headers(client, headers, profile):
    response = client.options(
        "/api/v1/synthesize",
        headers={
            "Origin": settings.ALLOWED_ORIGINS[0],
            "Access-Control-Request-Method": "POST",
        },
    )
    exposed = client.post(
        "/api/v1/synthesize",
        headers={**headers, "Origin": settings.ALLOWED_ORIGINS[0]},
        json={"voice_profile_id": profile, "text": "Cors check"},
    ).headers.get("access-control-expose-headers", "")
    assert response.status_code in (200, 204)
    assert "X-Voice-Engine" in exposed and "X-Voice-Engine-Fallback" in exposed
