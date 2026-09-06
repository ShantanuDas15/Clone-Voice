"""data integrity

Revision ID: 1234567890ac
Revises: 1234567890ab
Create Date: 2026-09-06 23:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1234567890ac"
down_revision: Union[str, None] = "1234567890ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_generations_voice_profile_id"),
        "generations",
        ["voice_profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_generations_voice_profile_id"), table_name="generations")
