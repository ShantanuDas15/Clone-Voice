"""users email_verified_at

Local signup never proved ownership of the address (HARDENING_PLAN.md
P2-H1), so accounts now carry the moment the owner proved it. Existing
Google accounts are backfilled to `created_at`, because Google verified the
address at sign-in (the callback rejects unverified ones). Existing local
accounts stay NULL: they were never verified and must do so once.

Revision ID: 1234567890ag
Revises: 1234567890af
Create Date: 2026-09-29 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ag"
down_revision: Union[str, None] = "1234567890af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE users SET email_verified_at = created_at WHERE provider <> 'local'"
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
