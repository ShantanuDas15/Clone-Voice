"""voice_profiles adult_confirmed_at

Decision Q4 (SPEECH_QUALITY_PLAN.md): children's voices are out of scope, so an
upload can carry an attestation that the speaker is an adult. The timestamp is
nullable: existing rows predate the question and are left null rather than
claiming an attestation nobody gave.

Revision ID: 1234567890ar
Revises: 1234567890aq
Create Date: 2026-10-22 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ar"
down_revision: Union[str, None] = "1234567890aq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_profiles",
        sa.Column("adult_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("voice_profiles", "adult_confirmed_at")
