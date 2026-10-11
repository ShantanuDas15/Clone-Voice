"""Rule-based sentence analysis (SPEECH_QUALITY_PLAN.md S5.1a)."""

import pytest

from backend.services.text_analysis import (EMOTIONS, LEXICON, PACES, Analysis,
                                            analyze, analyze_segments)
from backend.services.text_chunking import Boundary, split_into_segments


@pytest.mark.parametrize(
    "text,emotion",
    [
        ("I can't believe you!!", "angry"),
        ("I miss her...", "sad"),
        ("I am so happy today!", "happy"),
        ("I'm terrified of the dark.", "fearful"),
        ("Wow, that is unbelievable!", "surprised"),
        ("The meeting starts at noon.", "neutral"),
        ("Really?", "neutral"),
    ],
)
def test_the_plan_examples_get_their_emotion(text, emotion):
    assert analyze(text).emotion == emotion


def test_an_angry_double_exclamation_is_intense_and_energetic():
    a = analyze("I can't believe you!!")
    assert a.intensity >= 0.9 and a.arousal >= 0.7 and a.pace == "fast"
    assert a.valence < 0 and a.exclamations == 2


def test_a_sad_ellipsis_is_slow_and_low_arousal():
    a = analyze("I miss her...")
    assert a.pace == "slow" and a.arousal < 0.3 and a.valence < 0


def test_a_question_is_flagged_and_stays_neutral_without_evidence():
    a = analyze("Really?")
    assert a.is_question and a.emotion == "neutral" and a.intensity == 0.0


def test_a_neutral_sentence_has_no_intensity_valence_or_cues():
    a = analyze("The report is on the table.")
    assert (a.intensity, a.valence, a.cues, a.pace) == (0.0, 0.0, (), "normal")


def test_exclamations_and_caps_raise_intensity_but_never_past_one():
    plain = analyze("I am happy.")
    loud = analyze("I am HAPPY!!!!!")
    assert loud.intensity > plain.intensity and loud.intensity <= 1.0
    assert loud.arousal > plain.arousal


def test_emphasis_comes_from_caps_and_stars_in_order_without_duplicates():
    a = analyze("I said *never* touch THAT, NEVER.")
    assert a.emphasis_words == ("never", "that")


def test_short_caps_words_such_as_I_and_OK_are_not_emphasis():
    assert analyze("I said OK, so I go.").emphasis_words == ()


def test_a_negated_happy_word_turns_sad_but_weaker():
    plain, negated = analyze("I am happy."), analyze("I am not happy.")
    assert negated.emotion == "sad" and negated.intensity < plain.intensity
    assert "negated 'happy'" in negated.cues


def test_contradictory_cues_the_stronger_evidence_wins():
    a = analyze("I'm so happy...")
    assert a.emotion == "happy" and a.arousal < analyze("I'm so happy!").arousal


def test_a_longer_phrase_beats_the_shorter_one_inside_it():
    assert analyze("I can't believe you did that").emotion == "angry"
    assert analyze("I can't believe it").emotion == "surprised"


def test_a_lexicon_word_inside_another_word_does_not_count():
    assert analyze("The glad-handing was great, mostly a mislove.").emotion == "happy"
    assert analyze("Cryptography is fun.").emotion == "neutral"


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_input_is_neutral(text):
    a = analyze(text)
    assert a.emotion == "neutral" and a.intensity == 0.0 and a.cues == ()


def test_emoji_and_other_scripts_do_not_break_it():
    assert analyze("😀 こんにちは").emotion == "neutral"
    assert analyze("I am happy 😀").emotion == "happy"


def test_it_is_deterministic():
    text = "I hate this, but I love you!"
    assert analyze(text) == analyze(text)


def test_every_output_is_inside_its_documented_range():
    for text in ["!!!", "NO NO NO!!!", "so sad...", "wow?!", "love hate", "a" * 400]:
        a = analyze(text)
        assert a.emotion in EMOTIONS and a.pace in PACES
        assert 0 <= a.intensity <= 1 and 0 <= a.arousal <= 1
        assert -1 <= a.valence <= 1


def test_every_lexicon_entry_names_a_known_emotion_and_a_sane_weight():
    for phrase, (emotion, weight) in LEXICON.items():
        assert emotion in EMOTIONS and emotion != "neutral", phrase
        assert 0 < weight <= 1, phrase
        assert phrase == phrase.lower(), phrase


def test_a_passage_shifts_from_calm_to_angry_sentence_by_sentence():
    segments = split_into_segments(
        "The report is ready. I hate this delay! It is unacceptable!!", 200
    )
    emotions = [a.emotion for a in analyze_segments(segments)]
    assert emotions == ["neutral", "angry", "angry"]


def test_a_given_boundary_overrides_reading_the_text():
    assert analyze("Fine", Boundary.QUESTION).is_question
    assert isinstance(analyze("Fine"), Analysis)
