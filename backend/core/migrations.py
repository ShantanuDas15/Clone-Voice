"""Alembic head-revision lookup, schema-currency check (HARDENING P2-M2) and
model-vs-database drift detection."""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, List

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic"


@lru_cache(maxsize=1)
def get_head_revision() -> str:
    """Return the single head revision declared by the Alembic scripts."""
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check_schema_current(db: Session) -> None:
    """Raise unless ``alembic_version`` holds exactly the head revision."""
    rows = db.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    current = {row[0] for row in rows}
    head = get_head_revision()
    if current != {head}:
        raise RuntimeError(
            f"Schema not at Alembic head: db={sorted(current) or 'empty'}, head={head}"
        )


def _label(item: Any) -> str:
    """A short name for an alembic diff element (table, column, index, ...)."""
    return str(getattr(item, "name", None) or getattr(item, "key", None) or item)


def describe_diff(diff: tuple) -> str:
    """Render one alembic diff tuple as a readable line."""
    op = diff[0]
    if op.startswith("modify_"):
        # (op, schema, table, column, existing_kwargs, old, new)
        _, _, table, column, _, old, new = diff
        return f"{op} {table}.{column}: {old!r} -> {new!r}"
    if op.endswith("_column"):
        # (op, schema, table, Column)
        return f"{op} {diff[2]}.{_label(diff[3])}"
    return f"{op} {_label(diff[1])}"


def find_schema_drift(connection: Connection) -> List[str]:
    """Describe every difference between the live schema and the ORM models.

    An empty list means the migrations produce exactly what the models
    declare (tables, columns, types, nullability, indexes, constraints). A
    migration that was forgotten, or a model changed without one, shows up
    here instead of at the first query that touches the column.
    """
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    # Imported here: the models package pulls in the whole ORM.
    from backend.models import Base

    lines: List[str] = []
    for diff in compare_metadata(context, Base.metadata):
        # modify_* diffs arrive as a list of tuples for one column.
        for item in diff if isinstance(diff, list) else [diff]:
            lines.append(describe_diff(item))
    return lines
