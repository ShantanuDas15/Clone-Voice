"""Per-account failure throttle and the API rate limit (SEC-3)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import auth, synthesize, voice
from backend.core.config import Settings, settings
from backend.core.rate_limit import limiter
from backend.tests.test_rate_limit import fresh_limiter  # noqa: F401

PASSWORD = "Password123!"
EMAIL = "victim@example.com"
FAILURES = 10  # AUTH_PASSWORD_FAILURE_LIMIT's default


@pytest.fixture(autouse=True)
def behind_one_proxy(monkeypatch):
    """Let each attempt come from its own IP, so the per-IP limit never fires
    and only the per-account throttle is under test."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)


def _login(client: TestClient, n: int, email: str = EMAIL, password: str = "wrong-pw"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": f"198.51.100.{n}"},
    )


def _signup(client: TestClient, email: str = EMAIL) -> None:
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Vic"},
    )


def test_many_ips_guessing_one_account_get_locked_out(client, fresh_limiter):
    _signup(client)
    codes = [_login(client, n).status_code for n in range(FAILURES)]
    assert codes == [401] * FAILURES

    blocked = _login(client, 99)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_the_right_password_is_refused_while_locked(client, fresh_limiter):
    """Otherwise the lock would only slow guessing down, not stop it."""
    _signup(client)
    for n in range(FAILURES):
        _login(client, n)
    assert _login(client, 99, password=PASSWORD).status_code == 429


def test_the_lock_is_per_account(client, fresh_limiter):
    _signup(client)
    _signup(client, "other@example.com")
    for n in range(FAILURES):
        _login(client, n)
    assert _login(client, 99, "other@example.com", PASSWORD).status_code == 200


def test_an_unknown_address_is_throttled_like_a_real_one(client, fresh_limiter):
    """No 'locked' answer for real accounts only: that would reveal them."""
    codes = [_login(client, n, "nobody@example.com").status_code for n in range(11)]
    assert codes == [401] * FAILURES + [429]


def test_the_address_case_does_not_give_a_fresh_allowance(client, fresh_limiter):
    _signup(client)
    for n in range(FAILURES):
        _login(client, n, email=EMAIL.upper())
    assert _login(client, 99, email=EMAIL).status_code == 429


def test_a_successful_login_resets_the_count(client, fresh_limiter):
    _signup(client)
    for n in range(FAILURES - 1):
        _login(client, n)
    assert _login(client, 50, password=PASSWORD).status_code == 200
    # A full allowance again: nine more failures still do not lock.
    assert [_login(client, 60 + n).status_code for n in range(FAILURES - 1)] == [
        401
    ] * (FAILURES - 1)


def test_the_raw_address_never_reaches_the_rate_limit_store(client, fresh_limiter):
    _signup(client)
    _login(client, 1)
    keys = " ".join(map(str, limiter._storage.storage.keys()))
    assert "password-failures" in keys
    assert "victim" not in keys and "example.com" not in keys


def test_nothing_is_throttled_when_the_limiter_is_off(client):
    _signup(client)
    assert {_login(client, n).status_code for n in range(FAILURES + 5)} == {401}


# --- account erasure shares the guard ----------------------------------------


def test_repeated_wrong_passwords_lock_account_erasure(client, fresh_limiter):
    _signup(client)
    token = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    def erase(password):
        return client.request(
            "DELETE", "/api/v1/auth/me", headers=headers, json={"password": password}
        )

    assert [erase("nope").status_code for _ in range(FAILURES)] == [403] * FAILURES
    assert erase(PASSWORD).status_code == 429
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


# --- API_RATE_LIMIT ----------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        auth.logout,
        auth.get_me,
        auth.update_me,
        auth.google_login,
        auth.google_callback,
        voice.get_profiles,
        voice.delete_profile,
        synthesize.get_history,
    ],
)
def test_every_ordinary_endpoint_is_rate_limited(endpoint):
    assert f"{endpoint.__module__}.{endpoint.__name__}" in limiter._route_limits


def test_history_is_throttled_after_the_api_limit(client, fresh_limiter):
    _signup(client)
    token = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    limit = int(settings.API_RATE_LIMIT.split("/")[0])

    codes = [
        client.get("/api/v1/synthesize/history", headers=headers).status_code
        for _ in range(limit + 1)
    ]
    assert codes[:limit] == [200] * limit
    assert codes[limit] == 429


# --- configuration -----------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL=settings.DATABASE_URL,
        JWT_SECRET_KEY=settings.JWT_SECRET_KEY,
        **overrides,
    )


@pytest.mark.parametrize(
    "name", ["AUTH_PASSWORD_FAILURE_LIMIT", "API_RATE_LIMIT", "AUTH_LOGIN_RATE_LIMIT"]
)
@pytest.mark.parametrize("value", ["", "lots", "10/fortnight"])
def test_a_malformed_limit_fails_at_startup(name, value):
    with pytest.raises(ValidationError, match="not a valid rate limit"):
        _settings(**{name: value})


def test_a_well_formed_limit_is_accepted():
    assert _settings(AUTH_PASSWORD_FAILURE_LIMIT="3/hour").AUTH_PASSWORD_FAILURE_LIMIT
