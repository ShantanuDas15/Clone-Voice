"""Re-derive voice-profile embeddings from the stored enrolment clips (SPEECH_QUALITY_PLAN.md S4.5b).

Why: a profile keeps its audio, so its embedding can be rebuilt with the current speaker encoder.
That is the migration path behind the embedding-version guard (S4.5a): when the scheme changes,
``POST /synthesize`` refuses older profiles, and this tool brings them forward without asking
users to upload again. It also stamps ``embedding_version`` on profiles from before it was
recorded (NULL), which is only honest once the embedding has actually been rebuilt.

Safety: a dry run is the default and changes nothing; ``--apply`` writes. A profile is
all-or-nothing: every clip is decoded and embedded first, and only if all succeed are the files
replaced (each via a temporary file and ``os.replace``) and the row updated. A profile with a
missing or undecodable clip, or an unusable embedding, is skipped and reported, never half-changed.

Run (after provisioning weights)::

    python -m backend.rederive_profiles                 # dry run: what would change
    python -m backend.rederive_profiles --apply         # rewrite
    python -m backend.rederive_profiles --apply --only-outdated   # skip profiles already current
"""

import argparse
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np
from sqlalchemy.orm import Session

from backend.models.voice_profile import VoiceProfile
from backend.services.audio_processing import preprocess_audio
from backend.services.voice_embedding import (EMBEDDING_VERSION,
                                              aggregate_embeddings,
                                              is_usable_embedding)

logger = logging.getLogger(__name__)

Embedder = Callable[[np.ndarray], np.ndarray]


@dataclass
class Outcome:
    """What happened (or would happen) to one profile."""

    profile_id: str
    status: str  # updated | would_update | current | skipped
    detail: str = ""
    similarity: Optional[float] = (
        None  # cosine of the old and the new profile embedding
    )


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors (0.0 if either is all zeros)."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def _write_npy(path: str, array: np.ndarray) -> str:
    """Write ``array`` to a temporary file next to ``path`` and return the temporary path."""
    handle, tmp = tempfile.mkstemp(
        prefix=".rederive-", suffix=".npy", dir=os.path.dirname(path) or "."
    )
    with os.fdopen(handle, "wb") as out:
        np.save(out, array)
    return tmp


def _clips(profile: VoiceProfile) -> List[tuple]:
    """(audio path, embedding path) of each clip; an older profile has just its own sample."""
    if profile.samples:
        return [(s.audio_path, s.embedding_path) for s in profile.samples]
    return [(profile.audio_sample_path, profile.embedding_path)]


def rederive_profile(
    db: Session, profile: VoiceProfile, embed: Embedder, apply: bool
) -> Outcome:
    """Rebuild one profile's embeddings from its stored clips; write them only when ``apply``."""
    pid = str(profile.id)
    clips = _clips(profile)
    new_clip_embeddings = []
    try:
        for audio_path, _ in clips:
            if not os.path.isfile(audio_path):
                return Outcome(pid, "skipped", f"clip is missing: {audio_path}")
            embedding = embed(preprocess_audio(audio_path))
            if not is_usable_embedding(embedding):
                return Outcome(pid, "skipped", "the encoder gave an unusable embedding")
            new_clip_embeddings.append(np.asarray(embedding, np.float32))
    except Exception as error:  # a bad clip must not stop the other profiles
        logger.warning("Profile %s skipped: %s", pid, error)
        return Outcome(pid, "skipped", f"{type(error).__name__}: {error}"[:200])

    new_profile = (
        new_clip_embeddings[0]
        if len(new_clip_embeddings) == 1
        else aggregate_embeddings(new_clip_embeddings)
    )
    similarity = None
    if os.path.isfile(profile.embedding_path):
        similarity = round(_cosine(np.load(profile.embedding_path), new_profile), 4)
    if not apply:
        return Outcome(pid, "would_update", similarity=similarity)

    # Write every temporary file first; replace only when all of them exist.
    targets = {profile.embedding_path: new_profile}
    if profile.samples:
        for (_, clip_path), embedding in zip(clips, new_clip_embeddings):
            targets[clip_path] = embedding
    temporaries = {}
    try:
        for path, array in targets.items():
            temporaries[path] = _write_npy(path, array)
        for path, tmp in temporaries.items():
            os.replace(tmp, path)
        temporaries.clear()
    except Exception as error:
        logger.exception("Profile %s could not be written", pid)
        return Outcome(pid, "skipped", f"write failed: {error}"[:200])
    finally:
        for tmp in temporaries.values():
            try:
                os.remove(tmp)
            except OSError:
                pass
    try:
        profile.embedding_version = EMBEDDING_VERSION
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Profile %s version could not be saved", pid)
        return Outcome(pid, "skipped", f"database update failed: {error}"[:200])
    return Outcome(pid, "updated", similarity=similarity)


def rederive_all(
    db: Session, embed: Embedder, apply: bool, only_outdated: bool = False
) -> List[Outcome]:
    """Process every ready, non-deleted profile."""
    outcomes = []
    profiles = (
        db.query(VoiceProfile)
        .filter(VoiceProfile.deleted_at.is_(None), VoiceProfile.status == "ready")
        .order_by(VoiceProfile.created_at)
        .all()
    )
    for profile in profiles:
        if only_outdated and profile.embedding_version == EMBEDDING_VERSION:
            outcomes.append(Outcome(str(profile.id), "current"))
            continue
        outcomes.append(rederive_profile(db, profile, embed, apply))
    return outcomes


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument(
        "--only-outdated",
        action="store_true",
        help=f"skip profiles already at {EMBEDDING_VERSION}",
    )
    args = parser.parse_args(argv)

    from backend.core.database import SessionLocal
    from backend.services import tts_pipeline

    tts_pipeline.load_models("cpu")
    db = SessionLocal()
    try:
        outcomes = rederive_all(
            db, tts_pipeline.embed_speaker, args.apply, args.only_outdated
        )
    finally:
        db.close()
    for o in outcomes:
        extra = f" cosine={o.similarity}" if o.similarity is not None else ""
        print(f"{o.profile_id} {o.status}{extra} {o.detail}".rstrip())
    skipped = sum(o.status == "skipped" for o in outcomes)
    print(
        f"{len(outcomes)} profiles: "
        + ", ".join(
            f"{sum(o.status == s for o in outcomes)} {s}"
            for s in ("updated", "would_update", "current", "skipped")
        )
        + ("" if args.apply else " (dry run: nothing written)")
    )
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
