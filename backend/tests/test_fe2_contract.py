"""FE-2: signup session cookie, has_password, richer history, profile ordering."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.core.security import create_access_token
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.services.tts_pipeline import load_mock_models
from backend.tests.test_synthesize import upload_profile

PASSWORD = "Password123!"


@pytest.fixture(scope="module", autouse=True)
def mock_models():
    """Inject lightweight mock models once for this module."""
    load_mock_models("cpu")


def _sign_up(client: TestClient, email: str):
    """Register a user; return the signup response."""
    return client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Contract User"},
    )


def _headers(client: TestClient, email: str) -> dict:
    """Sign up, log in; return auth headers."""
    _sign_up(client, email)
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- BD-4: signup sets the refresh cookie -----------------------------------


def test_signup_sets_a_refresh_cookie_that_can_be_renewed(client):
    res = _sign_up(client, "cookie@example.com")
    assert res.status_code == 201
    assert "refresh_token" in res.cookies

    # The cookie is Secure, which the plain-http test client will not send back.
    client.cookies.clear()
    client.cookies.set("refresh_token", res.cookies["refresh_token"])

    renewed = client.post("/api/v1/auth/refresh")

    assert renewed.status_code == 200
    assert renewed.json()["access_token"]


def test_rejected_signup_sets_no_cookie(client):
    _sign_up(client, "dup@example.com")
    client.cookies.clear()
    res = _sign_up(client, "dup@example.com")
    assert res.status_code == 409
    assert "refresh_token" not in res.cookies


# --- BD-5: has_password ------------------------------------------------------


def test_me_reports_has_password_for_a_local_account(client):
    headers = _headers(client, "local@example.com")
    assert client.get("/api/v1/auth/me", headers=headers).json()["has_password"] is True


def test_me_reports_no_password_for_a_google_only_account(client, db_session):
    user = User(
        email="g@example.com",
        name="G",
        provider="google",
        hashed_password=None,
        email_verified_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token({"sub": str(user.id)})

    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert res.json()["has_password"] is False
    assert "hashed_password" not in res.json()


# --- BD-6: history shape and total ------------------------------------------


def _generation(db, user_id, profile_id, **overrides) -> Generation:
    """Insert a generation row directly."""
    row = Generation(
        user_id=user_id,
        voice_profile_id=profile_id,
        input_text=overrides.pop("input_text", "text"),
        status=overrides.pop("status", "completed"),
        **overrides,
    )
    db.add(row)
    db.commit()
    return row


def _user_and_profile(client, db, email, name="Voice"):
    """Create a user with one profile; return (headers, user, profile)."""
    headers = _headers(client, email)
    profile_id = upload_profile(client, headers)
    profile = db.get(VoiceProfile, uuid.UUID(profile_id))
    profile.name = name
    db.commit()
    return headers, profile.user_id, profile.id


def test_history_items_carry_profile_name_and_status(client, db_session):
    headers, user_id, profile_id = _user_and_profile(
        client, db_session, "h1@example.com", name="Narrator"
    )
    _generation(db_session, user_id, profile_id, status="failed")

    item = client.get("/api/v1/synthesize/history", headers=headers).json()[0]

    assert item["voice_profile_name"] == "Narrator"
    assert item["status"] == "failed"
    assert item["output_filename"] == ""
    assert item["audio_available"] is False


def test_history_total_counts_all_pages(client, db_session):
    headers, user_id, profile_id = _user_and_profile(
        client, db_session, "h2@example.com"
    )
    for index in range(3):
        _generation(db_session, user_id, profile_id, input_text=f"t{index}")

    page = client.get("/api/v1/synthesize/history?limit=2", headers=headers)
    rest = client.get("/api/v1/synthesize/history?limit=2&offset=2", headers=headers)
    beyond = client.get("/api/v1/synthesize/history?offset=10", headers=headers)

    assert len(page.json()) == 2 and page.headers["X-Total-Count"] == "3"
    assert len(rest.json()) == 1 and rest.headers["X-Total-Count"] == "3"
    assert beyond.json() == [] and beyond.headers["X-Total-Count"] == "3"


def test_history_total_ignores_other_users_and_deleted_profiles(client, db_session):
    headers, user_id, profile_id = _user_and_profile(
        client, db_session, "h3@example.com"
    )
    _generation(db_session, user_id, profile_id)
    _, other_id, other_profile_id = _user_and_profile(
        client, db_session, "h4@example.com"
    )
    _generation(db_session, other_id, other_profile_id)
    gone = VoiceProfile(
        user_id=user_id,
        name="Gone",
        audio_sample_path="",
        embedding_path="",
        consent_confirmed_at=datetime.now(timezone.utc),
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(gone)
    db_session.commit()
    gone_id = gone.id
    _generation(db_session, user_id, gone_id)

    res = client.get("/api/v1/synthesize/history", headers=headers)

    assert res.headers["X-Total-Count"] == "1"
    assert len(res.json()) == 1


def test_empty_history_total_is_zero(client):
    headers = _headers(client, "h5@example.com")
    res = client.get("/api/v1/synthesize/history", headers=headers)
    assert res.json() == [] and res.headers["X-Total-Count"] == "0"


def test_cors_exposes_the_total_count_header(client):
    headers = _headers(client, "h6@example.com")
    res = client.get(
        "/api/v1/synthesize/history",
        headers={**headers, "Origin": "http://localhost:3000"},
    )
    exposed = {
        h.strip().lower()
        for h in res.headers["access-control-expose-headers"].split(",")
    }
    assert "x-total-count" in exposed


# --- G-09: profiles newest first --------------------------------------------


def test_profiles_are_listed_newest_first(client, db_session):
    headers = _headers(client, "order@example.com")
    ids = [upload_profile(client, headers) for _ in range(3)]
    base = datetime.now(timezone.utc)
    for age, profile_id in enumerate(ids):
        row = db_session.get(VoiceProfile, uuid.UUID(profile_id))
        row.created_at = base - timedelta(hours=age)
    db_session.commit()

    listed = [
        p["id"] for p in client.get("/api/v1/voice/profiles", headers=headers).json()
    ]

    assert listed == ids
