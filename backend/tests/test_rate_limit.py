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
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "RL Test"},
    )
    resp = client.post(
        "/api/v1/auth/login",
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
    """POST /api/v1/synthesize must return HTTP 429 after 5 requests per minute.

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
            client.post("/api/v1/synthesize", headers=headers, json=body)
            for _ in range(6)
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
    """POST /api/v1/voice/upload must return HTTP 429 after 10 requests per minute.

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
                "/api/v1/voice/upload",
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


# ---------------------------------------------------------------------------
# HARDENING_PLAN.md finding M3: auth endpoints, shared storage, proxy-aware key
# ---------------------------------------------------------------------------

from pathlib import Path
from unittest.mock import patch

import yaml
from starlette.requests import Request

from backend.core import rate_limit
from backend.core.config import settings


def _request(peer: str = "10.0.0.9", xff: str | None = None) -> Request:
    """Build a bare Starlette request with a socket peer and optional XFF."""
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request(
        {"type": "http", "headers": headers, "client": (peer, 1234)},
    )


@pytest.fixture
def fresh_limiter():
    """Enable the limiter with empty counters; always disable and reset after."""
    app.state.limiter.reset()
    _enable_limiter()
    yield app.state.limiter
    _disable_limiter()
    app.state.limiter.reset()


def test_login_rate_limit_enforced(client: TestClient, fresh_limiter):
    """POST /login returns 429 on the 11th attempt/minute, even for bad creds."""
    codes = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "Wrong-pass-1"},
        ).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_signup_rate_limit_enforced(client: TestClient, fresh_limiter):
    """POST /signup returns 429 on the 6th attempt/minute."""
    codes = [
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"rl_signup_{i}@example.com",
                "password": "Password123!",
                "name": "RL",
            },
        ).status_code
        for i in range(6)
    ]
    assert codes[:5] == [201] * 5
    assert codes[5] == 429


def test_auth_limits_are_per_client_behind_trusted_proxy(
    client: TestClient, fresh_limiter, monkeypatch
):
    """With one trusted proxy, distinct X-Forwarded-For clients get own buckets."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    body = {"email": "nobody@example.com", "password": "Wrong-pass-1"}

    def attempt(ip: str) -> int:
        return client.post(
            "/api/v1/auth/login", json=body, headers={"X-Forwarded-For": ip}
        ).status_code

    assert [attempt("203.0.113.1") for _ in range(11)][-1] == 429
    assert attempt("203.0.113.2") == 401  # a different client is unaffected


def test_client_ip_ignores_forwarded_for_without_trusted_proxy(monkeypatch):
    """Default (0 proxies): a spoofed X-Forwarded-For must not change the key."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 0)
    assert rate_limit.get_client_ip(_request(xff="1.2.3.4")) == "10.0.0.9"


@pytest.mark.parametrize(
    "proxies, xff, expected",
    [
        (1, "198.51.100.7", "198.51.100.7"),
        # Client-injected left-most entries are ignored; last hop is trusted.
        (1, "6.6.6.6, 198.51.100.7", "198.51.100.7"),
        (2, "6.6.6.6, 198.51.100.7, 10.1.1.1", "198.51.100.7"),
        # Header missing/shorter than the proxy chain → fall back to the peer.
        (1, None, "10.0.0.9"),
        (2, "198.51.100.7", "10.0.0.9"),
        (1, "", "10.0.0.9"),
    ],
)
def test_client_ip_with_trusted_proxies(monkeypatch, proxies, xff, expected):
    """Key is the hop written by the outermost trusted proxy, never client text."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", proxies)
    assert rate_limit.get_client_ip(_request(xff=xff)) == expected


def test_build_limiter_uses_configured_storage_uri(monkeypatch):
    """The shared storage URI and proxy-aware key func reach the Limiter."""
    monkeypatch.setattr(settings, "RATE_LIMIT_STORAGE_URI", "redis://cache:6379/2")
    with patch.object(rate_limit, "Limiter") as limiter_cls:
        rate_limit.build_limiter()
    kwargs = limiter_cls.call_args.kwargs
    assert kwargs["storage_uri"] == "redis://cache:6379/2"
    assert kwargs["key_func"] is rate_limit.get_client_ip


def test_default_storage_uri_is_in_memory():
    """Unconfigured dev/test environments keep working without Redis."""
    assert settings.RATE_LIMIT_STORAGE_URI == "memory://"


def test_compose_wires_backend_to_shared_redis():
    """docker-compose provides Redis and points the backend's limiter at it."""
    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    )
    assert "redis" in compose["services"]
    assert "ports" not in compose["services"]["redis"]  # not host-exposed
    backend = compose["services"]["backend"]
    assert backend["environment"]["RATE_LIMIT_STORAGE_URI"].startswith("redis://redis")
    assert "redis" in backend["depends_on"]
