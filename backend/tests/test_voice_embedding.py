"""Combining several clips into one voice embedding (SPEECH_QUALITY_PLAN.md S2.1)."""

import numpy as np
import pytest

from backend.services.voice_embedding import (
    aggregate_embeddings,
    clip_agreement,
    find_outliers,
)


def _vec(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float32)


# --- aggregate_embeddings ----------------------------------------------------


def test_result_is_unit_length_float32():
    out = aggregate_embeddings([_vec(3, 0, 0), _vec(0, 4, 0)])
    assert out.dtype == np.float32
    assert np.linalg.norm(out) == pytest.approx(1.0, abs=1e-6)


def test_one_embedding_comes_back_normalised_in_the_same_direction():
    out = aggregate_embeddings([_vec(2, 0, 2)])
    assert out == pytest.approx(np.array([1, 0, 1]) / np.sqrt(2), abs=1e-6)


def test_order_does_not_matter():
    clips = [_vec(1, 0.2, 0), _vec(0.9, 0, 0.3), _vec(0.8, 0.1, 0.1)]
    forward = aggregate_embeddings(clips)
    backward = aggregate_embeddings(list(reversed(clips)))
    assert forward == pytest.approx(backward, abs=1e-6)


def test_magnitude_does_not_let_one_clip_dominate():
    quiet = aggregate_embeddings([_vec(1, 0), _vec(0, 1)])
    loud = aggregate_embeddings([_vec(1000, 0), _vec(0, 1)])
    assert loud == pytest.approx(quiet, abs=1e-6)


def test_a_duplicate_clip_pulls_the_mean_toward_itself():
    plain = aggregate_embeddings([_vec(1, 0), _vec(0, 1)])
    doubled = aggregate_embeddings([_vec(1, 0), _vec(1, 0), _vec(0, 1)])
    assert doubled[0] > plain[0]


def test_accepts_lists_of_python_floats_and_other_shapes_that_flatten():
    out = aggregate_embeddings([[1.0, 0.0], np.array([[0.0, 1.0]])])
    assert out.shape == (2,)


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [_vec(0, 0, 0)],
        [_vec(1, 0), _vec(0, 0)],
        [_vec(1, 0), _vec(1, 0, 0)],
        [_vec(1, np.nan)],
        [_vec(1, np.inf)],
    ],
)
def test_bad_input_is_rejected(bad):
    with pytest.raises(ValueError):
        aggregate_embeddings(bad)


def test_opposite_embeddings_have_no_mean_direction():
    with pytest.raises(ValueError):
        aggregate_embeddings([_vec(1, 0), _vec(-1, 0)])


# --- clip_agreement and find_outliers ---------------------------------------


def test_a_lone_clip_agrees_with_itself():
    assert clip_agreement([_vec(1, 2, 3)]) == [1.0]


def test_identical_clips_agree_fully():
    scores = clip_agreement([_vec(1, 0), _vec(2, 0), _vec(0.5, 0)])
    assert scores == pytest.approx([1.0, 1.0, 1.0])


def test_a_different_speaker_scores_lowest():
    same_a, same_b, other = _vec(1, 0.1, 0), _vec(0.95, 0.05, 0.05), _vec(0, 0.2, 1)
    scores = clip_agreement([same_a, same_b, other])
    assert scores[2] == min(scores)
    # the outlier also drags down the mean the good clips are compared with, so they score
    # about 0.7 rather than near 1; it is the outlier that falls far below them
    assert scores[0] > 0.6 and scores[1] > 0.6
    assert scores[2] < 0.3


def test_find_outliers_flags_only_the_clip_below_the_threshold():
    clips = [
        _vec(1, 0.1, 0),
        _vec(0.95, 0.05, 0.05),
        _vec(0.9, 0.1, 0.02),
        _vec(0, 0.2, 1),
    ]
    assert find_outliers(clips, min_agreement=0.6) == [3]
    assert find_outliers(clips, min_agreement=0.0) == []


def test_two_clips_cannot_out_vote_each_other():
    """With no majority there is nothing to flag, however different the clips are."""
    assert find_outliers([_vec(1, 0), _vec(0, 1)], min_agreement=0.99) == []
    assert find_outliers([_vec(1, 0)], min_agreement=0.99) == []


def test_find_outliers_still_validates_small_inputs():
    with pytest.raises(ValueError):
        find_outliers([_vec(0, 0)], min_agreement=0.5)
    with pytest.raises(ValueError):
        find_outliers([], min_agreement=0.5)
