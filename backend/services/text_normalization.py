"""English text normalisation for synthesis (SPEECH_QUALITY_PLAN.md S1.1).

Turns what people type into what is said, before the synthesizer's own cleaners (which
lowercase, expand digits and drop anything outside the symbol set). It runs first because
some decisions need the original case: ``FBI`` is spelled out, a shouted ``NO`` is not.

Everything here is a pure function of the text, so the same input always yields the same
speech. Anything it does not understand is left alone; the request validator then decides
whether the leftover characters can be spoken.
"""

import re
from typing import Dict

import inflect

from backend.services.sv2tts.synthesizer.hparams import hparams as synth_hparams
from backend.services.sv2tts.synthesizer.utils import cleaners

_inflect = inflect.engine()

# --- Spelled-out letters ------------------------------------------------------

# Spelled the way they sound, so the model is not asked to read a bare "f b i".
_LETTER_NAMES = {
    "a": "ay",
    "b": "bee",
    "c": "see",
    "d": "dee",
    "e": "ee",
    "f": "eff",
    "g": "jee",
    "h": "aitch",
    "i": "eye",
    "j": "jay",
    "k": "kay",
    "l": "el",
    "m": "em",
    "n": "en",
    "o": "oh",
    "p": "pee",
    "q": "cue",
    "r": "ar",
    "s": "ess",
    "t": "tee",
    "u": "you",
    "v": "vee",
    "w": "double you",
    "x": "ex",
    "y": "why",
    "z": "zee",
}


def spell(letters: str) -> str:
    """Spell ``letters`` as their names: ``"FBI"`` -> ``"eff bee eye"``."""
    return " ".join(_LETTER_NAMES[c] for c in letters.lower() if c in _LETTER_NAMES)


# Read as letters even though they contain a vowel. Words that are also common English
# words (IT, WHO, US, AM, ID, OR) are left out: shouted, they are far more likely words.
_SPELLED_ACRONYMS = frozenset(
    "FBI CIA NSA USA UK UN EU UAE NYC LA DC UFO VIP FAQ CEO CFO CTO COO API URL USB GPS "
    "DNA RNA ATM HIV AIDS BBC CNN NBA NFL ETA ASAP DIY FYI PR HR GDP IQ MRI USD EUR GBP "
    "KPI ROI NGO AI ML UI UX IOS EV SUV OEM LLC INC LTD CPU GPU".split()
)
# All-consonant shouts and interjections that must not be spelled letter by letter.
_NOT_ACRONYMS = frozenset("HMM SHH PSST BRR TSK NTH GRR MMM PFFT HM".split())
_ACRONYM = re.compile(r"\b([A-Z]{2,6})(s?)\b")


def _acronym(match: "re.Match[str]") -> str:
    """Spell an acronym; leave words (NASA) and shouted words (NO, STOP) alone.

    All capitals with no vowel (TV, HTML, PDF, CNN) are spelled, as is a listed acronym;
    ``y`` counts as a vowel so a shouted WHY or MY stays a word.
    """
    word, plural = match.group(1), match.group(2)
    if word == "OK":
        return "okay"
    if word in _NOT_ACRONYMS:
        return match.group(0)
    if word in _SPELLED_ACRONYMS or not set(word) & set("AEIOUY"):
        return spell(word) + (" ess" if plural else "")
    return match.group(0)


_DOTTED_INITIALS = re.compile(r"\b(?:[A-Z]\.){2,}(?P<end>\s*$)?")


def _dotted_initials(match: "re.Match[str]") -> str:
    """``U.S.A.`` -> spelled letters; the dots must not read as sentence ends.

    At the end of a line the final dot is the sentence's own full stop, so it is kept.
    """
    spoken = spell(match.group(0).replace(".", ""))
    end = match.group("end")
    return spoken if end is None else f"{spoken}.{end}"


# --- Symbols ------------------------------------------------------------------

