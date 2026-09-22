"""generations audit columns

HARDENING_PLAN.md finding L11: `generations` had no `updated_at`/
`deleted_at`, unlike `users`/`voice_profiles` — a deviation from CLAUDE.md
§6 ("All tables use created_at + updated_at audit timestamps... Use
deleted_at for soft deletes"). No route deletes a Generation today (it's
an append-only audit trail), so `deleted_at` stays NULL in practice; both
columns exist for schema consistency and any future soft-delete feature.

Revision ID: 1234567890ad
Revises: 1234567890ac
Create Date: 2026-09-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ad"
down_revision: Union[str, None] = "1234567890ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "generations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generations", "deleted_at")
    op.drop_column("generations", "updated_at")
