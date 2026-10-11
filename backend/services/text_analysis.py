"""Rule-based analysis of how a sentence should be delivered (SPEECH_QUALITY_PLAN.md S5.1a).

Pure, deterministic, local and English-only: no model, no network, no randomness. It reads
punctuation (``!``, ``?``, ``…``), ALL-CAPS words, ``*stressed*`` words, and a small hand-written
emotion lexicon, and returns a label, an intensity and the cues behind it, so a later style mapping
(S5.2) has something to act on.

Known limits, by design: no sarcasm or irony, no context beyond one sentence, a lexicon of about
sixty words, and negation handled only for the word right before an emotion word. A sentence with no
cue is ``neutral``; this module never guesses beyond its evidence.
"""

import re
from dataclasses import dataclass
from typing import Optional

from backend.services.text_chunking import Boundary, Segment, classify_ending

NEUTRAL = "neutral"
EMOTIONS = ("neutral", "happy", "sad", "angry", "fearful", "surprised")
PACES = ("slow", "normal", "fast")

# word or phrase -> (emotion, weight 0-1). Longer phrases are matched first.
LEXICON: dict[str, tuple[str, float]] = {
    "can't believe you": ("angry", 1.0),
    "sick of": ("angry", 0.8),
    "fed up": ("angry", 0.8),
    "can't believe": ("surprised", 0.6),
    "furious": ("angry", 1.0),
    "angry": ("angry", 0.9),
    "hate": ("angry", 0.9),
    "stupid": ("angry", 0.7),
    "idiot": ("angry", 0.8),
    "damn": ("angry", 0.6),
    "outrageous": ("angry", 0.8),
    "unacceptable": ("angry", 0.8),
    "how dare": ("angry", 1.0),
    "miss": ("sad", 0.7),
    "sad": ("sad", 0.9),
    "cry": ("sad", 0.7),
    "crying": ("sad", 0.7),
    "lonely": ("sad", 0.9),
    "alone": ("sad", 0.6),
    "grief": ("sad", 0.9),
    "heartbroken": ("sad", 1.0),
    "funeral": ("sad", 0.8),
    "passed away": ("sad", 0.9),
    "sorry": ("sad", 0.5),
    "lost": ("sad", 0.5),
    "happy": ("happy", 0.9),
    "glad": ("happy", 0.7),
    "wonderful": ("happy", 0.8),
    "amazing": ("happy", 0.8),
    "awesome": ("happy", 0.8),
    "great": ("happy", 0.6),
    "love": ("happy", 0.7),
    "delighted": ("happy", 0.9),
    "thrilled": ("happy", 0.9),
    "excited": ("happy", 0.8),
    "congratulations": ("happy", 0.9),
    "yay": ("happy", 0.9),
    "afraid": ("fearful", 0.8),
    "scared": ("fearful", 0.9),
    "terrified": ("fearful", 1.0),
    "frightened": ("fearful", 0.9),
    "panic": ("fearful", 0.8),
    "fear": ("fearful", 0.7),
    "wow": ("surprised", 0.8),
    "unbelievable": ("surprised", 0.7),
    "suddenly": ("surprised", 0.4),
    "oh my god": ("surprised", 0.8),
}
_PHRASES = sorted(LEXICON, key=len, reverse=True)
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
_STRESSED = re.compile(r"\*([^*\s][^*]*?)\*")
_NEGATORS = {"not", "never", "no", "isn't", "wasn't", "aren't", "don't", "didn't"}
# What a negated positive or negative word becomes (weakened: "not happy" is sad-ish, not sad).
_FLIP = {"happy": "sad", "sad": "happy"}
NEGATION_FACTOR = 0.6
# Below this evidence a sentence is neutral.
MIN_EVIDENCE = 0.4
# An ending of ellipsis suggests hesitation or sadness, but only weakly.
ELLIPSIS_SAD = 0.45
_CAPS_MIN_LENGTH = 3
_VALENCE = {
    "neutral": 0.0,
    "happy": 1.0,
    "sad": -0.8,
    "angry": -1.0,
    "fearful": -0.7,
    "surprised": 0.3,
}
_AROUSAL_SHIFT = {
    "neutral": 0.0,
    "happy": 0.25,
    "sad": -0.2,
    "angry": 0.35,
    "fearful": 0.3,
    "surprised": 0.3,
}


