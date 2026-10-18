"""Account data export (E1): POST /auth/me/export."""

import io
import json
import os
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.security import create_access_token
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.models.voice_profile_sample import VoiceProfileSample
from backend.services import account_export
from backend.tests.test_login_throttle import FAILURES
from backend.tests.test_rate_limit import fresh_limiter  # noqa: F401

PASSWORD = "Password123!"
URL = "/api/v1/auth/me/export"


def _file(root: str, user_id, name: str, data: bytes = b"RIFFdata") -> str:
    """Create a real file under `<root>/<user_id>/` and return its path."""
    directory = os.path.join(root, str(user_id))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _voice(db, user, label: str, clips: int = 2, text: str = "hello there"):
    """A ready profile with `clips` real clips and one generation."""
    paths = [
        _file(settings.UPLOAD_DIR, user.id, f"{label}{i}.wav", f"clip{i}".encode())
        for i in range(clips)
    ]
    profile = VoiceProfile(
        user_id=user.id,
        name=label,
        audio_sample_path=paths[0] if paths else "/nonexistent.wav",
        embedding_path=_file(settings.UPLOAD_DIR, user.id, f"{label}.npy"),
        status="ready",
        consent_confirmed_at=datetime.now(timezone.utc),
        terms_version="2026-09-30",
        samples=[
            VoiceProfileSample(
                position=i,
                audio_path=path,
                embedding_path=_file(settings.UPLOAD_DIR, user.id, f"{label}{i}.npy"),
                agreement=0.9,
                quality={"rating": "good"},
            )
            for i, path in enumerate(paths)
        ],
    )
    db.add(profile)
    db.flush()
    output = _file(settings.OUTPUT_DIR, user.id, f"{label}_out.wav", b"RIFFout")
    generation = Generation(
        user_id=user.id,
        voice_profile_id=profile.id,
        input_text=text,
        output_audio_path=output,
        status="completed",
        engine="sv2tts",
    )
    db.add(generation)
    db.commit()
    return profile, generation, output


def _signup(client: TestClient, email="export@example.com") -> dict:
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Eve"},
    )
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _open(response) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(response.content))


def _json(archive: zipfile.ZipFile, name: str):
    return json.loads(archive.read(name))


# --- contents ----------------------------------------------------------------


