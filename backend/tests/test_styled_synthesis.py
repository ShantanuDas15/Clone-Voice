"""Sentence-by-sentence synthesis with a style per sentence (SPEECH_QUALITY_PLAN.md S5.3a)."""

import asyncio
import os

import numpy as np
import pytest
import soundfile as sf

from backend.core import metrics
from backend.core.config import Settings, settings
from backend.services import styled_synthesis, tts_pipeline
from backend.services.chatterbox_engine import ChatterboxEngine
from backend.services.sv2tts_engine import Sv2ttsEngine
from backend.services.text_analysis import StyleOverride
from backend.services.tts_engine import (SynthesisResult, SynthesisStyle,
                                         VoiceConditioning)
from backend.tests.test_chatterbox_engine import (EMB, TOKEN, _Model, _Server,
                                                  _tone, _wav)

RATE = 24000


async def _direct(stage, fn, *args):
    return fn(*args)


class _Recorder(ChatterboxEngine):
    """The original Chatterbox engine, with the worker call replaced by a recording stub."""

    def __init__(self, name="chatterbox", seconds=0.5, truncated=0):
        super().__init__(name)
        self.calls = []
        self.seconds = seconds
        self.truncated = truncated
        self.rate = RATE

    async def synthesize(
        self, text, conditioning, style, *, run_stage, truncation_retries=0
    ):
        self.calls.append((text, style, truncation_retries))
        wave = np.full(int(self.seconds * self.rate), 0.1, np.float32)
        return SynthesisResult(wave, self.rate, self.truncated)


def _voice():
    return VoiceConditioning("chatterbox", "1", EMB, b"ref")


def _run(engine, text, **kwargs):
    return asyncio.run(
        styled_synthesis.synthesize_styled(
            engine, text, _voice(), run_stage=_direct, **kwargs
        )
    )


@pytest.fixture(autouse=True)
def _pauses(monkeypatch):
    monkeypatch.setattr(
        settings,
        "TTS_PAUSE_SECONDS",
        {**settings.TTS_PAUSE_SECONDS, "statement": 0.4, "exclamation": 0.45},
    )


# --- which engines are split --------------------------------------------------


def test_only_the_original_chatterbox_is_split():
    assert styled_synthesis.applies(ChatterboxEngine("chatterbox"))
    assert not styled_synthesis.applies(ChatterboxEngine("chatterbox_turbo"))
    assert not styled_synthesis.applies(ChatterboxEngine("chatterbox_nano"))
    assert not styled_synthesis.applies(Sv2ttsEngine())


def test_the_setting_is_off_by_default():
    assert Settings.model_fields["EMOTION_CONTROL_ENABLED"].default is False


# --- the plan ------------------------------------------------------------------


def test_a_passage_gets_one_style_per_sentence():
    planned = styled_synthesis.plan(
        "The meeting is at noon. I can't believe you did that!!", _Recorder()
    )
    assert [p.segment.text for p in planned] == [
        "The meeting is at noon.",
        "I can't believe you did that!!",
    ]
    calm, angry = (p.style.exaggeration for p in planned)
    assert calm == 0.5  # a cue-free sentence keeps the engine default
    assert angry > calm
    assert all(p.style.emotion == "neutral" for p in planned)  # no labelled emotion


def test_the_text_keeps_its_case_and_capitals_still_count_as_emphasis():
    (planned,) = styled_synthesis.plan("I said STOP right now", _Recorder())
    assert planned.segment.text == "I said STOP right now"
    assert planned.style.exaggeration > 0.5


def test_an_abbreviation_does_not_split_a_sentence():
    planned = styled_synthesis.plan("Dr. Smith arrived late.", _Recorder())
    assert [p.segment.text for p in planned] == ["doctor Smith arrived late."]


def test_symbols_are_spoken_but_case_is_kept():
    assert (
        styled_synthesis.speakable("Pay $4.50 at 10:30 PM") != "Pay $4.50 at 10:30 PM"
    )
    assert styled_synthesis.speakable("Tom & Jerry").startswith("Tom and Jerry")


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_blank_text_has_no_segments(text):
    assert styled_synthesis.plan(text, _Recorder()) == []


def test_a_long_sentence_is_cut_to_the_chunk_limit():
    engine = _Recorder()
    planned = styled_synthesis.plan(
        ("word " * 120).strip() + ".", engine, max_chars=100
    )
    assert len(planned) > 1
    assert all(len(p.segment.text) <= 100 for p in planned)


# --- the join --------------------------------------------------------------------


def test_segments_are_called_in_order_with_their_own_style_and_joined_with_pauses():
    engine = _Recorder(seconds=0.5)
    result = _run(engine, "It is fine. I hate this!")
    assert [c[0] for c in engine.calls] == ["It is fine.", "I hate this!"]
    assert engine.calls[0][1] != engine.calls[1][1]
    # 0.5 s + the statement pause (0.4 s) + 0.5 s, at the engine's own rate
    assert result.sample_rate == RATE
    assert len(result.waveform) == int((0.5 + 0.4 + 0.5) * RATE)
    gap = result.waveform[int(0.5 * RATE) : int(0.9 * RATE)]
    assert not gap.any()


