"""Punctuation-aware segmentation of synthesis input.

HARDENING_PLAN.md finding P2-M3 (length limits) and SPEECH_QUALITY_PLAN.md S1.2.

Each segment records how it ended (``Boundary``), so the synthesizer can pause for a
question differently from a full stop, and so a ``!`` or ``?`` is never merged into the
sentence before it, which would flatten its intonation into that sentence's.
"""

import re
from dataclasses import dataclass
from enum import Enum

_TERMINAL_RUN = r"[.!?…]+"
# A sentence is text up to a terminal (a run of . ! ? … or a single ; :) followed by
# whitespace or the end; anything after the last terminal is a final unterminated tail.
_SENTENCE = re.compile(rf"\S.*?(?:{_TERMINAL_RUN}|[;:])(?=\s|$)|\S.*")
_TRAILING_RUN = re.compile(rf"({_TERMINAL_RUN})$")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
_CLAUSE_BOUNDARY = re.compile(r"(?<=,)\s+")


class Boundary(str, Enum):
    """How a segment ended; the value is the key into ``settings.TTS_PAUSE_SECONDS``."""

    STATEMENT = "statement"  # ended with a full stop, or with no punctuation
    QUESTION = "question"  # ended with ?
    EXCLAMATION = "exclamation"  # ended with !
    ELLIPSIS = "ellipsis"  # ended with … or two or more dots
    CLAUSE = "clause"  # ended with ; or :
    COMMA = "comma"  # an over-long sentence cut after a comma
    WORD = "word"  # an over-long clause cut between words (or mid-token)
    PARAGRAPH = "paragraph"  # followed by a blank line


@dataclass(frozen=True)
class Segment:
    """A piece of text to decode in one pass, and how it ended."""

    text: str
    boundary: Boundary


def classify_ending(text: str) -> Boundary:
    """Return the ``Boundary`` that the end of ``text`` implies.

    A run containing ``?`` is a question (so ``?!`` is one); else one containing ``!`` is an
    exclamation; else ``…`` or two or more dots is an ellipsis; ``;`` and ``:`` are clauses;
    a trailing comma is a comma; anything else is a statement.
    """
    text = text.rstrip()
    run = _TRAILING_RUN.search(text)
    if run:
        chars = run.group(1)
        if "?" in chars:
            return Boundary.QUESTION
        if "!" in chars:
            return Boundary.EXCLAMATION
        if "…" in chars or chars.count(".") >= 2:
            return Boundary.ELLIPSIS
        return Boundary.STATEMENT
    if text.endswith((";", ":")):
        return Boundary.CLAUSE
    if text.endswith(","):
        return Boundary.COMMA
    return Boundary.STATEMENT


def _split_long(sentence: str, max_chars: int) -> list[Segment]:
    """Break an over-long sentence at commas, then at word boundaries.

    Every piece but the last gets the ``COMMA`` or ``WORD`` boundary; the last keeps the
    sentence's own ending.
    """
    final = classify_ending(sentence)
    pieces: list[Segment] = []
    for part in (p for p in _CLAUSE_BOUNDARY.split(sentence) if p.strip()):
        boundary = Boundary.COMMA
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars + 1)
            if cut <= 0:
                cut = max_chars  # a single unbroken token: hard cut
            pieces.append(Segment(part[:cut].strip(), Boundary.WORD))
            part = part[cut:].strip()
        if part:
            pieces.append(Segment(part, boundary))
    if pieces:
        pieces[-1] = Segment(pieces[-1].text, final)
    return pieces


def _split_paragraph(paragraph: str, max_chars: int) -> list[Segment]:
    """Split one paragraph into segments, merging only adjacent plain statements."""
    segments: list[Segment] = []
    for line in paragraph.split("\n"):
        for match in _SENTENCE.finditer(line):
            sentence = match.group(0).strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                segments.append(Segment(sentence, classify_ending(sentence)))
            else:
                segments.extend(_split_long(sentence, max_chars))

    merged: list[Segment] = []
    for segment in segments:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.boundary is Boundary.STATEMENT
            and segment.boundary is Boundary.STATEMENT
            and len(previous.text) + 1 + len(segment.text) <= max_chars
        ):
            merged[-1] = Segment(f"{previous.text} {segment.text}", Boundary.STATEMENT)
        else:
            merged.append(segment)
    return merged


def split_into_segments(text: str, max_chars: int) -> list[Segment]:
    """Split text into segments of at most ``max_chars`` each; ``[]`` for blank input.

    Sentences end at ``. ! ? …`` (a run counts once), ``; :`` or a newline. Adjacent segments
    are merged only when both are plain statements, so a question, exclamation, ellipsis or
    clause keeps its own decode (and so its own intonation) and its own pause. A blank line
    ends a paragraph: the last segment before it gets ``PARAGRAPH`` and nothing merges across.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    segments: list[Segment] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        pieces = _split_paragraph(paragraph, max_chars)
        if pieces and segments:
            segments[-1] = Segment(segments[-1].text, Boundary.PARAGRAPH)
        segments.extend(pieces)
    return segments
