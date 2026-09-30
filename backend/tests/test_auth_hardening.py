"""OAuth-state cookie attributes and the /refresh rate limit (plan item AU-4)."""

import pytest
from fastapi.testclient import TestClient

from backend.main import OAUTH_STATE_MAX_AGE_SECONDS, app, session_cookie_options
from backend.tests.test_rate_limit import (
    _disable_limiter,  # noqa: F401
    _enable_limiter,
    fresh_limiter,
)


@pytest.mark.parametrize("app_env", ["production", "staging", ""])
def test_session_cookie_is_https_only_outside_development(app_env):
    assert session_cookie_options(app_env)["https_only"] is True


def test_session_cookie_allows_plain_http_in_development():
    assert session_cookie_options("development")["https_only"] is False


def test_session_cookie_is_short_lived_and_lax():
    options = session_cookie_options("production")
    assert options["max_age"] == OAUTH_STATE_MAX_AGE_SECONDS <= 900
    assert options["same_site"] == "lax"


def test_the_middleware_actually_uses_those_options():
    """Guard against the options being defined but not applied."""
    layer = next(
        m for m in app.user_middleware if m.cls.__name__ == "SessionMiddleware"
    )
    assert layer.kwargs["max_age"] == OAUTH_STATE_MAX_AGE_SECONDS
    assert layer.kwargs["same_site"] == "lax"
    assert "https_only" in layer.kwargs


def test_google_login_redirect_sets_a_short_lived_session_cookie(
    client: TestClient,
):
    """The real /google redirect carries the state cookie with our attributes."""
    response = client.get("/api/v1/auth/google")
    cookie = response.headers["set-cookie"].lower()
    assert "session=" in cookie
    assert f"max-age={OAUTH_STATE_MAX_AGE_SECONDS}" in cookie
    assert "samesite=lax" in cookie


def test_refresh_is_rate_limited(client: TestClient, fresh_limiter):
    """The 61st renewal attempt in a minute gets 429; the rest are ordinary 401s."""
    codes = [client.post("/api/v1/auth/refresh").status_code for _ in range(61)]
    assert codes[:60] == [401] * 60
    assert codes[60] == 429
