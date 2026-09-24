"""Sentence chunking for synthesis input (HARDENING_PLAN.md finding P2-M3)."""

import re

# A sentence ends at ., !, ?, ; or : followed by whitespace, or at a newline.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;:])\s+|\n+")
_CLAUSE_BOUNDARY = re.compile(r"(?<=,)\s+")


def _split_long(piece: str, max_chars: int) -> list[str]:
    """Break an over-long sentence at commas, then at word boundaries."""
    pieces = [p for p in _CLAUSE_BOUNDARY.split(piece) if p.strip()]
    out: list[str] = []
    for part in pieces:
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars + 1)
            if cut <= 0:
                cut = max_chars  # single unbroken token: hard cut
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split text into sentence-sized chunks of at most ``max_chars`` each.

    Adjacent short sentences are merged up to the limit so the synthesizer
    isn't fed fragments; sentences over the limit are split at commas, then
    at spaces. Returns ``[]`` for blank input.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    sentences: list[str] = []
    for raw in _SENTENCE_BOUNDARY.split(text):
        raw = raw.strip()
        if not raw:
            continue
        sentences.extend(
            [raw] if len(raw) <= max_chars else _split_long(raw, max_chars)
        )

    chunks: list[str] = []
    for sentence in sentences:
        if chunks and len(chunks[-1]) + 1 + len(sentence) <= max_chars:
            chunks[-1] = f"{chunks[-1]} {sentence}"
        else:
            chunks.append(sentence)
    return chunks
