"""generations emotions_used and sound_tags_dropped columns

Record the per-sentence emotion labels and the sound tags an engine could not make
(SPEECH_QUALITY_PLAN.md S7.1f). Nullable: NULL means none, or the row predates this.

Revision ID: 1234567890aq
Revises: 1234567890ap
Create Date: 2026-10-15 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890aq"
down_revision: Union[str, None] = "1234567890ap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("emotions_used", sa.Text(), nullable=True))
    op.add_column(
        "generations",
        sa.Column("sound_tags_dropped", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generations", "sound_tags_dropped")
    op.drop_column("generations", "emotions_used")
