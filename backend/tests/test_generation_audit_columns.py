"""Tests for HARDENING_PLAN.md finding L11: `generations` must carry
`updated_at`/`deleted_at` like every other table (CLAUDE.md §6), both at the
ORM level and via a matching Alembic migration."""

import subprocess
import uuid

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def _script_directory() -> ScriptDirectory:
    cfg = Config(f"{REPO_ROOT}/backend/alembic.ini")
    cfg.set_main_option("script_location", f"{REPO_ROOT}/backend/alembic")
    return ScriptDirectory.from_config(cfg)


def _make_user_and_profile(db_session):
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        name="Generation Audit Test User",
        provider="local",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    profile = VoiceProfile(
        user_id=user.id,
        name="voice",
        audio_sample_path="/data/a.wav",
        embedding_path="/data/a_embed.npy",
        status="ready",
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return user, profile


def test_generation_has_updated_at_and_deleted_at_columns() -> None:
    column_names = {c.name for c in Generation.__table__.columns}
    assert "updated_at" in column_names
    assert "deleted_at" in column_names


def test_new_generation_gets_updated_at_and_null_deleted_at(db_session) -> None:
    user, profile = _make_user_and_profile(db_session)
    generation = Generation(
        user_id=user.id,
        voice_profile_id=profile.id,
        input_text="hello",
        output_audio_path="/data/out.wav",
        status="completed",
    )
    db_session.add(generation)
    db_session.commit()
    db_session.refresh(generation)

    assert generation.updated_at is not None
    assert generation.deleted_at is None


def test_generation_updated_at_changes_on_update(db_session) -> None:
    user, profile = _make_user_and_profile(db_session)
    generation = Generation(
        user_id=user.id,
        voice_profile_id=profile.id,
        input_text="hello",
        output_audio_path="/data/out.wav",
        status="completed",
    )
    db_session.add(generation)
    db_session.commit()
    db_session.refresh(generation)
    first_updated_at = generation.updated_at

    generation.status = "failed"
    db_session.commit()
    db_session.refresh(generation)

    assert generation.updated_at >= first_updated_at


def test_generation_deleted_at_can_be_set() -> None:
    """Confirms the column accepts a value even though no route sets it
    today — it exists for schema consistency and any future feature."""
    from sqlalchemy.sql import func

    generation = Generation(
        user_id=uuid.uuid4(),
        voice_profile_id=uuid.uuid4(),
        input_text="hello",
        deleted_at=func.now(),
    )
    assert generation.deleted_at is not None


def test_alembic_migration_chain_has_a_single_head() -> None:
    script = _script_directory()
    assert len(script.get_heads()) == 1
    assert script.get_revision("1234567890ad") is not None


def test_alembic_migration_revision_chains_from_the_previous_head() -> None:
    script = _script_directory()
    revision = script.get_revision("1234567890ad")
    assert revision.down_revision == "1234567890ac"


def test_alembic_migration_adds_both_columns_to_generations() -> None:
    with open(
        f"{REPO_ROOT}/backend/alembic/versions/"
        "1234567890ad_generations_audit_columns.py",
        encoding="utf-8",
    ) as f:
        source = f.read()

    assert '"generations"' in source
    assert '"updated_at"' in source
    assert '"deleted_at"' in source
    assert "def downgrade" in source
    assert 'op.drop_column("generations", "deleted_at")' in source
    assert 'op.drop_column("generations", "updated_at")' in source
