from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from backend.services.audio_quality import QualityReport


class QualityHintOut(BaseModel):
    """One thing the user can fix in their recording."""

    code: str
    severity: str  # "warning" or "poor"
    message: str


class QualityMeasuresOut(BaseModel):
    """Physical measures of the uploaded recording."""

    voiced_seconds: float
    snr_db: float
    clipping_ratio: float
    high_band_db: float
    level_dbfs: float
    decay_drop_db: float


class QualityOut(BaseModel):
    """How well the recording suits cloning, with advice (SPEECH_QUALITY_PLAN.md S2.2)."""

    rating: str  # "good", "fair" or "poor"
    hints: List[QualityHintOut]
    measures: QualityMeasuresOut

    @classmethod
    def from_report(cls, report: QualityReport) -> "QualityOut":
        """Build the response model from a ``QualityReport``, rounding the measures."""
        m = report.measures
        return cls(
            rating=report.rating,
            hints=[
                QualityHintOut(code=h.code, severity=h.severity, message=h.message)
                for h in report.hints
            ],
            measures=QualityMeasuresOut(
                voiced_seconds=round(m.voiced_seconds, 2),
                snr_db=round(m.snr_db, 1),
                clipping_ratio=round(m.clipping_ratio, 5),
                high_band_db=round(m.high_band_db, 1),
                level_dbfs=round(m.level_dbfs, 1),
                decay_drop_db=round(m.decay_drop_db, 1),
            ),
        )


class SampleOut(BaseModel):
    """One clip of the upload and how it compares with the others."""

    position: int
    # Cosine with the mean of the other clips (1.0 for a single clip).
    agreement: float
    # True when the clip scores low against the others: probably another speaker.
    mismatch: bool
    quality: Optional[QualityOut] = None


class VoiceProfileOut(BaseModel):
    id: UUID
    name: str
    status: str
    consent_confirmed_at: datetime
    terms_version: str
    created_at: datetime
    # The embedding scheme the profile was made with; None on profiles from before it was recorded.
    embedding_version: Optional[str] = None
    # One entry per enrolment clip, in order; empty for a profile from before clips were stored.
    samples: List[SampleOut] = []

    model_config = {"from_attributes": True}


class VoiceProfileUploadOut(VoiceProfileOut):
    """The upload response: the profile, plus recording-quality reports when they could be made.

    ``quality`` is the report of the lowest-rated clip (the one most worth re-recording);
    ``samples`` (inherited) has one entry per clip, in order.
    """

    quality: Optional[QualityOut] = None
