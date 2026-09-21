"""Security-focused tests covering JWT, token rotation, and authorization."""

import io
import uuid
import wave

import numpy as np
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
        t = np.arange(48000) / 16000  # 3 s voiced tone (passes M4 duration checks)
        wav_file.writeframes(
            (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()
        )
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
    import jwt

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
    import jwt

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
    import jwt

    from backend.core.config import settings

    access, _ = _signup_and_login(client, "type3@example.com")
    sub = jwt.decode(access, options={"verify_signature": False})["sub"]
    legacy = jwt.encode(
        {"sub": sub, "exp": 9999999999},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 401


def test_expired_token_rejected(client: TestClient):
    """A validly signed but expired access token gets 401."""
    from datetime import timedelta

    access, _ = _signup_and_login(client, "exp1@example.com")
    sub = _decode_unverified(access)["sub"]
    expired = create_access_token({"sub": sub}, expires_delta=timedelta(seconds=-5))
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_alg_none_token_rejected(client: TestClient):
    """An unsigned `alg: none` token (algorithm-confusion attack) gets 401."""
    import jwt

    access, _ = _signup_and_login(client, "none1@example.com")
    claims = _decode_unverified(access)
    forged = jwt.encode(claims, key=None, algorithm="none")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_token_signed_with_other_algorithm_or_key_rejected(client: TestClient):
    """Tokens signed with a different key or HS512 instead of HS256 get 401."""
    import jwt

    access, _ = _signup_and_login(client, "alg1@example.com")
    claims = _decode_unverified(access)
    wrong_key = jwt.encode(claims, "k" * 40, algorithm="HS256")
    wrong_alg = jwt.encode(claims, _settings().JWT_SECRET_KEY, algorithm="HS512")
    for token in (wrong_key, wrong_alg):
        resp = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401


def test_tampered_token_rejected(client: TestClient):
    """Altering the payload of a signed token invalidates the signature."""
    access, _ = _signup_and_login(client, "tamper1@example.com")
    header, payload, sig = access.split(".")
    flipped = payload[:-2] + ("AA" if not payload.endswith("AA") else "BB")
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {header}.{flipped}.{sig}"},
    )
    assert resp.status_code == 401


def _settings():
    """Return the live settings object."""
    from backend.core.config import settings

    return settings


def _decode_unverified(token: str) -> dict:
    """Decode a token's claims without verifying its signature."""
    import jwt

    return jwt.decode(token, options={"verify_signature": False})
