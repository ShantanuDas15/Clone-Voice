"""Tests for punctuation-aware segmentation and pauses.

HARDENING_PLAN.md finding P2-M3; SPEECH_QUALITY_PLAN.md S1.2 and S1.3.
"""

import logging

import numpy as np
import pytest

from backend.core.config import DEFAULT_TTS_PAUSE_SECONDS, settings
from backend.services import tts_pipeline
from backend.services.sv2tts.synthesizer.hparams import hparams as synth_hparams
from backend.services.text_chunking import (
    Boundary,
    Segment,
    classify_ending,
    split_into_segments,
)

EMB = np.zeros(256, dtype=np.float32)


# ---- unit: split_into_segments -----------------------------------------------


def _texts(text: str, limit: int = 150) -> list[str]:
    return [s.text for s in split_into_segments(text, limit)]


def _boundaries(text: str, limit: int = 150) -> list[Boundary]:
    return [s.boundary for s in split_into_segments(text, limit)]


def test_short_text_is_a_single_statement() -> None:
    assert split_into_segments("Hello world.", 150) == [
        Segment("Hello world.", Boundary.STATEMENT)
    ]


@pytest.mark.parametrize("blank", ["", "   ", "\n\n", "\n \n\n"])
def test_blank_text_yields_no_segments(blank: str) -> None:
    assert split_into_segments(blank, 150) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Done.", Boundary.STATEMENT),
        ("Done", Boundary.STATEMENT),
        ("Really?", Boundary.QUESTION),
        ("No way!", Boundary.EXCLAMATION),
        ("Really?!", Boundary.QUESTION),
        ("What!?", Boundary.QUESTION),
        ("Stop!!!", Boundary.EXCLAMATION),
        ("Well...", Boundary.ELLIPSIS),
        ("Well\u2026", Boundary.ELLIPSIS),
        ("First:", Boundary.CLAUSE),
        ("First;", Boundary.CLAUSE),
        ("alpha,", Boundary.COMMA),
    ],
)
def test_ending_classification(text: str, expected: Boundary) -> None:
    assert classify_ending(text) is expected


def test_each_terminal_keeps_its_own_segment_and_boundary() -> None:
    text = "It is late. Are you coming? Hurry up! Fine... Wait: go."
    assert split_into_segments(text, 150) == [
        Segment("It is late.", Boundary.STATEMENT),
        Segment("Are you coming?", Boundary.QUESTION),
        Segment("Hurry up!", Boundary.EXCLAMATION),
        Segment("Fine...", Boundary.ELLIPSIS),
        Segment("Wait:", Boundary.CLAUSE),
        Segment("go.", Boundary.STATEMENT),
    ]


def test_an_exclamation_is_never_merged_into_the_sentence_before_it() -> None:
    """Merging is what used to flatten a `!` into a neighbouring statement."""
    assert _texts("It is fine. Not really! It is fine.") == [
        "It is fine.",
        "Not really!",
        "It is fine.",
    ]


def test_adjacent_statements_are_merged_up_to_the_limit() -> None:
    assert _texts("A. B. C. D.") == ["A. B. C. D."]
    assert _texts("First one. Second one. Third one.", 25) == [
        "First one. Second one.",
        "Third one.",
    ]


def test_a_statement_followed_by_a_question_is_not_merged() -> None:
    assert _texts("Yes. Is it?") == ["Yes.", "Is it?"]


def test_newlines_split_like_the_reference_demo() -> None:
    assert _texts("line one\nline two", 9) == ["line one", "line two"]


def test_a_blank_line_is_a_paragraph_break_nothing_merges_across() -> None:
    segments = split_into_segments("One.\n\nTwo.", 150)
    assert segments == [
        Segment("One.", Boundary.PARAGRAPH),
        Segment("Two.", Boundary.STATEMENT),
    ]


def test_paragraph_break_after_a_question_still_pauses_as_a_paragraph() -> None:
    assert _boundaries("Ready?\n\nGo!") == [Boundary.PARAGRAPH, Boundary.EXCLAMATION]


def test_overlong_sentence_splits_at_commas_then_words() -> None:
    text = "alpha beta, gamma delta epsilon zeta eta theta"
    segments = split_into_segments(text, 20)
    assert all(len(s.text) <= 20 for s in segments)
    joined = " ".join(s.text for s in segments)
    assert joined.replace(",", "").split() == text.replace(",", "").split()
    assert segments[0].boundary is Boundary.COMMA
    assert segments[-1].boundary is Boundary.STATEMENT  # the sentence's own ending


def test_overlong_question_keeps_the_question_on_its_last_piece_only() -> None:
    segments = split_into_segments("one two three four five six seven eight nine?", 20)
    assert [s.boundary for s in segments[:-1]] == [Boundary.WORD] * (len(segments) - 1)
    assert segments[-1].boundary is Boundary.QUESTION


def test_unbroken_token_is_hard_cut() -> None:
    segments = split_into_segments("x" * 45, 20)
    assert [len(s.text) for s in segments] == [20, 20, 5]
    assert [s.boundary for s in segments[:-1]] == [Boundary.WORD, Boundary.WORD]


@pytest.mark.parametrize("length", [1, 149, 150, 151, 500])
def test_every_segment_respects_limit_and_nothing_is_lost(length: int) -> None:
    text = ("word " * 200)[:length].strip() or "w"
    texts = _texts(text, 150)
    assert all(0 < len(t) <= 150 for t in texts)
    assert "".join(texts).replace(" ", "") == text.replace(" ", "")


def test_punctuation_only_input_is_kept() -> None:
    assert _texts("?!") == ["?!"]
    assert _boundaries("?!") == [Boundary.QUESTION]
    assert _texts(".") == ["."]


