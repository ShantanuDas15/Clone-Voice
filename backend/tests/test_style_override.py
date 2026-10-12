"""The user's emotion and intensity on a synthesis request (SPEECH_QUALITY_PLAN.md S5.4a)."""

import asyncio
import os
import uuid

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import synthesize as synthesize_api
from backend.core.config import settings
from backend.schemas.synthesize import SynthesizeRequest
from backend.services import styled_synthesis, tts_pipeline
from backend.services.text_analysis import (EMOTIONS, StyleOverride, analyze,
                                            apply_override)
from backend.services.tts_pipeline import InferenceResult
from backend.tests.test_chatterbox_engine import (EMB, TOKEN, _Server, _tone,
                                                  _wav)
from backend.tests.test_styled_synthesis import _OriginalModel, _Recorder

PROFILE = str(uuid.uuid4())


# --- the pure override --------------------------------------------------------


def test_a_named_emotion_replaces_the_detected_one():
    plain = analyze("The meeting is at noon.")
    angry = apply_override(plain, StyleOverride("angry"))
    assert plain.emotion == "neutral" and angry.emotion == "angry"
    assert angry.arousal > plain.arousal and angry.valence < 0
    assert "requested: angry" in angry.cues


def test_a_named_emotion_matches_what_the_analysis_gives_a_detected_one():
    detected = analyze("I hate this!")
    forced = apply_override(
        analyze("I hate this!"), StyleOverride("angry", detected.intensity)
    )
    assert (forced.emotion, forced.arousal) == (detected.emotion, detected.arousal)


def test_intensity_scales_the_energy():
    base = analyze("It is fine.")
    low = apply_override(base, StyleOverride("angry", 0.5))
    high = apply_override(base, StyleOverride("angry", 1.0))
    assert high.arousal > low.arousal
    assert apply_override(base, StyleOverride("angry")).intensity == 0.7


def test_sad_lowers_the_energy_and_neutral_resets_it():
    shouted = analyze("I hate this!!")
    assert apply_override(shouted, StyleOverride("sad", 1.0)).arousal < shouted.arousal
    neutral = apply_override(shouted, StyleOverride("neutral"))
    assert neutral.emotion == "neutral" and neutral.intensity == 0.0


@pytest.mark.parametrize("emotion", EMOTIONS)
def test_every_emotion_is_accepted(emotion):
    result = apply_override(analyze("Hello there."), StyleOverride(emotion, 0.9))
    assert 0.0 <= result.arousal <= 1.0 and result.emotion == emotion


# --- the request ----------------------------------------------------------------


def test_the_request_defaults_to_auto():
    req = SynthesizeRequest(voice_profile_id=PROFILE, text="Hi")
    assert (req.emotion, req.intensity) == ("auto", None)


def test_a_named_emotion_with_an_intensity_is_valid():
    req = SynthesizeRequest(
        voice_profile_id=PROFILE, text="Hi", emotion="sad", intensity=0.4
    )
    assert (req.emotion, req.intensity) == ("sad", 0.4)


@pytest.mark.parametrize(
    "fields",
    [
        {"emotion": "furious"},
        {"emotion": "angry", "intensity": 1.5},
        {"emotion": "angry", "intensity": -0.1},
        {"intensity": 0.5},
        {"emotion": "neutral", "intensity": 0.5},
        {"emotion": "angry", "intensity": float("nan")},
    ],
)
def test_bad_emotion_fields_are_rejected(fields):
    with pytest.raises(ValidationError):
        SynthesizeRequest(voice_profile_id=PROFILE, text="Hi", **fields)


# --- the plan and the pipeline -----------------------------------------------------


def test_the_override_reaches_every_segment():
    planned = styled_synthesis.plan(
        "It is fine. Nothing to see.", _Recorder(), override=StyleOverride("angry", 1.0)
    )
    assert planned and all(p.style.exaggeration > 0.5 for p in planned)


def test_without_an_override_a_calm_text_keeps_the_default():
    planned = styled_synthesis.plan("It is fine.", _Recorder())
    assert planned[0].style.exaggeration == 0.5


