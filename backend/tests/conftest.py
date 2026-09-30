"""Shared test fixtures for the CloneVoice backend test suite."""

import os

# The API schema is off outside development; several tests read /openapi.json.
# Set before `backend.main` is imported below (settings are read at import).
os.environ.setdefault("API_DOCS_ENABLED", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.main as main_module
from backend.core.config import settings
from backend.core.database import Base, get_db
from backend.core.migrations import get_head_revision
from backend.main import app
from backend.services.tts_pipeline import load_mock_models

# Disable rate limiting for all tests by default.  Every test request uses the
# same "testclient" IP, so leaving the limiter on would cause the tight
# per-minute limits (5 or 10 req/min) to trip mid-suite.
# Tests in test_rate_limit.py re-enable it explicitly and clear storage in
# their own setup/teardown.
app.state.limiter.enabled = False


@pytest.fixture(autouse=True)
def email_verification_off_by_default(monkeypatch):
    """Most tests sign up a local user and go straight to a gated endpoint.

    The gate itself is covered in test_email_verification.py, which switches
    it back on explicitly.
    """
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)


@pytest.fixture(autouse=True)
def no_real_email_by_default(monkeypatch):
    """Never let a test reach a real mail provider, whatever backend/.env says.

    Settings are read from the developer's own `.env`, which may hold a live
    Resend key; without this every signup in the suite would call the real
    API. Tests that exercise a transport select it and patch its network
    boundary themselves (see test_email_verification.py).
    """
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "disabled")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "")


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

# Session-scoped engine — one connection kept alive for the entire test session.
# Tables are created once and torn down between tests via BEGIN/ROLLBACK.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_ml_models():
    """Load lightweight mock ML models once for the entire test session.

    Runs before any individual test module so every module that exercises the
    inference pipeline (including test_security.py, which runs alphabetically
    before the TTS-specific modules) has models available without relying on
    hidden execution-order side-effects.
    """
    load_mock_models("cpu")


def _stamp_alembic_head() -> None:
    """Mimic `alembic upgrade head` so the readiness schema check passes."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
        )
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": get_head_revision()},
        )


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once at the start of the test session."""
    Base.metadata.create_all(bind=engine)
    _stamp_alembic_head()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(create_tables):
    """Provide a per-test DB session that is fully rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db_session, monkeypatch):
    """Provide a FastAPI test client wired to the isolated per-test DB session."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # HARDENING_PLAN.md finding P2-L8: readiness's `_check_database` no longer
    # takes the request-scoped `get_db` session (see main.py) — it opens its
    # own via the module-level `SessionLocal` it imported. Point that at the
    # same in-memory test engine `TestingSessionLocal` uses, so it still runs
    # against the test DB instead of the real DATABASE_URL.
    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolated_storage_dirs(monkeypatch, tmp_path):
    """Point UPLOAD_DIR/OUTPUT_DIR at per-test temp dirs (HARDENING_PLAN.md M9).

    Guarantees no test writes user-style files into the real backend/uploads
    or backend/outputs; pytest removes ``tmp_path`` automatically.
    """
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(tmp_path / "outputs"))
