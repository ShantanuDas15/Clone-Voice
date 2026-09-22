"""Database connection and session management."""

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.core.config import settings


def _build_engine_kwargs() -> dict:
    """Build `create_engine` kwargs for `settings.DATABASE_URL`.

    HARDENING_PLAN.md finding L5: the engine previously had no
    `pool_pre_ping`, pool sizing, or connect timeout, so a stale pooled
    connection (dropped by a DB restart, or reaped by an idle-connection
    proxy) surfaced as a request-time error instead of being transparently
    discarded and replaced.

    `pool_pre_ping` is safe and applies to every backend. Pool sizing and a
    DBAPI-level connect timeout are Postgres/psycopg2-specific — SQLite (used
    by the test suite via an in-memory URL) has no server-side connections or
    pool-of-connections concept, so those kwargs are skipped for it rather
    than passed and silently ignored (or erroring, in the connect_args case).
    """
    kwargs = {"pool_pre_ping": True}
    if make_url(settings.DATABASE_URL).get_backend_name() != "sqlite":
        kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
            connect_args={"connect_timeout": int(settings.DB_CONNECT_TIMEOUT_SECONDS)},
        )
    return kwargs


engine = create_engine(settings.DATABASE_URL, **_build_engine_kwargs())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
