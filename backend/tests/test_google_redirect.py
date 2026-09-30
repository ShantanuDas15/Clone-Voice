"""The Google callback is a browser navigation: it redirects, never returns JSON."""

from unittest.mock import AsyncMock, patch

import pytest
from authlib.integrations.starlette_client import OAuthError
from fastapi.testclient import TestClient

from backend.core.config import settings


def _callback(client: TestClient, user_info=None, error=None):
    """Hit the callback with Google mocked at its boundary."""
    kwargs = (
        {"side_effect": error} if error else {"return_value": {"userinfo": user_info}}
    )
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        **kwargs,
    ):
        return client.get("/api/v1/auth/google/callback?code=c&state=s")


GOOD = {
    "email": "redir@example.com",
    "email_verified": True,
    "sub": "sub-redir",
    "name": "R",
}


def test_success_redirects_into_the_web_app_with_a_cookie(client: TestClient):
    response = _callback(client, GOOD)
    assert response.status_code == 302
    assert response.headers["location"] == f"{settings.FRONTEND_URL}/auth/callback"
    assert response.cookies.get("refresh_token")


def test_success_puts_no_token_in_the_url(client: TestClient):
    location = _callback(client, GOOD).headers["location"]
    assert "?" not in location
    assert "token" not in location


def test_success_cookie_is_httponly_and_secure(client: TestClient):
    cookie = _callback(client, GOOD).headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie


def test_redirect_is_not_cacheable(client: TestClient):
    assert _callback(client, GOOD).headers["cache-control"] == "no-store"


def test_frontend_url_trailing_slash_is_normalised(client: TestClient):
    with patch.object(settings, "FRONTEND_URL", "https://app.example.com/"):
        location = _callback(client, GOOD).headers["location"]
    assert location == "https://app.example.com/auth/callback"


@pytest.mark.parametrize(
    "user_info,code",
    [
        ({"email_verified": True}, "google_no_email"),
        (
            {"email": "a@example.com", "email_verified": False},
            "google_email_unverified",
        ),
    ],
)
def test_rejections_redirect_to_login_with_an_error_code(
    client: TestClient, user_info, code
):
    response = _callback(client, user_info)
    assert response.status_code == 302
    assert response.headers["location"] == f"{settings.FRONTEND_URL}/login?error={code}"
    assert "refresh_token" not in response.cookies


def test_oauth_error_redirects_to_login(client: TestClient):
    response = _callback(client, error=OAuthError(error="access_denied"))
    assert response.headers["location"].endswith("/login?error=google_failed")


def test_unexpected_error_redirects_without_leaking_details(client: TestClient):
    response = _callback(client, error=RuntimeError("secret internal detail"))
    assert response.headers["location"].endswith("/login?error=google_failed")
    assert "secret" not in response.headers["location"]


def test_redirect_target_ignores_request_input(client: TestClient):
    """No parameter on the callback can steer the redirect (no open redirect)."""
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": GOOD},
    ):
        response = client.get(
            "/api/v1/auth/google/callback?code=c&state=s"
            "&next=https://evil.example&redirect_uri=https://evil.example"
        )
    assert response.headers["location"].startswith(settings.FRONTEND_URL)
