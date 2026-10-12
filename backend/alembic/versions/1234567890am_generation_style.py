"""generations style columns

Record the delivery a user asked for on a generation (SPEECH_QUALITY_PLAN.md S7.1b): the emotion,
its intensity, and whether the engine applied it. Nullable: NULL means no emotion was requested
(``auto``) or the row predates this.

Revision ID: 1234567890am
Revises: 1234567890al
Create Date: 2026-10-12 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890am"
down_revision: Union[str, None] = "1234567890al"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations", sa.Column("emotion", sa.String(length=20), nullable=True)
    )
    op.add_column("generations", sa.Column("intensity", sa.Float(), nullable=True))
    op.add_column(
        "generations", sa.Column("style_applied", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("generations", "style_applied")
    op.drop_column("generations", "intensity")
    op.drop_column("generations", "emotion")
