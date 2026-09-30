"""Account and voice-data erasure (SEC-2)."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.security import create_access_token
from backend.models.generation import Generation
from backend.models.refresh_token import RefreshToken
from backend.models.user import User
from backend.models.user_identity import UserIdentity
from backend.models.voice_profile import VoiceProfile
from backend.services.erasure import (
    ERASED_NAME,
    ERASED_TEXT,
    remove_files,
    remove_user_storage,
)
from backend.services.storage_cleanup import get_protected_paths

PASSWORD = "Password123!"


def _file(root: str, user_id, name: str) -> str:
    """Create a small real file under `<root>/<user_id>/` and return its path."""
    directory = os.path.join(root, str(user_id))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(b"RIFF")
    return path


def _voice(db, user, label: str):
    """A ready profile with real sample, embedding and one generated output."""
    sample = _file(settings.UPLOAD_DIR, user.id, f"{label}.wav")
    embedding = _file(settings.UPLOAD_DIR, user.id, f"{label}_embed.npy")
    output = _file(settings.OUTPUT_DIR, user.id, f"{label}_out.wav")
    profile = VoiceProfile(
        user_id=user.id,
        name=label,
        audio_sample_path=sample,
        embedding_path=embedding,
        status="ready",
        consent_confirmed_at=datetime.now(timezone.utc),
    )
    db.add(profile)
    db.flush()
    generation = Generation(
        user_id=user.id,
        voice_profile_id=profile.id,
        input_text="a private sentence",
        output_audio_path=output,
        status="completed",
    )
    db.add(generation)
    db.commit()
    return profile, generation, (sample, embedding, output)


def _signup(client: TestClient, email="erase@example.com") -> dict:
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Eve"},
    )
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _delete_me(client: TestClient, headers: dict, **body):
    return client.request("DELETE", "/api/v1/auth/me", headers=headers, json=body)


# --- profile deletion --------------------------------------------------------


def test_deleting_a_profile_removes_its_files_and_outputs(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    profile, generation, paths = _voice(db_session, user, "mine")

    response = client.delete(f"/api/v1/voice/profiles/{profile.id}", headers=headers)

    assert response.status_code == 200
    assert not any(os.path.exists(p) for p in paths)
    db_session.refresh(profile)
    db_session.refresh(generation)
    assert profile.deleted_at is not None and generation.deleted_at is not None
    # The row survives as the audit trail, but nothing protects the output.
    assert os.path.abspath(paths[2]) not in get_protected_paths(db_session, 30)


def test_deleting_one_profile_leaves_the_others_alone(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    doomed, _, _ = _voice(db_session, user, "doomed")
    _, kept_generation, kept_paths = _voice(db_session, user, "kept")

    client.delete(f"/api/v1/voice/profiles/{doomed.id}", headers=headers)

    assert all(os.path.exists(p) for p in kept_paths)
    db_session.refresh(kept_generation)
    assert kept_generation.deleted_at is None


# --- account erasure ---------------------------------------------------------


def test_erasing_an_account_removes_all_data_and_scrubs_the_row(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    user_id = user.id
    _, generation, paths = _voice(db_session, user, "a")
    stray = _file(settings.UPLOAD_DIR, user_id, "orphan.wav")

    response = _delete_me(client, headers, password=PASSWORD)

    assert response.status_code == 204
    assert not any(os.path.exists(p) for p in (*paths, stray))
    assert not os.path.isdir(os.path.join(settings.UPLOAD_DIR, str(user_id)))
    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.deleted_at is not None
    assert user.email == f"{user_id}@deleted.invalid"
    assert user.name == ERASED_NAME
    assert user.hashed_password is None and user.avatar_url is None
    generation = db_session.get(Generation, generation.id)
    assert generation.input_text == ERASED_TEXT
    assert generation.output_audio_path is None and generation.deleted_at is not None


def test_erasure_clears_the_refresh_cookie_and_revokes_every_session(
    client, db_session
):
    headers = _signup(client)  # logging in issues a refresh token
    live = db_session.query(RefreshToken).filter(RefreshToken.revoked_at.is_(None))
    assert live.count() == 1

    response = _delete_me(client, headers, password=PASSWORD)

    cookie = response.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie and "max-age=0" in cookie
    assert live.count() == 0


def test_an_erased_account_is_locked_out_and_its_address_is_free(client):
    headers = _signup(client)
    _delete_me(client, headers, password=PASSWORD)

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"email": "erase@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401
    again = client.post(
        "/api/v1/auth/signup",
        json={"email": "erase@example.com", "password": PASSWORD, "name": "New"},
    )
    assert again.status_code == 201


def test_a_wrong_or_missing_password_erases_nothing(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    _, _, paths = _voice(db_session, user, "safe")

    assert _delete_me(client, headers, password="wrong").status_code == 403
    assert _delete_me(client, headers).status_code == 403

    assert all(os.path.exists(p) for p in paths)
    db_session.expire_all()
    assert db_session.query(User).one().deleted_at is None


def test_erasure_requires_authentication(client):
    assert client.request("DELETE", "/api/v1/auth/me", json={}).status_code == 401


def test_a_google_only_account_needs_no_password(client, db_session):
    user = User(email="g@example.com", name="Gee", provider="google")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserIdentity(
            user_id=user.id,
            provider="google",
            provider_subject="sub-1",
            email=user.email,
        )
    )
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}

    assert _delete_me(client, headers).status_code == 204

    db_session.expire_all()
    identity = db_session.query(UserIdentity).one()
    assert identity.email == f"{user.id}@deleted.invalid"
    assert identity.deleted_at is not None


def test_erasing_one_account_does_not_touch_another(client, db_session):
    headers = _signup(client)
    other = User(email="other@example.com", name="Other", provider="local")
    db_session.add(other)
    db_session.commit()
    _, generation, paths = _voice(db_session, other, "theirs")

    _delete_me(client, headers, password=PASSWORD)

    assert all(os.path.exists(p) for p in paths)
    db_session.expire_all()
    generation = db_session.get(Generation, generation.id)
    assert generation.input_text == "a private sentence"
    assert generation.deleted_at is None
    assert db_session.get(User, other.id).deleted_at is None


# --- file helpers ------------------------------------------------------------


def test_remove_files_refuses_paths_outside_the_storage_directories(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("x")
    assert remove_files([str(outside), "", str(tmp_path / "missing")]) == 0
    assert outside.exists()


def test_remove_files_refuses_a_traversal_out_of_storage(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("x")
    sneaky = os.path.join(settings.UPLOAD_DIR, "..", "keep.txt")
    assert remove_files([sneaky]) == 0
    assert outside.exists()


def test_remove_user_storage_tolerates_a_user_with_no_files():
    remove_user_storage(uuid.uuid4())
