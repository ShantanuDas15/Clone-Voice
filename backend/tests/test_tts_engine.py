"""The TTSEngine interface and the SV2TTS engine behind it (SPEECH_QUALITY_PLAN.md S4.1)."""

import asyncio
import os
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings, settings
from backend.schemas.synthesize import SynthesizeRequest
from backend.services import tts_engine, tts_pipeline
from backend.services.sv2tts_engine import MAX_CHARS, Sv2ttsEngine, retry_chunk_chars
from backend.services.tts_engine import (
    EngineCapabilities,
    SynthesisResult,
    SynthesisStyle,
    TTSEngine,
    UnsupportedStyleError,
    VoiceConditioning,
    WrongEngineError,
    get_engine,
)

SR = 16000
EMB = np.ones(256, np.float32) / 16.0


def _voiced(seconds=1.8, amp=0.2):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


async def _direct(stage, fn, *args):
    """A stage runner with no slot or timeout: just call it."""
    return fn(*args)


@pytest.fixture(autouse=True)
def mock_models():
    tts_pipeline.load_mock_models("cpu")


# --- registry and setting ---------------------------------------------------


def test_the_default_engine_is_sv2tts_and_is_shared():
    engine = get_engine()
    assert isinstance(engine, Sv2ttsEngine) and isinstance(engine, TTSEngine)
    assert get_engine() is engine


def test_an_unknown_engine_is_refused_by_the_setting_and_the_registry():
    with pytest.raises(Exception):
        Settings(TTS_ENGINE="nonsense")
    with pytest.raises(ValueError):
        tts_engine._build("nonsense")


def test_the_interface_cannot_be_instantiated_incomplete():
    with pytest.raises(TypeError):
        TTSEngine()


# --- capabilities -----------------------------------------------------------


def test_capabilities_describe_a_neutral_16khz_engine():
    caps = get_engine().capabilities()
    assert caps == EngineCapabilities(
        name="sv2tts",
        version="1",
        sample_rate=settings.VOCODER_SAMPLE_RATE,
        max_chars=MAX_CHARS,
        emotions=("neutral",),
    )


def test_max_chars_matches_the_request_schema():
    schema = SynthesizeRequest.model_json_schema()
    assert MAX_CHARS == schema["properties"]["text"]["maxLength"]


# --- conditioning and style -------------------------------------------------


def test_conditioning_is_tagged_with_the_engine_and_version():
    c = get_engine().conditioning_from_array(EMB)
    assert (c.engine, c.version) == ("sv2tts", "1")
    assert np.array_equal(c.embedding, EMB)


@pytest.mark.parametrize("engine,version", [("other", "1"), ("sv2tts", "2")])
def test_a_voice_from_another_engine_or_version_is_refused(engine, version):
    with pytest.raises(WrongEngineError):
        get_engine().check_request(VoiceConditioning(engine, version, EMB), None)


@pytest.mark.parametrize(
    "style", [None, SynthesisStyle(), SynthesisStyle("neutral", 0.5)]
)
def test_neutral_styles_are_accepted(style):
    get_engine().check_request(get_engine().conditioning_from_array(EMB), style)


def test_an_emotion_the_engine_cannot_speak_is_refused():
    with pytest.raises(UnsupportedStyleError):
        get_engine().check_request(
            get_engine().conditioning_from_array(EMB), SynthesisStyle("angry", 1.0)
        )


# --- the engine's work -------------------------------------------------------


def test_prepare_voice_wraps_the_speaker_embedding():
    async def fake(audio):
        return EMB

    with patch.object(tts_pipeline, "embed_speaker_async", fake):
        c = asyncio.run(get_engine().prepare_voice(np.zeros(16000, np.float32)))
    assert np.array_equal(c.embedding, EMB) and c.engine == "sv2tts"


def test_synthesize_runs_the_synthesizer_then_the_vocoder_as_timed_stages():
    stages = []

    async def run_stage(stage, fn, *args):
        stages.append(stage)
        return fn(*args)

    engine = get_engine()
    result = asyncio.run(
        engine.synthesize(
            "Hello there.",
            engine.conditioning_from_array(EMB),
            None,
            run_stage=run_stage,
        )
    )
    assert stages == ["synthesizer", "vocoder"]
    assert isinstance(result, SynthesisResult)
    assert result.sample_rate == settings.VOCODER_SAMPLE_RATE
    assert result.waveform.ndim == 1 and result.truncated_decodes == 0


