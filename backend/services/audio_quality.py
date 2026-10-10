"""Measure how good a voice sample is for cloning (SPEECH_QUALITY_PLAN.md S2.2).

Pure numpy/librosa: no model. Each measure is a plain physical quantity of the recording, so a
user can be told what to fix ("too noisy", "sounds like a phone call") instead of getting a
poor clone from a sample that was accepted without comment.

The input is the clip as decoded at 16 kHz mono, *before* trimming or levelling, because
noise and clipping are judged against the whole recording.
"""

import warnings
from dataclasses import dataclass
from typing import List, Optional, Tuple

import librosa
import numpy as np

SAMPLE_RATE = 16000
FRAME = 320  # 20 ms
HOP = 160  # 10 ms
# A noise floor needs frames that are only noise; digital silence has none to speak of.
SNR_CAP_DB = 60.0
# Samples at or beyond this fraction of full scale count towards clipping when they run on.
CLIP_LEVEL = 0.99
HIGH_BAND_HZ = 4000


# --- Thresholds ----------------------------------------------------------------
#
# Set from SPEECH_QUALITY_STUDY.md (recording-quality study, 120 LibriSpeech clips and their
# degraded copies; clone-similarity change against the clean reference):
#
#   noise at 20 / 10 / 5 dB SNR   -0.064 / -0.100 / -0.129   (every speaker worse)
#   clipping, 0.3% / 6% of samples -0.038 / -0.124
#   telephone band                 -0.038
#   a very quiet recording         -0.001  (the upload path already levels it: no hint)
#
# A clean recording had SNR >= 19.5 dB (5.8% below 25), clipping <= 0.13% and energy above
# 4 kHz no lower than -33.5 dB relative to the band below it.
SNR_WARN_DB = 25.0  # 98% of 20 dB-noise clips are below this, 5.8% of clean ones
SNR_POOR_DB = 15.0
CLIP_WARN_RATIO = (
    0.001  # 0.1% of samples; 0.8% of clean clips, all heavily clipped ones
)
CLIP_POOR_RATIO = 0.02
BAND_LIMITED_DB = -45.0  # clean >= -33.5; simulated phone band <= -83
SOURCE_BAND_LIMITED_HZ = 8000  # an 8 kHz (or lower) original has nothing above 4 kHz
# The product asks for 10 to 30 s of speech. This is guidance, not a measured effect.
SHORT_VOICED_SECONDS = 10.0


@dataclass(frozen=True)
class QualityHint:
    """One thing a user can fix, and how serious it is (``warning`` or ``poor``)."""

    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class QualityReport:
    """The measures of a recording, what to tell the user, and an overall rating."""

    measures: "QualityMeasures"
    hints: Tuple[QualityHint, ...]
    rating: str  # "good" (no hints), "fair" (warnings only) or "poor" (any poor hint)


@dataclass(frozen=True)
class QualityMeasures:
    """Physical measures of one recording."""

    duration_seconds: float
    voiced_seconds: float
    snr_db: float
    clipping_ratio: float
    high_band_db: float
    level_dbfs: float


def _frame_rms(y: np.ndarray) -> np.ndarray:
    """RMS of each 20 ms frame (10 ms hop)."""
    return librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP, center=True)[0]


