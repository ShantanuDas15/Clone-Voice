"""Integration tests verifying that rate limiting is correctly enforced.

All rate limit tests:
1. Enable the limiter (disabled globally by conftest.py) INSIDE the try block.
2. Exercise the endpoint until the limit fires.
3. Always disable in a ``finally`` block to avoid cross-test pollution.

Storage is NOT cleared between tests — it is naturally empty because the
limiter is disabled (``_enabled=False``) for all other tests, so no requests
ever increment the counters before these tests run.  After these tests the
limiter is disabled again, so stale counter data is irrelevant.

The TestClient presents ``host = "testclient"`` for every request, so all
requests in a session share the same rate-limit bucket per endpoint.

Note on slowapi response body: the built-in ``_rate_limit_exceeded_handler``
returns ``{"error": "Rate limit exceeded: ..."}`` — the key is ``"error"``,
not ``"detail"`` (unlike standard FastAPI HTTPException responses).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signup_and_token(client: TestClient, email: str) -> dict:
    """Create a user account and return Bearer auth headers."""
    client.post(
        "/api/auth/signup",
        json={"email": email, "password": "Password123!", "name": "RL Test"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _enable_limiter() -> None:
    """Enable the rate limiter."""
    app.state.limiter.enabled = True


def _disable_limiter() -> None:
    """Disable the rate limiter."""
    app.state.limiter.enabled = False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_rate_limit_disabled_in_tests_by_default():
    """Limiter must be disabled by conftest.py so existing tests cannot trip it.

    This test runs *without* enabling the limiter — it just checks the flag
    that conftest sets at module scope.
    """
    assert app.state.limiter.enabled is False, (
        "Rate limiter should be disabled for the test suite by default. "
        "Check conftest.py — app.state.limiter.enabled = False must be present."
    )


def test_synthesize_rate_limit_enforced(client: TestClient):
    """POST /api/synthesize must return HTTP 429 after 5 requests per minute.

    Strategy: send 6 requests with valid auth but a random (non-existent)
    voice_profile_id.  Requests 1–5 return 404 (profile not found — the route
    handler executes after the rate limit is counted).  Request 6 must return
    429 — the limiter fires before the route handler, so no inference runs.

    The limiter is enabled inside the try block so the finally clause is
    guaranteed to disable it regardless of any assertion failure.
    """
    headers = _signup_and_token(client, "rl_synth@example.com")
    body = {
        "voice_profile_id": str(uuid.uuid4()),
        "text": "Rate limit test payload",
    }

    try:
        _enable_limiter()
        responses = [
            client.post("/api/synthesize", headers=headers, json=body) for _ in range(6)
        ]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, (
            f"Expected a 429 Too Many Requests after 5 synthesize calls. "
            f"Got status codes: {status_codes}"
        )
        # Verify the 429 body uses slowapi's 'error' key (not 'detail')
        last_429 = next(r for r in responses if r.status_code == 429)
        body_json = last_429.json()
        assert (
            "error" in body_json
        ), f"429 response body should contain 'error' key: {body_json}"
    finally:
        _disable_limiter()


def test_voice_upload_rate_limit_enforced(client: TestClient):
    """POST /api/voice/upload must return HTTP 429 after 10 requests per minute.

    Strategy: send 11 requests with valid auth and a minimal WAV file.
    Requests 1–10 will return 4xx (audio too short / validation error).
    Request 11 must return 429 — the limiter fires before validation.

    The limiter is enabled inside the try block so the finally clause is
    guaranteed to disable it regardless of any assertion failure.
    """
    headers = _signup_and_token(client, "rl_upload@example.com")

    try:
        _enable_limiter()
        responses = []
        for _ in range(11):
            resp = client.post(
                "/api/voice/upload",
                headers=headers,
                data={"name": "RL Upload"},
                files={"file": ("test.wav", b"\x00", "audio/wav")},
            )
            responses.append(resp)

        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, (
            f"Expected a 429 Too Many Requests after 10 upload calls. "
            f"Got status codes: {status_codes}"
        )
        last_429 = next(r for r in responses if r.status_code == 429)
        body_json = last_429.json()
        assert (
            "error" in body_json
        ), f"429 response body should contain 'error' key: {body_json}"
    finally:
        _disable_limiter()
