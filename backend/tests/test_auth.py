import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
    assert all(model["loaded"] for model in body["models"].values())


def test_signup_success(client: TestClient):
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_signup_duplicate_email(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    assert response.status_code == 409


def test_signup_duplicate_email_does_not_log_raw_email(client: TestClient, caplog):
    """HARDENING_PLAN.md finding L10: the rejection log must carry the
    existing user's id, never the raw (PII) email address."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "duplicate-signup@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    with caplog.at_level("WARNING", logger="backend.api.auth"):
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "duplicate-signup@example.com",
                "password": "Password123!",
                "name": "Test User",
            },
        )

    assert response.status_code == 409
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "duplicate-signup@example.com" not in log_text
    assert "user_id=" in log_text


def test_signup_invalid_email(client: TestClient):
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "not-an-email", "password": "Password123!", "name": "Test User"},
    )
    assert response.status_code == 422


def test_signup_missing_password(client: TestClient):
    response = client.post(
        "/api/v1/auth/signup", json={"email": "test@example.com", "name": "Test User"}
    )
    assert response.status_code == 422


def test_login_success(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in response.cookies


def test_login_wrong_password(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401


def test_login_nonexistent_email(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "Password123!"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "email,password",
    [
        ("nobody@example.com", "Password123!"),  # unknown email
        ("test@example.com", "WrongPassword!"),  # known email, wrong password
    ],
)
def test_failed_login_does_not_log_raw_email(
    client: TestClient, caplog, email, password
):
    """HARDENING_PLAN.md finding L10: a failed login must never write the
    raw email into the logs, whether the email is unknown or the password
    was simply wrong — only a non-reversible hash of it."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    with caplog.at_level("WARNING", logger="backend.api.auth"):
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )

    assert response.status_code == 401
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert email not in log_text
    assert "email_hash=" in log_text


def test_successful_login_does_not_log_raw_email(client: TestClient, caplog):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "success-login@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    with caplog.at_level("INFO", logger="backend.api.auth"):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "success-login@example.com", "password": "Password123!"},
        )

    assert response.status_code == 200
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "success-login@example.com" not in log_text
    assert "user_id=" in log_text


def test_me_authenticated(client: TestClient):
    signup_resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    token = signup_resp.json()["access_token"]
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"
    assert "id" in data


def test_me_unauthenticated(client: TestClient):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_expired_token(client: TestClient):
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert response.status_code == 401


