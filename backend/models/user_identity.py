import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from backend.core.database import Base


class UserIdentity(Base):
    """An external sign-in identity (today: a Google account) linked to a user.

    `provider_subject` is the provider's stable account id (Google's `sub`).
    Sign-in matches on it rather than on the email address, because an email
    can change hands or be recycled while the subject never is. Unlinking is
    not implemented: a soft-deleted row would keep its subject reserved.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_subject", name="uq_user_identities_provider_subject"
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String(50), nullable=False)
    provider_subject = Column(String(255), nullable=False)
    # The address the provider reported when the identity was linked (audit
    # only; never used to find a user once the identity exists).
    email = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