def _run(monkeypatch, tmp_path, enabled, override):
    model = _OriginalModel()
    model.output = _tone(1.0, rate=24000)
    server = _Server(model)
    monkeypatch.setattr(settings, "TTS_ENGINE", "chatterbox")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "EMOTION_CONTROL_ENABLED", enabled)
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), _tone(6.0), 16000)
    try:
        result = asyncio.run(
            tts_pipeline.run_inference_pipeline(
                "It is fine.",
                EMB,
                "override-user",
                reference_audio_path=str(ref),
                style_override=override,
            )
        )
    finally:
        server.stop()
    os.remove(result[0])
    return model, result


def test_the_pipeline_applies_a_requested_emotion(monkeypatch, tmp_path):
    model, result = _run(monkeypatch, tmp_path, True, StyleOverride("angry", 1.0))
    assert model.calls[0][1] > 0.5  # a calm sentence, delivered angrily
    assert result.style_applied is True


def test_the_flag_off_ignores_it_and_says_so(monkeypatch, tmp_path):
    model, result = _run(monkeypatch, tmp_path, False, StyleOverride("angry", 1.0))
    assert model.calls[0][1] is None
    assert result.style_applied is False


def test_sv2tts_ignores_it_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "EMOTION_CONTROL_ENABLED", True)
    tts_pipeline.load_mock_models("cpu")
    result = asyncio.run(
        tts_pipeline.run_inference_pipeline(
            "Hello.",
            np.ones(256, np.float32) / 16,
            "who",
            style_override=StyleOverride("sad"),
        )
    )
    os.remove(result[0])
    assert result.style_applied is False


# --- the API ---------------------------------------------------------------------


@pytest.fixture
def auth(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "ov@example.com", "password": "Password123!", "name": "O"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "ov@example.com", "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def profile(client, auth) -> str:
    tts_pipeline.load_mock_models("cpu")
    return client.post(
        "/api/v1/voice/upload",
        headers=auth,
        data={"name": "O", "consent_confirmed": "true"},
        files={"file": ("a.wav", _wav(_tone(4.0, amp=0.5)), "audio/wav")},
    ).json()["id"]


def _post(client, auth, profile, **extra):
    return client.post(
        "/api/v1/synthesize",
        headers=auth,
        json={"voice_profile_id": profile, "text": "Hello there.", **extra},
    )


def test_an_auto_request_sends_no_override_and_no_header(
    client, auth, profile, monkeypatch
):
    seen = {}
    real = synthesize_api.run_inference_pipeline

    async def spy(*args, **kwargs):
        seen.update(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(synthesize_api, "run_inference_pipeline", spy)
    response = _post(client, auth, profile)
    assert response.status_code == 200
    assert "style_override" not in seen and "X-Voice-Style" not in response.headers


def test_a_requested_emotion_is_passed_on_and_reported_ignored_on_sv2tts(
    client, auth, profile, monkeypatch
):
    seen = {}
    real = synthesize_api.run_inference_pipeline

    async def spy(*args, **kwargs):
        seen.update(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(synthesize_api, "run_inference_pipeline", spy)
    response = _post(client, auth, profile, emotion="sad", intensity=0.4)
    assert response.status_code == 200
    assert seen["style_override"] == StyleOverride("sad", 0.4)
    assert response.headers["X-Voice-Style"] == "ignored"


def test_the_header_says_applied_when_the_engine_used_the_style(
    client, auth, profile, monkeypatch
):
    real = synthesize_api.run_inference_pipeline

    async def applied(*args, **kwargs):
        result = await real(*args, **kwargs)
        return InferenceResult(
            result[0], result[1], result.engine, result.engine_version, None, True
        )

    monkeypatch.setattr(synthesize_api, "run_inference_pipeline", applied)
    response = _post(client, auth, profile, emotion="happy")
    assert response.headers["X-Voice-Style"] == "applied"


@pytest.mark.parametrize(
    "extra",
    [{"emotion": "furious"}, {"intensity": 0.5}, {"emotion": "sad", "intensity": 2}],
)
def test_bad_fields_are_a_422(client, auth, profile, extra):
    assert _post(client, auth, profile, **extra).status_code == 422
