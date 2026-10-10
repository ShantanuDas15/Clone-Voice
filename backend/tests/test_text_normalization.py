"""English text normalisation (SPEECH_QUALITY_PLAN.md S1.1).

Table-driven: each row is a sentence a person might type and what should be said.
"""

import uuid

import pytest
from pydantic import ValidationError

from backend.schemas.synthesize import SynthesizeRequest
from backend.services import tts_pipeline
from backend.services.sv2tts.synthesizer.hparams import hparams as synth_hparams
from backend.services.text_normalization import clean_text, normalize_text, spell

# --- spelled letters ---------------------------------------------------------


def test_spell_uses_letter_names():
    assert spell("FBI") == "eff bee eye"
    assert spell("tv") == "tee vee"
    assert spell("W") == "double you"
    assert spell("") == ""


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The FBI called", "The eff bee eye called"),
        ("a TV and a PC", "a tee vee and a pee see"),
        ("an HTML page", "an aitch tee em el page"),
        ("two CPUs", "two see pee you ess"),
        ("NASA launched it", "NASA launched it"),  # a word, not letters
        ("I said NO", "I said NO"),  # a shouted word is not an acronym
        ("STOP RIGHT NOW", "STOP RIGHT NOW"),
        ("WHY MY", "WHY MY"),  # y counts as a vowel
        ("HMM and SHH", "HMM and SHH"),  # interjections without a vowel
        ("It is IT again", "It is IT again"),  # ambiguous words are never spelled
        ("OK then", "okay then"),
        ("I live in the U.S.A.", "I live in the you ess ay."),
        ("The U.S. Army", "The you ess Army"),
    ],
)
def test_acronyms_and_shouting(text, expected):
    assert normalize_text(text) == expected


# --- symbols -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tom & Jerry", "Tom and Jerry"),
        ("Tom&Jerry", "Tom and Jerry"),
        ("50% off", "50 percent off"),
        ("a #1 fan", "a number 1 fan"),
        ("use #python", "use hashtag python"),
        ("x + y = z", "x plus y equals z"),
        ("C++", "C plus plus"),
        ("about ~5 miles", "about about 5 miles"),
        ("and/or", "and or"),
        ("him/her", "him slash her"),
        ("ping @alex", "ping at alex"),
        ("meet @ noon", "meet at noon"),
        ("This is *really* good", "This is really good"),
        ("***Wow***", "Wow"),
        ("a stray * star", "a stray star"),
    ],
)
def test_symbols_become_words(text, expected):
    assert normalize_text(text) == expected


def test_latin_abbreviations():
    assert (
        normalize_text("fruit, e.g. apples, i.e. fresh")
        == "fruit, for example apples, that is fresh"
    )
    assert normalize_text("cats, dogs etc. and more") == "cats, dogs et cetera and more"
    assert normalize_text("cats, dogs etc.") == "cats, dogs et cetera."
    assert normalize_text("us vs. them") == "us versus them"


# --- addresses ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("mail me@x.com now", "mail me at x dot com now"),
        (
            "mail a.b+c@mail.example.org",
            "mail a dot b plus c at mail dot example dot org",
        ),
        ("visit www.example.com today", "visit example dot com today"),
        (
            "see https://example.com/a-b?x=1",
            "see example dot com slash a dash b question mark x equals 1",
        ),
        ("Visit example.com.", "Visit example dot com."),
        ("the end.Then more", "the end.Then more"),  # no known TLD: not an address
    ],
)
def test_addresses_are_read_aloud(text, expected):
    assert normalize_text(text) == expected


# --- times, dates, fractions, units -----------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("at 10:30", "at 10 30"),
        ("at 10:05", "at 10 oh 5"),
        ("at 10:00", "at 10 o'clock"),
        ("at 10:30 PM", "at 10 30 pee em"),
        ("at 9:00 a.m. sharp", "at 9 ay em sharp"),
        ("at 9 pm", "at 9 pee em"),
        ("at 25:99", "at 25:99"),  # not a clock time: left alone
        ("ratio 3:45:10", "ratio 3:45:10"),
    ],
)
def test_times(text, expected):
    assert normalize_text(text) == expected