def test_the_pause_follows_the_previous_segment_s_ending(monkeypatch):
    monkeypatch.setitem(settings.TTS_PAUSE_SECONDS, "exclamation", 0.7)
    result = _run(_Recorder(seconds=0.5), "Stop! Go on.")
    assert len(result.waveform) == int((0.5 + 0.7 + 0.5) * RATE)


def test_one_segment_is_one_call_with_no_pause():
    engine = _Recorder(seconds=0.5)
    result = _run(engine, "Just one sentence.")
    assert len(engine.calls) == 1
    assert len(result.waveform) == int(0.5 * RATE)


def test_truncated_decodes_add_up_so_the_gate_sees_them_all():
    result = _run(_Recorder(truncated=1), "One! Two! Three!")
    assert result.truncated_decodes == 3


def test_the_retry_hint_reaches_every_segment():
    engine = _Recorder()
    _run(engine, "One! Two!", truncation_retries=2)
    assert [c[2] for c in engine.calls] == [2, 2]


def test_blank_text_is_sent_whole_like_the_one_call_path():
    engine = _Recorder()
    _run(engine, "   ")
    assert engine.calls == [("   ", None, 0)]


def test_a_sample_rate_change_mid_request_is_an_error():
    class Drifting(_Recorder):
        async def synthesize(self, *args, **kwargs):
            result = await super().synthesize(*args, **kwargs)
            self.rate = 16000
            return result

    with pytest.raises(RuntimeError, match="sample rate"):
        _run(Drifting(), "One! Two!")


def test_a_failing_segment_fails_the_request():
    class Failing(_Recorder):
        async def synthesize(self, text, *args, **kwargs):
            if text.startswith("Two"):
                raise RuntimeError("boom")
            return await super().synthesize(text, *args, **kwargs)

    with pytest.raises(RuntimeError, match="boom"):
        _run(Failing(), "One! Two!")


# --- through the pipeline and a real worker app ---------------------------------


class _OriginalModel(_Model):
    """A worker model that is the 'original' one and records the exaggeration it was given."""

    model = "original"

    def synthesize(self, text, reference_wav, truncation_retries, exaggeration=None):
        self.calls.append((text, exaggeration))
        return self.output, 24000


def _pipeline(monkeypatch, tmp_path, text, enabled):
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
                text, EMB, "styled-user", reference_audio_path=str(ref)
            )
        )
    finally:
        server.stop()
    return model, result


def test_the_flag_off_sends_the_whole_text_in_one_call(monkeypatch, tmp_path):
    model, result = _pipeline(
        monkeypatch, tmp_path, "It is fine. I hate this!!", enabled=False
    )
    assert [c[0] for c in model.calls] == ["It is fine. I hate this!!"]
    assert model.calls[0][1] is None
    assert result.engine == "chatterbox"


def test_the_flag_on_sends_each_sentence_with_its_own_exaggeration(
    monkeypatch, tmp_path
):
    model, result = _pipeline(
        monkeypatch, tmp_path, "It is fine. I hate this!!", enabled=True
    )
    assert [c[0] for c in model.calls] == ["It is fine.", "I hate this!!"]
    calm, angry = (c[1] for c in model.calls)
    assert calm == 0.5 and angry > calm
    assert result.engine == "chatterbox" and result.engine_fallback_from is None
    audio, rate = sf.read(result[0])
    assert rate == 24000
    # two 1 s sentences and a 0.4 s pause, levelled but not trimmed
    assert abs(len(audio) / rate - 2.4) < 0.2
    os.remove(result[0])


def test_sv2tts_is_never_split_even_with_the_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "EMOTION_CONTROL_ENABLED", True)
    tts_pipeline.load_mock_models("cpu")
    seen = []

    original = styled_synthesis.synthesize_styled

    async def spy(*args, **kwargs):
        seen.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(styled_synthesis, "synthesize_styled", spy)
    result = asyncio.run(
        tts_pipeline.run_inference_pipeline("Hello. World!", EMB, "styled-user")
    )
    assert not seen
    os.remove(result[0])


# --- the emotion metric (S7.3b) ---------------------------------------------------


def _count(emotion, source):
    value = metrics.registry.get_sample_value(
        "clonevoice_sentences_styled_total", {"emotion": emotion, "source": source}
    )
    return value or 0.0


def test_each_sentence_is_counted_by_its_detected_emotion():
    neutral, angry = _count("neutral", "detected"), _count("angry", "detected")
    _run(_Recorder(), "The meeting is at noon. I hate this!!")
    assert _count("neutral", "detected") == neutral + 1
    assert _count("angry", "detected") == angry + 1


def test_a_requested_emotion_is_counted_as_requested():
    sad, detected = _count("sad", "requested"), _count("neutral", "detected")
    asyncio.run(
        styled_synthesis.synthesize_styled(
            _Recorder(),
            "It is fine. All good.",
            _voice(),
            run_stage=_direct,
            override=StyleOverride("sad"),
        )
    )
    assert _count("sad", "requested") == sad + 1  # one merged statement segment
    assert _count("neutral", "detected") == detected


def test_a_failed_sentence_is_not_counted():
    class Failing(_Recorder):
        async def synthesize(self, text, *args, **kwargs):
            raise RuntimeError("boom")

    before = _count("neutral", "detected")
    with pytest.raises(RuntimeError):
        _run(Failing(), "It is fine.")
    assert _count("neutral", "detected") == before
