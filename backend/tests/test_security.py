"""Security-focused tests covering JWT, token rotation, and authorization."""

import io
import uuid

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.sql import func


def test_jwt_secret_too_short_raises():
    """Settings must reject JWT_SECRET_KEY values shorter than 32 characters."""
    from backend.core.config import Settings

    try:
        Settings(JWT_SECRET_KEY="short_key", DATABASE_URL="sqlite://")
        assert False, "Expected ValidationError was not raised"
    except (ValidationError, ValueError):
        pass  # Expected — short secret must be rejected


def test_refresh_token_rotated(client: TestClient):
    """After calling /refresh, the cookie value must differ from the original."""
    client.post(
        "/api/auth/signup",
        json={
            "email": "rotate@example.com",
            "password": "Password123!",
            "name": "Rotate User",
        },
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "rotate@example.com", "password": "Password123!"},
    )
    old_refresh = login_resp.cookies.get("refresh_token")
    assert old_refresh is not None

    refresh_resp = client.post(
        "/api/auth/refresh", cookies={"refresh_token": old_refresh}
    )
    assert refresh_resp.status_code == 200

    new_refresh = refresh_resp.cookies.get("refresh_token")
    assert new_refresh is not None
    assert new_refresh != old_refresh


def test_deleted_user_token_rejected(client: TestClient, db_session):
    """A token issued before soft-delete must be rejected with 401."""
    from backend.core.security import create_access_token, hash_password
    from backend.models.user import User

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
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 401


def test_path_not_in_generation_response(client: TestClient):
    """GenerationOut must not expose any OS path separator in its JSON response."""
    import wave

    # Set up user and upload profile
    client.post(
        "/api/auth/signup",
        json={
            "email": "pathcheck@example.com",
            "password": "Password123!",
            "name": "Path Check",
        },
    )
    token = client.post(
        "/api/auth/login",
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
        "/api/voice/upload",
        headers=headers,
        data={"name": "Path Voice"},
        files={"file": ("path.wav", wav_bytes, "audio/wav")},
    )
    assert up_res.status_code == 201
    profile_id = up_res.json()["id"]

    # Synthesize to generate a history entry
    client.post(
        "/api/synthesize",
        headers=headers,
        json={"voice_profile_id": profile_id, "text": "Path check test"},
    )

    history = client.get("/api/synthesize/history", headers=headers).json()
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
