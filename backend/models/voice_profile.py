import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from backend.core.config import settings
from backend.core.database import Base


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    audio_sample_path = Column(Text, nullable=False)
    embedding_path = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="ready")
    # Responsible-use safeguard: the uploader's attestation that they have
    # the right to use this voice sample, captured at upload time. A non-null
    # timestamp *is* the record of consent — there is no unconsented row, so
    # no separate boolean is needed alongside it.
    consent_confirmed_at = Column(DateTime(timezone=True), nullable=False)
    # The acceptable-use terms version the uploader attested to (RU-2). Rows
    # that predate versioning carry the literal "legacy".
    terms_version = Column(
        String(50), nullable=False, default=lambda: settings.TERMS_VERSION
    )
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
    # Enrolment clips of a multi-clip profile (S2.1b); empty for older profiles.
    samples = relationship(
        "VoiceProfileSample",
        order_by="VoiceProfileSample.position",
        cascade="all, delete-orphan",
        lazy="select",
    )
