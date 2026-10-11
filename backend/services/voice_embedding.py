"""Combine several clips of one speaker into a single voice embedding.

SPEECH_QUALITY_PLAN.md S2.1. Pure numpy, no model: the encoder runs elsewhere
(`tts_pipeline.embed_speaker`); this module only decides how its outputs combine.

A speaker's voice varies from clip to clip (words, loudness, mood, microphone), so one
clip's embedding is a noisy estimate. The mean of several, re-normalised, is a steadier
one, and it is the same operation resemblyzer applies across the windows of a single clip.
"""

from typing import List, Sequence

import numpy as np

# A clip scoring below this against the others is probably a different speaker (SPEECH_QUALITY_STUDY.md,
# S2.1a: 95.8% of other-speaker clips fell below it, 1.7% of true clips did). A warning, never a control.
CLIP_AGREEMENT_WARN = 0.75


def _as_unit_matrix(embeddings: Sequence[np.ndarray]) -> np.ndarray:
    """Stack embeddings into rows of unit length; reject empty, ragged or zero input."""
    if len(embeddings) == 0:
        raise ValueError("at least one embedding is required")
    rows = [np.asarray(e, dtype=np.float64).ravel() for e in embeddings]
    if len({r.shape for r in rows}) != 1:
        raise ValueError("embeddings must all have the same length")
    matrix = np.stack(rows)
    norms = np.linalg.norm(matrix, axis=1)
    if not np.all(np.isfinite(matrix)) or np.any(norms == 0.0):
        raise ValueError("embeddings must be finite and non-zero")
    return matrix / norms[:, None]


def aggregate_embeddings(embeddings: Sequence[np.ndarray]) -> np.ndarray:
    """Return the unit-length mean of ``embeddings`` as float32.

    Each embedding is normalised first so that no single clip dominates by magnitude, and the
    result does not depend on their order. One embedding comes back normalised, unchanged in
    direction.
    """
    mean = _as_unit_matrix(embeddings).mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm == 0.0:
        raise ValueError("embeddings cancel out and have no mean direction")
    return (mean / norm).astype(np.float32)


def clip_agreement(embeddings: Sequence[np.ndarray]) -> List[float]:
    """Cosine of each clip with the mean of the *other* clips; a lone clip scores 1.0.

    A clip that disagrees with the rest is probably another person, or unusable audio.
    """
    matrix = _as_unit_matrix(embeddings)
    if len(matrix) == 1:
        return [1.0]
    total = matrix.sum(axis=0)
    scores = []
    for row in matrix:
        others = total - row
        scores.append(float(np.dot(row, others) / np.linalg.norm(others)))
    return scores


def find_outliers(embeddings: Sequence[np.ndarray], min_agreement: float) -> List[int]:
    """Indices of clips whose agreement with the others is below ``min_agreement``.

    With fewer than three clips there is no majority to compare against, so nothing is flagged.
    """
    if len(embeddings) < 3:
        _as_unit_matrix(embeddings)  # still validate the input
        return []
    return [i for i, s in enumerate(clip_agreement(embeddings)) if s < min_agreement]
