"""voice_profiles consent_confirmed_at

Responsible-use safeguard: an uploader must now explicitly attest they have
the right to use a voice sample, captured as a timestamp on the profile row
(the record of consent, not a separate boolean alongside it). Existing rows
predate the safeguard, so they are backfilled to their own `created_at` —
documented here rather than left NULL, since the column is not nullable.

Revision ID: 1234567890af
Revises: 1234567890ae
Create Date: 2026-09-28 15:02:52.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890af"
down_revision: Union[str, None] = "1234567890ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_profiles",
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill existing rows to their own created_at (documented assumption
    # above), then make the column mandatory for every row going forward.
    op.execute(
        "UPDATE voice_profiles SET consent_confirmed_at = created_at "
        "WHERE consent_confirmed_at IS NULL"
    )
    op.alter_column("voice_profiles", "consent_confirmed_at", nullable=False)


def downgrade() -> None:
    op.drop_column("voice_profiles", "consent_confirmed_at")
