"""H1: GET /synthesize/history?q= keeps the rows whose typed text contains it."""

import uuid
from datetime import datetime, timezone

import pytest

from backend.api.synthesize import HISTORY_SEARCH_MAX_LENGTH
from backend.models.voice_profile import VoiceProfile
from backend.services.tts_pipeline import load_mock_models
from backend.tests.test_fe2_contract import _generation, _user_and_profile
from backend.tests.test_synthesize import upload_profile

URL = "/api/v1/synthesize/history"


@pytest.fixture(scope="module", autouse=True)
def mock_models():
    """Inject lightweight mock models once for this module."""
    load_mock_models("cpu")


def _texts(response) -> set:
    return {g["input_text"] for g in response.json()}


def _seed(client, db, email, texts):
    """A user with one voice and a generation per text; return (headers, user, profile)."""
    headers, user_id, profile = _user_and_profile(client, db, email)
    for text in texts:
        _generation(db, user_id, profile, input_text=text)
    return headers, user_id, profile


def test_matches_a_substring_ignoring_case(client, db_session):
    headers, _, _ = _seed(
        client,
        db_session,
        "h1a@example.com",
        ["Happy BIRTHDAY, Sam!", "the weather today", "birthday cake"],
    )

    res = client.get(URL, params={"q": "birthDay"}, headers=headers)

    assert _texts(res) == {"Happy BIRTHDAY, Sam!", "birthday cake"}
    assert res.headers["X-Total-Count"] == "2"


def test_no_match_is_an_empty_list_with_total_zero(client, db_session):
    headers, _, _ = _seed(client, db_session, "h1b@example.com", ["hello"])

    res = client.get(URL, params={"q": "zebra"}, headers=headers)

    assert res.status_code == 200
    assert res.json() == [] and res.headers["X-Total-Count"] == "0"


@pytest.mark.parametrize(
    "needle, matching",
    [("50%", "save 50% today"), ("a_b", "see a_b here"), ("a\\b", "path a\\b ok")],
)
def test_wildcards_are_matched_literally(client, db_session, needle, matching):
    headers, _, _ = _seed(
        client,
        db_session,
        f"h1c{abs(hash(needle))}@example.com",
        [matching, "save 500 today", "see aXb here", "path a b ok"],
    )

    res = client.get(URL, params={"q": needle}, headers=headers)

    assert _texts(res) == {matching}


def test_a_lone_wildcard_does_not_match_everything(client, db_session):
    headers, _, _ = _seed(client, db_session, "h1d@example.com", ["one", "two%"])

    assert _texts(client.get(URL, params={"q": "%"}, headers=headers)) == {"two%"}
    assert _texts(client.get(URL, params={"q": "_"}, headers=headers)) == set()


@pytest.mark.parametrize("q", ["", "   ", "\t"])
def test_a_blank_query_is_ignored(client, db_session, q):
    headers, _, _ = _seed(client, db_session, f"h1e{len(q)}@example.com", ["a", "b"])

    res = client.get(URL, params={"q": q}, headers=headers)

    assert _texts(res) == {"a", "b"} and res.headers["X-Total-Count"] == "2"


def test_surrounding_spaces_are_trimmed(client, db_session):
    headers, _, _ = _seed(
        client, db_session, "h1f@example.com", ["good morning", "bye"]
    )

    res = client.get(URL, params={"q": "  morning "}, headers=headers)

    assert _texts(res) == {"good morning"}


def test_non_ascii_text_matches(client, db_session):
    headers, _, _ = _seed(
        client, db_session, "h1g@example.com", ["café au lait", "tea"]
    )

    assert _texts(client.get(URL, params={"q": "café"}, headers=headers)) == {
        "café au lait"
    }


def test_composes_with_voice_filter_paging_and_total(client, db_session):
    headers, user_id, first = _user_and_profile(client, db_session, "h1h@example.com")
    second = db_session.get(VoiceProfile, uuid.UUID(upload_profile(client, headers))).id
    for index in range(3):
        _generation(db_session, user_id, first, input_text=f"cat story {index}")
    _generation(db_session, user_id, second, input_text="cat on the second voice")
    _generation(db_session, user_id, first, input_text="dog story")

    everything = client.get(URL, params={"q": "cat"}, headers=headers)
    one_voice = client.get(
        URL, params={"q": "cat", "voice_profile_id": str(first)}, headers=headers
    )
    page = client.get(
        URL, params={"q": "cat", "limit": 2, "offset": 2}, headers=headers
    )

    assert everything.headers["X-Total-Count"] == "4"
    assert one_voice.headers["X-Total-Count"] == "3"
    assert "cat on the second voice" not in _texts(one_voice)
    assert len(page.json()) == 2 and page.headers["X-Total-Count"] == "4"


def test_never_returns_other_users_deleted_or_erased_rows(client, db_session):
    headers, user_id, profile = _user_and_profile(client, db_session, "h1i@example.com")
    _generation(db_session, user_id, profile, input_text="mine secret")
    _generation(
        db_session,
        user_id,
        profile,
        input_text="deleted secret",
        deleted_at=datetime.now(timezone.utc),
    )
    _generation(
        db_session,
        user_id,
        profile,
        input_text="[erased]",
        deleted_at=datetime.now(timezone.utc),
    )
    _, other_id, other_profile = _user_and_profile(
        client, db_session, "h1j@example.com"
    )
    _generation(db_session, other_id, other_profile, input_text="their secret")

    assert _texts(client.get(URL, params={"q": "secret"}, headers=headers)) == {
        "mine secret"
    }
    assert _texts(client.get(URL, params={"q": "erased"}, headers=headers)) == set()


def test_rows_of_a_deleted_voice_are_not_searched(client, db_session):
    headers, user_id, profile = _user_and_profile(client, db_session, "h1k@example.com")
    _generation(db_session, user_id, profile, input_text="orphaned words")
    client.delete(f"/api/v1/voice/profiles/{profile}", headers=headers)

    res = client.get(URL, params={"q": "orphaned"}, headers=headers)

    assert res.json() == [] and res.headers["X-Total-Count"] == "0"


def test_the_length_limit_is_a_422_at_the_boundary(client, db_session):
    headers, _, _ = _seed(client, db_session, "h1l@example.com", ["x"])

    ok = client.get(URL, params={"q": "y" * HISTORY_SEARCH_MAX_LENGTH}, headers=headers)
    too_long = client.get(
        URL, params={"q": "y" * (HISTORY_SEARCH_MAX_LENGTH + 1)}, headers=headers
    )

    assert ok.status_code == 200 and too_long.status_code == 422


def test_search_needs_a_token(client):
    assert client.get(URL, params={"q": "x"}).status_code == 401


def test_the_app_does_not_log_the_search_text(client, db_session, caplog):
    headers, _, _ = _seed(client, db_session, "h1m@example.com", ["hello"])

    with caplog.at_level("DEBUG"):
        client.get(URL, params={"q": "very-private-needle"}, headers=headers)

    app_lines = [r.getMessage() for r in caplog.records if r.name.startswith("backend")]
    assert app_lines and not any("very-private-needle" in line for line in app_lines)
