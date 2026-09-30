"""SEC-1 hardening: exact CORS origins, the docs toggle, constant-time login."""

import pytest
from pydantic import ValidationError

from backend.core import security
from backend.core.config import Settings, settings
from backend.main import docs_settings


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL=settings.DATABASE_URL,
        JWT_SECRET_KEY=settings.JWT_SECRET_KEY,
        **overrides,
    )


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "https://app.example.com/",
        "https://app.example.com/app",
        "app.example.com",
        "ftp://app.example.com",
    ],
)
def test_allowed_origins_must_be_exact_origins(origin):
    with pytest.raises(ValidationError, match="exact origins"):
        _settings(ALLOWED_ORIGINS=[origin])


def test_allowed_origins_accepts_exact_origins():
    origins = ["https://app.example.com", "http://localhost:3000"]
    assert _settings(ALLOWED_ORIGINS=origins).ALLOWED_ORIGINS == origins


def test_docs_are_off_in_production_by_default():
    assert docs_settings("production", False) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


@pytest.mark.parametrize(
    "app_env, enabled", [("development", False), ("production", True)]
)
def test_docs_are_on_in_development_or_when_enabled(app_env, enabled):
    assert docs_settings(app_env, enabled) == {}


def test_login_checks_a_password_even_when_the_account_has_no_hash(monkeypatch):
    """No stored hash must still cost one bcrypt verification, then fail."""
    calls = []
    monkeypatch.setattr(
        security, "verify_password", lambda plain, hashed: calls.append(hashed) or False
    )
    assert security.verify_password_or_dummy("pw", None) is False
    assert len(calls) == 1 and calls[0] == security._dummy_password_hash()


def test_login_verifies_against_the_real_hash_when_there_is_one():
    hashed = security.hash_password("right")
    assert security.verify_password_or_dummy("right", hashed) is True
    assert security.verify_password_or_dummy("wrong", hashed) is False
