"""FE-1: replaying past generations and CORS header exposure for the web app."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.models.generation import Generation
from backend.services.tts_pipeline import load_mock_models
from backend.tests.test_synthesize import upload_profile

ORIGIN = "http://localhost:3000"


@pytest.fixture(scope="module", autouse=True)
def mock_models():
    """Inject lightweight mock models once for this module."""
    load_mock_models("cpu")


def _sign_in(client: TestClient, email: str) -> dict:
    """Sign up and log in a user; return its auth headers."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "Audio User"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def headers(client: TestClient) -> dict:
    """Auth headers for the primary test user."""
    return _sign_in(client, "audio@example.com")


def _synthesize(client: TestClient, headers: dict, text: str = "Replay me"):
    """Create a profile and one generation; return (profile_id, response)."""
    profile_id = upload_profile(client, headers)
    res = client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile_id, "text": text},
    )
    assert res.status_code == 200
    return profile_id, res


def _latest(client: TestClient, headers: dict) -> dict:
    """The newest history item."""
    return client.get("/api/v1/synthesize/history", headers=headers).json()[0]


def test_audio_matches_the_original_synthesis(client, headers):
    _, created = _synthesize(client, headers)
    item = _latest(client, headers)

    res = client.get(f"/api/v1/synthesize/{item['id']}/audio", headers=headers)

    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert res.content == created.content
    assert item["id"] in res.headers["content-disposition"]


def test_history_reports_audio_available(client, headers):
    _synthesize(client, headers)
    assert _latest(client, headers)["audio_available"] is True


def test_audio_requires_authentication(client, headers):
    _synthesize(client, headers)
    item = _latest(client, headers)
    assert client.get(f"/api/v1/synthesize/{item['id']}/audio").status_code == 401


def test_audio_rejects_a_non_uuid_id(client, headers):
    res = client.get("/api/v1/synthesize/not-a-uuid/audio", headers=headers)
    assert res.status_code == 422


def test_audio_unknown_id_is_404(client, headers):
    res = client.get(f"/api/v1/synthesize/{uuid.uuid4()}/audio", headers=headers)
    assert res.status_code == 404


def test_audio_of_another_users_generation_is_404(client, headers):
    _synthesize(client, headers)
    item = _latest(client, headers)
    other = _sign_in(client, "intruder@example.com")

    res = client.get(f"/api/v1/synthesize/{item['id']}/audio", headers=other)

    assert res.status_code == 404


def test_audio_of_a_soft_deleted_generation_is_404(client, headers):
    profile_id, _ = _synthesize(client, headers)
    item = _latest(client, headers)
    client.delete(f"/api/v1/voice/profiles/{profile_id}", headers=headers)

    res = client.get(f"/api/v1/synthesize/{item['id']}/audio", headers=headers)

    assert res.status_code == 404


def test_audio_of_a_failed_generation_is_404(client, headers, db_session):
    profile_id, _ = _synthesize(client, headers)
    item = _latest(client, headers)
    row = db_session.get(Generation, uuid.UUID(item["id"]))
    row.status = "failed"
    row.output_audio_path = None
    db_session.commit()

    res = client.get(f"/api/v1/synthesize/{item['id']}/audio", headers=headers)

    assert res.status_code == 404
    assert _latest(client, headers)["audio_available"] is False


def test_pruned_file_is_410_and_flagged_unavailable(client, headers, db_session):
    _synthesize(client, headers)
    item = _latest(client, headers)
    row = db_session.get(Generation, uuid.UUID(item["id"]))
    os.remove(row.output_audio_path)

    res = client.get(f"/api/v1/synthesize/{item['id']}/audio", headers=headers)

    assert res.status_code == 410
    assert _latest(client, headers)["audio_available"] is False


def test_path_outside_output_dir_is_never_served(client, headers, db_session, tmp_path):
    _synthesize(client, headers)
    item = _latest(client, headers)
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"RIFF....WAVEnot-an-output")
    row = db_session.get(Generation, uuid.UUID(item["id"]))
    row.output_audio_path = str(outside)
    db_session.commit()

    res = client.get(f"/api/v1/synthesize/{item['id']}/audio", headers=headers)

    assert res.status_code == 410
    assert b"not-an-output" not in res.content
    assert _latest(client, headers)["audio_available"] is False


def test_cors_exposes_headers_the_web_app_reads(client, headers):
    _synthesize(client, headers)
    item = _latest(client, headers)
    res = client.get(
        f"/api/v1/synthesize/{item['id']}/audio",
        headers={**headers, "Origin": ORIGIN},
    )
    assert res.status_code == 200
    exposed = {
        h.strip().lower()
        for h in res.headers["access-control-expose-headers"].split(",")
    }
    assert {"content-disposition", "x-request-id", "retry-after"} <= exposed
