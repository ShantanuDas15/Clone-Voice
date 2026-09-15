from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from unidecode import unidecode

from backend.services.sv2tts.synthesizer.utils.symbols import \
    symbols as _sv2tts_symbols

# The real Tacotron2 checkpoint's embedding table only has one row per symbol
# in this exact set (HARDENING_PLAN.md finding H2). "_" (pad) and "~" (eos)
# are internal control symbols the cleaner pipeline never emits from user
# text, so they're excluded from what a *request* may produce.
_ALLOWED_TEXT_CHARS = set(_sv2tts_symbols) - {"_", "~"}


def _unsupported_characters(text: str) -> List[str]:
    """Return the distinct raw input characters the real cleaner pipeline
    (`english_cleaners`: unidecode transliteration + digit/abbreviation
    expansion) cannot turn into anything the SV2TTS symbol table represents.

    The vendored `text_to_sequence()` silently *drops* such characters
    rather than raising, which would otherwise let a request "succeed"
    while quietly losing part of the requested text — this function is what
    turns that into a clean 422 at the API boundary instead.

    Digits are special-cased: `expand_numbers` (not unidecode) converts them
    to words before symbol mapping ("5" -> "five"), so per-character
    unidecode is not representative of what actually happens to a digit.
    For every other character, per-character unidecode is exactly the
    transformation `english_cleaners` applies before symbol mapping: a
    character whose transliteration is empty (dropped — e.g. emoji) or
    still contains characters outside the symbol set (unidecode leaves
    control characters and unmapped symbols like "{" unchanged) is
    unsupported.
    """
    problems = []
    for ch in dict.fromkeys(text):  # de-duplicate, preserve first-seen order
        if ch.isdigit():
            continue
        transliterated = unidecode(ch).lower()
        if not transliterated or (set(transliterated) - _ALLOWED_TEXT_CHARS):
            problems.append(ch)
    return problems


class SynthesizeRequest(BaseModel):
    voice_profile_id: UUID
    text: str = Field(..., min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def validate_supported_characters(cls, v: str) -> str:
        """Reject text containing characters the SV2TTS symbol set cannot
        represent, even after the real cleaner pipeline's transliteration
        and digit expansion (see `_unsupported_characters`)."""
        unsupported = _unsupported_characters(v)
        if unsupported:
            raise ValueError(
                "Text contains characters unsupported by the SV2TTS symbol "
                f"set: {''.join(unsupported)!r}. Supported: A-Z, a-z, "
                "digits (expanded to words), accented/transliterable Latin "
                "text, and basic punctuation ( !'\"(),-.:;? )."
            )
        return v


class GenerationOut(BaseModel):
    id: UUID
    voice_profile_id: UUID
    input_text: str
    output_filename: str
    duration_seconds: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}
