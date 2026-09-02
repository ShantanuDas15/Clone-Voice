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
