"""D3: GET /synthesize/history?voice_profile_id= narrows the list and its total."""

import uuid

import pytest

from backend.models.voice_profile import VoiceProfile
from backend.services.tts_pipeline import load_mock_models
from backend.tests.test_fe2_contract import (_generation, _headers,
                                             _user_and_profile)
from backend.tests.test_synthesize import upload_profile

URL = "/api/v1/synthesize/history"


@pytest.fixture(scope="module", autouse=True)
def mock_models():
    """Inject lightweight mock models once for this module."""
    load_mock_models("cpu")


def _second_profile(client, db, headers):
    """Upload another profile for the same user; return its id."""
    return db.get(VoiceProfile, uuid.UUID(upload_profile(client, headers))).id


def test_filter_returns_only_that_voice_and_counts_it(client, db_session):
    headers, user_id, first = _user_and_profile(client, db_session, "d3a@example.com")
    second = _second_profile(client, db_session, headers)
    _generation(db_session, user_id, first, input_text="one")
    _generation(db_session, user_id, second, input_text="two")
    _generation(db_session, user_id, second, input_text="three")

    res = client.get(f"{URL}?voice_profile_id={second}", headers=headers)

    assert {g["input_text"] for g in res.json()} == {"two", "three"}
    assert res.headers["X-Total-Count"] == "2"


def test_filter_combines_with_limit_and_offset(client, db_session):
    headers, user_id, profile = _user_and_profile(client, db_session, "d3b@example.com")
    for index in range(3):
        _generation(db_session, user_id, profile, input_text=f"t{index}")

    res = client.get(f"{URL}?voice_profile_id={profile}&limit=2", headers=headers)
    rest = client.get(
        f"{URL}?voice_profile_id={profile}&limit=2&offset=2", headers=headers
    )

    assert len(res.json()) == 2 and res.headers["X-Total-Count"] == "3"
    assert len(rest.json()) == 1 and rest.headers["X-Total-Count"] == "3"


def test_foreign_or_unknown_voice_matches_nothing(client, db_session):
    headers, user_id, profile = _user_and_profile(client, db_session, "d3c@example.com")
    _generation(db_session, user_id, profile)
    _, other_id, other_profile = _user_and_profile(
        client, db_session, "d3d@example.com"
    )
    _generation(db_session, other_id, other_profile, input_text="secret")

    for target in (other_profile, uuid.uuid4()):
        res = client.get(f"{URL}?voice_profile_id={target}", headers=headers)
        assert res.status_code == 200
        assert res.json() == [] and res.headers["X-Total-Count"] == "0"


def test_no_filter_is_unchanged(client, db_session):
    headers, user_id, first = _user_and_profile(client, db_session, "d3e@example.com")
    second = _second_profile(client, db_session, headers)
    _generation(db_session, user_id, first)
    _generation(db_session, user_id, second)

    res = client.get(URL, headers=headers)

    assert len(res.json()) == 2 and res.headers["X-Total-Count"] == "2"


def test_malformed_voice_id_is_rejected(client):
    headers = _headers(client, "d3f@example.com")
    res = client.get(f"{URL}?voice_profile_id=not-a-uuid", headers=headers)
    assert res.status_code == 422
