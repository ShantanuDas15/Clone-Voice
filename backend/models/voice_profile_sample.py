import uuid

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, Text,
                        UniqueConstraint)
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from backend.core.database import Base


class VoiceProfileSample(Base):
    """One enrolment clip of a voice profile (SPEECH_QUALITY_PLAN.md S2.1b).

    A profile built from several clips keeps each clip's audio and embedding so
    the profile embedding can be re-derived and so erasure removes every file.
    Profiles created before this table existed have no rows here; their single
    clip is still the profile's own ``audio_sample_path``.
    """

    __tablename__ = "voice_profile_samples"
    __table_args__ = (
        UniqueConstraint(
            "voice_profile_id", "position", name="uq_voice_profile_samples_position"
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    voice_profile_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("voice_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Upload order, from 0.
    position = Column(Integer, nullable=False)
    audio_path = Column(Text, nullable=False)
    embedding_path = Column(Text, nullable=False)
    # Cosine of this clip with the mean of the others (1.0 for a lone clip).
    agreement = Column(Float, nullable=False)
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
