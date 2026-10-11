"""generations.engine columns

Record which speech engine produced each generation (SPEECH_QUALITY_PLAN.md S7.1), and which
engine was unavailable when the backup engine served it instead. Nullable: rows from before this
was recorded stay NULL, which means "not recorded", not "sv2tts".

Revision ID: 1234567890al
Revises: 1234567890ak
Create Date: 2026-10-11 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890al"
down_revision: Union[str, None] = "1234567890ak"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations", sa.Column("engine", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "generations", sa.Column("engine_version", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "generations",
        sa.Column("engine_fallback_from", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generations", "engine_fallback_from")
    op.drop_column("generations", "engine_version")
    op.drop_column("generations", "engine")
