"""Fill in the recording-quality report of clips stored before reports were kept (SPEECH_QUALITY_PLAN.md S2.2d).

Why: ``voice_profile_samples.quality`` (S2.2c) is NULL for every clip uploaded earlier, so the
profile listing shows no advice for them. A clip's audio is still on disk, so the same assessment
the upload runs can be run now. No model is needed: it is the signal analysis in ``audio_quality``.

Safety: a dry run is the default and changes nothing; ``--apply`` writes. Only clips whose
``quality`` is NULL are touched, an existing report is never overwritten, and a clip that is
missing or cannot be decoded is skipped and reported while the others still get theirs. Each
profile is committed on its own, so an interruption leaves whole profiles done, never a row half
written.

Run::

    python -m backend.backfill_quality            # dry run: what would be filled
    python -m backend.backfill_quality --apply    # write the reports
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.models.voice_profile import VoiceProfile
from backend.schemas.voice import QualityOut
from backend.services.audio_quality import QualityReport, assess_file

logger = logging.getLogger(__name__)

Assessor = Callable[[str], QualityReport]


@dataclass
class Outcome:
    """What happened (or would happen) to one clip."""

    profile_id: str
    position: int
    status: str  # filled | would_fill | skipped
    detail: str = ""


def backfill_all(
    db: Session, apply: bool, assess: Assessor = assess_file
) -> List[Outcome]:
    """Assess every clip of every ready, non-deleted profile that has no stored report."""
    outcomes: List[Outcome] = []
    profiles = (
        db.query(VoiceProfile)
        .filter(VoiceProfile.deleted_at.is_(None), VoiceProfile.status == "ready")
        .order_by(VoiceProfile.created_at)
        .all()
    )
    for profile in profiles:
        pid = str(profile.id)
        pending = [s for s in profile.samples if s.quality is None]
        done = []
        for sample in pending:
            if not os.path.isfile(sample.audio_path):
                outcomes.append(
                    Outcome(pid, sample.position, "skipped", "clip file is missing")
                )
                continue
            try:
                report = QualityOut.from_report(assess(sample.audio_path))
            except Exception as error:  # a bad clip must not stop the others
                logger.warning("Clip %s/%s skipped: %s", pid, sample.position, error)
                outcomes.append(
                    Outcome(
                        pid,
                        sample.position,
                        "skipped",
                        f"{type(error).__name__}: {error}"[:200],
                    )
                )
                continue
            if apply:
                sample.quality = report.model_dump()
                done.append(sample)
            else:
                outcomes.append(Outcome(pid, sample.position, "would_fill"))
        if done:
            try:
                db.commit()
            except Exception as error:
                db.rollback()
                logger.exception("Profile %s reports could not be saved", pid)
                for sample in done:
                    outcomes.append(
                        Outcome(
                            pid,
                            sample.position,
                            "skipped",
                            f"database update failed: {error}"[:200],
                        )
                    )
                continue
            outcomes.extend(Outcome(pid, s.position, "filled") for s in done)
    return outcomes


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point; returns the process exit code (1 when any clip was skipped)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)

    from backend.core.database import SessionLocal

    db = SessionLocal()
    try:
        outcomes = backfill_all(db, args.apply)
    finally:
        db.close()
    for o in outcomes:
        print(f"{o.profile_id}#{o.position} {o.status} {o.detail}".rstrip())
    skipped = sum(o.status == "skipped" for o in outcomes)
    print(
        f"{len(outcomes)} clips: "
        + ", ".join(
            f"{sum(o.status == s for o in outcomes)} {s}"
            for s in ("filled", "would_fill", "skipped")
        )
        + ("" if args.apply else " (dry run: nothing written)")
    )
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
