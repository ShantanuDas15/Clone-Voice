"""Turn a sentence analysis into what an engine can actually do (SPEECH_QUALITY_PLAN.md S5.2a).

No engine here has labelled emotions (SPEECH_QUALITY_STUDY.md): SV2TTS is neutral only, and
Chatterbox's ``exaggeration`` is one intensity control that mostly moves loudness (about 10 dB across
0.25 to 1.5) and leaves duration and pitch range alone. So the honest mapping is:

* an emotion label is passed to an engine only if the engine lists it, otherwise it becomes
  ``neutral`` (never an error: an unsupported style must not fail a request);
* for the original Chatterbox, the sentence's arousal sets ``exaggeration``, held to the range the
  study measured as safe for speaker similarity (at 1.0 the similarity fell 0.021, inside the plan's
  0.03 limit; at 1.5 it fell 0.067). A cue-free sentence maps to exactly the engine default, 0.5;
* Turbo and Nano ignore ``exaggeration``, and SV2TTS has no such control, so they get no controls.

These numbers are starting points taken from a small study (six adult speakers, one seed), not a
tuned model. Nothing calls this yet; S5.3 applies it per sentence.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from backend.services.text_analysis import NEUTRAL_AROUSAL, Analysis
from backend.services.tts_engine import NEUTRAL, SynthesisStyle

EXAGGERATION_DEFAULT = 0.5
EXAGGERATION_MIN = 0.25
EXAGGERATION_MAX = 1.0
# Exaggeration gained per unit of arousal above the cue-free level: calm 0.1 -> 0.34, tense 0.9 -> 0.98.
EXAGGERATION_PER_AROUSAL = 0.8
# Engines whose delivery ``exaggeration`` controls.
EXAGGERATION_ENGINES = frozenset({"chatterbox"})


@dataclass(frozen=True)
class EngineControls:
    """Per-sentence engine parameters; ``None`` means leave the engine's default."""

    exaggeration: Optional[float] = None


def resolve_style(analysis: Analysis, supported: Tuple[str, ...]) -> SynthesisStyle:
    """The style to ask an engine for: the analysed emotion if it lists it, else neutral."""
    if analysis.emotion in supported and analysis.emotion != NEUTRAL:
        return SynthesisStyle(analysis.emotion, analysis.intensity)
    return SynthesisStyle(NEUTRAL, 0.0)


def engine_controls(engine_name: str, analysis: Analysis) -> EngineControls:
    """The engine parameters that carry this sentence's energy; none for an engine without them."""
    if engine_name not in EXAGGERATION_ENGINES:
        return EngineControls()
    value = EXAGGERATION_DEFAULT + EXAGGERATION_PER_AROUSAL * (
        analysis.arousal - NEUTRAL_AROUSAL
    )
    return EngineControls(
        exaggeration=round(max(EXAGGERATION_MIN, min(EXAGGERATION_MAX, value)), 3)
    )
