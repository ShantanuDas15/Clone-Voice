"""The evaluation corpus tool and the expressive sentence set (SPEECH_QUALITY_PLAN.md S0.2)."""

import io
import json
import uuid
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import evaluate_synthesis as es
from backend import prepare_eval_corpus as pc
from backend.schemas.synthesize import SynthesizeRequest

SR = pc.SAMPLE_RATE

# --- pitch groups ------------------------------------------------------------


@pytest.mark.parametrize(
    "hz,expected",
    [
        (95.0, "adult_low_f0"),
        (164.9, "adult_low_f0"),
        (165.0, "adult_high_f0"),
        (210.0, "adult_high_f0"),
        (None, "unknown"),
        (0.0, "unknown"),
        (float("nan"), "unknown"),
    ],
)
def test_pitch_group(hz, expected):
    assert pc.pitch_group(hz) == expected


# --- clip choice -------------------------------------------------------------


def _clips(*seconds: float, prefix: str = "u"):
    return [pc.Clip(f"{prefix}{i:02d}", s) for i, s in enumerate(seconds)]


def test_reference_is_the_clip_nearest_fifteen_seconds_in_range():
    clips = _clips(4, 6, 8, 12, 17, 28, 5, 6, 7, 9)
    reference, held = pc.choose_clips(clips)
    assert reference.seconds == 17  # 17 s is 2 s from 15; 12 s is 3 s away
    assert reference.id not in {c.id for c in held}
    assert len(held) == pc.HELDOUT_CLIPS


def test_reference_tie_breaks_on_id_and_must_be_in_range():
    clips = _clips(14, 16, 4, 5, 6, 7, 8)
    reference, _ = pc.choose_clips(clips)
    assert reference.id == "u00"  # 14 and 16 are equally close: lower id wins
    assert pc.choose_clips(_clips(9.9, 4, 5, 6, 7, 8)) is None  # nothing in 10..30
    assert pc.choose_clips(_clips(30.1, 4, 5, 6, 7, 8)) is None


def test_heldout_clips_are_in_range_and_ordered():
    clips = _clips(15, 2.9, 20.1, 3, 20, 5, 6, 7, 8)
    reference, held = pc.choose_clips(clips)
    assert [c.seconds for c in held] == [3, 20, 5, 6, 7]  # ids u03, u04, u05, u06, u07
    assert all(3 <= c.seconds <= 20 for c in held)


def test_a_speaker_with_too_few_heldout_clips_does_not_qualify():
    assert pc.choose_clips(_clips(15, 4, 5, 6, 7)) is None  # only 4 others
    assert pc.choose_clips([]) is None


# --- speaker choice ----------------------------------------------------------


def _speaker(n_ok: bool = True):
    return _clips(15, 4, 5, 6, 7, 8) if n_ok else _clips(2, 3)


def test_choose_speakers_is_even_deterministic_and_skips_ineligible():
    clips = {f"{i:03d}": _speaker() for i in range(40)}
    clips["bad"] = _speaker(False)
    chosen = pc.choose_speakers(clips, 4)
    assert chosen == ["000", "010", "020", "030"]
    assert pc.choose_speakers(clips, 4) == chosen
    assert "bad" not in pc.choose_speakers(clips, 100)


def test_choose_speakers_returns_everyone_eligible_when_asked_for_more():
    clips = {"a": _speaker(), "b": _speaker()}
    assert pc.choose_speakers(clips, 5) == ["a", "b"]
    with pytest.raises(ValueError):
        pc.choose_speakers(clips, 0)


# --- writing the corpus ------------------------------------------------------


def _flac(seconds: float, hz: float) -> bytes:
    t = np.arange(int(SR * seconds)) / SR
    y = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, y, SR, format="FLAC")
    return buffer.getvalue()


def test_write_corpus_layout_groups_and_manifest(tmp_path):
    by_speaker = {}
    for speaker, hz in (("low", 110.0), ("high", 220.0)):
        rows = [
            (pc.Clip(f"{speaker}-{i}", s), _flac(s, hz))
            for i, s in enumerate([11, 4, 5, 6, 7, 8])
        ]
        by_speaker[speaker] = rows
    manifest = pc.write_corpus(by_speaker, 2, tmp_path)

    files = sorted(p.name for p in (tmp_path / "low").iterdir())
    assert files[0].startswith("0_ref_")  # the reference sorts first
    assert len(files) == 1 + pc.HELDOUT_CLIPS
    assert json.loads((tmp_path / "groups.json").read_text()) == {
        "high": "adult_high_f0",
        "low": "adult_low_f0",
    }
    assert manifest["speakers"]["low"]["reference"]["seconds"] == 11.0
    assert "no child/elderly" in manifest["group_note"]
    audio, rate = sf.read(next((tmp_path / "low").glob("0_ref_*")))
    assert rate == SR and audio.ndim == 1
    # the corpus is readable by the study as it is
    assert set(es.load_dataset(tmp_path)) == {"low", "high"}


def test_decode_rejects_other_sample_rates():
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(8000, np.float32), 8000, format="WAV")
    with pytest.raises(ValueError):
        pc._decode(buffer.getvalue())


# --- the expressive sentence set ---------------------------------------------


@pytest.fixture(scope="module")
def sentences():
    return es.load_sentences()


def test_fixture_has_forty_unique_complete_groups(sentences):
    assert len(sentences) == 40
    assert len({s["id"] for s in sentences}) == 40
    assert len({s["stem"] for s in sentences}) == 40
    for item in sentences:
        assert {"id", "stem", *es.EMOTIONS} <= set(item)
        assert all(str(item[k]).strip() for k in ("stem", *es.EMOTIONS))


def test_every_stem_has_no_terminal_and_every_sentence_ends_in_one(sentences):
    for item in sentences:
        assert item["stem"][-1].isalnum(), item["stem"]
        for emotion in es.EMOTIONS:
            assert item[emotion][-1] in ".!?", item[emotion]


def test_expressive_sentences_carry_the_expected_punctuation(sentences):
    """Happy and angry lines are exclamatory; neutral lines are plain statements."""
    for item in sentences:
        assert item["neutral"].endswith(".") and "!" not in item["neutral"]
        assert "!" in item["happy"] or "?" in item["happy"], item["happy"]
        assert "!" in item["angry"] or "?" in item["angry"], item["angry"]


def test_every_text_is_accepted_by_the_api_validator(sentences):
    def accepted(text: str) -> None:
        SynthesizeRequest(voice_profile_id=uuid.uuid4(), text=text)

    for item in sentences:
        for terminal in ".?!":
            accepted(item["stem"] + terminal)
        for emotion in es.EMOTIONS:
            accepted(item[emotion])
            assert len(item[emotion]) <= 500


def test_load_sentences_rejects_a_malformed_file(tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps({"sentences": [{"id": "x", "stem": "y"}]}))
    with pytest.raises(SystemExit):
        es.load_sentences(bad)
    bad.write_text("[]")
    with pytest.raises(SystemExit):
        es.load_sentences(bad)


def test_default_sentences_path_exists():
    assert Path(es.DEFAULT_SENTENCES).is_file()
