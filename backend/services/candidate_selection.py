"""Choose the best of several synthesis candidates (SPEECH_QUALITY_PLAN.md S2.5).

SV2TTS samples stochastically (dropout stays on at inference), so the same text and voice give a
slightly different result each time, some closer to the speaker than others. Pure numpy, no model:
the encoder runs elsewhere; this module only scores and ranks what it produced.
"""

from typing import Optional, Sequence

import numpy as np

# Returned for a candidate that cannot be scored (blank or non-finite embedding): below any real
# cosine, so it never wins against a candidate that could be scored.
UNSCORABLE = -1.0


def speaker_similarity(profile: np.ndarray, candidate: Optional[np.ndarray]) -> float:
    """Cosine of the profile embedding and a candidate's embedding; ``UNSCORABLE`` if unusable."""
    if candidate is None:
        return UNSCORABLE
    a = np.asarray(profile, dtype=np.float64).ravel()
    b = np.asarray(candidate, dtype=np.float64).ravel()
    if a.shape != b.shape or not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        return UNSCORABLE
    norms = np.linalg.norm(a) * np.linalg.norm(b)
    if norms == 0.0:
        return UNSCORABLE
    return float(np.clip(np.dot(a, b) / norms, -1.0, 1.0))


def pick_best(scores: Sequence[float]) -> int:
    """Index of the highest score; the earliest wins a tie, so N=1 and ties are deterministic."""
    if len(scores) == 0:
        raise ValueError("at least one candidate is required")
    best = 0
    for i, score in enumerate(scores):
        if score > scores[best]:
            best = i
    return best
