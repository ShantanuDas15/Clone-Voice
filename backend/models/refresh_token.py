import uuid

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from backend.core.database import Base


class RefreshToken(Base):
    """One issued refresh token; ``id`` is the JWT's ``jti`` claim.

    ``revoked_at`` marks a token as used (rotated) or signed out; rows are
    only deleted by the cleanup pass, once long expired (HARDENING_PLAN.md
    finding P2-M4).
    """

    __tablename__ = "refresh_tokens"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