_EMPHASIS = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")
_PERCENT = re.compile(r"%")
_HASH_NUMBER = re.compile(r"#\s?(?=\d)")
_HASH_TAG = re.compile(r"#(?=[A-Za-z])")
_APPROX = re.compile(r"~\s?(?=\d)")
_PLUS = re.compile(r"\s?\+\s?")
_EQUALS = re.compile(r"\s?=\s?")
_AMPERSAND = re.compile(r"\s?&\s?")
_AND_OR = re.compile(r"\band/or\b", re.IGNORECASE)
_LETTER_SLASH = re.compile(r"(?<=[A-Za-z])/(?=[A-Za-z])")
_AT = re.compile(r"\s@\s|@(?=[A-Za-z])")

_LATIN = [
    (re.compile(r"\be\.g\.", re.IGNORECASE), "for example"),
    (re.compile(r"\bi\.e\.", re.IGNORECASE), "that is"),
    (re.compile(r"\betc\.(?=\s+[a-z])", re.IGNORECASE), "et cetera"),
    (re.compile(r"\betc\.", re.IGNORECASE), "et cetera."),
    (re.compile(r"\bvs\.?(?=\s)", re.IGNORECASE), "versus"),
]

# --- Addresses ----------------------------------------------------------------

_EMAIL = re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_TLDS = "com|org|net|edu|gov|io|co|uk|ai|info|dev|app"
_URL = re.compile(
    rf"\b(?:https?://)?(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:{_TLDS})\b"
    r"(?:/[\w\-./?=&%#]*)?",
    re.IGNORECASE,
)
_SCHEME_URL = re.compile(r"\bhttps?://\S+", re.IGNORECASE)


def _speak_address(text: str) -> str:
    """Read an email or URL aloud: ``a.b@x.com`` -> ``a dot b at x dot com``."""
    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    text = text.rstrip(".,;:!?")
    return (
        text.replace("@", " at ")
        .replace(".", " dot ")
        .replace("/", " slash ")
        .replace("-", " dash ")
        .replace("?", " question mark ")
        .replace("=", " equals ")
        .replace("&", " and ")
        .replace("_", " underscore ")
    )


# --- Time, dates, fractions, units -------------------------------------------

_TIME = re.compile(r"\b(\d{1,2}):(\d{2})(?:\s?([AaPp])\.?\s?[Mm]\.?)?(?![\d:])")
_BARE_MERIDIEM = re.compile(r"\b(\d{1,2})\s?([AaPp])\.?[Mm]\.?(?=[\s,;:!?)]|$)")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_FRACTION = re.compile(r"(?<![\d/.])(\d{1,3})/(\d{1,3})(?![\d/])")

_MONTHS = (
    "January February March April May June July August September October November December"
).split()


def _meridiem(letter: str) -> str:
    return spell(letter + "m")


def _speak_time(match: "re.Match[str]") -> str:
    """``10:05 pm`` -> ``10 oh 5 pee em``; invalid clock values are left as they are."""
    hour, minute, ampm = int(match.group(1)), int(match.group(2)), match.group(3)
    if hour > 23 or minute > 59:
        return match.group(0)
    suffix = f" {_meridiem(ampm)}" if ampm else ""
    if minute == 0:
        return f"{hour}{suffix}" if ampm else f"{hour} o'clock"
    if minute < 10:
        return f"{hour} oh {minute}{suffix}"
    return f"{hour} {minute}{suffix}"


def _speak_iso_date(match: "re.Match[str]") -> str:
    """``2024-10-10`` -> ``October 10th, 2024``; impossible dates are left alone."""
    year, month, day = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return match.group(0)
    return f"{_MONTHS[month - 1]} {_inflect.ordinal(day)}, {year}"


def _speak_fraction(match: "re.Match[str]") -> str:
    """``3/4`` -> ``3 fourths``, ``1/2`` -> ``1 half``; a zero denominator is left alone."""
    num, den = int(match.group(1)), int(match.group(2))
    if den == 0:
        return match.group(0)
    if den == 2:
        return f"{num} {'half' if num == 1 else 'halves'}"
    word = "quarter" if den == 4 else _inflect.ordinal(_inflect.number_to_words(den))
    return f"{num} {word}{'' if num == 1 else 's'}"