def test_export_contains_the_users_data_and_audio(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    profile, generation, _ = _voice(db_session, user, "mine")

    response = client.post(URL, headers=headers, json={"password": PASSWORD})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    archive = _open(response)
    assert set(archive.namelist()) == {
        "account.json",
        "voice_profiles.json",
        "generations.json",
        "README.txt",
        f"voice_samples/{profile.id}/0.wav",
        f"voice_samples/{profile.id}/1.wav",
        f"generations/{generation.id}.wav",
    }
    assert archive.read(f"voice_samples/{profile.id}/1.wav") == b"clip1"
    assert archive.read(f"generations/{generation.id}.wav") == b"RIFFout"
    assert _json(archive, "account.json")["email"] == "export@example.com"
    [entry] = _json(archive, "voice_profiles.json")
    assert entry["id"] == str(profile.id) and entry["terms_version"] == "2026-09-30"
    assert [c["position"] for c in entry["clips"]] == [0, 1]
    assert entry["clips"][0]["audio_file"] == f"voice_samples/{profile.id}/0.wav"
    [row] = _json(archive, "generations.json")
    assert row["text"] == "hello there" and row["engine"] == "sv2tts"


def test_export_never_includes_credentials_or_embeddings(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    _voice(db_session, user, "mine")
    password_hash = user.hashed_password

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    blob = b"".join(archive.read(n) for n in archive.namelist())
    assert password_hash.encode() not in blob
    assert b"hashed_password" not in blob and b"refresh" not in blob
    assert not any(n.endswith(".npy") for n in archive.namelist())
    assert b".npy" not in blob and b"embedding_path" not in blob


def test_export_omits_other_users_and_deleted_rows(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    other = User(email="other@example.com", name="Oz", provider="local")
    db_session.add(other)
    db_session.commit()
    _voice(db_session, other, "theirs", text="not yours")
    _voice(db_session, user, "kept", text="mine")
    _, gone, _ = _voice(db_session, user, "gone")
    gone.deleted_at = datetime.now(timezone.utc)
    gone.input_text = "[erased]"
    gone.output_audio_path = None
    db_session.commit()

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    ids = [g["id"] for g in _json(archive, "generations.json")]
    assert len(ids) == 1 and str(gone.id) not in ids
    blob = b"".join(archive.read(n) for n in archive.namelist())
    assert b"not yours" not in blob and b"theirs" not in blob
    assert f"generations/{gone.id}.wav" not in archive.namelist()


def test_a_pruned_output_is_listed_without_audio(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    _, generation, output = _voice(db_session, user, "mine")
    os.unlink(output)

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    [row] = _json(archive, "generations.json")
    assert row["audio_file"] is None and row["text"] == "hello there"
    assert f"generations/{generation.id}.wav" not in archive.namelist()


def test_a_path_outside_storage_is_never_read(client, db_session, tmp_path):
    headers = _signup(client)
    user = db_session.query(User).one()
    _, generation, _ = _voice(db_session, user, "mine")
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"TOP-SECRET")
    generation.output_audio_path = str(secret)
    db_session.commit()

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    blob = b"".join(archive.read(n) for n in archive.namelist())
    assert b"TOP-SECRET" not in blob
    assert _json(archive, "generations.json")[0]["audio_file"] is None


def test_a_profile_without_clips_falls_back_to_its_sample(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    profile, _, _ = _voice(db_session, user, "legacy", clips=1)
    for sample in profile.samples:
        db_session.delete(sample)
    db_session.commit()

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    assert f"voice_samples/{profile.id}/0.wav" in archive.namelist()
    [entry] = _json(archive, "voice_profiles.json")
    assert len(entry["clips"]) == 1


def test_an_account_with_no_data_gets_a_valid_empty_archive(client):
    headers = _signup(client)

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    assert _json(archive, "voice_profiles.json") == []
    assert _json(archive, "generations.json") == []
    assert "README.txt" in archive.namelist()


def test_a_ten_clip_profile_exports_every_clip(client, db_session):
    headers = _signup(client)
    user = db_session.query(User).one()
    profile, _, _ = _voice(db_session, user, "wide", clips=10)

    archive = _open(client.post(URL, headers=headers, json={"password": PASSWORD}))

    clips = [
        n for n in archive.namelist() if n.startswith(f"voice_samples/{profile.id}")
    ]
    assert len(clips) == 10


# --- authentication ----------------------------------------------------------


def test_export_needs_a_token(client):
    assert client.post(URL, json={}).status_code == 401


def test_wrong_or_missing_password_is_refused(client):
    headers = _signup(client)

    assert (
        client.post(URL, headers=headers, json={"password": "nope"}).status_code == 403
    )
    assert client.post(URL, headers=headers, json={}).status_code == 403
    assert client.post(URL, headers=headers).status_code == 403


def test_an_overlong_password_is_a_validation_error_not_a_crash(client):
    headers = _signup(client)

    response = client.post(URL, headers=headers, json={"password": "x" * 5000})

    assert response.status_code == 422


def test_a_google_only_account_exports_without_a_password(client, db_session):
    user = User(email="g@example.com", name="Gee", provider="google")
    db_session.add(user)
    db_session.commit()
    token = create_access_token({"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}
    _voice(db_session, user, "g")

    for kwargs in ({}, {"json": {}}):
        response = client.post(URL, headers=headers, **kwargs)
        assert response.status_code == 200
        assert "account.json" in _open(response).namelist()


def test_an_unverified_user_can_still_export(client, monkeypatch):
    headers = _signup(client)
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)

    assert (
        client.post(URL, headers=headers, json={"password": PASSWORD}).status_code
        == 200
    )


def test_repeated_wrong_passwords_lock_the_export(client, fresh_limiter):  # noqa: F811
    headers = _signup(client)

    codes = [
        client.post(URL, headers=headers, json={"password": "nope"}).status_code
        for _ in range(FAILURES)
    ]

    assert codes == [403] * FAILURES
    assert (
        client.post(URL, headers=headers, json={"password": PASSWORD}).status_code
        == 429
    )


# --- operation ---------------------------------------------------------------


def test_a_busy_service_answers_429_with_retry_after(client, monkeypatch):
    headers = _signup(client)
    held = [account_export.EXPORT_SLOTS.acquire(blocking=False) for _ in range(2)]
    try:
        response = client.post(URL, headers=headers, json={"password": PASSWORD})
    finally:
        for ok in held:
            if ok:
                account_export.EXPORT_SLOTS.release()

    assert response.status_code == 429
    assert response.headers["retry-after"] == str(
        account_export.EXPORT_RETRY_AFTER_SECONDS
    )
    # The slots are free again afterwards.
    assert (
        client.post(URL, headers=headers, json={"password": PASSWORD}).status_code
        == 200
    )


def test_the_temp_file_is_removed_after_the_response(client, monkeypatch):
    headers = _signup(client)
    built = []
    real = account_export.build_export

    def spy(db, user):
        path = real(db, user)
        built.append(path)
        return path

    from backend.api import auth

    monkeypatch.setattr(auth, "build_export", spy)

    assert (
        client.post(URL, headers=headers, json={"password": PASSWORD}).status_code
        == 200
    )

    assert len(built) == 1 and not os.path.exists(built[0])


def test_a_failed_build_leaves_no_temp_file_and_frees_the_slot(
    client, db_session, monkeypatch
):
    headers = _signup(client)
    user = db_session.query(User).one()
    _voice(db_session, user, "mine")
    created = []
    real_mkstemp = account_export.tempfile.mkstemp

    def tracking(*args, **kwargs):
        handle, path = real_mkstemp(*args, **kwargs)
        created.append(path)
        return handle, path

    def boom(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(account_export.tempfile, "mkstemp", tracking)
        patched.setattr(account_export, "_add_audio", boom)
        with pytest.raises(OSError):
            client.post(URL, headers=headers, json={"password": PASSWORD})

    assert created and not any(os.path.exists(p) for p in created)
    assert (
        client.post(URL, headers=headers, json={"password": PASSWORD}).status_code
        == 200
    )
