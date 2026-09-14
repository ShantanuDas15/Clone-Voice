"""Tests for API versioning (Hardening Phase 4.1)."""

from fastapi.testclient import TestClient

from backend.main import API_V1_PREFIX, app


def test_api_v1_prefix_is_slash_api_slash_v1() -> None:
    """The versioned prefix constant must be exactly `/api/v1`."""
    assert API_V1_PREFIX == "/api/v1"


def test_all_routers_mounted_under_api_v1() -> None:
    """Every application route (other than `/health` and docs) must live under
    `/api/v1`, so future breaking changes can be shipped as `/api/v2` without
    disturbing existing clients."""
    exempt = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path or path in exempt:
            continue
        assert path.startswith(API_V1_PREFIX), f"Unversioned route: {path}"


def test_versioned_endpoint_is_reachable(client: TestClient) -> None:
    """A known endpoint responds correctly under the new `/api/v1` prefix."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "versioning@example.com",
            "password": "Password123!",
            "name": "Versioning Test",
        },
    )
    assert response.status_code in (200, 201)


def test_legacy_unversioned_path_is_gone(client: TestClient) -> None:
    """The pre-versioning path must no longer resolve, confirming the move
    (not a duplicate mount) happened."""
    response = client.post(
        "/api/auth/signup",
        json={"email": "legacy@example.com", "password": "Password123!"},
    )
    assert response.status_code == 404


def test_health_endpoint_remains_unversioned(client: TestClient) -> None:
    """Health checks are infrastructure-level and stay outside API versioning."""
    response = client.get("/health")
    assert response.status_code in (200, 503)
