from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.tests.test_voice import auth_headers  # noqa: F401  (pytest fixture)
from backend.tests.test_voice import create_dummy_wav


def _upload(client: TestClient, headers, **extra):
    """POST a valid sample with consent, plus any extra form fields."""
    return client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "Terms Voice", "consent_confirmed": "true", **extra},
        files={"file": ("t.wav", create_dummy_wav(), "audio/wav")},
    )


def test_terms_endpoint_is_public_and_returns_version(client: TestClient) -> None:
    """No auth needed: a signed-out visitor can read what they would accept."""
    with patch("backend.core.config.settings.TERMS_VERSION", "2099-01-01"):
        response = client.get("/api/v1/terms")
    assert response.status_code == 200
    assert response.json() == {"version": "2099-01-01", "url": None}


def test_terms_endpoint_returns_configured_url(client: TestClient) -> None:
    with patch("backend.core.config.settings.TERMS_URL", "https://example.com/terms"):
        response = client.get("/api/v1/terms")
    assert response.json()["url"] == "https://example.com/terms"


def test_upload_with_matching_terms_version_succeeds(
    client: TestClient, auth_headers
) -> None:
    current = client.get("/api/v1/terms").json()["version"]
    response = _upload(client, auth_headers, terms_version=current)
    assert response.status_code == 201
    assert response.json()["terms_version"] == current


def test_upload_with_stale_terms_version_is_rejected(
    client: TestClient, auth_headers, db_session
) -> None:
    """A client that showed an old version must re-confirm, and no row or
    file work happens for it."""
    from backend.models.voice_profile import VoiceProfile

    response = _upload(client, auth_headers, terms_version="1999-01-01")
    assert response.status_code == 409
    assert "changed" in response.json()["detail"]
    assert db_session.query(VoiceProfile).count() == 0


def test_upload_without_terms_version_records_current(
    client: TestClient, auth_headers
) -> None:
    """Omitting the field stays accepted and records the version in force."""
    response = _upload(client, auth_headers)
    assert response.status_code == 201
    assert response.json()["terms_version"]


def test_overlong_terms_version_is_rejected(client: TestClient, auth_headers) -> None:
    assert _upload(client, auth_headers, terms_version="x" * 51).status_code == 422
