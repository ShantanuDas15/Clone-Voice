"""generations seed columns

Record the seed a user asked for on a generation (SPEECH_QUALITY_PLAN.md S7.1d) and whether
the engine that spoke could apply it. Nullable: NULL means no seed was requested or the row
predates this.

Revision ID: 1234567890ap
Revises: 1234567890ao
Create Date: 2026-10-15 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ap"
down_revision: Union[str, None] = "1234567890ao"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("seed", sa.Integer(), nullable=True))
    op.add_column("generations", sa.Column("seed_applied", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("generations", "seed_applied")
    op.drop_column("generations", "seed")
