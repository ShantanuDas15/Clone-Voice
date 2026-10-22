"""The positive control for the question metric (SPEECH_QUALITY_PLAN.md S0.3)."""

import numpy as np
import pytest

from backend import question_control as qc
from backend.tests.test_evaluate_synthesis import SR, tone

# --- labelling heuristic -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["DO YOU THINK SO", "is it better than anywhere else", "HAVE I TOLD YOU ABOUT IT"],
)
def test_yes_no_questions_are_recognised(text):
    assert qc.is_yes_no_question(text)
    assert not qc.is_statement(text)


@pytest.mark.parametrize(
    "text",
    [
        "WHAT DO YOU THINK OF IT",  # wh-question
        "DO YOU THINK SO SHE ASKED",  # attribution
        "DO IT",  # too short
        "I DO NOT KNOW WHAT YOU MEAN BY THAT",  # statement
        "DO THE WORK AND THEN GO HOME TONIGHT",  # imperative: no pronoun
        "",
    ],
)
def test_other_utterances_are_not_yes_no_questions(text):
    assert not qc.is_yes_no_question(text)


def test_statements_exclude_questions_wh_words_attributions_and_length_extremes():
    assert qc.is_statement("THE HOUSE STOOD ON A HILL")
    assert not qc.is_statement("WHY DID THE HOUSE STAND THERE")
    assert not qc.is_statement("THE HOUSE STOOD THERE HE SAID")
    assert not qc.is_statement("TOO SHORT")
    assert not qc.is_statement(" ".join(["WORD"] * (qc.MAX_WORDS + 1)))


# --- AUC ---------------------------------------------------------------------


def test_auc_is_one_zero_and_half_for_the_extreme_cases():
    assert qc.auc([3, 4], [1, 2]) == 1.0
    assert qc.auc([1, 2], [3, 4]) == 0.0
    assert qc.auc([1, 1], [1, 1]) == 0.5


def test_auc_is_none_when_a_group_is_empty():
    assert qc.auc([], [1.0]) is None
    assert qc.auc([1.0], []) is None


def test_bootstrap_auc_brackets_the_point_and_is_deterministic():
    pos, neg = [3.0, 4.0, 5.0, 2.5], [1.0, 2.0, 3.5, 0.5, 2.7]
    first = qc.bootstrap_auc(pos, neg)
    assert first == qc.bootstrap_auc(pos, neg)
    point, low, high = first
    assert low <= point <= high


def test_bootstrap_auc_is_nan_when_a_group_is_empty():
    assert all(np.isnan(v) for v in qc.bootstrap_auc([], [1.0]))


# --- summary -----------------------------------------------------------------


def test_summary_separates_when_questions_clearly_rise_more():
    summary = qc.summarize(
        [4.0 + 0.1 * i for i in range(20)], [-1.0 + 0.1 * i for i in range(30)]
    )
    assert summary["auc"] == 1.0
    assert summary["separates"] is True
    assert summary["questions"]["n"] == 20
    assert summary["questions"]["share_rising"] == 1.0


def test_summary_does_not_separate_identical_groups():
    values = [float(i) for i in range(20)]
    summary = qc.summarize(values, values)
    assert abs(summary["auc"] - 0.5) < 0.05
    assert summary["separates"] is False


def test_summary_with_no_questions_does_not_claim_separation():
    summary = qc.summarize([], [1.0, 2.0])
    assert summary["separates"] is False
    assert summary["questions"]["share_rising"] is None


# --- slopes ------------------------------------------------------------------


def test_slopes_see_a_final_rise_and_skip_unmeasurable_clips():
    rising = tone(150.0, 220.0, seconds=1.5)
    falling = tone(220.0, 150.0, seconds=1.5)
    silent = np.zeros(SR, dtype=np.float32)
    result = qc.slopes([("a", rising), ("b", falling), ("c", silent)])
    assert len(result) == 2
    assert result[0] > 0 > result[1]