def estimate_snr_db(y: np.ndarray) -> float:
    """Signal-to-noise ratio in dB from the frame-energy distribution.

    The quietest tenth of frames stands for the noise floor and the loudest third for speech.
    This is an estimate (it assumes the clip contains both), good enough to tell a clean
    recording from a noisy one; it is not a laboratory measurement. A clip with no measurable
    noise floor is capped at ``SNR_CAP_DB``.
    """
    rms = _frame_rms(y)
    if len(rms) < 10:
        return SNR_CAP_DB
    power = np.sort(rms.astype(np.float64) ** 2)
    noise = float(np.mean(power[: max(1, len(power) // 10)]))
    speech = float(np.mean(power[-max(1, len(power) // 3) :]))
    if speech <= 0.0:
        return 0.0
    if noise <= 1e-12:
        return SNR_CAP_DB
    ratio = max(speech - noise, 1e-12) / noise
    return float(min(10.0 * np.log10(ratio), SNR_CAP_DB))


def clipping_ratio(y: np.ndarray, level: float = CLIP_LEVEL) -> float:
    """Share of samples that sit at full scale as part of a flat run of two or more.

    A single peak at full scale is not clipping; consecutive samples stuck at the limit are.
    """
    y = np.asarray(y)
    if len(y) < 2:
        return 0.0
    hot = np.abs(y) >= level
    run = hot[1:] & hot[:-1]
    return float(
        (run.sum() + (run & ~np.concatenate([[False], run[:-1]])).sum()) / len(y)
    )


def high_band_db(y: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """Energy above 4 kHz relative to the energy below it, in dB (more negative = duller).

    A band-limited recording (a phone call, a low-rate codec) has almost nothing above 4 kHz,
    so this drops far below what full-band speech gives. It compares two parts of the same
    recording, so it does not depend on how loud the clip is. Returns -120 for silence.
    """
    y = np.asarray(y, dtype=np.float32)
    if len(y) < 1024:
        return -120.0
    energy = (np.abs(librosa.stft(y, n_fft=1024, hop_length=HOP)) ** 2).mean(axis=1)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    low = float(energy[(freqs >= 100) & (freqs < HIGH_BAND_HZ)].sum())
    high = float(energy[freqs >= HIGH_BAND_HZ].sum())
    if low <= 0.0:
        return -120.0
    return float(max(10.0 * np.log10(max(high, 1e-20) / low), -120.0))


def level_dbfs(y: np.ndarray) -> float:
    """RMS level of the louder half of the frames in dBFS, floored at -120."""
    rms = _frame_rms(np.asarray(y, dtype=np.float32))
    if len(rms) == 0:
        return -120.0
    loud = np.sort(rms)[len(rms) // 2 :]
    value = float(np.sqrt(np.mean(loud.astype(np.float64) ** 2)))
    return -120.0 if value <= 0.0 else max(20.0 * np.log10(value), -120.0)


def measure_quality(y: np.ndarray, sr: int = SAMPLE_RATE) -> QualityMeasures:
    """Measure one clip (mono float audio at ``sr``)."""
    y = np.asarray(y, dtype=np.float32)
    if len(y) == 0:
        return QualityMeasures(0.0, 0.0, 0.0, 0.0, -120.0, -120.0)
    trimmed, _ = librosa.effects.trim(y, top_db=30)
    return QualityMeasures(
        duration_seconds=len(y) / sr,
        voiced_seconds=len(trimmed) / sr,
        snr_db=estimate_snr_db(y),
        clipping_ratio=clipping_ratio(y),
        high_band_db=high_band_db(y, sr),
        level_dbfs=level_dbfs(y),
    )


_NOISE_WARN = QualityHint(
    "noisy",
    "warning",
    "There is background noise. Record somewhere quieter, or hold the microphone closer.",
)
_NOISE_POOR = QualityHint(
    "very_noisy",
    "poor",
    "The recording is very noisy, and the cloned voice will sound much less like you. "
    "Record in a quiet room.",
)
_CLIP_WARN = QualityHint(
    "distorted",
    "warning",
    "The recording is slightly distorted because it was too loud. Lower the input volume "
    "or speak a little farther from the microphone.",
)
_CLIP_POOR = QualityHint(
    "very_distorted",
    "poor",
    "The recording is badly distorted because it was far too loud. Lower the input volume "
    "or move back from the microphone and record again.",
)
_BAND_LIMITED = QualityHint(
    "band_limited",
    "warning",
    "This sounds like a phone call or a low-quality recording. A recording made with a "
    "microphone in a quiet room gives a closer voice.",
)
_SHORT = QualityHint(
    "short",
    "warning",
    "Only a short amount of speech was found. Samples of 10 to 30 seconds give the closest voice.",
)


def assess_quality(
    y: np.ndarray, sr: int = SAMPLE_RATE, source_sample_rate: Optional[int] = None
) -> QualityReport:
    """Measure a clip and turn the measures into hints and a rating.

    ``source_sample_rate`` is the rate the file was recorded at, before it was resampled to
    ``sr``; an original at or below 8 kHz has no content above 4 kHz whatever the spectrum
    of the resampled copy shows. Volume never produces a hint: the upload path levels quiet
    audio and the study found no effect.
    """
    measures = measure_quality(y, sr)
    hints: List[QualityHint] = []
    if measures.snr_db < SNR_POOR_DB:
        hints.append(_NOISE_POOR)
    elif measures.snr_db < SNR_WARN_DB:
        hints.append(_NOISE_WARN)
    if measures.clipping_ratio > CLIP_POOR_RATIO:
        hints.append(_CLIP_POOR)
    elif measures.clipping_ratio > CLIP_WARN_RATIO:
        hints.append(_CLIP_WARN)
    if measures.high_band_db < BAND_LIMITED_DB or (
        source_sample_rate is not None and source_sample_rate <= SOURCE_BAND_LIMITED_HZ
    ):
        hints.append(_BAND_LIMITED)
    if measures.voiced_seconds < SHORT_VOICED_SECONDS:
        hints.append(_SHORT)
    if any(h.severity == "poor" for h in hints):
        rating = "poor"
    elif hints:
        rating = "fair"
    else:
        rating = "good"
    return QualityReport(measures=measures, hints=tuple(hints), rating=rating)


def assess_file(file_path: str) -> QualityReport:
    """Decode an audio file at 16 kHz mono and assess it.

    Reads at most 301 s, matching the upload limit, so an oversized file cannot make this
    slow. Raises whatever the decoder raises; callers treat a failure as "no report".
    """
    # librosa says "PySoundFile failed, trying audioread" for every MP3 and WebM: its own
    # deprecation notice about a fallback it still performs. It is not about our code, so only
    # that message is silenced; any other warning still shows.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="PySoundFile failed", category=FutureWarning
        )
        source_rate = int(librosa.get_samplerate(file_path))
        y, _ = librosa.load(file_path, sr=SAMPLE_RATE, duration=301.0)
    return assess_quality(y, SAMPLE_RATE, source_sample_rate=source_rate)
