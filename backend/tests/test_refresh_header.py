"""POST /auth/refresh requires X-Requested-With (RAILWAY_READINESS_REPORT.md F-10)."""

from fastapi.testclient import TestClient

REFRESH = "/api/v1/auth/refresh"


def _refresh_cookie(client: TestClient) -> None:
    """Sign a user up and leave their refresh token on the client."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "header@example.com",
            "password": "Password123!",
            "name": "Header User",
        },
    )
    assert response.status_code == 201
    token = response.cookies.get("refresh_token")
    assert token
    client.cookies.clear()
    # The cookie is Secure, so hand it over the way a browser on https would.
    client.cookies.set("refresh_token", token)


def test_refresh_without_the_header_is_refused(client: TestClient) -> None:
    """A valid cookie alone is not enough."""
    _refresh_cookie(client)
    del client.headers["X-Requested-With"]
    response = client.post(REFRESH)
    assert response.status_code == 403
    assert "X-Requested-With" in response.json()["detail"]


def test_refresh_with_the_wrong_header_value_is_refused(client: TestClient) -> None:
    """Only the exact value counts."""
    _refresh_cookie(client)
    response = client.post(REFRESH, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 403


def test_refresh_with_the_header_succeeds(client: TestClient) -> None:
    """The web app's request shape works."""
    _refresh_cookie(client)
    response = client.post(REFRESH)
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_refused_refresh_does_not_consume_the_token(client: TestClient) -> None:
    """The header check runs before the token is rotated."""
    _refresh_cookie(client)
    del client.headers["X-Requested-With"]
    assert client.post(REFRESH).status_code == 403
    client.headers["X-Requested-With"] = "XMLHttpRequest"
    assert client.post(REFRESH).status_code == 200
