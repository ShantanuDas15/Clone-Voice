"""Model-vs-database drift detection (backend/core/migrations.py,
backend/check_schema.py).

The guard's real target is Postgres, where CI runs it after `alembic upgrade
head` (.github/workflows/backend-schema.yml). These tests cover the logic on
in-memory SQLite: that a matching schema is clean, that each kind of drift is
reported, and that the CLI's exit codes and CI wiring hold.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend import check_schema
from backend.core.migrations import (describe_diff, find_schema_drift,
                                     get_head_revision)
from backend.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_engine():
    """A private in-memory database, so drift can be injected freely."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    yield engine
    engine.dispose()


def _stamp(engine, revision: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision})


def test_a_schema_built_from_the_models_has_no_drift(scratch_engine):
    Base.metadata.create_all(scratch_engine)
    with scratch_engine.connect() as connection:
        assert find_schema_drift(connection) == []


def test_a_missing_table_is_reported_with_its_index(scratch_engine):
    tables = [t for t in Base.metadata.sorted_tables if t.name != "refresh_tokens"]
    Base.metadata.create_all(scratch_engine, tables=tables)
    with scratch_engine.connect() as connection:
        drift = find_schema_drift(connection)
    assert "add_table refresh_tokens" in drift


def test_an_extra_column_is_reported(scratch_engine):
    Base.metadata.create_all(scratch_engine)
    with scratch_engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN drift_probe TEXT"))
    with scratch_engine.connect() as connection:
        assert find_schema_drift(connection) == ["remove_column users.drift_probe"]


def test_an_extra_index_is_reported(scratch_engine):
    Base.metadata.create_all(scratch_engine)
    with scratch_engine.begin() as conn:
        conn.execute(text("CREATE INDEX drift_idx ON users(name)"))
    with scratch_engine.connect() as connection:
        assert find_schema_drift(connection) == ["remove_index drift_idx"]


def test_a_changed_column_is_reported_as_one_readable_line():
    line = describe_diff(("modify_nullable", None, "users", "email", {}, False, True))
    assert line == "modify_nullable users.email: False -> True"


def test_modify_diffs_delivered_as_a_list_are_flattened(scratch_engine):
    """alembic groups the changes to one column into a list."""
    Base.metadata.create_all(scratch_engine)
    grouped = [("modify_nullable", None, "users", "email", {}, False, True)]
    with patch("backend.core.migrations.compare_metadata", return_value=[grouped]):
        with scratch_engine.connect() as connection:
            assert find_schema_drift(connection) == [
                "modify_nullable users.email: False -> True"
            ]


# --- CLI ---------------------------------------------------------------------


def _run_cli(engine, capsys):
    with patch.object(check_schema, "engine", engine):
        code = check_schema.main([])
    return code, capsys.readouterr()


def test_cli_passes_at_head_with_no_drift(scratch_engine, capsys):
    Base.metadata.create_all(scratch_engine)
    _stamp(scratch_engine, get_head_revision())
    code, out = _run_cli(scratch_engine, capsys)
    assert code == 0
    assert "matches the models" in out.out


def test_cli_fails_on_drift_and_names_it(scratch_engine, capsys):
    Base.metadata.create_all(scratch_engine)
    _stamp(scratch_engine, get_head_revision())
    with scratch_engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN drift_probe TEXT"))
    code, out = _run_cli(scratch_engine, capsys)
    assert code == 1
    assert "drift: remove_column users.drift_probe" in out.err


def test_cli_fails_when_the_database_is_behind_head(scratch_engine, capsys):
    Base.metadata.create_all(scratch_engine)
    _stamp(scratch_engine, "0")
    code, out = _run_cli(scratch_engine, capsys)
    assert code == 1
    assert "not at Alembic head" in out.err


def test_cli_reports_both_problems_together(scratch_engine, capsys):
    Base.metadata.create_all(scratch_engine)
    _stamp(scratch_engine, "0")
    with scratch_engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN drift_probe TEXT"))
    _, out = _run_cli(scratch_engine, capsys)
    assert "not at Alembic head" in out.err and "drift_probe" in out.err


def test_cli_exits_2_when_the_database_is_unreachable(capsys):
    dead = create_engine("postgresql+psycopg2://u:p@127.0.0.1:1/none")
    code, out = _run_cli(dead, capsys)
    assert code == 2
    assert "cannot check the schema" in out.err


# --- CI wiring ---------------------------------------------------------------

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "backend-schema.yml"


def test_ci_runs_the_guard_against_a_real_postgres():
    text_ = WORKFLOW.read_text()
    assert "postgres:15" in text_  # the version docker-compose.yml runs
    assert "alembic -c backend/alembic.ini upgrade head" in text_
    assert "python -m backend.check_schema" in text_


def test_ci_proves_the_guard_can_fail_and_that_downgrades_work():
    text_ = WORKFLOW.read_text()
    # A negative control: inject drift, expect a failure, remove it again.
    assert "drift_probe" in text_
    # Every migration must also be reversible and re-appliable.
    assert "alembic -c backend/alembic.ini downgrade base" in text_


def test_ci_triggers_on_the_files_that_can_cause_drift():
    text_ = WORKFLOW.read_text()
    for path in (
        "backend/alembic/**",
        "backend/models/**",
        "backend/core/migrations.py",
        "backend/check_schema.py",
        ".github/workflows/backend-schema.yml",
    ):
        assert f'"{path}"' in text_, path


def test_ci_installs_only_pinned_versions_from_requirements():
    """The job installs a minimal subset (no torch) but must use the same
    pins as the image, taken from requirements.txt rather than repeated."""
    text_ = WORKFLOW.read_text()
    assert "backend/requirements.txt" in text_
    for name in ("alembic", "sqlalchemy", "psycopg2-binary", "pydantic-settings"):
        assert re.search(name, text_, re.IGNORECASE), name