def test_synthesize_reports_decodes_cut_off_by_the_length_cap(monkeypatch):
    monkeypatch.setattr(tts_pipeline.synth_hparams, "max_mel_frames", 8)
    engine = get_engine()
    result = asyncio.run(
        engine.synthesize(
            "A sentence long enough to pass the cap.",
            engine.conditioning_from_array(EMB),
            None,
            run_stage=_direct,
        )
    )
    assert result.truncated_decodes >= 1


def test_synthesize_refuses_before_running_any_stage():
    stages = []

    async def run_stage(stage, fn, *args):
        stages.append(stage)

    engine = get_engine()
    with pytest.raises(WrongEngineError):
        asyncio.run(
            engine.synthesize(
                "Hi.", VoiceConditioning("other", "1", EMB), None, run_stage=run_stage
            )
        )
    with pytest.raises(UnsupportedStyleError):
        asyncio.run(
            engine.synthesize(
                "Hi.",
                engine.conditioning_from_array(EMB),
                SynthesisStyle("sad"),
                run_stage=run_stage,
            )
        )
    assert stages == []


@pytest.mark.parametrize(
    "retries,expected", [(0, None), (1, 75), (2, 37), (3, 20), (4, 20), (9, 20)]
)
def test_retry_chunks_halve_down_to_a_floor(retries, expected):
    assert retry_chunk_chars(retries) == expected


def test_retry_chunks_follow_the_configured_chunk_size(monkeypatch):
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 100)
    assert retry_chunk_chars(1) == 50


def test_the_engine_reports_model_health():
    health = get_engine().health("cpu")
    assert health["ready"] is True


# --- the pipeline works with any engine --------------------------------------


class _OtherEngine(TTSEngine):
    """A second engine: proves the pipeline depends on the interface, not on SV2TTS."""

    name = "other"
    version = "9"

    def __init__(self, waveforms):
        self.waveforms = list(waveforms)
        self.retries_seen = []

    def capabilities(self):
        return EngineCapabilities("other", "9", SR, 500, ("neutral", "happy"))

    def health(self, expected_device=None):
        return {"ready": True}

    def conditioning_from_array(self, embedding):
        return VoiceConditioning("other", "9", embedding)

    async def prepare_voice(self, audio):
        return self.conditioning_from_array(EMB)

    async def synthesize(
        self, text, conditioning, style, *, run_stage, truncation_retries=0
    ):
        self.check_request(conditioning, style)
        self.retries_seen.append(truncation_retries)
        wave = await run_stage("only_stage", lambda: self.waveforms.pop(0))
        # The first attempt reports a truncated decode, later ones do not.
        return SynthesisResult(wave, SR, 1 if len(self.retries_seen) == 1 else 0)


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)


def test_the_pipeline_gates_retries_and_saves_for_any_engine(gate_on):
    other = _OtherEngine([_voiced(), _voiced()])
    with patch.object(tts_engine, "get_engine", lambda: other):
        path, duration = asyncio.run(
            tts_pipeline.run_inference_pipeline(
                "Hello there my friend today.", EMB, "engine-user"
            )
        )
    # Truncated first attempt -> retried, and the engine was told so.
    assert other.retries_seen == [0, 1]
    assert os.path.exists(path) and duration == pytest.approx(1.8, abs=0.01)


def test_the_pipeline_passes_engine_errors_through(gate_on):
    class Broken(_OtherEngine):
        async def synthesize(self, *a, **k):
            raise WrongEngineError("nope")

    with patch.object(tts_engine, "get_engine", lambda: Broken([])), pytest.raises(
        WrongEngineError
    ):
        asyncio.run(tts_pipeline.run_inference_pipeline("Hi there.", EMB, "u"))


# --- readiness --------------------------------------------------------------


def test_readiness_reports_the_active_engine(client: TestClient):
    body = client.get("/health/ready").json()
    assert body["engine"] == {
        "name": "sv2tts",
        "version": "1",
        "sample_rate": settings.VOCODER_SAMPLE_RATE,
        "max_chars": 500,
        "emotions": ["neutral"],
    }
    assert "models" in body  # the existing fields are unchanged
