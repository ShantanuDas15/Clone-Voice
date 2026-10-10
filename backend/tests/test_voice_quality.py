"""The upload response reports recording quality (SPEECH_QUALITY_PLAN.md S2.2)."""

import io
import wave
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

SR = 16000


@pytest.fixture
def auth_headers(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "quality@example.com", "password": "Password123!", "name": "Q"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "quality@example.com", "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _wav(y: np.ndarray) -> bytes:
    samples = (np.clip(y, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(samples.tobytes())
    return buf.getvalue()


def _voice(seconds=12.0, amp=0.3) -> np.ndarray:
    """Phrase-like bursts of a voice with harmonics up to 7 kHz."""
    t = np.arange(int(SR * seconds)) / SR
    carrier = sum(np.sin(2 * np.pi * 180 * k * t) / k for k in range(1, 39))
    envelope = (np.sin(2 * np.pi * 1.5 * t) > -0.2).astype(np.float64)
    y = carrier * envelope
    return amp * y / np.max(np.abs(y))


def _upload(client, headers, y, name="Voice"):
    return client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": name, "consent_confirmed": "true"},
        files={"file": ("s.wav", _wav(y), "audio/wav")},
    )


def test_a_clean_upload_reports_a_good_rating_and_its_measures(client, auth_headers):
    response = _upload(client, auth_headers, _voice())
    assert response.status_code == 201
    quality = response.json()["quality"]
    assert quality["rating"] == "good"
    assert quality["hints"] == []
    assert set(quality["measures"]) == {
        "voiced_seconds",
        "snr_db",
        "clipping_ratio",
        "high_band_db",
        "level_dbfs",
    }
    assert quality["measures"]["voiced_seconds"] > 5


def test_a_noisy_distorted_upload_still_succeeds_and_says_what_to_fix(
    client, auth_headers
):
    rng = np.random.default_rng(0)
    noisy = np.clip(_voice() * 40, -1, 1) + 0.2 * rng.standard_normal(SR * 12)
    response = _upload(client, auth_headers, noisy)
    assert response.status_code == 201  # advice, never a rejection
    assert response.json()["status"] == "ready"
    quality = response.json()["quality"]
    codes = {h["code"] for h in quality["hints"]}
    assert "very_distorted" in codes
    assert quality["rating"] == "poor"
    assert all(h["message"] for h in quality["hints"])


def test_a_short_clip_gets_the_length_advice(client, auth_headers):
    response = _upload(client, auth_headers, _voice(seconds=4.0))
    assert response.status_code == 201
    assert "short" in {h["code"] for h in response.json()["quality"]["hints"]}


def test_a_failed_assessment_never_costs_the_user_their_profile(client, auth_headers):
    with patch(
        "backend.api.voice.assess_file", side_effect=RuntimeError("decoder blew up")
    ):
        response = _upload(client, auth_headers, _voice())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready" and body["quality"] is None
    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    assert [p["id"] for p in profiles] == [body["id"]]


def test_the_profile_list_does_not_carry_a_quality_report(client, auth_headers):
    _upload(client, auth_headers, _voice())
    profiles = client.get("/api/v1/voice/profiles", headers=auth_headers).json()
    assert len(profiles) == 1 and "quality" not in profiles[0]


def test_the_existing_profile_fields_are_unchanged(client, auth_headers):
    body = _upload(client, auth_headers, _voice()).json()
    assert {
        "id",
        "name",
        "status",
        "consent_confirmed_at",
        "terms_version",
        "created_at",
    } <= set(body)
