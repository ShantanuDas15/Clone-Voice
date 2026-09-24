"""Tests for liveness/readiness split (HARDENING_PLAN.md finding M7)."""

import asyncio
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.services import tts_pipeline


@pytest.fixture
def restore_warmup():
    """Reset the cached warm-up status after a test mutates it."""
    original = tts_pipeline._warmup_status
    yield
    tts_pipeline._warmup_status = original


def test_liveness_ok_and_has_no_dependencies(client: TestClient) -> None:
    """Liveness stays 200 even when the DB and models are both broken."""
    with patch.object(
        main_module, "_check_database", side_effect=RuntimeError("db down")
    ), patch.object(tts_pipeline, "_vocoder", None):
        resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


@pytest.mark.parametrize("path", ["/health/ready", "/health"])
def test_readiness_ok_when_db_and_models_up(client: TestClient, path: str) -> None:
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == {"ok": True}
    assert body["warmup"] == "disabled"
    assert body["models"]["encoder"]["loaded"] is True


def test_readiness_503_when_database_down(client: TestClient) -> None:
    with patch.object(
        main_module, "_check_database", side_effect=RuntimeError("secret dsn leak")
    ):
        resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == {"ok": False}
    # models are fine; only the DB flipped readiness
    assert body["models"]["vocoder"]["loaded"] is True
    assert "secret dsn leak" not in resp.text


def test_readiness_503_when_database_check_times_out(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(main_module.settings, "READINESS_DB_TIMEOUT_SECONDS", 0.05)

    def slow(_db):
        time.sleep(0.5)

    with patch.object(main_module, "_check_database", side_effect=slow):
        resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["database"] == {"ok": False}


def test_readiness_503_when_model_missing_but_db_ok(client: TestClient) -> None:
    with patch.object(tts_pipeline, "_synthesizer", None):
        resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["database"] == {"ok": True}
    assert body["models"]["synthesizer"]["loaded"] is False


def test_database_check_runs_real_select_1(db_session) -> None:
    """The helper runs against a real (SQLite) session stamped at Alembic head."""
    main_module._check_database(db_session)  # must not raise


@pytest.mark.parametrize(
    "state,expected_status", [("failed", 503), ("pending", 503), ("ok", 200)]
)
def test_readiness_reflects_warmup_state(
    client: TestClient, restore_warmup, state: str, expected_status: int
) -> None:
    tts_pipeline._warmup_status = state
    resp = client.get("/health/ready")
    assert resp.status_code == expected_status
    assert resp.json()["warmup"] == state


def test_warmup_inference_success_records_ok(restore_warmup) -> None:
    assert asyncio.run(tts_pipeline.warmup_inference()) is True
    assert tts_pipeline.get_warmup_status() == "ok"


def test_warmup_inference_failure_records_failed_without_raising(
    restore_warmup,
) -> None:
    with patch.object(
        tts_pipeline, "_warmup_forward_pass", side_effect=RuntimeError("boom")
    ):
        assert asyncio.run(tts_pipeline.warmup_inference()) is False
    assert tts_pipeline.get_warmup_status() == "failed"


def test_warmup_releases_inference_permit(restore_warmup) -> None:
    """Warm-up must not leave the single inference permit held."""
    asyncio.run(tts_pipeline.warmup_inference())
    assert not tts_pipeline._inference_semaphore.locked()


def test_lifespan_runs_warmup_only_when_enabled(monkeypatch) -> None:
    async def _ok() -> bool:
        return True

    for enabled, expected_calls in ((False, 0), (True, 1)):
        monkeypatch.setattr(main_module.settings, "READINESS_WARMUP_ENABLED", enabled)
        with patch("backend.main.load_models"), patch(
            "backend.main.warmup_inference", side_effect=_ok
        ) as warm:
            with TestClient(main_module.app):
                pass
        assert warm.call_count == expected_calls


# ---------------------------------------------------------------------------
# HARDENING_PLAN.md finding P2-M2: readiness verifies the Alembic head
# ---------------------------------------------------------------------------


def _fresh_session(with_version_table: bool, version: str | None = None):
    """Return an isolated in-memory SQLite session, optionally stamped."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    if with_version_table:
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            if version is not None:
                conn.execute(
                    text("INSERT INTO alembic_version VALUES (:v)"), {"v": version}
                )
    return sessionmaker(bind=eng)()


def test_head_revision_matches_latest_migration_file() -> None:
    from backend.core.migrations import get_head_revision

    assert get_head_revision() == "1234567890ae"


def test_schema_check_passes_at_head() -> None:
    from backend.core.migrations import check_schema_current, get_head_revision

    db = _fresh_session(True, get_head_revision())
    try:
        check_schema_current(db)  # must not raise
    finally:
        db.close()


@pytest.mark.parametrize(
    "with_table,version", [(False, None), (True, None), (True, "1234567890ab")]
)
def test_schema_check_fails_when_unmigrated_or_stale(with_table, version) -> None:
    from backend.core.migrations import check_schema_current

    db = _fresh_session(with_table, version)
    try:
        with pytest.raises(Exception):
            check_schema_current(db)
    finally:
        db.close()


def test_readiness_503_when_schema_not_at_head(client: TestClient) -> None:
    with patch.object(
        main_module, "check_schema_current", side_effect=RuntimeError("stale")
    ):
        resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["database"] == {"ok": False}