def test_ellipsis_runs_and_unicode_ellipsis_stay_one_segment() -> None:
    assert _texts("Hmm..... maybe") == ["Hmm.....", "maybe"]
    assert _boundaries("Hmm\u2026 maybe") == [Boundary.ELLIPSIS, Boundary.STATEMENT]


def test_a_dot_inside_a_token_is_not_a_sentence_end() -> None:
    assert _texts("see e.g.x now") == ["see e.g.x now"]


def test_invalid_limit_raises() -> None:
    with pytest.raises(ValueError):
        split_into_segments("hi", 0)


def test_boundary_names_match_the_configured_pause_table() -> None:
    """A boundary missing from the table would KeyError at synthesis time."""
    assert {b.value for b in Boundary} == set(DEFAULT_TTS_PAUSE_SECONDS)


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


def _pause(boundary: Boundary) -> int:
    return int(
        settings.TTS_PAUSE_SECONDS[boundary.value]
        * synth_hparams.sample_rate
        / synth_hparams.hop_size
    )


def test_multi_chunk_mel_is_chunks_plus_pauses(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 20)
    text = "First sentence here. Second one follows!"
    mel = tts_pipeline.synthesize_speech(text, EMB)
    pause = _pause(Boundary.STATEMENT)  # the gap follows the FIRST segment's ending
    expected = (
        _frames_for("First sentence here.") + pause + _frames_for("Second one follows!")
    )
    assert mel.shape == (80, expected)
    assert mel.dtype == np.float32
    # the inserted gap is the mel floor (silence)
    gap_start = _frames_for("First sentence here.")
    assert np.all(mel[:, gap_start : gap_start + pause] == -synth_hparams.max_abs_value)


def test_pause_length_depends_on_how_the_previous_segment_ended(monkeypatch) -> None:
    """The same two sentences, joined after a statement, a question and a paragraph."""
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 10)  # keep them from merging
    base = _frames_for("Go now.") + _frames_for("Go now.")
    lengths = {}
    for name, first, sep in [
        ("statement", "Go now.", " "),
        ("question", "Go now?", " "),
        ("exclamation", "Go now!", " "),
        ("ellipsis", "Go now...", " "),
        ("paragraph", "Go now.", "\n\n"),
    ]:
        mel = tts_pipeline.synthesize_speech(first + sep + "Go now.", EMB)
        lengths[name] = mel.shape[1] - _frames_for(first) - _frames_for("Go now.")
    assert lengths == {
        "statement": _pause(Boundary.STATEMENT),
        "question": _pause(Boundary.QUESTION),
        "exclamation": _pause(Boundary.EXCLAMATION),
        "ellipsis": _pause(Boundary.ELLIPSIS),
        "paragraph": _pause(Boundary.PARAGRAPH),
    }
    assert (
        lengths["paragraph"]
        > lengths["ellipsis"]
        > lengths["question"]
        > lengths["statement"]
    )
    assert base > 0


def test_a_configured_pause_is_honoured(monkeypatch) -> None:
    monkeypatch.setitem(settings.TTS_PAUSE_SECONDS, "question", 1.0)
    mel = tts_pipeline.synthesize_speech("Go now? Go now.", EMB)
    gap = mel.shape[1] - _frames_for("Go now?") - _frames_for("Go now.")
    assert gap == int(1.0 * synth_hparams.sample_rate / synth_hparams.hop_size)


def test_line_and_paragraph_breaks_survive_cleaning() -> None:
    cleaned = tts_pipeline._clean_for_chunking(
        "Dr. Who has  3 cats.\n\n  Next   line\nthird"
    )
    assert cleaned == "doctor who has three cats.\n\nnext line\nthird"


def test_a_zero_pause_joins_the_segments_directly(monkeypatch) -> None:
    monkeypatch.setitem(settings.TTS_PAUSE_SECONDS, "statement", 0.0)
    mel = tts_pipeline.synthesize_speech("Go now. Go now?", EMB)
    # "Go now." and "Go now?" are not merged (different endings); no gap between them
    assert mel.shape[1] == _frames_for("Go now.") + _frames_for("Go now?")


def test_blank_text_still_reaches_the_single_chunk_path() -> None:
    assert tts_pipeline.synthesize_speech("   ", EMB).shape[0] == 80


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


# ---- chunking counts cleaned symbols, not raw characters --------------------


def test_clean_for_chunking_expands_numbers() -> None:
    cleaned = tts_pipeline._clean_for_chunking("I paid $45 for 12 tickets.")
    assert not any(ch.isdigit() for ch in cleaned)
    assert len(cleaned) > len("I paid $45 for 12 tickets.")


def test_clean_for_chunking_leaves_arpabet_braces_raw() -> None:
    text = "Turn left on {HH AW1 S S T AH0 N} Street."
    assert tts_pipeline._clean_for_chunking(text) == text


def test_digit_heavy_chunks_respect_limit_after_cleaning(monkeypatch) -> None:
    """120 raw digit-heavy chars expand to ~250 symbols; the limit must hold."""
    seen: list[str] = []
    real = tts_pipeline._synthesize_chunk

    def spy(text: str, emb: np.ndarray) -> np.ndarray:
        seen.append(text)
        return real(text, emb)

    monkeypatch.setattr(tts_pipeline, "_synthesize_chunk", spy)
    text = ("In 2024 there were 1,234,567 visitors, 89 percent paid $45.50. " * 8)[:500]
    tts_pipeline.synthesize_speech(text, EMB)
    assert len(seen) > 1
    decoded = [len(tts_pipeline._clean_for_chunking(chunk)) for chunk in seen]
    assert max(decoded) <= settings.TTS_CHUNK_MAX_CHARS
