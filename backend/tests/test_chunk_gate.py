"""The per-chunk speech-time check for long text (SPEECH_QUALITY_PLAN.md S3.6)."""

import asyncio
from unittest.mock import patch

import numpy as np
import pytest

from backend.core.config import settings
from backend.services import tts_pipeline
from backend.services.audio_gate import (ChunkSpan, check_output,
                                         worst_chunk_speech_ratio)
from backend.services.sv2tts_engine import Sv2ttsEngine
from backend.services.tts_engine import VoiceConditioning
from backend.services.tts_pipeline import OutputQualityError

SR = 16000
EIGHT = 8  # words: expected speech about 2.2 s
SIXTEEN_WORDS = " ".join(["word"] * 16)  # outside the whole-clip model's range


def _voiced(seconds: float, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


def _two_chunks(first: float, second: float, pause: float = 0.5):
    """Two 8-word chunks of the given speech seconds with a typed pause between."""
    gap = np.zeros(int(SR * pause), dtype=np.float32)
    a, b = _voiced(first), _voiced(second)
    wav = np.concatenate([a, gap, b])
    spans = (
        ChunkSpan(EIGHT, 0, len(a)),
        ChunkSpan(EIGHT, len(a) + len(gap), len(wav)),
    )
    return wav, spans


def _gate(wav, spans, limit):
    return check_output(
        wav,
        SR,
        SIXTEEN_WORDS,
        0,
        1.0,
        1.8,
        chunk_spans=spans,
        max_chunk_speech_ratio=limit,
    )


# --- the measure ------------------------------------------------------------


def test_a_dragged_chunk_is_not_averaged_away_by_the_others():
    wav, spans = _two_chunks(2.3, 4.5)
    assert worst_chunk_speech_ratio(wav, SR, spans) == pytest.approx(
        4.5 / 2.212, abs=0.05
    )


def test_chunks_all_within_the_model_have_a_ratio_near_one():
    wav, spans = _two_chunks(2.3, 2.2)
    assert worst_chunk_speech_ratio(wav, SR, spans) == pytest.approx(1.04, abs=0.05)


def test_the_pause_between_chunks_is_outside_every_span():
    wav, spans = _two_chunks(2.3, 2.3, pause=1.5)
    assert worst_chunk_speech_ratio(wav, SR, spans) < 1.2


def test_chunks_outside_the_calibrated_word_range_are_not_judged():
    wav = _voiced(3.0)
    spans = (ChunkSpan(3, 0, SR), ChunkSpan(20, SR, 3 * SR))
    assert worst_chunk_speech_ratio(wav, SR, spans) is None


def test_spans_past_the_end_are_clamped_and_empty_spans_ignored():
    wav = _voiced(2.3)
    spans = (ChunkSpan(EIGHT, -100, 10**9), ChunkSpan(EIGHT, 500, 500))
    assert worst_chunk_speech_ratio(wav, SR, spans) == pytest.approx(1.04, abs=0.05)


# --- the gate ---------------------------------------------------------------


def test_a_dragged_chunk_fails_the_gate_when_the_limit_is_set():
    wav, spans = _two_chunks(2.3, 4.5)
    result = _gate(wav, spans, 1.8)
    assert result.reasons == ("chunk_speech_too_long",)
    assert (
        result.measures.speech_ratio is None
    )  # 16 words: the whole-clip check skips it


def test_the_same_audio_passes_with_the_limit_off_but_is_still_measured():
    wav, spans = _two_chunks(2.3, 4.5)
    result = _gate(wav, spans, None)
    assert result.passed
    assert result.measures.worst_chunk_ratio == pytest.approx(2.03, abs=0.05)


def test_normal_chunks_pass_with_the_limit_set():
    wav, spans = _two_chunks(2.3, 2.2)
    assert _gate(wav, spans, 1.8).passed


def test_one_span_or_none_leaves_the_chunk_check_to_the_whole_clip():
    wav, spans = _two_chunks(2.3, 4.5)
    assert _gate(wav, spans[:1], 1.8).measures.worst_chunk_ratio is None
    assert _gate(wav, (), 1.8).measures.worst_chunk_ratio is None
    assert _gate(wav, (), 1.8).passed


# --- spans from the pipeline ------------------------------------------------

EMB = np.ones(256, np.float32)
THREE_SENTENCES = "One two three four. Five six seven eight. Nine ten eleven twelve."


@pytest.fixture
def mock_models(monkeypatch):
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 25)
    tts_pipeline.load_mock_models("cpu")


