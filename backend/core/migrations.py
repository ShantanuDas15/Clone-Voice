"""Alembic head-revision lookup and schema-currency check (HARDENING P2-M2)."""

import logging
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
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
