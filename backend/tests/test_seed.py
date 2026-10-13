"""A request seed makes SV2TTS sampling repeatable (SPEECH_QUALITY_PLAN.md S7.1c)."""

import asyncio
import os
from unittest.mock import patch

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core.config import settings
from backend.schemas.synthesize import SynthesizeRequest
from backend.services import tts_engine, tts_pipeline
from backend.services.tts_engine import (EngineCapabilities, SynthesisResult,
                                         TTSEngine, VoiceConditioning)
from backend.tests.test_chatterbox_engine import _tone, _wav
from backend.tests.test_style_override import auth, profile  # noqa: F401

SR = 16000
EMB = np.eye(256, dtype=np.float32)[0]
ID = "11111111-1111-1111-1111-111111111111"


def _voiced(seconds: float = 1.8) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


# --- the request ----------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 7, 2**31 - 1])
def test_a_seed_in_range_is_accepted(seed):
    assert SynthesizeRequest(voice_profile_id=ID, text="Hi.", seed=seed).seed == seed


@pytest.mark.parametrize("seed", [-1, 2**31, "abc", 1.5])
def test_a_seed_out_of_range_is_rejected(seed):
    with pytest.raises(ValidationError):
        SynthesizeRequest(voice_profile_id=ID, text="Hi.", seed=seed)


def test_no_seed_by_default():
    assert SynthesizeRequest(voice_profile_id=ID, text="Hi.").seed is None


# --- the stage -------------------------------------------------------------------


def test_the_stage_seeds_the_generator_so_a_seed_repeats_and_differs():
    def draw(*_args):
        return np.array([float(torch.rand(1))], np.float32)

    with patch.object(tts_pipeline, "synthesize_speech", draw):
        run = tts_pipeline._synthesize_counting_truncation
        a, _ = run("x", EMB, None, 5)
        b, _ = run("x", EMB, None, 5)
        c, _ = run("x", EMB, None, 6)
    assert a[0] == b[0] and a[0] != c[0]


def test_without_a_seed_the_stage_leaves_the_generator_alone():
    torch.manual_seed(123)
    expected = float(torch.rand(1))
    torch.manual_seed(123)
    with patch.object(tts_pipeline, "synthesize_speech", lambda *a: np.zeros(1)):
        tts_pipeline._synthesize_counting_truncation("x", EMB)
    assert float(torch.rand(1)) == expected


# --- the pipeline ----------------------------------------------------------------


def _run(seed, text="Hello there my friend today."):
    return asyncio.run(
        tts_pipeline.run_inference_pipeline(text, EMB, "seed-user", seed=seed)
    )


def test_a_seed_reaches_the_stage_and_is_reported_applied():
    tts_pipeline.load_mock_models("cpu")
    seen = []
    real = tts_pipeline._synthesize_counting_truncation

    def spy(*args, **kwargs):
        seen.append(kwargs.get("seed"))
        return real(*args, **kwargs)

    with patch.object(
        tts_pipeline, "_synthesize_counting_truncation", spy
    ), patch.object(tts_pipeline, "vocode", lambda mel: _voiced()):
        result = _run(41)
    assert seen == [41] and result.seed_applied is True


def test_no_seed_changes_nothing():
    tts_pipeline.load_mock_models("cpu")
    seen = []
    real = tts_pipeline._synthesize_counting_truncation

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real(*args, **kwargs)

    with patch.object(
        tts_pipeline, "_synthesize_counting_truncation", spy
    ), patch.object(tts_pipeline, "vocode", lambda mel: _voiced()):
        result = _run(None)
    assert seen == [{}] and result.seed_applied is False


def test_a_retry_and_best_of_candidates_use_distinct_derived_seeds(monkeypatch):
    tts_pipeline.load_mock_models("cpu")
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 3)
    seen = []
    real = tts_pipeline._synthesize_counting_truncation

    def spy(*args, **kwargs):
        seen.append(kwargs.get("seed"))
        return real(*args, **kwargs)

    with patch.object(
        tts_pipeline, "_synthesize_counting_truncation", spy
    ), patch.object(tts_pipeline, "vocode", lambda mel: _voiced()), patch.object(
        tts_pipeline, "_embed_candidate", lambda w: EMB
    ):
        _run(10)
    assert seen == [10, 1000 + 10, 1001 + 10]


def test_an_engine_that_cannot_be_seeded_is_never_passed_one():
    tts_pipeline.load_mock_models("cpu")
    calls = []

    class Other(TTSEngine):
        name = "other"
        version = "9"

        def capabilities(self):
            return EngineCapabilities("other", "9", SR, 500, ("neutral",))

        def health(self, expected_device=None):
            return {"ready": True}

        def conditioning_from_array(self, embedding):
            return VoiceConditioning("other", "9", embedding)

        async def prepare_voice(self, audio):
            return self.conditioning_from_array(EMB)

        async def synthesize(
            self, text, conditioning, style, *, run_stage, truncation_retries=0
        ):
            calls.append(1)
            return SynthesisResult(_voiced(), SR, 0)

    with patch.object(tts_engine, "get_engine", lambda: Other()):
        result = _run(3)
    assert calls == [1] and result.seed_applied is False


# --- the API ----------------------------------------------------------------------


def _post(client, auth, profile, **extra):
    return client.post(
        "/api/v1/synthesize",
        headers=auth,
        json={"voice_profile_id": profile, "text": "Hello there.", **extra},
    )


def test_the_header_reports_a_seed_that_reached_the_engine(client, auth, profile):
    response = _post(client, auth, profile, seed=9)
    assert response.status_code == 200
    assert response.headers["X-Voice-Seed"] == "applied"


def test_no_seed_sends_no_header(client, auth, profile):
    assert "X-Voice-Seed" not in _post(client, auth, profile).headers


def test_the_header_says_ignored_when_the_engine_cannot_be_seeded(
    client, auth, profile, monkeypatch
):
    from backend.api import synthesize as api
    from backend.services.tts_pipeline import InferenceResult

    real = api.run_inference_pipeline

    async def unseeded(*args, **kwargs):
        r = await real(*args, **kwargs)
        return InferenceResult(r[0], r[1], "other", "1")

    monkeypatch.setattr(api, "run_inference_pipeline", unseeded)
    assert _post(client, auth, profile, seed=9).headers["X-Voice-Seed"] == "ignored"


def test_an_invalid_seed_is_a_422(client, auth, profile):
    assert _post(client, auth, profile, seed=-4).status_code == 422
