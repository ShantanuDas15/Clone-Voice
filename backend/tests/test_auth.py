from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_signup_success(client: TestClient):
    response = client.post(
        "/api/auth/signup",
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
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    assert response.status_code == 409


def test_signup_invalid_email(client: TestClient):
    response = client.post(
        "/api/auth/signup",
        json={"email": "not-an-email", "password": "Password123!", "name": "Test User"},
    )
    assert response.status_code == 422


def test_signup_missing_password(client: TestClient):
    response = client.post(
        "/api/auth/signup", json={"email": "test@example.com", "name": "Test User"}
    )
    assert response.status_code == 422


def test_login_success(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in response.cookies


def test_login_wrong_password(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401


def test_login_nonexistent_email(client: TestClient):
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "Password123!"},
    )
    assert response.status_code == 401


def test_me_authenticated(client: TestClient):
    signup_resp = client.post(
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    token = signup_resp.json()["access_token"]
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"
    assert "id" in data


def test_me_unauthenticated(client: TestClient):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_expired_token(client: TestClient):
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert response.status_code == 401


def test_refresh_valid_cookie(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "test@example.com",
            "password": "Password123!",
            "name": "Test User",
        },
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
    )
    refresh_cookie = login_resp.cookies.get("refresh_token")
    response = client.post(
        "/api/auth/refresh", cookies={"refresh_token": refresh_cookie}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_refresh_missing_cookie(client: TestClient):
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401


from unittest.mock import AsyncMock, patch

from authlib.integrations.starlette_client import OAuthError


def test_google_callback_new_user(client: TestClient):
    mock_token = {"access_token": "mock", "id_token": "mock"}
    mock_user_info = {
        "email": "newgoogleuser@example.com",
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
                "/api/auth/google/callback?code=mock_code&state=mock_state"
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in response.cookies

            # Verify it's actually in DB as google provider
            token = data["access_token"]
            me_resp = client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            me_data = me_resp.json()
            assert me_data["email"] == "newgoogleuser@example.com"
            assert me_data["provider"] == "google"


def test_google_callback_existing_local(client: TestClient):
    # Setup local user
    client.post(
        "/api/auth/signup",
        json={
            "email": "localgoogle@example.com",
            "password": "Password123!",
            "name": "Local User",
        },
    )

    mock_token = {"access_token": "mock", "id_token": "mock"}
    mock_user_info = {
        "email": "localgoogle@example.com",
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
                "/api/auth/google/callback?code=mock_code&state=mock_state"
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data

            # Check provider changed to google
            token = data["access_token"]
            me_resp = client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            me_data = me_resp.json()
            assert me_data["provider"] == "google"
            assert me_data["avatar_url"] == "http://example.com/pic.jpg"


def test_google_callback_invalid_code(client: TestClient):
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token", new_callable=AsyncMock
    ) as mock_auth:
        mock_auth.side_effect = OAuthError(
            error="invalid_grant", description="Invalid code"
        )

        response = client.get(
            "/api/auth/google/callback?code=bad_code&state=mock_state"
        )

        assert response.status_code == 400
        assert "OAuth error" in response.json()["detail"]


def test_update_me(client: TestClient):
    # Setup token
    client.post(
        "/api/auth/signup",
        json={
            "email": "update@example.com",
            "password": "Password123!",
            "name": "Test",
        },
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "update@example.com", "password": "Password123!"},
    ).json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Valid update
    res = client.patch("/api/auth/me", headers=auth_headers, json={"name": "New Name"})
    assert res.status_code == 200
    assert res.json()["name"] == "New Name"

    # Invalid update
    res = client.patch("/api/auth/me", headers=auth_headers, json={"name": ""})
    assert res.status_code == 422
