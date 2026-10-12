"""Mapping a sentence analysis to engine controls (SPEECH_QUALITY_PLAN.md S5.2a)."""

import pytest

from backend.services.style_mapping import (EXAGGERATION_DEFAULT,
                                            EXAGGERATION_MAX, EXAGGERATION_MIN,
                                            EngineControls, build_style,
                                            engine_controls, resolve_style)
from backend.services.text_analysis import EMOTIONS, analyze
from backend.services.tts_engine import NEUTRAL, SynthesisStyle


def test_every_emotion_label_maps_to_neutral_for_a_neutral_only_engine():
    for text in ("I hate this!", "I miss her...", "I am happy!", "Wow!", "Hello."):
        assert resolve_style(analyze(text), (NEUTRAL,)) == SynthesisStyle(NEUTRAL, 0.0)


def test_a_listed_emotion_is_passed_with_its_intensity():
    a = analyze("I hate this!")
    style = resolve_style(a, ("neutral", "angry"))
    assert style == SynthesisStyle("angry", a.intensity)


def test_an_unlisted_emotion_falls_back_to_neutral_not_an_error():
    assert resolve_style(analyze("I hate this!"), ("neutral", "happy")).emotion == (
        NEUTRAL
    )


def test_every_label_is_handled():
    for emotion in EMOTIONS:
        a = analyze("x")
        a = type(a)(**{**a.__dict__, "emotion": emotion, "intensity": 0.5})
        assert resolve_style(a, EMOTIONS).emotion == emotion
        assert resolve_style(a, (NEUTRAL,)).emotion == NEUTRAL


def test_a_cue_free_sentence_gets_exactly_the_engine_default():
    c = engine_controls("chatterbox", analyze("The report is on the table."))
    assert c.exaggeration == EXAGGERATION_DEFAULT


def test_energy_raises_exaggeration_and_calm_lowers_it():
    calm = engine_controls("chatterbox", analyze("I miss her...")).exaggeration
    plain = engine_controls("chatterbox", analyze("It is noon.")).exaggeration
    loud = engine_controls("chatterbox", analyze("I can't believe you!!")).exaggeration
    assert calm < plain < loud


@pytest.mark.parametrize(
    "text", ["!!!!!!", "NO NO NO!!!!", "so sad...", "", "wow?!", "hate hate!!!"]
)
def test_exaggeration_stays_inside_the_measured_safe_range(text):
    value = engine_controls("chatterbox", analyze(text)).exaggeration
    assert EXAGGERATION_MIN <= value <= EXAGGERATION_MAX


@pytest.mark.parametrize(
    "engine", ["sv2tts", "chatterbox_turbo", "chatterbox_nano", "unknown"]
)
def test_engines_without_the_control_get_none(engine):
    assert engine_controls(engine, analyze("I hate this!!")) == EngineControls()


def test_build_style_carries_the_emotion_and_the_engine_control():
    calm = analyze("The report is on the table.")
    assert build_style("chatterbox", (NEUTRAL,), calm) == SynthesisStyle(
        NEUTRAL, 0.0, EXAGGERATION_DEFAULT
    )
    loud = analyze("I hate this!!")
    style = build_style("chatterbox", (NEUTRAL,), loud)
    assert style.emotion == NEUTRAL and style.exaggeration > EXAGGERATION_DEFAULT


def test_build_style_leaves_the_control_unset_for_an_engine_without_it():
    for name in ("sv2tts", "chatterbox_turbo", "chatterbox_nano"):
        assert (
            build_style(name, (NEUTRAL,), analyze("I hate this!!")).exaggeration is None
        )
