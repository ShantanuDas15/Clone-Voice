"""voice_profiles.embedding_version

Record which speaker-embedding scheme a profile's embedding was made with
(SPEECH_QUALITY_PLAN.md S4.5a), so a profile made for one scheme is never fed to another.
Nullable: rows from before this was recorded stay NULL, meaning "not recorded" (they were all made
by the SV2TTS encoder).

Revision ID: 1234567890an
Revises: 1234567890am
Create Date: 2026-10-12 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890an"
down_revision: Union[str, None] = "1234567890am"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_profiles",
        sa.Column("embedding_version", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("voice_profiles", "embedding_version")
