"""The emotion-accuracy metric of backend/evaluate_synthesis.py (SPEECH_QUALITY_PLAN.md S0.3)."""

import sys
import types

import numpy as np
import pytest

from backend import evaluate_synthesis as es

SENTENCES = [
    {
        "id": "a",
        "stem": "x",
        "neutral": "n1",
        "happy": "h1",
        "sad": "s1",
        "angry": "a1",
    },
    {
        "id": "b",
        "stem": "y",
        "neutral": "n2",
        "happy": "h2",
        "sad": "s2",
        "angry": "a2",
    },
]


# --- pure metrics -------------------------------------------------------------


def test_accuracy_counts_agreeing_pairs():
    pairs = [
        ("happy", "happy"),
        ("sad", "angry"),
        ("angry", "angry"),
        ("neutral", "sad"),
    ]
    assert es.emotion_accuracy(pairs) == pytest.approx(0.5)


def test_accuracy_of_nothing_is_none_not_zero():
    assert es.emotion_accuracy([]) is None


def test_recall_looks_only_at_the_intended_label():
    pairs = [("happy", "happy"), ("happy", "sad"), ("sad", "sad")]
    assert es.emotion_recall(pairs, "happy") == pytest.approx(0.5)
    assert es.emotion_recall(pairs, "sad") == 1.0
    assert es.emotion_recall(pairs, "angry") is None  # none were intended


def test_confusion_shows_every_label_and_counts_heard_labels():
    table = es.emotion_confusion([("happy", "sad"), ("happy", "sad"), ("sad", "sad")])
    assert set(table) == set(es.EMOTIONS)
    assert all(set(row) == set(es.EMOTIONS) for row in table.values())
    assert table["happy"]["sad"] == 2 and table["sad"]["sad"] == 1
    assert sum(sum(row.values()) for row in table.values()) == 3


# --- per-speaker evaluation ---------------------------------------------------


def _fake_synth(calls):
    def synth(text, embedding, speaker, seed):
        calls.append((text, seed))
        return np.full(1600, ord(text[0]), dtype=np.float32)

    return synth


def test_evaluate_emotions_renders_four_per_sentence_with_distinct_seeds(monkeypatch):
    calls = []
    monkeypatch.setattr(es, "_synthesize", _fake_synth(calls))
    es.evaluate_emotions(np.zeros(256), "spk", 7, SENTENCES, lambda audio: "neutral")
    assert [text for text, _ in calls] == [
        "n1", "h1", "s1", "a1", "n2", "h2", "s2", "a2",
    ]  # fmt: skip
    seeds = [seed for _, seed in calls]
    assert len(set(seeds)) == len(seeds)  # no two renderings share a seed


def test_evaluate_emotions_scores_the_classifier_against_the_intended_label(
    monkeypatch,
):
    monkeypatch.setattr(es, "_synthesize", _fake_synth([]))
    by_first_letter = {ord("n"): "neutral", ord("h"): "happy", ord("s"): "sad"}
    # Perfect on neutral/happy/sad, always wrong on angry.
    row = es.evaluate_emotions(
        np.zeros(256),
        "spk",
        7,
        SENTENCES,
        lambda audio: by_first_letter.get(int(audio[0]), "neutral"),
    )
    assert row["emotion_accuracy"] == pytest.approx(0.75)
    assert row["emotion_recall_happy"] == 1.0
    assert row["emotion_recall_angry"] == 0.0
    assert len(row["emotion_pairs"]) == 8


def test_a_classifier_that_always_says_neutral_scores_chance(monkeypatch):
    """The no-emotion-control case: the metric must not flatter it."""
    monkeypatch.setattr(es, "_synthesize", _fake_synth([]))
    row = es.evaluate_emotions(np.zeros(256), "spk", 7, SENTENCES, lambda a: "neutral")
    assert row["emotion_accuracy"] == pytest.approx(0.25)


def test_evaluate_emotions_with_no_sentences_reports_none(monkeypatch):
    monkeypatch.setattr(es, "_synthesize", _fake_synth([]))
    row = es.evaluate_emotions(np.zeros(256), "spk", 7, [], lambda audio: "neutral")
    assert row["emotion_accuracy"] is None and row["emotion_pairs"] == []


# --- the classifier wrapper ---------------------------------------------------


def _fake_transformers(monkeypatch, id2label, winner):
    """Install a stand-in ``transformers`` whose model always picks class ``winner``."""
    import torch

    class Model:
        config = types.SimpleNamespace(id2label=id2label)

        def eval(self):
            return self

        def __call__(self, **inputs):
            logits = torch.zeros(1, len(id2label))
            logits[0, winner] = 1.0
            return types.SimpleNamespace(logits=logits)

    module = types.SimpleNamespace(
        AutoFeatureExtractor=types.SimpleNamespace(
            from_pretrained=lambda name: lambda audio, **kw: {"input_values": audio}
        ),
        AutoModelForAudioClassification=types.SimpleNamespace(
            from_pretrained=lambda name: Model()
        ),
    )
    monkeypatch.setitem(sys.modules, "transformers", module)


def test_classifier_maps_the_models_short_labels_to_ours(monkeypatch):
    _fake_transformers(monkeypatch, {0: "neu", 1: "hap", 2: "ang", 3: "sad"}, winner=2)
    classify = es.make_emotion_classifier()
    assert classify(np.zeros(16000, np.float32)) == "angry"


def test_classifier_refuses_a_model_with_other_classes(monkeypatch):
    _fake_transformers(monkeypatch, {0: "neu", 1: "hap", 2: "fear", 3: "sad"}, winner=0)
    with pytest.raises(SystemExit, match="expected"):
        es.make_emotion_classifier()


def test_classifier_without_transformers_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)  # makes the import fail
    with pytest.raises(SystemExit, match="pip install transformers"):
        es.make_emotion_classifier()