def test_iso_dates():
    assert normalize_text("on 2024-10-10") == "on October 10th, 2024"
    assert normalize_text("on 2024-02-01") == "on February 1st, 2024"
    assert normalize_text("on 2024-13-40") == "on 2024-13-40"  # impossible: untouched


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3/4 cup", "3 quarters cup"),
        ("1/2 pie", "1 half pie"),
        ("3/2 pies", "3 halves pies"),
        ("1/3 left", "1 third left"),
        ("2/3 left", "2 thirds left"),
        ("1/0 never", "1/0 never"),
        ("10/10/2024", "10/10/2024"),  # an ambiguous date is not guessed
    ],
)
def test_fractions(text, expected):
    assert normalize_text(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("5kg", "5 kilograms"),
        ("1 kg", "1 kilogram"),
        ("10 km/h", "10 kilometers per hour"),
        ("60 mph", "60 miles per hour"),
        ("5 ft", "5 feet"),
        ("1 ft", "1 foot"),
        ("16 GB", "16 gigabytes"),
        ("20°C", "20 degrees Celsius"),
        ("68 °F", "68 degrees Fahrenheit"),
        ("2.5 cm", "2.5 centimeters"),
        ("a 5g speck", "a 5g speck"),  # g is ambiguous: not a unit here
        ("kg of rice", "kg of rice"),  # no number: left alone
    ],
)
def test_units(text, expected):
    assert normalize_text(text) == expected


# --- boundaries --------------------------------------------------------------


@pytest.mark.parametrize("text", ["", " ", "...", "?!", "Hello, world."])
def test_plain_and_degenerate_text_is_unchanged(text):
    assert normalize_text(text) == text.strip()


def test_normalisation_is_deterministic_and_stable_on_its_own_output():
    text = "At 10:30 PM the FBI said NO & left; 5kg, 50%."
    once = normalize_text(text)
    assert normalize_text(text) == once
    assert normalize_text(once) == once


def test_very_long_text_is_handled():
    text = "The FBI said 50% of it. " * 400
    assert normalize_text(text).count("eff bee eye") == 400


# --- clean_text: normalise, then the synthesizer's cleaners, per line -------


def test_clean_text_lowercases_expands_numbers_and_keeps_line_breaks():
    cleaned = clean_text("Dr. Who has  3 cats.\n\n  Next   line\nthird")
    assert cleaned == "doctor who has three cats.\n\nnext line\nthird"


def test_clean_text_end_to_end_examples():
    assert clean_text("Pay $4.50 at 10:30 PM") == (
        "pay four dollars, fifty cents at ten thirty pee em"
    )
    assert (
        clean_text("I paid $45 for 12 tickets.")
        == "i paid forty-five dollars for twelve tickets."
    )


def test_clean_text_leaves_arpabet_braces_raw():
    text = "Turn left on {HH AW1 S S T AH0 N} Street."
    assert clean_text(text) == text


def test_the_pipeline_cleans_through_the_same_function():
    text = "The FBI & 50% of us."
    assert tts_pipeline._clean_for_chunking(text) == clean_text(text)


def test_pipeline_cleaner_names_are_what_clean_text_runs():
    assert synth_hparams.tts_cleaner_names == ["english_cleaners"]


# --- the request validator accepts exactly what can be spoken ----------------


def _request(text: str) -> SynthesizeRequest:
    return SynthesizeRequest(voice_profile_id=uuid.uuid4(), text=text)


@pytest.mark.parametrize(
    "text",
    [
        "Pay $4.50 or £3 or 50% now",
        "Tom & Jerry, c/o x + y = z",
        "Email me@example.com or visit www.example.com",
        "This is *really* good",
        "At 10:30 PM on 2024-10-10, 5kg and 20°C",
        "The FBI said NO!",
        "a #1 fan of 3/4 cups",
        "Wait\u2026 \u201cquoted\u201d \u2014 done",
    ],
)
def test_validator_accepts_what_the_pipeline_can_say(text):
    assert _request(text).text == text


@pytest.mark.parametrize(
    "text,bad",
    [
        ("hello \U0001f600 world", "\U0001f600"),
        ("[laugh] ok", "["),
        ("Turn left on {HH AW1}.", "{"),
        ("hello\x00world", "\x00"),
        ("a_b", "_"),
        ("ok ~ ok", "~"),
    ],
)
def test_validator_still_rejects_what_would_be_lost(text, bad):
    with pytest.raises(ValidationError, match="unsupported") as err:
        _request(text)
    # the message shows the characters escaped, as repr does
    assert repr(bad)[1:-1] in str(err.value)