def test_refresh_valid_cookie(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
    )
    refresh_cookie = login_resp.cookies.get("refresh_token")
    response = client.post(
        "/api/v1/auth/refresh", cookies={"refresh_token": refresh_cookie}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_refresh_missing_cookie(client: TestClient):
    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


from unittest.mock import AsyncMock, patch

from authlib.integrations.starlette_client import OAuthError


def test_google_callback_new_user(client: TestClient):
    mock_token = {"access_token": "mock", "id_token": "mock"}
    mock_user_info = {
        "email": "newgoogleuser@example.com",
        "email_verified": True,
        "name": "Google User",
        "picture": "http://example.com/pic.jpg",
    }

    with patch(
        "backend.api.auth.oauth.google.authorize_access_token", new_callable=AsyncMock
    ) as mock_auth:
        with patch(
            "backend.api.auth.oauth.google.parse_id_token", new_callable=AsyncMock
        ) as mock_parse:
            mock_auth.return_value = mock_token
            mock_parse.return_value = mock_user_info

            # Since authorize_access_token relies on starlette session, the TestClient request needs a session cookie,
            # but mocking authorize_access_token bypasses the actual session verification inside authlib!
            response = client.get(
                "/api/v1/auth/google/callback?code=mock_code&state=mock_state"
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in response.cookies

            # Verify it's actually in DB as google provider
            token = data["access_token"]
            me_resp = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            me_data = me_resp.json()
            assert me_data["email"] == "newgoogleuser@example.com"
            assert me_data["provider"] == "google"


def test_google_callback_existing_local(client: TestClient):
    # Setup local user
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "localgoogle@example.com",
            "password": "Password123!",
            "name": "Local User",
        },
    )

    mock_token = {"access_token": "mock", "id_token": "mock"}
    mock_user_info = {
        "email": "localgoogle@example.com",
        "email_verified": True,
        "name": "Google User",
        "picture": "http://example.com/pic.jpg",
    }

    with patch(
        "backend.api.auth.oauth.google.authorize_access_token", new_callable=AsyncMock
    ) as mock_auth:
        with patch(
            "backend.api.auth.oauth.google.parse_id_token", new_callable=AsyncMock
        ) as mock_parse:
            mock_auth.return_value = mock_token
            mock_parse.return_value = mock_user_info

            response = client.get(
                "/api/v1/auth/google/callback?code=mock_code&state=mock_state"
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data

            # Check provider changed to google
            token = data["access_token"]
            me_resp = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            me_data = me_resp.json()
            assert me_data["provider"] == "google"
            assert me_data["avatar_url"] == "http://example.com/pic.jpg"


@pytest.mark.parametrize(
    "email,pre_existing_local",
    [
        ("newgoogleuser2@example.com", False),
        ("localgoogle2@example.com", True),
    ],
)
def test_google_callback_does_not_log_raw_email(
    client: TestClient, caplog, email, pre_existing_local
):
    """HARDENING_PLAN.md finding L10: neither the new-user nor the
    existing-user Google sign-in path may write the raw email into logs."""
    if pre_existing_local:
        client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "Password123!", "name": "Local User"},
        )

    mock_token = {"access_token": "mock", "id_token": "mock"}
    mock_user_info = {
        "email": email,
        "email_verified": True,
        "name": "Google User",
        "picture": "http://example.com/pic.jpg",
    }

    with patch(
        "backend.api.auth.oauth.google.authorize_access_token", new_callable=AsyncMock
    ) as mock_auth:
        with patch(
            "backend.api.auth.oauth.google.parse_id_token", new_callable=AsyncMock
        ) as mock_parse:
            mock_auth.return_value = mock_token
            mock_parse.return_value = mock_user_info

            with caplog.at_level("INFO", logger="backend.api.auth"):
                response = client.get(
                    "/api/v1/auth/google/callback?code=mock_code&state=mock_state"
                )

    assert response.status_code == 200
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert email not in log_text
    assert "user_id=" in log_text


@pytest.mark.parametrize(
    "claims",
    [
        {"email_verified": False},
        {},
        {"email_verified": "true"},
        {"email_verified": None},
    ],
)
def test_google_callback_rejects_unverified_email(client: TestClient, claims):
    """Unverified/missing/non-boolean email_verified must not create or link."""
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "victim@example.com",
            "password": "Password123!",
            "name": "Victim",
        },
    )
    for email in ("victim@example.com", "brandnew@example.com"):
        user_info = {"email": email, "name": "Attacker", **claims}
        with patch(
            "backend.api.auth.oauth.google.authorize_access_token",
            new_callable=AsyncMock,
        ) as mock_auth:
            mock_auth.return_value = {"userinfo": user_info}
            response = client.get("/api/v1/auth/google/callback?code=c&state=s")
        assert response.status_code == 400
        assert "not verified" in response.json()["detail"]
        assert "refresh_token" not in response.cookies

    # Victim's local account untouched, and login with password still works.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "Password123!"},
    )
    assert login.status_code == 200
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.json()["provider"] == "local"


def test_google_callback_invalid_code(client: TestClient):
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token", new_callable=AsyncMock
    ) as mock_auth:
        mock_auth.side_effect = OAuthError(
            error="invalid_grant", description="Invalid code"
        )

        response = client.get(
            "/api/v1/auth/google/callback?code=bad_code&state=mock_state"
        )

        assert response.status_code == 400
        assert "OAuth error" in response.json()["detail"]


def test_update_me(client: TestClient):
    # Setup token
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": "update@example.com",
            "password": "Password123!",
            "name": "Test",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "update@example.com", "password": "Password123!"},
    ).json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Valid update
    res = client.patch(
        "/api/v1/auth/me", headers=auth_headers, json={"name": "New Name"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "New Name"

    # Invalid update
    res = client.patch("/api/v1/auth/me", headers=auth_headers, json={"name": ""})
    assert res.status_code == 422
