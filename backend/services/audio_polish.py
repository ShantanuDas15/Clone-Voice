"""Level and clean up synthesized speech before it is stored (SPEECH_QUALITY_PLAN.md S3.3).

Pure numpy/scipy: no model. The vocoder's raw output sits at whatever level the checkpoint
happens to produce and is only clipped to +-1, so one voice can come out much quieter than
another, and a waveform may carry a DC offset and start or end on a non-zero sample (a click
in a player). This module fixes the level and the edges and nothing else: it never changes
the pitch, timing or timbre of the speech. Speech has a high crest factor, so a few isolated
peaks would stop the gain far below the target; a short look-ahead limiter (S3.3b) trims only
those peaks, by at most a configured number of dB, so the level can reach the target.

Loudness is ITU-R BS.1770-4 integrated loudness (K-weighting, 400 ms blocks, absolute and
relative gates), implemented here because ``pyloudnorm`` is not a dependency. The peak
ceiling is a true-peak estimate (4x oversampled), not the sample peak.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import lfilter, resample_poly

logger = logging.getLogger(__name__)

BLOCK_SECONDS = 0.4
BLOCK_HOP_SECONDS = 0.1  # 75% overlap, as BS.1770 specifies
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
FADE_SECONDS = 0.01
LIMITER_LOOKAHEAD_SECONDS = 0.005
LIMITER_LEVEL_PASSES = 3
LEVEL_TOLERANCE_LU = 0.1
TRUE_PEAK_OVERSAMPLE = 4

# Never boost by more than this: a very quiet or mostly-noise output would otherwise be
# amplified into a hiss rather than speech.
MAX_GAIN_DB = 24.0


@dataclass(frozen=True)
class PolishReport:
    """What ``polish_waveform`` measured and did (for logs and tests)."""

    input_lufs: Optional[float]
    output_lufs: Optional[float]
    gain_db: float
    peak_limited: bool
    limiter_reduction_db: float = 0.0


def _k_weighting_coefficients(sample_rate: int) -> tuple:
    """Return the two BS.1770 K-weighting biquads (shelf, high-pass) for a sample rate."""
    # Stage 1: high shelf modelling the head's acoustic effect.
    gain_db, q, fc = 3.999843853973347, 0.7071752369554196, 1681.9744509555319
    k = np.tan(np.pi * fc / sample_rate)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh**0.4996667741545416
    a0 = 1.0 + k / q + k**2
    shelf_b = np.array(
        [
            (vh + vb * k / q + k**2) / a0,
            2.0 * (k**2 - vh) / a0,
            (vh - vb * k / q + k**2) / a0,
        ]
    )
    shelf_a = np.array([1.0, 2.0 * (k**2 - 1.0) / a0, (1.0 - k / q + k**2) / a0])

    # Stage 2: revised low-frequency (RLB) high-pass.
    q, fc = 0.5003270373253953, 38.13547087613982
    k = np.tan(np.pi * fc / sample_rate)
    a0 = 1.0 + k / q + k**2
    hp_b = np.array([1.0, -2.0, 1.0])
    hp_a = np.array([1.0, 2.0 * (k**2 - 1.0) / a0, (1.0 - k / q + k**2) / a0])
    return (shelf_b, shelf_a), (hp_b, hp_a)


def integrated_loudness(waveform: np.ndarray, sample_rate: int) -> Optional[float]:
    """Return BS.1770-4 integrated loudness in LUFS, or None if nothing is loud enough.

    Audio shorter than one 400 ms block is measured as a single ungated block. None means
    every block fell under the absolute gate (silence), so there is no level to normalise.
    """
    if waveform.ndim != 1:
        raise ValueError("integrated_loudness expects a mono waveform")
    if waveform.size == 0 or not np.all(np.isfinite(waveform)):
        return None

    (sb, sa), (hb, ha) = _k_weighting_coefficients(sample_rate)
    weighted = lfilter(hb, ha, lfilter(sb, sa, waveform.astype(np.float64)))
    squared = weighted**2

    block = int(round(BLOCK_SECONDS * sample_rate))
    hop = int(round(BLOCK_HOP_SECONDS * sample_rate))
    if squared.size < block:
        mean_square = np.array([squared.mean()])
    else:
        # Block mean-squares through a cumulative sum: one pass, no 4x re-reading.
        csum = np.concatenate(([0.0], np.cumsum(squared)))
        starts = np.arange(0, squared.size - block + 1, hop)
        mean_square = (csum[starts + block] - csum[starts]) / block

    with np.errstate(divide="ignore"):
        block_lufs = -0.691 + 10.0 * np.log10(mean_square)
    above_absolute = block_lufs > ABSOLUTE_GATE_LUFS
    if not above_absolute.any():
        return None

    relative_gate = (
        -0.691 + 10.0 * np.log10(mean_square[above_absolute].mean()) + RELATIVE_GATE_LU
    )
    kept = above_absolute & (block_lufs > relative_gate)
    return float(-0.691 + 10.0 * np.log10(mean_square[kept].mean()))


def true_peak(waveform: np.ndarray) -> float:
    """Return the oversampled peak magnitude (linear), which can exceed the sample peak."""
    if waveform.size == 0:
        return 0.0
    oversampled = resample_poly(waveform.astype(np.float64), TRUE_PEAK_OVERSAMPLE, 1)
    return float(np.max(np.abs(oversampled)))


def apply_edge_fades(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    """Fade the first and last ``FADE_SECONDS`` in and out so playback never starts on a step."""
    fade = min(int(FADE_SECONDS * sample_rate), waveform.size // 2)
    if fade < 2:
        return waveform
    ramp = np.linspace(0.0, 1.0, fade, dtype=waveform.dtype)
    out = waveform.copy()
    out[:fade] *= ramp
    out[-fade:] *= ramp[::-1]
    return out


def limit_peaks(waveform: np.ndarray, sample_rate: int, ceiling: float) -> np.ndarray:
    """Return the waveform with every sample peak at or under ``ceiling`` (linear), smoothly.

    A look-ahead limiter: the gain needed at each sample is spread over
    ``LIMITER_LOOKAHEAD_SECONDS`` on both sides (minimum, then moving average), so it ramps
    down before a peak and back up after it instead of clipping. Samples already under the
    ceiling keep unity gain away from peaks.
    """
    if ceiling <= 0.0:
        raise ValueError("ceiling must be positive")
    magnitude = np.abs(waveform).astype(np.float64)
    if magnitude.size == 0 or magnitude.max() <= ceiling:
        return waveform
    needed = np.minimum(1.0, ceiling / np.maximum(magnitude, 1e-12))
    window = (
        max(int(LIMITER_LOOKAHEAD_SECONDS * sample_rate), 1) | 1
    )  # odd, so it is centred
    # The minimum over 2*window-1 samples makes every sample in the averaging window at least as
    # strict as the sample being protected, so the average can never undershoot the need.
    floor = minimum_filter1d(needed, size=2 * window - 1, mode="nearest")
    smooth = uniform_filter1d(floor, size=window, mode="nearest")
    return (waveform * smooth.astype(waveform.dtype)).astype(np.float32)


def _apply_gain(
    cleaned: np.ndarray, sample_rate: int, gain_db: float, ceiling: float
) -> tuple:
    """Return ``(waveform, peak_reduction_db)``: ``cleaned`` at the gain, peaks held to ``ceiling``."""
    scaled = (cleaned * np.float32(10.0 ** (gain_db / 20.0))).astype(np.float32)
    before = float(np.max(np.abs(scaled)))
    if true_peak(scaled) <= ceiling:
        return scaled, 0.0
    limited = limit_peaks(scaled, sample_rate, ceiling)
    # Sample peaks are now under the ceiling; inter-sample overshoot is removed by a final trim.
    overshoot = true_peak(limited) / ceiling
    if overshoot > 1.0:
        limited = (limited / np.float32(overshoot)).astype(np.float32)
    after = float(np.max(np.abs(limited)))
    return limited, float(20.0 * np.log10(before / after)) if after > 0.0 else 0.0


def polish_waveform(
    waveform: np.ndarray,
    sample_rate: int,
    target_lufs: float,
    peak_ceiling_dbfs: float,
    limiter_max_reduction_db: float = 0.0,
) -> tuple:
    """Remove DC, fade the edges and level to ``target_lufs`` without exceeding the ceiling.

    Returns ``(waveform, PolishReport)`` with a float32 waveform. Silent input is returned
    unchanged (there is no level to match). Without a limiter (``limiter_max_reduction_db``
    of 0) the ceiling stops the gain short of the target and ``peak_limited`` is set: the
    speech is never clipped or compressed to hit the number. With a limiter the gain may go
    up to that many dB past the ceiling and the limiter trims the peaks above it; the true
    peak still never exceeds the ceiling.

    Raises:
        ValueError: If the waveform is not 1-D, or is empty or non-finite (a vocoder fault
            the caller must not store as audio), or the limiter allowance is negative.
    """
    if waveform.ndim != 1:
        raise ValueError("polish_waveform expects a mono waveform")
    if waveform.size == 0 or not np.all(np.isfinite(waveform)):
        raise ValueError("waveform is empty or contains non-finite samples")
    if limiter_max_reduction_db < 0.0:
        raise ValueError("limiter_max_reduction_db must not be negative")

    cleaned = waveform.astype(np.float32) - np.float32(waveform.mean())
    cleaned = apply_edge_fades(cleaned, sample_rate)

    measured = integrated_loudness(cleaned, sample_rate)
    peak = true_peak(cleaned)
    if measured is None or peak == 0.0:
        return cleaned, PolishReport(measured, measured, 0.0, False)

    ceiling_linear = 10.0 ** (peak_ceiling_dbfs / 20.0)
    wanted_db = min(target_lufs - measured, MAX_GAIN_DB)
    clean_db = peak_ceiling_dbfs - 20.0 * np.log10(peak)  # gain that needs no limiting
    max_db = clean_db + limiter_max_reduction_db
    gain_db = float(min(wanted_db, max_db))

    leveled, reduction_db = _apply_gain(cleaned, sample_rate, gain_db, ceiling_linear)
    # Limiting lowers the level a little: top the gain up a few times, within the allowance.
    for _ in range(LIMITER_LEVEL_PASSES if reduction_db > 0.0 else 0):
        level = integrated_loudness(leveled, sample_rate)
        shortfall = target_lufs - level if level is not None else 0.0
        step = min(shortfall, max_db - gain_db, MAX_GAIN_DB - gain_db)
        if step <= LEVEL_TOLERANCE_LU:
            break
        gain_db += step
        leveled, reduction_db = _apply_gain(
            cleaned, sample_rate, gain_db, ceiling_linear
        )

    report = PolishReport(
        input_lufs=measured,
        output_lufs=integrated_loudness(leveled, sample_rate),
        gain_db=gain_db,
        peak_limited=wanted_db > max_db,
        limiter_reduction_db=reduction_db,
    )
    logger.debug(
        "Polished output: %.1f -> %s LUFS (gain %+.1f dB, limiter %.1f dB, peak_limited=%s)",
        measured,
        "n/a" if report.output_lufs is None else f"{report.output_lufs:.1f}",
        gain_db,
        reduction_db,
        report.peak_limited,
    )
    return leveled, report