@dataclass(frozen=True)
class Analysis:
    """How one sentence should be delivered, and the cues that say so."""

    emotion: str
    intensity: float  # 0 (none) to 1
    arousal: float  # 0 (calm) to 1 (energetic)
    valence: float  # -1 (negative) to 1 (positive)
    pace: str  # slow | normal | fast
    is_question: bool
    emphasis_words: tuple[str, ...]
    exclamations: int
    cues: tuple[str, ...]  # human-readable reasons, for logs and tests


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _emphasis(text: str) -> tuple[str, ...]:
    """Words marked with ``*stars*`` or written in ALL CAPS (3+ letters), lowercased, in order."""
    found = [m.group(1).lower() for m in _STRESSED.finditer(text)]
    plain = _STRESSED.sub(" ", text)
    found += [
        w.lower()
        for w in _WORD.findall(plain)
        if len(w) >= _CAPS_MIN_LENGTH and w.isupper()
    ]
    seen: list[str] = []
    for word in found:
        if word not in seen:
            seen.append(word)
    return tuple(seen)


def _lexical_scores(text: str, cues: list[str]) -> dict[str, float]:
    """Evidence per emotion from the lexicon, with a flip for a negated happy/sad word."""
    lowered = " " + text.lower().replace("’", "'") + " "
    scores: dict[str, float] = {}
    for phrase in _PHRASES:
        emotion, weight = LEXICON[phrase]
        for match in re.finditer(rf"(?<![a-z']){re.escape(phrase)}(?![a-z'])", lowered):
            before = _WORD.findall(lowered[: match.start()])[-1:]
            if before and before[0] in _NEGATORS and emotion in _FLIP:
                emotion, weight = _FLIP[emotion], weight * NEGATION_FACTOR
                cues.append(f"negated '{phrase}'")
            else:
                cues.append(f"word '{phrase}'")
            scores[emotion] = max(scores.get(emotion, 0.0), weight)
            # Blank the match so a shorter entry inside a longer phrase does not count twice.
            lowered = (
                lowered[: match.start()]
                + " " * (match.end() - match.start())
                + lowered[match.end() :]
            )
    return scores


def analyze(text: str, boundary: Optional[Boundary] = None) -> Analysis:
    """Analyse one sentence.

    ``boundary`` is how the sentence ended, if known (from ``Segment``); otherwise it is read
    from the text itself.
    """
    text = (text or "").strip()
    if not text:
        return Analysis(NEUTRAL, 0.0, 0.3, 0.0, "normal", False, (), 0, ())
    cues: list[str] = []
    ending = boundary or classify_ending(text)
    exclamations = text.count("!")
    emphasis = _emphasis(text)
    scores = _lexical_scores(text, cues)

    if ending is Boundary.ELLIPSIS:
        scores["sad"] = max(scores.get("sad", 0.0), ELLIPSIS_SAD)
        cues.append("ends with an ellipsis")
    if exclamations:
        cues.append(f"{exclamations} exclamation mark(s)")
    if emphasis:
        cues.append("emphasis: " + ", ".join(emphasis))

    emotion, evidence = NEUTRAL, 0.0
    if scores:
        # Ties go to the earlier name in EMOTIONS, so the result never depends on dict order.
        emotion, evidence = max(
            scores.items(), key=lambda kv: (kv[1], -EMOTIONS.index(kv[0]))
        )
    if evidence < MIN_EVIDENCE:
        emotion, evidence = NEUTRAL, 0.0

    intensity = 0.0
    if emotion != NEUTRAL:
        intensity = _clamp(
            evidence
            + 0.12 * min(exclamations, 3)
            + (0.15 if emphasis else 0.0)
            - (0.1 if ending is Boundary.ELLIPSIS and emotion != "sad" else 0.0)
        )
    arousal = _clamp(
        0.3
        + 0.12 * min(exclamations, 3)
        + (0.15 if emphasis else 0.0)
        + _AROUSAL_SHIFT[emotion] * max(intensity, 0.5 if emotion != NEUTRAL else 0.0)
    )
    if emotion == "sad" and ending is Boundary.ELLIPSIS:
        arousal = _clamp(arousal - 0.1)
    if arousal >= 0.7:
        pace = "fast"
    elif arousal <= 0.25 or (emotion == "sad" and intensity >= 0.5):
        pace = "slow"
    else:
        pace = "normal"
    return Analysis(
        emotion=emotion,
        intensity=round(intensity, 3),
        arousal=round(arousal, 3),
        valence=round(_clamp(_VALENCE[emotion] * intensity, -1.0, 1.0), 3),
        pace=pace,
        is_question=ending is Boundary.QUESTION,
        emphasis_words=emphasis,
        exclamations=exclamations,
        cues=tuple(cues),
    )


def analyze_segments(segments: list[Segment]) -> list[Analysis]:
    """Analyse each segment on its own, using how it ended."""
    return [analyze(s.text, s.boundary) for s in segments]
