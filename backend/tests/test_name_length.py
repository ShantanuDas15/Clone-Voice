"""HARDENING_PLAN.md P2-L1: `name` inputs are bounded to the String(255) columns."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.tests.test_voice import (auth_headers,  # noqa: F401
                                      create_dummy_wav)

MAX_NAME = 255


def _signup(client: TestClient, name: str):
    """POST a signup with the given display name."""
    return client.post(
        "/api/v1/auth/signup",
        json={"email": "len@example.com", "password": "Password123!", "name": name},
    )


def _upload(client: TestClient, headers: dict, name: str):
    """POST a valid WAV upload with the given profile name."""
    files = {"file": ("t.wav", create_dummy_wav(), "audio/wav")}
    return client.post(
        "/api/v1/voice/upload", headers=headers, data={"name": name}, files=files
    )


@pytest.mark.parametrize("name", ["", "x" * (MAX_NAME + 1)])
def test_signup_rejects_out_of_bounds_name(client: TestClient, name: str):
    """Empty and over-length signup names are rejected with 422."""
    assert _signup(client, name).status_code == 422


def test_signup_accepts_name_at_limit(client: TestClient):
    """A 255-character signup name is accepted."""
    assert _signup(client, "x" * MAX_NAME).status_code == 201


@pytest.mark.parametrize("name", ["", "x" * (MAX_NAME + 1)])
def test_upload_rejects_out_of_bounds_name_before_saving(
    client: TestClient, auth_headers, name: str  # noqa: F811
):
    """Bad upload names get 422 before any file is saved or inference runs."""
    with patch("backend.api.voice.save_upload") as save, patch(
        "backend.api.voice.embed_speaker_async"
    ) as embed:
        resp = _upload(client, auth_headers, name)
    assert resp.status_code == 422
    save.assert_not_called()
    embed.assert_not_called()


def test_upload_accepts_name_at_limit(client: TestClient, auth_headers):  # noqa: F811
    """A 255-character upload name is accepted."""
    resp = _upload(client, auth_headers, "x" * MAX_NAME)
    assert resp.status_code == 201
    assert resp.json()["name"] == "x" * MAX_NAME
