"""lower-case user emails

Addresses are now stored and compared in lower case (`Bob@x.com` and
`bob@x.com` reach the same inbox, so they must be one account). Login and the
Google callback look users up by the lower-cased address, so a legacy
mixed-case row would otherwise become impossible to sign in to.

Existing rows are lower-cased, then a CHECK constraint makes the database
refuse anything else (which also makes the unique index case-insensitive).

If two rows differ only by case, lower-casing would violate the unique index,
and choosing which account survives is not a decision a migration can make.
The upgrade stops before changing anything and names the addresses so an
operator can merge or remove one by hand, then re-run it.

Revision ID: 1234567890aj
Revises: 1234567890ai
Create Date: 2026-09-30 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision: str = "1234567890aj"
down_revision: Union[str, None] = "1234567890ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_users_email_lowercase"
# Bound the addresses quoted in the error; a real collision set is tiny.
MAX_LISTED_COLLISIONS = 20


def assert_no_case_collisions(connection: Connection) -> None:
    """Raise, changing nothing, if two users' emails differ only by case."""
    rows = connection.execute(
        sa.text(
            "SELECT lower(email) FROM users GROUP BY lower(email) "
            "HAVING count(*) > 1 ORDER BY 1 LIMIT :limit"
        ),
        {"limit": MAX_LISTED_COLLISIONS},
    ).fetchall()
    if rows:
        listed = ", ".join(row[0] for row in rows)
        raise RuntimeError(
            "Cannot lower-case users.email: these addresses exist more than once "
            f"differing only by case (first {MAX_LISTED_COLLISIONS} shown): "
            f"{listed}. Merge or remove the duplicate accounts, then re-run."
        )


def lowercase_existing_emails(connection: Connection) -> None:
    """Lower-case every stored address that is not already."""
    connection.execute(
        sa.text("UPDATE users SET email = lower(email) WHERE email <> lower(email)")
    )


def upgrade() -> None:
    connection = op.get_bind()
    assert_no_case_collisions(connection)
    lowercase_existing_emails(connection)
    op.create_check_constraint(CONSTRAINT_NAME, "users", "email = lower(email)")


def downgrade() -> None:
    # The original casing is not recoverable; the rows stay lower case.
    op.drop_constraint(CONSTRAINT_NAME, "users", type_="check")
