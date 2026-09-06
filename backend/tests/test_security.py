from fastapi.testclient import TestClient


def test_refresh_token_rotated(client: TestClient):
    client.post(
        "/api/auth/signup",
        json={
            "email": "rotate@example.com",
            "password": "Password123!",
            "name": "Rotate User",
        },
    )
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "rotate@example.com", "password": "Password123!"},
    )
    old_refresh = login_resp.cookies.get("refresh_token")
    assert old_refresh is not None

    refresh_resp = client.post(
        "/api/auth/refresh", cookies={"refresh_token": old_refresh}
    )
    assert refresh_resp.status_code == 200

    new_refresh = refresh_resp.cookies.get("refresh_token")
    assert new_refresh is not None
    assert new_refresh != old_refresh
