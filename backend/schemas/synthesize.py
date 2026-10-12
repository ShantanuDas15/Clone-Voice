from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from unidecode import unidecode

from backend.services import style_markup
from backend.services.sv2tts.synthesizer.utils.symbols import \
    symbols as _sv2tts_symbols
from backend.services.text_normalization import clean_text

# The real Tacotron2 checkpoint's embedding table only has one row per symbol
# in this exact set (HARDENING_PLAN.md finding H2). "_" (pad) and "~" (eos)
# are internal control symbols the cleaner pipeline never emits from user
# text, so they're excluded from what a *request* may produce.
_ALLOWED_TEXT_CHARS = set(_sv2tts_symbols) - {"_", "~"}


def _unsupported_characters(text: str) -> List[str]:
    """Return the distinct characters that would be lost or unreadable when ``text`` is spoken.

    The text goes through the same normalisation and cleaning as synthesis
    (`text_normalization.clean_text`), so a character the pipeline can say (a `$` amount,
    `%`, `&`, an email address, `*emphasis*`, an acronym) is accepted, and what remains is
    judged against the SV2TTS symbol table. The vendored `text_to_sequence()` silently
    *drops* anything outside it, which would let a request "succeed" while quietly losing
    part of the text; this function turns that into a clean 422 instead.

    Two cases are rejected: a character whose transliteration is empty (it vanishes
    without a trace, e.g. an emoji), and anything still outside the symbol set after
    cleaning (control characters, `{}` ARPAbet braces, `[` `]`, `~`, `_`).
    Digits are expanded to words by the cleaners, and newlines become pauses.
    """
    problems = [
        ch
        for ch in dict.fromkeys(text)
        if not ch.isspace() and not ch.isdigit() and not unidecode(ch)
    ]
    for ch in dict.fromkeys(clean_text(text)):
        if (
            ch != "\n"
            and not ch.isdigit()
            and ch not in _ALLOWED_TEXT_CHARS
            and ch not in problems
        ):
            problems.append(ch)
    return problems


class SynthesizeRequest(BaseModel):
    voice_profile_id: UUID
    text: str = Field(..., min_length=1, max_length=500)
    # SPEECH_QUALITY_PLAN.md S5.4a: how to deliver the text. "auto" (the default) leaves it to the
    # text analysis. A named emotion replaces the detected one for every sentence; intensity
    # (0 to 1) is how strongly, and only makes sense with a named emotion other than neutral.
    emotion: Literal[
        "auto", "neutral", "happy", "sad", "angry", "fearful", "surprised"
    ] = "auto"
    intensity: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def intensity_needs_an_emotion(self) -> "SynthesizeRequest":
        """Reject an intensity with nothing to apply it to (auto or neutral)."""
        if self.intensity is not None and self.emotion in ("auto", "neutral"):
            raise ValueError("intensity needs an emotion other than auto or neutral")
        return self

    @field_validator("text")
    @classmethod
    def validate_supported_characters(cls, v: str) -> str:
        """Reject text containing characters the SV2TTS symbol set cannot
        represent, even after the real cleaner pipeline's transliteration
        and digit expansion (see `_unsupported_characters`)."""
        try:
            style_markup.parse(v)
        except style_markup.MarkupError as error:
            raise ValueError(f"Emotion tags are not well formed: {error}") from None
        spoken = style_markup.bare(v)
        if not spoken.strip():
            raise ValueError("Text has nothing to say once its tags are removed")
        unsupported = _unsupported_characters(spoken)
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
    voice_profile_name: str
    status: str
    input_text: str
    output_filename: str
    duration_seconds: Optional[float] = None
    audio_available: bool = False
    created_at: datetime
    # The engine that produced the audio; engine_fallback_from is set when the preferred
    # engine was unavailable and the backup voice engine served the request. None on old rows.
    engine: Optional[str] = None
    engine_fallback_from: Optional[str] = None
    # The emotion the user asked for (None = auto), its strength, and whether the engine applied it.
    emotion: Optional[str] = None
    intensity: Optional[float] = None
    style_applied: Optional[bool] = None

    model_config = {"from_attributes": True}
