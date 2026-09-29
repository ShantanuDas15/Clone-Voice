"""Verify the database matches the code: at Alembic head, with no drift.

    python -m backend.check_schema

Exits 0 when ``alembic_version`` holds the head revision and the live schema
equals the ORM models; 1 (listing every difference) otherwise; 2 when the
database cannot be reached. Run it after ``alembic upgrade head`` in CI, or
against a deployed database to confirm a migration did what the models expect.
"""

import sys
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.database import engine
from backend.core.migrations import check_schema_current, find_schema_drift


def main(argv: Optional[List[str]] = None) -> int:
    """Run both checks and report; returns the process exit code."""
    problems: List[str] = []
    try:
        with engine.connect() as connection:
            try:
                check_schema_current(Session(bind=connection))
            except RuntimeError as error:
                problems.append(str(error))
            problems.extend(f"drift: {line}" for line in find_schema_drift(connection))
    except SQLAlchemyError as error:
        print(f"cannot check the schema: {error}", file=sys.stderr)
        return 2

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("Schema is at head and matches the models.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