# Longest first so "kmh" is not read as "km" followed by "h".
_UNITS: Dict[str, str] = {
    "km/h": "kilometers per hour",
    "kph": "kilometers per hour",
    "mph": "miles per hour",
    "kg": "kilograms",
    "mg": "milligrams",
    "km": "kilometers",
    "cm": "centimeters",
    "mm": "millimeters",
    "lbs": "pounds",
    "lb": "pounds",
    "oz": "ounces",
    "ft": "feet",
    "kb": "kilobytes",
    "mb": "megabytes",
    "gb": "gigabytes",
    "tb": "terabytes",
    "khz": "kilohertz",
    "mhz": "megahertz",
    "ghz": "gigahertz",
    "hz": "hertz",
    "ms": "milliseconds",
}
_UNIT = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s?("
    + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
    + r")\b(?!/)",
    re.IGNORECASE,
)
_DEGREES = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?°\s?([CF])\b")


def _speak_unit(match: "re.Match[str]") -> str:
    """``5kg`` -> ``5 kilograms``; a quantity of exactly one gets the singular."""
    number, unit = match.group(1), _UNITS[match.group(2).lower()]
    if number == "1" and unit.endswith("s") and unit not in {"feet", "hertz"}:
        unit = unit[:-1]
    if number == "1" and unit == "feet":
        unit = "foot"
    return f"{number} {unit}"


def _speak_degrees(match: "re.Match[str]") -> str:
    """``20°C`` -> ``20 degrees Celsius``."""
    scale = "Celsius" if match.group(2) == "C" else "Fahrenheit"
    return f"{match.group(1)} degrees {scale}"


def _sub_all(text: str, rules: "list[tuple[re.Pattern, object]]") -> str:
    """Apply each (pattern, replacement) rule in order."""
    for pattern, replacement in rules:
        text = pattern.sub(replacement, text)  # type: ignore[arg-type]
    return text


_WHITESPACE = re.compile(r"[ \t]{2,}")


def normalize_text(text: str) -> str:
    """Rewrite one line of English into plainly speakable words; see the module docstring.

    Order matters: addresses before dots and slashes are touched, times and dates before
    fractions and numbers, spelling last because it relies on the original case.
    """
    text = _EMPHASIS.sub(r"\1", text).replace("*", "")
    text = _EMAIL.sub(lambda m: _speak_address(m.group(0)), text)
    text = _SCHEME_URL.sub(lambda m: _speak_address(m.group(0)), text)
    text = _URL.sub(lambda m: _speak_address(m.group(0)), text)
    for pattern, spoken in _LATIN:
        text = pattern.sub(spoken, text)
    text = _TIME.sub(_speak_time, text)
    text = _BARE_MERIDIEM.sub(lambda m: f"{m.group(1)} {_meridiem(m.group(2))}", text)
    text = _ISO_DATE.sub(_speak_iso_date, text)
    text = _DEGREES.sub(_speak_degrees, text)
    text = _UNIT.sub(_speak_unit, text)
    text = _FRACTION.sub(_speak_fraction, text)
    text = _sub_all(
        text,
        [
            (_PERCENT, " percent "),
            (_HASH_NUMBER, " number "),
            (_HASH_TAG, " hashtag "),
            (_APPROX, " about "),
            (_AND_OR, "and or"),
            (_LETTER_SLASH, " slash "),
            (_AT, " at "),
            (_AMPERSAND, " and "),
            (_PLUS, " plus "),
            (_EQUALS, " equals "),
        ],
    )
    text = _DOTTED_INITIALS.sub(_dotted_initials, text)
    text = _ACRONYM.sub(_acronym, text)
    return _WHITESPACE.sub(" ", text).strip()


def clean_text(text: str) -> str:
    """Normalise then run the synthesizer's cleaners, line by line.

    Each line is handled on its own: the cleaners collapse all whitespace, which would
    otherwise erase the line and paragraph breaks the segmenter turns into pauses. Text
    with ARPAbet braces is returned untouched, since lowercasing would corrupt phonemes.
    """
    if "{" in text:
        return text
    lines = []
    for line in text.split("\n"):
        line = normalize_text(line)
        for name in synth_hparams.tts_cleaner_names:
            line = getattr(cleaners, name)(line)
        lines.append(line.strip())
    return "\n".join(lines)
