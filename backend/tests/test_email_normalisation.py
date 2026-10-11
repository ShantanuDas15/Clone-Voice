"""Lower-case emails (SEC-1): request schemas, login, and the migration."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from backend.core.migrations import get_head_revision
from backend.models.user import User

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "1234567890aj_lowercase_emails.py"
)
SIGNUP = {"email": "Bob@Example.COM", "password": "Password123!", "name": "Bob"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("lowercase_emails", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scratch_engine():
    """A private in-memory database with a bare `users` table."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)"))
    yield engine
    engine.dispose()


def _emails(engine) -> list:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT email FROM users ORDER BY id"))]


# --- API ---------------------------------------------------------------------


def test_signup_stores_the_address_in_lower_case(client: TestClient, db_session):
    assert client.post("/api/v1/auth/signup", json=SIGNUP).status_code == 201
    assert db_session.query(User).one().email == "bob@example.com"


def test_login_ignores_the_case_of_the_address(client: TestClient):
    client.post("/api/v1/auth/signup", json=SIGNUP)
    for email in ("bob@example.com", "BOB@EXAMPLE.COM"):
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
        )
        assert response.status_code == 200


def test_signup_with_a_different_case_is_a_duplicate(client: TestClient):
    client.post("/api/v1/auth/signup", json=SIGNUP)
    again = client.post(
        "/api/v1/auth/signup", json={**SIGNUP, "email": "bob@example.com"}
    )
    assert again.status_code == 409


def test_the_database_refuses_a_mixed_case_address(db_session):
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():  # savepoint: keep the test transaction usable
            db_session.add(User(email="Bob@Example.com", name="Bob", provider="local"))


def test_a_soft_deleted_account_cannot_log_in(client: TestClient, db_session):
    client.post("/api/v1/auth/signup", json=SIGNUP)
    db_session.query(User).update({"deleted_at": datetime.now(timezone.utc)})
    db_session.flush()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "Password123!"},
    )
    assert response.status_code == 401
    assert "refresh_token" not in response.cookies


# --- Migration ---------------------------------------------------------------


def test_the_migration_chain_has_one_head_and_this_revision_is_in_it():
    # The head moves with each migration; this revision's own parent is what it pins.
    assert get_head_revision() == "1234567890ak"
    assert _load_migration().down_revision == "1234567890ai"


def test_migration_lowercases_only_what_needs_it(scratch_engine):
    with scratch_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (email) VALUES ('Bob@X.com'), ('amy@x.com')")
        )
        _load_migration().lowercase_existing_emails(conn)
    assert _emails(scratch_engine) == ["bob@x.com", "amy@x.com"]


def test_migration_stops_on_case_collisions_and_changes_nothing(scratch_engine):
    with scratch_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (email) VALUES ('Bob@x.com'), ('bob@x.com')")
        )
    migration = _load_migration()
    with scratch_engine.connect() as conn:
        with pytest.raises(RuntimeError, match="bob@x.com"):
            migration.assert_no_case_collisions(conn)
    assert _emails(scratch_engine) == ["Bob@x.com", "bob@x.com"]


def test_migration_passes_when_there_are_no_collisions(scratch_engine):
    with scratch_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email) VALUES ('Bob@x.com')"))
        _load_migration().assert_no_case_collisions(conn)
