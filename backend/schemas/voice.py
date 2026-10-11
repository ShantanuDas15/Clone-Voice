from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from backend.services.audio_quality import QualityReport


class VoiceProfileOut(BaseModel):
    id: UUID
    name: str
    status: str
    consent_confirmed_at: datetime
    terms_version: str
    created_at: datetime

    model_config = {"from_attributes": True}


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


class VoiceProfileUploadOut(VoiceProfileOut):
    """The upload response: the profile, plus recording-quality reports when they could be made.

    ``quality`` is the report of the lowest-rated clip (the one most worth re-recording);
    ``samples`` has one entry per uploaded clip, in upload order.
    """

    quality: Optional[QualityOut] = None
    samples: List[SampleOut] = []
