"""Security-focused tests covering JWT, token rotation, and authorization."""

import io
import uuid
import wave

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.sql import func

from backend.core.config import Settings
from backend.core.security import create_access_token, hash_password
from backend.models.user import User


def test_jwt_secret_too_short_raises():
    """Settings must reject JWT_SECRET_KEY values shorter than 32 characters."""

    try:
        Settings(JWT_SECRET_KEY="short_key", DATABASE_URL="sqlite://")
        assert False, "Expected ValidationError was not raised"
    except (ValidationError, ValueError):
        pass  # Expected — short secret must be rejected


def test_refresh_token_rotated(client: TestClient):
    """After calling /refresh, the cookie value must differ from the original."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "rotate@example.com",
            "password": "Password123!",
            "name": "Rotate User",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "rotate@example.com", "password": "Password123!"},
    )
    old_refresh = login_resp.cookies.get("refresh_token")
    assert old_refresh is not None

    refresh_resp = client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": old_refresh}
    )
    assert refresh_resp.status_code == 200

    new_refresh = refresh_resp.cookies.get("refresh_token")
    assert new_refresh is not None
    assert new_refresh != old_refresh


def test_deleted_user_token_rejected(client: TestClient, db_session):
    """A token issued before soft-delete must be rejected with 401."""

    # Create user and issue a token
    user = User(
        email="deleted@example.com",
        name="Deleted User",
        hashed_password=hash_password("Password123!"),
        provider="local",
    )
    db_session.add(user)
    db_session.flush()

    token = create_access_token(data={"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # Soft-delete the user
    user.deleted_at = func.now()
    db_session.flush()

    # Old token must now be rejected
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401


def test_path_not_in_generation_response(client: TestClient):
    """GenerationOut must not expose any OS path separator in its JSON response."""

    # Set up user and upload profile
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "pathcheck@example.com",
            "password": "Password123!",
            "name": "Path Check",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "pathcheck@example.com", "password": "Password123!"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00" * 1000)
    buf.seek(0)
    wav_bytes = buf.read()

    up_res = client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "Path Voice"},
        files={"file": ("path.wav", wav_bytes, "audio/wav")},
    )
    assert up_res.status_code == 201
    profile_id = up_res.json()["id"]

    # Synthesize to generate a history entry
    client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile_id, "text": "Path check test"},
    )

    history = client.get("/api/v1/synthesize/history", headers=headers).json()
    assert len(history) >= 1

    # Verify no OS path separators appear in filename field
    for entry in history:
        filename = entry.get("output_filename", "")
        assert (
            "/" not in filename
        ), f"OS path separator found in output_filename: {filename}"
        assert (
            "\\" not in filename
        ), f"OS path separator found in output_filename: {filename}"


def _signup_and_login(client: TestClient, email: str) -> tuple[str, str]:
    """Register and log in a user, returning (access_token, refresh_cookie)."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "Type User"},
    )
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    )
    return resp.json()["access_token"], resp.cookies.get("refresh_token")


def test_token_type_claims():
    """Access and refresh tokens carry distinct `type` claims."""
    from jose import jwt

    from backend.core.config import settings
    from backend.core.security import create_refresh_token

    claims = {"sub": "abc"}
    keys = (settings.JWT_SECRET_KEY, [settings.JWT_ALGORITHM])
    access = jwt.decode(create_access_token(claims), keys[0], algorithms=keys[1])
    refresh = jwt.decode(create_refresh_token(claims), keys[0], algorithms=keys[1])
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"


def test_caller_cannot_override_type_claim():
    """A `type` key in the caller-supplied data must not win over the real type."""
    from jose import jwt

    from backend.core.config import settings

    token = create_access_token({"sub": "abc", "type": "refresh"})
    payload = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    assert payload["type"] == "access"


def test_refresh_token_rejected_as_access_token(client: TestClient):
    """A refresh token presented as a bearer token must get 401 on /me."""
    _, refresh = _signup_and_login(client, "type1@example.com")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401


def test_access_token_rejected_at_refresh(client: TestClient):
    """An access token presented in the refresh cookie must get 401."""
    access, _ = _signup_and_login(client, "type2@example.com")
    resp = client.post("/api/v1/auth/refresh", cookies={"refresh_token": access})
    assert resp.status_code == 401


def test_untyped_legacy_token_rejected(client: TestClient):
    """A validly signed token with no `type` claim is rejected on /me."""
    from jose import jwt

    from backend.core.config import settings

    access, _ = _signup_and_login(client, "type3@example.com")
    sub = jwt.get_unverified_claims(access)["sub"]
    legacy = jwt.encode(
        {"sub": sub, "exp": 9999999999},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 401
