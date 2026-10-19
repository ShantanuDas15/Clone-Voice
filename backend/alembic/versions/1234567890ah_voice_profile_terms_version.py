"""voice_profiles terms_version

Responsible-use safeguard (RU-2): the consent attestation now also records
which version of the acceptable-use terms it was given against, so a consent
can be traced to the exact wording in force. Existing rows predate versioning
and are backfilled with the literal "legacy" rather than a real version they
never saw; the column is not nullable.

Revision ID: 1234567890ah
Revises: 1234567890ag
Create Date: 2026-09-30 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ah"
down_revision: Union[str, None] = "1234567890ag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_profiles",
        sa.Column("terms_version", sa.String(length=50), nullable=True),
    )
    op.execute(
        "UPDATE voice_profiles SET terms_version = 'legacy' "
        "WHERE terms_version IS NULL"
    )
    op.alter_column("voice_profiles", "terms_version", nullable=False)


def downgrade() -> None:
    op.drop_column("voice_profiles", "terms_version")
