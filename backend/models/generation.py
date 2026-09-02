import uuid

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from backend.core.database import Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class Generation(Base):
    __tablename__ = "generations"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    voice_profile_id = Column(
        Uuid(as_uuid=True), ForeignKey("voice_profiles.id"), nullable=False
    )
    input_text = Column(Text, nullable=False)
    output_audio_path = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    tts_metadata = Column(JSON_TYPE, default=dict)
    status = Column(String(50), nullable=False, default="completed")
    created_at = Column(
        DateTime(timezone=True), default=func.now(), nullable=False, index=True
    )
