"""generations waveform peaks

Store 64 bar heights (0..100) of each generated clip so the History list can draw a preview
without downloading the audio (FRONTEND_UX_IMPROVEMENT_PLAN.md H4). Nullable: NULL means no
preview (a failed row, silence, or a row from before this).

Revision ID: 1234567890as
Revises: 1234567890ar
Create Date: 2026-11-03 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1234567890as"
down_revision: Union[str, None] = "1234567890ar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column(
            "waveform_peaks",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("generations", "waveform_peaks")
