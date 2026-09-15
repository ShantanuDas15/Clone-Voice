"""Unit tests for SynthesizeRequest's SV2TTS character-set validation
(HARDENING_PLAN.md finding H2)."""

import uuid

import pytest
from pydantic import ValidationError

from backend.schemas.synthesize import SynthesizeRequest


def _make(text: str) -> SynthesizeRequest:
    return SynthesizeRequest(voice_profile_id=uuid.uuid4(), text=text)


def test_accepts_plain_ascii_text():
    req = _make("Hello, world!")
    assert req.text == "Hello, world!"


def test_accepts_digits_expanded_by_cleaners():
    """Digits aren't literal symbols but the real cleaner pipeline expands
    them to words before symbol mapping, so they must be accepted, not
    rejected as "unsupported"."""
    req = _make("I have 5 cats.")
    assert req.text == "I have 5 cats."


def test_accepts_accented_latin_text_transliterated_by_cleaners():
    req = _make("café naïve")
    assert "é" in req.text  # validator doesn't mutate the stored text


def test_rejects_emoji():
    with pytest.raises(ValidationError, match="unsupported"):
        _make("Hello \U0001F600")


def test_rejects_symbols_unidecode_cannot_transliterate():
    """Unlike scripts unidecode CAN romanize (e.g. hiragana -> "a"), a
    symbol like a heart has no transliteration at all and is dropped by
    unidecode — this must still be caught, since text_to_sequence() would
    otherwise silently drop it and synthesize only the remaining text."""
    with pytest.raises(ValidationError, match="unsupported"):
        _make("I ❤ this")


def test_accepts_hiragana_transliterated_by_unidecode():
    """unidecode romanizes hiragana instead of dropping it — text containing
    it must not be falsely rejected as "unsupported"."""
    req = _make("あいう")
    assert req.text == "あいう"


def test_rejects_control_characters():
    with pytest.raises(ValidationError, match="unsupported"):
        _make("hello\x00world")


def test_rejects_curly_brace_arpabet_escape():
    """Curly braces are the vendored text_to_sequence()'s ARPAbet escape
    syntax, whose `@`-prefixed phoneme symbols aren't in this checkpoint's
    symbol table — reject at the API boundary rather than let it fail deep
    in symbol lookup."""
    with pytest.raises(ValidationError, match="unsupported"):
        _make("Turn left on {HH AW1 S}.")


def test_rejects_empty_string():
    with pytest.raises(ValidationError):
        _make("")


def test_rejects_text_over_max_length():
    with pytest.raises(ValidationError):
        _make("a" * 501)
