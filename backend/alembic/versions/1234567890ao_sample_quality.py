"""voice_profile_samples.quality

Keep each enrolment clip's recording-quality report (SPEECH_QUALITY_PLAN.md S2.2c), so
a later request can show the advice again instead of only the upload response. Nullable:
clips from before this was stored, and clips whose assessment failed, stay NULL.

Revision ID: 1234567890ao
Revises: 1234567890an
Create Date: 2026-10-14 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ao"
down_revision: Union[str, None] = "1234567890an"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_profile_samples", sa.Column("quality", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("voice_profile_samples", "quality")