def test_the_spans_tile_the_joined_mel_with_the_typed_pauses_between(mock_models):
    mel, _, spans = tts_pipeline._synthesize_counting_truncation(THREE_SENTENCES, EMB)
    assert len(spans) == 3 and all(words == 4 for words, _, _ in spans)
    assert spans[0][1] == 0 and spans[-1][2] == mel.shape[1]
    for (_, _, end), (_, start, _) in zip(spans, spans[1:]):
        assert start > end  # a pause sits between neighbours
    assert all(end > start for _, start, end in spans)


def test_a_single_chunk_text_reports_one_span_and_a_double_reports_none(mock_models):
    _, _, spans = tts_pipeline._synthesize_counting_truncation("Hi there.", EMB)
    assert len(spans) == 1
    with patch.object(tts_pipeline, "synthesize_speech", lambda *a: np.zeros((80, 5))):
        assert tts_pipeline._synthesize_counting_truncation("x", EMB)[2] == ()


def test_spans_do_not_leak_between_calls_on_one_thread(mock_models):
    tts_pipeline._synthesize_counting_truncation(THREE_SENTENCES, EMB)
    with patch.object(tts_pipeline, "synthesize_speech", lambda *a: np.zeros((80, 5))):
        assert tts_pipeline._synthesize_counting_truncation("x", EMB)[2] == ()


# --- the engine -------------------------------------------------------------


async def _direct(_stage, fn, *args):
    return fn(*args)


def _synthesize(engine_stage):
    voice = VoiceConditioning("sv2tts", "1", EMB)
    with patch.object(
        tts_pipeline, "_synthesize_counting_truncation", engine_stage
    ), patch.object(tts_pipeline, "vocode", lambda mel: _voiced(1.0)):
        return asyncio.run(
            Sv2ttsEngine().synthesize("x", voice, None, run_stage=_direct)
        )


def test_the_engine_converts_mel_frames_to_samples():
    hop = tts_pipeline.synth_hparams.hop_size
    result = _synthesize(lambda *a: (np.zeros((80, 50)), 0, ((6, 0, 10), (7, 12, 40))))
    assert result.chunk_spans == (
        ChunkSpan(6, 0, 10 * hop),
        ChunkSpan(7, 12 * hop, 40 * hop),
    )


def test_the_engine_accepts_a_stage_that_returns_no_spans():
    assert _synthesize(lambda *a: (np.zeros((80, 50)), 2)).chunk_spans == ()


# --- the pipeline -----------------------------------------------------------


@pytest.fixture
def chunked_run(monkeypatch):
    """A long text whose waveform has one dragged 8-word chunk, gate on, retries off."""
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_QUALITY_MAX_ATTEMPTS", 1)
    tts_pipeline.load_mock_models("cpu")
    wav, spans = _two_chunks(2.3, 4.5)
    hop = tts_pipeline.synth_hparams.hop_size
    frames = tuple(
        (sp.words, sp.start_sample // hop, sp.end_sample // hop) for sp in spans
    )

    def run():
        with patch.object(
            tts_pipeline,
            "_synthesize_counting_truncation",
            lambda *a, **k: (np.zeros((80, 50)), 0, frames),
        ), patch.object(tts_pipeline, "vocode", lambda mel: wav):
            return asyncio.run(
                tts_pipeline.run_inference_pipeline(SIXTEEN_WORDS, EMB, "chunk-user")
            )

    return run


def test_the_pipeline_serves_a_dragged_chunk_while_the_limit_is_off(
    chunked_run, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_GATE_CHUNK_MAX_SPEECH_RATIO", 0.0)
    path, _ = chunked_run()
    assert path


def test_the_pipeline_refuses_a_dragged_chunk_once_the_limit_is_set(
    chunked_run, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_GATE_CHUNK_MAX_SPEECH_RATIO", 1.8)
    with pytest.raises(OutputQualityError) as caught:
        chunked_run()
    assert "chunk_speech_too_long" in caught.value.reasons
