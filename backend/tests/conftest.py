"""Shared test fixtures for the CloneVoice backend test suite."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.database import Base, get_db
from backend.main import app
from backend.services.tts_pipeline import load_mock_models

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


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once at the start of the test session."""
    Base.metadata.create_all(bind=engine)
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
def client(db_session):
    """Provide a FastAPI test client wired to the isolated per-test DB session."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
