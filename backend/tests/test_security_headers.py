"""Baseline security headers: HSTS outside development, nosniff always."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.security_headers import HSTS_VALUE, SecurityHeadersMiddleware


def _client(hsts: bool) -> TestClient:
    """A tiny app wrapped in the middleware."""
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict:
        """Return a constant body."""
        return {"ok": True}

    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
    return TestClient(app)


def test_hsts_and_nosniff_are_set() -> None:
    """Both headers appear on a normal response."""
    response = _client(hsts=True).get("/ping")
    assert response.headers["strict-transport-security"] == HSTS_VALUE
    assert response.headers["x-content-type-options"] == "nosniff"


def test_hsts_is_omitted_when_disabled() -> None:
    """Development turns HSTS off but keeps nosniff."""
    response = _client(hsts=False).get("/ping")
    assert "strict-transport-security" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_headers_are_on_error_responses() -> None:
    """A 404 carries them as well."""
    response = _client(hsts=True).get("/missing")
    assert response.status_code == 404
    assert "strict-transport-security" in response.headers


def test_real_app_sends_nosniff(client: TestClient) -> None:
    """The real app is wrapped in the middleware."""
    response = client.get("/health/live")
    assert response.headers.get("x-content-type-options") == "nosniff"
