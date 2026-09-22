"""Tests for HARDENING_PLAN.md finding L5: the DB engine must be built with
`pool_pre_ping`, pool sizing, and a connect timeout — not SQLAlchemy's bare
defaults, which silently hand out stale/dead pooled connections after a DB
restart instead of transparently recycling them."""

from sqlalchemy import create_engine, text

from backend.core.config import settings
from backend.core.database import _build_engine_kwargs, engine


def test_real_engine_has_pre_ping_enabled() -> None:
    """The module-level `engine` (built from `settings.DATABASE_URL`) must
    always ping a pooled connection before handing it to a caller."""
    assert engine.pool._pre_ping is True


def test_build_engine_kwargs_for_postgres(monkeypatch) -> None:
    """A Postgres URL gets pool sizing plus a psycopg2 `connect_timeout`."""
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://u:p@host:5432/db")

    kwargs = _build_engine_kwargs()

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == settings.DB_POOL_SIZE
    assert kwargs["max_overflow"] == settings.DB_MAX_OVERFLOW
    assert kwargs["pool_timeout"] == settings.DB_POOL_TIMEOUT_SECONDS
    assert kwargs["connect_args"] == {
        "connect_timeout": int(settings.DB_CONNECT_TIMEOUT_SECONDS)
    }


def test_build_engine_kwargs_for_sqlite_skips_postgres_only_options(
    monkeypatch,
) -> None:
    """SQLite has no server-side connections/pool concept — pool sizing and
    the psycopg2-specific `connect_timeout` must not be passed for it."""
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///:memory:")

    kwargs = _build_engine_kwargs()

    assert kwargs == {"pool_pre_ping": True}


def test_sqlite_engine_can_still_be_created_with_these_kwargs() -> None:
    """A SQLite engine built with the kwargs `_build_engine_kwargs` would
    produce for a SQLite URL must not error — proves the kwargs are actually
    valid for the `sqlite3` DBAPI, not just computed correctly."""
    test_engine = create_engine("sqlite:///:memory:", pool_pre_ping=True)
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
