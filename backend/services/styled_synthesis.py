"""Speak a text sentence by sentence, each with its own style (SPEECH_QUALITY_PLAN.md S5.3a).

An engine that has a delivery control (the original Chatterbox's ``exaggeration``) normally gets
the whole text in one call, so every sentence is delivered the same way. With
``EMOTION_CONTROL_ENABLED`` the pipeline instead splits the text with the S1.2 segmenter,
analyses each segment (S5.1a), maps the analysis to the engine's controls (S5.2a/b), calls the
engine once per segment and joins the audio with the S1.3 pauses, so a passage that moves from
calm to angry shifts while it is spoken.

Differences from the one-call path, all deliberate:

* the text sent to the engine keeps its case (the engine reads capitals and punctuation) but is
  normalised (times, units, symbols, acronyms) and has its abbreviations expanded first, so a
  full stop inside ``Dr.`` is not taken for a sentence end. The one-call path sends the raw text;
* one engine call per segment, so a request costs several worker calls (each under the stage
  timeout) instead of one;
* segments are joined by silence at the engine's own sample rate, not in mel space.

Engines without a delivery control (SV2TTS, Turbo, Nano) are never split: ``applies`` is false
for them, so they keep the one-call path.
"""

import logging
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np

from backend.core import metrics
from backend.core.config import settings
from backend.services.style_mapping import EXAGGERATION_ENGINES, build_style
from backend.services.style_markup import parse, strip
from backend.services.sv2tts.synthesizer.utils.cleaners import \
    expand_abbreviations
from backend.services.text_analysis import (Analysis, StyleOverride, analyze,
                                            apply_override)
from backend.services.text_chunking import (Boundary, Segment,
                                            split_into_segments)
from backend.services.text_normalization import normalize_text
from backend.services.tts_engine import (StageRunner, SynthesisResult,
                                         SynthesisStyle, TTSEngine,
                                         VoiceConditioning, canary_bucket)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StyledSegment:
    """One piece of the text, the style to deliver it in, and how it ended."""

    segment: Segment
    style: SynthesisStyle
    # What the analysis (or the user) called this sentence, before the engine's limits turned it
    # into a style; this is what the emotion metric counts.
    emotion: str = "neutral"
    # True when the emotion was asked for (the request or an inline tag), not detected.
    requested: bool = False


EMOTION_CANARY_SALT = "emotion-control:"


def enabled_for(user_id: str) -> bool:
    """True if this user gets sentence-by-sentence styling: everyone with the flag, else the canary."""
    if settings.EMOTION_CONTROL_ENABLED:
        return True
    return (
        settings.EMOTION_CONTROL_PERCENT > 0
        and canary_bucket(user_id, EMOTION_CANARY_SALT)
        < settings.EMOTION_CONTROL_PERCENT
    )


def applies(engine: TTSEngine) -> bool:
    """True if the engine has a delivery control worth a call per sentence."""
    return (
        engine.name in EXAGGERATION_ENGINES or len(engine.capabilities().emotions) > 1
    )


def speakable(text: str) -> str:
    """The text with symbols and abbreviations spoken out and its case kept, line by line."""
    return "\n".join(
        expand_abbreviations(normalize_text(line)).strip() for line in text.split("\n")
    )


def plan(
    text: str,
    engine: TTSEngine,
    max_chars: Optional[int] = None,
    override: Optional[StyleOverride] = None,
) -> list[StyledSegment]:
    """Split the text into segments and choose each one's style; ``[]`` for blank text.

    An ``override`` (the user's emotion and strength) replaces the detected emotion of every
    segment; the text's own cues (exclamation marks, capitals) still add to the energy.
    """
    limit = max_chars or settings.TTS_CHUNK_MAX_CHARS
    emotions = engine.capabilities().emotions
    planned = []
    for run in parse(text):
        # An inline tag wins over the request-level emotion for its own text.
        chosen = StyleOverride(run.emotion) if run.emotion else override
        segments = split_into_segments(speakable(run.text), limit)
        if segments and not _ends_a_sentence(segments[-1].text):
            # A tag cut the sentence here, not punctuation: join with a word-sized gap.
            segments[-1] = replace(segments[-1], boundary=Boundary.WORD)
        for segment in segments:
            analysis = _analysis(segment, chosen)
            planned.append(
                StyledSegment(
                    segment,
                    build_style(engine.name, emotions, analysis),
                    analysis.emotion,
                    chosen is not None,
                )
            )
    return planned


def _ends_a_sentence(text: str) -> bool:
    """True if the text ends with sentence or clause punctuation."""
    return text.rstrip().endswith((".", "!", "?", "…", ";", ":", ","))


def _analysis(segment: Segment, override: Optional[StyleOverride]) -> Analysis:
    """The segment's analysis, with the user's request applied if there is one."""
    analysis = analyze(segment.text, segment.boundary)
    return apply_override(analysis, override) if override else analysis


def _pause(boundary_value: str, sample_rate: int) -> np.ndarray:
    """Digital silence for a segment that ended with the given boundary."""
    seconds = settings.TTS_PAUSE_SECONDS[boundary_value]
    return np.zeros(int(seconds * sample_rate), np.float32)


async def synthesize_styled(
    engine: TTSEngine,
    text: str,
    conditioning: VoiceConditioning,
    *,
    run_stage: StageRunner,
    truncation_retries: int = 0,
    override: Optional[StyleOverride] = None,
) -> SynthesisResult:
    """Synthesize each segment with its own style and join them with typed pauses.

    The text may carry inline emotion tags (``style_markup``); each tagged stretch is delivered
    in its tag's emotion.

    Truncated decodes add up across segments, so the quality gate sees them all. If the text has
    no segments (blank after cleaning) it is sent whole, as the one-call path would.
    """
    planned = plan(text, engine, override=override)
    if not planned:
        return await engine.synthesize(
            strip(text),
            conditioning,
            None,
            run_stage=run_stage,
            truncation_retries=truncation_retries,
        )
    parts: list[np.ndarray] = []
    rate = 0
    truncated = 0
    for index, item in enumerate(planned):
        result = await engine.synthesize(
            item.segment.text,
            conditioning,
            item.style,
            run_stage=run_stage,
            truncation_retries=truncation_retries,
        )
        if rate and result.sample_rate != rate:
            raise RuntimeError(
                f"{engine.name} changed sample rate mid-request ({rate} to {result.sample_rate})"
            )
        rate = result.sample_rate
        if index:
            parts.append(_pause(planned[index - 1].segment.boundary.value, rate))
        parts.append(np.asarray(result.waveform, np.float32))
        truncated += result.truncated_decodes
        metrics.SENTENCES_STYLED.labels(
            item.emotion, "requested" if item.requested else "detected"
        ).inc()
    logger.debug(
        "Styled synthesis: %d segments, exaggeration %s",
        len(planned),
        [item.style.exaggeration for item in planned],
    )
    return SynthesisResult(np.concatenate(parts), rate, truncated)
