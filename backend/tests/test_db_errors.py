"""Database-outage handling (backend/core/db_errors.py).

Before this, a query that failed while the database was unreachable returned
`500 text/plain "Internal Server Error"` from every DB-touching route.
"""

import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import (DBAPIError, IntegrityError, InterfaceError,
                            OperationalError, ProgrammingError,
                            SQLAlchemyError)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from backend.core.database import get_db
from backend.core.db_errors import (DB_RETRY_AFTER_SECONDS,
                                    DB_UNAVAILABLE_DETAIL,
                                    INTERNAL_ERROR_DETAIL, db_unavailable,
                                    is_transient_db_error,
                                    register_db_error_handlers)
from backend.core.security import create_access_token
from backend.main import app

REFUSED = Exception("connection to server at 127.0.0.1, port 5432 failed: refused")


def _dropped_connection() -> DBAPIError:
    return DBAPIError("stmt", {}, Exception("gone"), connection_invalidated=True)


# --- Classification ----------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("stmt", {}, REFUSED),
        InterfaceError("stmt", {}, Exception("connection already closed")),
        PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached"),
        _dropped_connection(),
    ],
)
def test_transient_errors_are_recognised(error):
    assert is_transient_db_error(error) is True


@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("stmt", {}, Exception("duplicate key")),
        ProgrammingError("stmt", {}, Exception("no such column")),
        DBAPIError("stmt", {}, Exception("x"), connection_invalidated=False),
        SQLAlchemyError("generic"),
        ValueError("not a database error"),
    ],
)
def test_non_transient_errors_are_not(error):
    assert is_transient_db_error(error) is False


def test_db_unavailable_is_a_503_with_retry_after():
    error = db_unavailable()
    assert error.status_code == 503
    assert error.detail == DB_UNAVAILABLE_DETAIL
    assert error.headers == {"Retry-After": str(DB_RETRY_AFTER_SECONDS)}


# --- The handler on a minimal app -------------------------------------------


def _client_that_raises(error: Exception) -> TestClient:
    small = FastAPI()
    register_db_error_handlers(small)

    @small.get("/boom")
    def boom():
        raise error

    return TestClient(small, raise_server_exceptions=False)


def test_an_outage_becomes_a_json_503_with_retry_after():
    res = _client_that_raises(OperationalError("SELECT 1", {}, REFUSED)).get("/boom")
    assert res.status_code == 503
    assert res.headers["content-type"].startswith("application/json")
    assert res.headers["Retry-After"] == str(DB_RETRY_AFTER_SECONDS)
    assert res.json() == {"detail": DB_UNAVAILABLE_DETAIL}


def test_a_non_transient_error_becomes_a_json_500_without_retry_after():
    res = _client_that_raises(ProgrammingError("SELECT x", {}, Exception("bad"))).get(
        "/boom"
    )
    assert res.status_code == 500
    assert res.headers["content-type"].startswith("application/json")
    assert "Retry-After" not in res.headers
    assert res.json() == {"detail": INTERNAL_ERROR_DETAIL}


def test_the_response_never_leaks_sql_parameters_or_driver_text():
    error = OperationalError(
        "SELECT * FROM users WHERE email = %(e)s", {"e": "victim@example.com"}, REFUSED
    )
    body = _client_that_raises(error).get("/boom").text
    for secret in ("victim@example.com", "SELECT", "127.0.0.1", "psycopg2"):
        assert secret not in body


def test_other_exceptions_are_left_alone():
    """Only database errors are mapped; a bug elsewhere is still a plain 500."""
    res = _client_that_raises(ValueError("bug")).get("/boom")
    assert res.status_code == 500
    assert res.headers["content-type"].startswith("text/plain")


# --- Logging -----------------------------------------------------------------


def test_outage_is_logged_as_an_error_with_the_connection_detail(caplog):
    with caplog.at_level(logging.ERROR, logger="backend.core.db_errors"):
        _client_that_raises(OperationalError("SELECT 1", {}, REFUSED)).get("/boom")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "Database unavailable during GET /boom" in text
    assert "port 5432" in text  # the operator needs to see which server


def test_non_transient_errors_are_logged_without_exception_text(caplog):
    """Postgres messages quote row values (a duplicate key names the email), so
    only the class, pgcode and stack frames may be logged."""
    orig = Exception(
        "duplicate key ... DETAIL: Key (email)=(victim@example.com) exists"
    )
    orig.pgcode = "23505"
    error = IntegrityError(
        "INSERT INTO users ...", {"email": "victim@example.com"}, orig
    )
    with caplog.at_level(logging.ERROR, logger="backend.core.db_errors"):
        _client_that_raises(error).get("/boom")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "pgcode=23505" in text
    assert "IntegrityError" in text
    assert "victim@example.com" not in text
    assert "INSERT INTO" not in text


# --- On the real app ---------------------------------------------------------


@pytest.fixture
def broken_db():
    """Every query on the session fails the way an unreachable database does."""
    session = MagicMock()
    session.query.side_effect = OperationalError("SELECT 1", {}, REFUSED)
    session.execute.side_effect = OperationalError("SELECT 1", {}, REFUSED)
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize(
    "method, path, kwargs",
    [
        (
            "post",
            "/api/v1/auth/login",
            {"json": {"email": "a@b.co", "password": "x" * 8}},
        ),
        (
            "post",
            "/api/v1/auth/signup",
            {"json": {"email": "a@b.co", "password": "x" * 8, "name": "A"}},
        ),
        ("post", "/api/v1/auth/forgot-password", {"json": {"email": "a@b.co"}}),
        ("get", "/api/v1/voice/profiles", {"auth": True}),
        ("get", "/api/v1/auth/me", {"auth": True}),
    ],
)
def test_every_db_touching_route_answers_503_during_an_outage(
    broken_db, method, path, kwargs
):
    """The routes that used to return a bare text/plain 500."""
    client = TestClient(app, raise_server_exceptions=False)
    if kwargs.pop("auth", False):
        token = create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
        kwargs["headers"] = {"Authorization": f"Bearer {token}"}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 503, res.text
    assert res.headers["Retry-After"] == str(DB_RETRY_AFTER_SECONDS)
    assert res.json()["detail"] == DB_UNAVAILABLE_DETAIL


def test_the_503_still_carries_cors_headers(broken_db):
    """The browser must be able to read the error, not report a CORS failure."""
    client = TestClient(app, raise_server_exceptions=False)
    origin = "http://localhost:3000"
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "a@b.co", "password": "x" * 8},
        headers={"Origin": origin},
    )
    assert res.status_code == 503
    assert res.headers["access-control-allow-origin"] == origin


def test_liveness_does_not_touch_the_database(broken_db):
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health/live").status_code == 200
