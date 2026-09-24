"""Tests for sentence chunking (HARDENING_PLAN.md finding P2-M3)."""

import logging

import numpy as np
import pytest

from backend.core.config import settings
from backend.services import tts_pipeline
from backend.services.sv2tts.synthesizer.hparams import hparams as synth_hparams
from backend.services.text_chunking import split_into_chunks

EMB = np.zeros(256, dtype=np.float32)


# ---- unit: split_into_chunks -------------------------------------------------


def test_short_text_is_a_single_chunk() -> None:
    assert split_into_chunks("Hello world.", 150) == ["Hello world."]


@pytest.mark.parametrize("blank", ["", "   ", "\n\n"])
def test_blank_text_yields_no_chunks(blank: str) -> None:
    assert split_into_chunks(blank, 150) == []


def test_splits_on_sentence_boundaries_when_over_limit() -> None:
    text = "First sentence here. Second one follows! Is there a third? Yes."
    chunks = split_into_chunks(text, 25)
    assert chunks == [
        "First sentence here.",
        "Second one follows!",
        "Is there a third? Yes.",
    ]


def test_short_sentences_are_merged_up_to_limit() -> None:
    assert split_into_chunks("A. B. C. D.", 150) == ["A. B. C. D."]


def test_newlines_split_like_the_reference_demo() -> None:
    assert split_into_chunks("line one\nline two", 9) == ["line one", "line two"]


def test_overlong_sentence_splits_at_commas_then_words() -> None:
    text = "alpha beta, gamma delta epsilon zeta eta theta"
    chunks = split_into_chunks(text, 20)
    assert all(len(c) <= 20 for c in chunks)
    assert " ".join(chunks).replace(",", "").split() == text.replace(",", "").split()


def test_unbroken_token_is_hard_cut() -> None:
    chunks = split_into_chunks("x" * 45, 20)
    assert [len(c) for c in chunks] == [20, 20, 5]


@pytest.mark.parametrize("length", [1, 149, 150, 151, 500])
def test_every_chunk_respects_limit_and_nothing_is_lost(length: int) -> None:
    text = ("word " * 200)[:length].strip() or "w"
    chunks = split_into_chunks(text, 150)
    assert all(0 < len(c) <= 150 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_invalid_limit_raises() -> None:
    with pytest.raises(ValueError):
        split_into_chunks("hi", 0)


# ---- pipeline: chunked synthesis ---------------------------------------------


def _frames_for(text: str) -> int:
    """Mock synthesizer emits len(sequence) * 5 frames (before the cap)."""
    return tts_pipeline._synthesize_chunk(text, EMB).shape[1]


def test_single_chunk_matches_direct_synthesis() -> None:
    text = "Hello world."
    assert tts_pipeline.synthesize_speech(text, EMB).shape == (
        80,
        _frames_for(text),
    )


def test_multi_chunk_mel_is_chunks_plus_pauses(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 20)
    text = "First sentence here. Second one follows!"
    mel = tts_pipeline.synthesize_speech(text, EMB)
    pause = int(
        settings.TTS_CHUNK_PAUSE_SECONDS
        * synth_hparams.sample_rate
        / synth_hparams.hop_size
    )
    expected = (
        _frames_for("First sentence here.") + pause + _frames_for("Second one follows!")
    )
    assert mel.shape == (80, expected)
    assert mel.dtype == np.float32
    # the inserted gap is the mel floor (silence)
    gap_start = _frames_for("First sentence here.")
    assert np.all(mel[:, gap_start : gap_start + pause] == -synth_hparams.max_abs_value)


def test_long_text_decodes_each_chunk_within_step_cap(monkeypatch) -> None:
    """A 500-char text never asks one decode for more than the training cap."""
    seen: list[int] = []
    real = tts_pipeline._synthesize_chunk

    def spy(text: str, emb: np.ndarray) -> np.ndarray:
        seen.append(len(text))
        return real(text, emb)

    monkeypatch.setattr(tts_pipeline, "_synthesize_chunk", spy)
    text = " ".join(
        ["This is a moderately long sentence number %d." % i for i in range(11)]
    )[:500]
    tts_pipeline.synthesize_speech(text, EMB)
    assert len(seen) > 1
    assert max(seen) <= settings.TTS_CHUNK_MAX_CHARS


def test_step_cap_is_passed_and_truncation_is_logged(monkeypatch, caplog) -> None:
    monkeypatch.setattr(synth_hparams, "max_mel_frames", 10)
    with caplog.at_level(logging.WARNING, logger=tts_pipeline.logger.name):
        mel = tts_pipeline._synthesize_chunk("a fairly long chunk of text", EMB)
    assert mel.shape[1] == 10
    assert "truncated" in caplog.text


def test_no_truncation_warning_under_cap(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=tts_pipeline.logger.name):
        tts_pipeline._synthesize_chunk("Hi.", EMB)
    assert "truncated" not in caplog.text
