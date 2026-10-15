"""Inline emotion tags in the request text (SPEECH_QUALITY_PLAN.md S5.4b).

``I was calm. [angry]Get out of my house![/angry] Then I left.`` asks for the middle sentence to
be delivered angrily and the rest as the analysis (or the request-level emotion) decides. The tag
names are the emotion names of ``text_analysis.EMOTIONS``. Anything else in square brackets is not
markup and stays in the text, where the character check rejects it as before.

The sound-event tags ``[laugh]``, ``[chuckle]`` and ``[cough]`` (S6.2a) are different: they are
not about delivery but a sound the model makes, which only some engines can (``Turbo`` and
``Nano``). They are accepted in any request; an engine that cannot make the sound never sees the
tag (``prepare`` removes it), so the request still succeeds.

A tag that is opened and not closed, closed without being opened, closed as another emotion or
nested inside another is an error, never silently guessed at.
"""

import re
from dataclasses import dataclass
from typing import Optional

from backend.services.text_analysis import EMOTIONS

_TAG = re.compile(r"\[(/?)(%s)\]" % "|".join(EMOTIONS), re.IGNORECASE)


NONVERBAL = ("laugh", "chuckle", "cough")
_NONVERBAL = re.compile(r"\[(%s)\]" % "|".join(NONVERBAL), re.IGNORECASE)


class MarkupError(ValueError):
    """The emotion tags in a text are not well formed."""


@dataclass(frozen=True)
class Run:
    """A stretch of text and the emotion its tag asked for (None = outside any tag)."""

    text: str
    emotion: Optional[str] = None


def has_markup(text: str) -> bool:
    """True if the text contains at least one emotion tag."""
    return _TAG.search(text) is not None


def parse(text: str) -> list[Run]:
    """Split a text into runs at its emotion tags; blank runs are dropped.

    Raises ``MarkupError`` for unbalanced, mismatched or nested tags.
    """
    runs: list[Run] = []
    current: Optional[str] = None
    position = 0
    for match in _TAG.finditer(text):
        closing, name = bool(match.group(1)), match.group(2).lower()
        runs.append(Run(text[position : match.start()], current))
        if closing:
            if current != name:
                raise MarkupError(
                    f"[/{name}] closes a tag that is not open"
                    if current is None
                    else f"[/{name}] closes [{current}]"
                )
            current = None
        else:
            if current is not None:
                raise MarkupError(
                    f"[{name}] opens inside [{current}]: tags cannot nest"
                )
            current = name
        position = match.end()
    if current is not None:
        raise MarkupError(f"[{current}] is never closed")
    runs.append(Run(text[position:], None))
    return [run for run in runs if run.text.strip()]


def strip_nonverbal(text: str, keep: tuple = ()) -> str:
    """The text with sound-event tags removed, except those in ``keep`` (written lowercase)."""

    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1).lower()
        return f"[{name}]" if name in keep else ""

    result = _NONVERBAL.sub(_replace, text)
    # Closing the gap a removed tag left; text without a removed tag is returned as it came.
    return re.sub(r" {2,}", " ", result) if result != text else result


def dropped_nonverbal(text: str, supported: tuple = ()) -> tuple:
    """The sound tags in ``text`` that an engine supporting only ``supported`` will not make.

    Lowercase, each once, in order of first appearance.
    """
    names = (m.group(1).lower() for m in _NONVERBAL.finditer(text))
    return tuple(dict.fromkeys(n for n in names if n not in supported))


def bare(text: str) -> str:
    """The text with every tag removed: what is left to be read aloud."""
    return strip_nonverbal(strip(text))


def prepare(text: str, supported: tuple = ()) -> str:
    """The text an engine is sent: emotion tags removed, and only the sound tags it supports."""
    return strip_nonverbal(strip(text), supported)


def strip(text: str) -> str:
    """The text with its emotion tags removed (what an engine without styling speaks).

    Does not validate; call ``parse`` first when the tags may be malformed.
    """
    return _TAG.sub("", text)
