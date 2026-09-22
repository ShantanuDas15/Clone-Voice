"""Tests for HARDENING_PLAN.md finding L6: the session cookie (used by
authlib's OAuth flow, see api/auth.py) must be signed with its own secret,
not the JWT signing secret."""

import logging

from starlette.middleware.sessions import SessionMiddleware

from backend.main import app, resolve_session_secret_key


def test_uses_session_secret_key_when_set() -> None:
    assert (
        resolve_session_secret_key("session-secret", "jwt-secret") == "session-secret"
    )


def test_falls_back_to_jwt_secret_key_when_unset() -> None:
    assert resolve_session_secret_key("", "jwt-secret") == "jwt-secret"


def test_warns_when_falling_back(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        resolve_session_secret_key("", "jwt-secret")

    assert any("SESSION_SECRET_KEY" in record.message for record in caplog.records)


def test_no_warning_when_session_secret_key_set(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        resolve_session_secret_key("session-secret", "jwt-secret")

    assert not any("SESSION_SECRET_KEY" in record.message for record in caplog.records)


def test_app_session_middleware_is_registered_with_a_secret() -> None:
    """The real app must actually wire SessionMiddleware up (not just define
    the helper) so authlib's OAuth flow has a session to store state in."""
    session_middlewares = [m for m in app.user_middleware if m.cls is SessionMiddleware]

    assert len(session_middlewares) == 1
    assert session_middlewares[0].kwargs["secret_key"]
