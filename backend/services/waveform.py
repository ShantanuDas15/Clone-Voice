"""Waveform peaks of a generated WAV, for the History preview (UX plan H4)."""

import logging
from typing import List, Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

#: Bars stored per generation; matches the bars the frontend draws.
WAVEFORM_BARS = 64
#: Peaks are whole numbers 0..100 (the loudest bar is 100): small to store, plenty to draw.
PEAK_SCALE = 100


def bucket_peaks(samples: np.ndarray, bars: int = WAVEFORM_BARS) -> Optional[List[int]]:
    """Reduce samples to ``bars`` heights 0..100, the loudest slice being 100; None if silent."""
    if samples.size == 0 or bars <= 0:
        return None
    magnitudes = np.abs(samples.astype(np.float32))
    edges = np.linspace(0, magnitudes.size, bars + 1).astype(int)
    peaks = np.array(
        [
            magnitudes[start : max(start + 1, end)].max()
            for start, end in zip(edges[:-1], edges[1:])
            if start < magnitudes.size
        ],
        dtype=np.float32,
    )
    loudest = float(peaks.max()) if peaks.size else 0.0
    if loudest <= 0.0:
        return None
    return [int(round(v)) for v in peaks / loudest * PEAK_SCALE]


def compute_waveform_peaks(path: str, bars: int = WAVEFORM_BARS) -> Optional[List[int]]:
    """Peaks of the WAV at ``path``, or None when it cannot be read. Never raises: a preview must
    not make a finished generation fail."""
    try:
        data, _ = sf.read(path, dtype="float32", always_2d=True)
        return bucket_peaks(data[:, 0], bars)
    except Exception:  # noqa: BLE001 - any decode problem just means no preview
        logger.warning("Could not compute waveform peaks for %s", path, exc_info=True)
        return None
