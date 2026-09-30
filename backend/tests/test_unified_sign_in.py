"""One account, two ways in: email/password and Google (plan item AU-1).

Google is mocked at its boundary and mail is captured by the `outbox`
fixture, so nothing here contacts a real service.
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.tests.test_email_verification import (
    PASSWORD,
    _signup,  # noqa: F401
    _token_in,
    _user,
    outbox,
)

EMAIL = "both@example.com"
NEW_PASSWORD = "BrandNewPass456!"


def _google(client: TestClient, email: str = EMAIL):
    """Run the Google callback for an email-verified Google identity."""
    claims = {
        "email": email,
        "email_verified": True,
        "sub": "sub-" + email,
        "name": "Owner",
    }
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": claims},
    ):
        return client.get("/api/v1/auth/google/callback?code=c&state=s")


def _password_login(client: TestClient, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": password}
    )


def _verify_by_email(client: TestClient, outbox) -> None:
    """Complete email verification through the emailed link."""
    token = _token_in(outbox[0])
    resp = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200


def test_verified_local_account_keeps_password_after_google_link(
    client: TestClient, outbox
):
    """The owner already proved the inbox, so Google adds a second way in."""
    _signup(client, EMAIL)
    _verify_by_email(client, outbox)
    assert _password_login(client).status_code == 200

    assert _google(client).status_code == 302

    assert _password_login(client).status_code == 200
    assert _google(client).status_code == 302


def test_verified_link_does_not_revoke_existing_sessions(client: TestClient, outbox):
    """Nothing suspicious happened, so the user's other devices stay signed in."""
    _signup(client, EMAIL)
    _verify_by_email(client, outbox)
    refresh = _password_login(client).cookies.get("refresh_token")
    assert refresh

    _google(client)

    client.cookies.clear()
    client.cookies.set("refresh_token", refresh)
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_unverified_local_account_still_loses_password_on_google_link(
    client: TestClient, outbox
):
    """The squatter defence is unchanged for an address nobody has proven."""
    _signup(client, EMAIL)
    assert _google(client).status_code == 302
    assert _password_login(client).status_code == 401


def test_google_only_account_can_add_a_password(client: TestClient, outbox):
    """Sign in with Google first, then set a password by email."""
    assert _google(client).status_code == 302
    assert _password_login(client).status_code == 401  # no password yet

    client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    assert len(outbox) == 1
    assert "signs in with Google" in outbox[0].get_content()
    token = _token_in(outbox[0])

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 200

    assert _password_login(client, NEW_PASSWORD).status_code == 200
    assert _google(client).status_code == 302  # Google still works


def test_set_password_token_is_single_use(client: TestClient, outbox):
    _google(client)
    client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    token = _token_in(outbox[0])
    body = {"token": token, "new_password": NEW_PASSWORD}
    assert client.post("/api/v1/auth/reset-password", json=body).status_code == 200
    assert client.post("/api/v1/auth/reset-password", json=body).status_code == 400


def test_set_password_enforces_the_password_rules(client: TestClient, outbox):
    _google(client)
    client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": _token_in(outbox[0]), "new_password": "short"},
    )
    assert resp.status_code == 422
    assert _password_login(client, "short").status_code in (401, 422)


def test_signup_with_a_google_accounts_email_is_still_refused(
    client: TestClient, outbox
):
    """Nobody can grab a Google user's address by signing up with it."""
    _google(client)
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": EMAIL, "password": PASSWORD, "name": "Squatter"},
    )
    assert resp.status_code == 409
