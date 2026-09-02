import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class Generation(Base):
    __tablename__ = "generations"

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voice_profile_id = Column(
        UUID(as_uuid=True), ForeignKey("voice_profiles.id"), nullable=False
    )
    input_text = Column(Text, nullable=False)
    output_audio_path = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    tts_metadata = Column(JSONB, server_default=text("'{}'::jsonb"))
    status = Column(String(50), nullable=False, server_default="completed")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
