"""D1: deleting one generation (GENERATION_DELETE_PLAN.md): audio file and typed text."""

import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from backend.models.generation import Generation
from backend.services import erasure
from backend.services.tts_pipeline import load_mock_models
from backend.tests.test_synthesize import upload_profile


@pytest.fixture(scope="module", autouse=True)
def mock_models():
    """Inject lightweight mock models once for this module."""
    load_mock_models("cpu")


def _sign_in(client: TestClient, email: str) -> dict:
    """Sign up and log in a user; return its auth headers."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "Delete User"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def headers(client: TestClient) -> dict:
    """Auth headers for the primary test user."""
    return _sign_in(client, "deleter@example.com")


def _generate(client: TestClient, headers: dict, profile_id: str, text: str) -> str:
    """Synthesize once; return the new generation's id.

    Found by diffing the history, not by position: two rows made in the same second tie on
    ``created_at``, so "the newest" is ambiguous.
    """
    before = {
        i["id"]
        for i in client.get("/api/v1/synthesize/history", headers=headers).json()
    }
    res = client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile_id, "text": text},
    )
    assert res.status_code == 200
    after = client.get("/api/v1/synthesize/history", headers=headers).json()
    (new,) = [i["id"] for i in after if i["id"] not in before]
    return new


@pytest.fixture
def made(client, headers, db_session):
    """A profile with one generation: (profile_id, generation_id, output path)."""
    profile_id = upload_profile(client, headers)
    generation_id = _generate(client, headers, profile_id, "Delete me please")
    row = db_session.get(Generation, uuid.UUID(generation_id))
    assert os.path.isfile(row.output_audio_path)
    return profile_id, generation_id, row.output_audio_path


def _delete(client, headers, generation_id):
    return client.delete(f"/api/v1/synthesize/{generation_id}", headers=headers)


def _history(client, headers):
    res = client.get("/api/v1/synthesize/history", headers=headers)
    return res.json(), int(res.headers["X-Total-Count"])


# --- unit: erase_generation -------------------------------------------------------------


def _row(**over) -> Generation:
    base = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        voice_profile_id=uuid.uuid4(),
        input_text="private words",
        output_audio_path="/data/outputs/u/a.wav",
        status="completed",
    )
    return Generation(**{**base, **over})


def test_erase_generation_scrubs_the_row_and_returns_the_file():
    row = _row()
    files = erasure.erase_generation(None, row)
    assert files == ["/data/outputs/u/a.wav"]
    assert row.input_text == erasure.ERASED_TEXT
    assert row.output_audio_path is None
    assert row.deleted_at is not None


def test_erase_generation_without_audio_returns_nothing_but_still_scrubs():
    row = _row(output_audio_path=None, status="failed")
    assert erasure.erase_generation(None, row) == []
    assert row.input_text == erasure.ERASED_TEXT
    assert row.deleted_at is not None


def test_erase_generation_on_an_already_deleted_row_changes_nothing():
    row = _row()
    erasure.erase_generation(None, row)
    stamp = row.deleted_at
    assert erasure.erase_generation(None, row) == []
    assert row.deleted_at == stamp


# --- integration ------------------------------------------------------------------------


def test_delete_removes_the_file_and_scrubs_the_row(client, headers, made, db_session):
    _, generation_id, path = made

    res = _delete(client, headers, generation_id)

    assert res.status_code == 204
    assert res.content == b""
    assert not os.path.exists(path)
    row = db_session.get(Generation, uuid.UUID(generation_id))
    db_session.refresh(row)
    assert row.deleted_at is not None
    assert row.input_text == erasure.ERASED_TEXT
    assert row.output_audio_path is None


def test_history_and_its_total_drop_the_deleted_generation(client, headers, made):
    profile_id, generation_id, _ = made
    keep_id = _generate(client, headers, profile_id, "Keep me")
    items, total = _history(client, headers)
    assert total == 2

    assert _delete(client, headers, generation_id).status_code == 204

    items, total = _history(client, headers)
    assert total == 1
    assert [item["id"] for item in items] == [keep_id]
    assert items[0]["input_text"] == "Keep me"
    assert items[0]["audio_available"] is True


def test_the_audio_of_a_deleted_generation_is_404(client, headers, made):
    _, generation_id, _ = made
    _delete(client, headers, generation_id)
    res = client.get(f"/api/v1/synthesize/{generation_id}/audio", headers=headers)
    assert res.status_code == 404


def test_deleting_twice_is_404(client, headers, made):
    _, generation_id, _ = made
    assert _delete(client, headers, generation_id).status_code == 204
    assert _delete(client, headers, generation_id).status_code == 404


def test_unknown_id_is_404(client, headers):
    assert _delete(client, headers, uuid.uuid4()).status_code == 404


def test_another_users_generation_is_404_and_their_file_survives(client, headers, made):
    _, generation_id, path = made
    intruder = _sign_in(client, "intruder-delete@example.com")

    assert _delete(client, intruder, generation_id).status_code == 404

    assert os.path.isfile(path)
    items, total = _history(client, headers)
    assert total == 1 and items[0]["id"] == generation_id


def test_a_malformed_id_is_422(client, headers):
    res = client.delete("/api/v1/synthesize/not-a-uuid", headers=headers)
    assert res.status_code == 422


def test_deleting_requires_authentication(client, made):
    _, generation_id, path = made
    res = client.delete(f"/api/v1/synthesize/{generation_id}")
    assert res.status_code == 401
    assert os.path.isfile(path)


def test_a_failed_generation_without_audio_can_be_deleted(
    client, headers, made, db_session
):
    _, generation_id, path = made
    row = db_session.get(Generation, uuid.UUID(generation_id))
    os.remove(path)
    row.status = "failed"
    row.output_audio_path = None
    db_session.commit()

    assert _delete(client, headers, generation_id).status_code == 204

    db_session.refresh(row)
    assert row.deleted_at is not None
    assert row.input_text == erasure.ERASED_TEXT


def test_a_file_already_gone_from_disk_still_gives_204(client, headers, made):
    _, generation_id, path = made
    os.remove(path)  # pruned by retention before the user got here
    assert _delete(client, headers, generation_id).status_code == 204
    assert _history(client, headers)[1] == 0


def test_a_path_outside_storage_is_never_removed(
    client, headers, made, db_session, tmp_path
):
    _, generation_id, _ = made
    outside = tmp_path / "elsewhere" / "keep.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"RIFF....WAVEnot-ours")
    row = db_session.get(Generation, uuid.UUID(generation_id))
    row.output_audio_path = str(outside)
    db_session.commit()

    assert _delete(client, headers, generation_id).status_code == 204

    assert outside.exists()  # the row is erased, a file outside storage is left alone


def test_an_empty_output_path_is_handled(client, headers, made, db_session):
    _, generation_id, _ = made
    row = db_session.get(Generation, uuid.UUID(generation_id))
    row.output_audio_path = ""
    db_session.commit()
    assert _delete(client, headers, generation_id).status_code == 204


def test_other_generations_of_the_same_voice_are_untouched(
    client, headers, made, db_session
):
    profile_id, generation_id, _ = made
    keep_id = _generate(client, headers, profile_id, "Still here")
    keep_path = db_session.get(Generation, uuid.UUID(keep_id)).output_audio_path

    _delete(client, headers, generation_id)

    assert os.path.isfile(keep_path)
    res = client.get(f"/api/v1/synthesize/{keep_id}/audio", headers=headers)
    assert res.status_code == 200


def test_the_voice_can_be_deleted_afterwards(client, headers, made, db_session):
    profile_id, generation_id, _ = made
    keep_id = _generate(client, headers, profile_id, "Second one")
    keep_path = db_session.get(Generation, uuid.UUID(keep_id)).output_audio_path
    _delete(client, headers, generation_id)

    res = client.delete(f"/api/v1/voice/profiles/{profile_id}", headers=headers)

    assert res.status_code == 200
    assert not os.path.exists(
        keep_path
    )  # the voice still takes the remaining clips with it
    db_session.expire_all()
    deleted = db_session.get(Generation, uuid.UUID(generation_id))
    assert (
        deleted.input_text == erasure.ERASED_TEXT
    )  # not resurrected or double-handled


def test_an_unverified_user_can_still_delete_their_own_generation(
    client, headers, made, db_session
):
    """Removing your own data is never gated on email state (the route takes no verified check)."""
    from backend.models.user import User

    _, generation_id, _ = made
    user = db_session.query(User).filter(User.email == "deleter@example.com").one()
    user.email_verified_at = None
    db_session.commit()

    assert _delete(client, headers, generation_id).status_code == 204


# --- failure paths ----------------------------------------------------------------------


def test_a_failed_commit_removes_no_file_and_answers_503(
    client, headers, made, db_session
):
    _, generation_id, path = made
    failure = OperationalError("stmt", {}, Exception("connection lost"))
    with patch.object(db_session, "commit", side_effect=failure), patch.object(
        db_session, "rollback"
    ) as rollback:
        res = _delete(client, headers, generation_id)

    assert res.status_code == 503
    assert "Retry-After" in res.headers
    rollback.assert_called_once()
    assert os.path.isfile(path)  # nothing deleted because nothing was committed


def test_another_database_error_answers_500_and_keeps_the_file(
    client, headers, made, db_session
):
    _, generation_id, path = made
    with patch.object(
        db_session, "commit", side_effect=SQLAlchemyError("boom")
    ), patch.object(db_session, "rollback"):
        res = _delete(client, headers, generation_id)

    assert res.status_code == 500
    assert res.json()["detail"] == "Failed to delete the generation"
    assert os.path.isfile(path)
