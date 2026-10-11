"""voice_profile_samples table

A voice profile can now be built from several clips of one speaker
(SPEECH_QUALITY_PLAN.md S2.1b). Each clip's audio and embedding paths are kept
here so erasure and cleanup know every file the profile owns.

Existing profiles are not backfilled: their one clip stays on the profile row.

Revision ID: 1234567890ak
Revises: 1234567890aj
Create Date: 2026-10-11 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1234567890ak"
down_revision: Union[str, None] = "1234567890aj"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_profile_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("audio_path", sa.Text(), nullable=False),
        sa.Column("embedding_path", sa.Text(), nullable=False),
        sa.Column("agreement", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"], ["voice_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "voice_profile_id", "position", name="uq_voice_profile_samples_position"
        ),
    )
    op.create_index(
        op.f("ix_voice_profile_samples_voice_profile_id"),
        "voice_profile_samples",
        ["voice_profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_voice_profile_samples_voice_profile_id"),
        table_name="voice_profile_samples",
    )
    op.drop_table("voice_profile_samples")
