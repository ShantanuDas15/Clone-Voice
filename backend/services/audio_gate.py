"""Cheap automatic checks on a synthesized waveform (SPEECH_QUALITY_PLAN.md S3.4).

Tacotron is autoregressive: it can stop early, never emit its stop token, or the vocoder can
distort. Rather than store and serve such audio, the pipeline asks this module whether the
raw vocoder output is plausible speech for the text, and retries or refuses if it is not.

Pure numpy, no model. Thresholds come from SPEECH_QUALITY_STUDY.md (the S3.4 calibration:
168 real syntheses, 6 LibriSpeech speakers, 20 ordinary texts and 8 stress texts each).
Only truncation was ever seen failing on ordinary text; the other checks are wide-margin
guards that never fired on the 120 ordinary outputs.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

FRAME_SECONDS = 0.02
# A frame is silent when it is this far below the utterance's loud level (its 95th
# percentile frame level), so a quiet voice and a loud one are judged alike.
SILENCE_BELOW_LOUD_DB = 30.0
# Absolute floor: loud frames this quiet mean nothing audible was produced.
# Ordinary outputs had a loud level of at least -37 dBFS.
SILENT_LEVEL_DBFS = -45.0
# Ordinary outputs, with their typed pauses, were at most 67% silent.
MOSTLY_SILENT_RATIO = 0.85
# A silent stretch longer than the longest configured pause plus this is not a pause.
# Ordinary outputs' longest silence was 0.90 s against a 0.70 s paragraph pause.
LONG_SILENCE_MARGIN_SECONDS = 1.0
# Samples at full scale after the vocoder's clip to +-1. Ordinary outputs: at most 0.96%;
# one one-word output had 8.3% (audibly distorted).
CLIP_LEVEL = 0.999
MAX_CLIPPING_RATIO = 0.02
# Duration model: seconds = BASE + PER_WORD * spoken words (fit on 119 ordinary outputs,
# which include their pauses). The check is on the ratio and only for texts long enough
# for the model to mean something: ordinary 0.68 to 1.64, odd long words are far outside
# it and are not broken, so single words and short phrases are exempt.
DURATION_BASE_SECONDS = 0.29
DURATION_PER_WORD_SECONDS = 0.287
DURATION_RATIO_BOUNDS: Tuple[float, float] = (0.35, 2.5)
DURATION_MIN_WORDS = 4

_WORD = re.compile(r"[A-Za-z0-9']+")


@dataclass(frozen=True)
class GateMeasures:
    """What was measured on the waveform."""

    duration_seconds: float
    spoken_words: int
    level_dbfs: float
    silence_ratio: float
    longest_silence_seconds: float
    clipping_ratio: float
    duration_ratio: Optional[float]


@dataclass(frozen=True)
class GateResult:
    """The verdict. ``reasons`` are stable codes, empty when ``passed``."""

    passed: bool
    reasons: Tuple[str, ...]
    measures: Optional[GateMeasures]


def count_spoken_words(spoken_text: str) -> int:
    """Count the words in text that has already been normalised for speech."""
    return len(_WORD.findall(spoken_text))


def _longest_run(mask: np.ndarray) -> int:
    """Length of the longest run of True in a boolean array."""
    if not mask.any():
        return 0
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return int((edges[1::2] - edges[::2]).max())


def measure_output(
    waveform: np.ndarray, sample_rate: int, spoken_words: int
) -> GateMeasures:
    """Measure a finite, non-empty mono waveform."""
    frame = max(1, int(FRAME_SECONDS * sample_rate))
    frames = len(waveform) // frame
    duration = len(waveform) / sample_rate
    if frames == 0:
        level = -120.0
        silence_ratio, longest = 1.0, duration
    else:
        blocks = waveform[: frames * frame].astype(np.float64).reshape(frames, frame)
        rms_db = 20.0 * np.log10(np.sqrt((blocks**2).mean(axis=1)) + 1e-12)
        level = float(np.percentile(rms_db, 95))
        silent = rms_db < level - SILENCE_BELOW_LOUD_DB
        silence_ratio = float(silent.mean())
        longest = _longest_run(silent) * FRAME_SECONDS
    expected = DURATION_BASE_SECONDS + DURATION_PER_WORD_SECONDS * spoken_words
    return GateMeasures(
        duration_seconds=duration,
        spoken_words=spoken_words,
        level_dbfs=level,
        silence_ratio=silence_ratio,
        longest_silence_seconds=longest,
        clipping_ratio=float((np.abs(waveform) >= CLIP_LEVEL).mean()),
        duration_ratio=(
            duration / expected if spoken_words >= DURATION_MIN_WORDS else None
        ),
    )


def check_output(
    waveform: np.ndarray,
    sample_rate: int,
    spoken_text: str,
    truncated_chunks: int,
    max_pause_seconds: float,
) -> GateResult:
    """Decide whether ``waveform`` is plausible speech for ``spoken_text``.

    Args:
        waveform: Mono vocoder output.
        sample_rate: Its sample rate.
        spoken_text: The text as it is spoken (after normalisation).
        truncated_chunks: How many decodes hit the synthesizer's frame cap.
        max_pause_seconds: The longest pause the pipeline can insert on purpose.
    """
    if waveform.ndim != 1 or waveform.size == 0:
        return GateResult(False, ("empty",), None)
    if not np.all(np.isfinite(waveform)):
        return GateResult(False, ("non_finite",), None)

    measures = measure_output(waveform, sample_rate, count_spoken_words(spoken_text))
    reasons = []
    if truncated_chunks > 0:
        reasons.append("truncated")
    if measures.level_dbfs < SILENT_LEVEL_DBFS:
        reasons.append("silent")
    elif measures.silence_ratio > MOSTLY_SILENT_RATIO:
        reasons.append("mostly_silent")
    if (
        measures.longest_silence_seconds
        > max_pause_seconds + LONG_SILENCE_MARGIN_SECONDS
    ):
        reasons.append("long_silence")
    if measures.clipping_ratio > MAX_CLIPPING_RATIO:
        reasons.append("clipping")
    ratio = measures.duration_ratio
    if ratio is not None and not (
        DURATION_RATIO_BOUNDS[0] <= ratio <= DURATION_RATIO_BOUNDS[1]
    ):
        reasons.append("duration_too_short" if ratio < 1.0 else "duration_too_long")
    return GateResult(not reasons, tuple(reasons), measures)
