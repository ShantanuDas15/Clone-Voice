"""Self-service export of everything the service holds for one account (E1).

The archive holds the account fields, the voice profiles with their clips and
the generation history as JSON, plus the user's own recordings and generated
audio. Credentials, refresh tokens, speaker embeddings (derived, model-specific)
and soft-deleted rows (already scrubbed by erasure) are left out.

The zip is built in a temp file so memory stays flat for large audio; the
caller streams it and removes it.
"""

import json
import logging
import os
import tempfile
import threading
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.services.erasure import _within_storage

logger = logging.getLogger(__name__)

# One export builds a zip of the user's audio; two at a time bounds the burst.
EXPORT_SLOTS = threading.BoundedSemaphore(2)
EXPORT_RETRY_AFTER_SECONDS = 30

README_TEXT = """CloneVoice data export

account.json         your account details
voice_profiles.json  your voices and their recordings (clips)
generations.json     the speech you generated, with the text you typed
voice_samples/       the recordings you uploaded
generations/         the generated audio that has not yet expired

Not included: your password, sign-in sessions, and the speaker embeddings
derived from your recordings (they are only meaningful to the voice model).
Audio files that were removed (for example by the retention period) are listed
with "audio_file": null.
"""


def _iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601 text for a timestamp, or None."""
    return value.isoformat() if value else None


def _add_audio(archive: zipfile.ZipFile, path: Optional[str], member: str) -> bool:
    """Add a stored file under `member`; False if absent or outside storage."""
    if not path or not _within_storage(path) or not os.path.isfile(path):
        return False
    archive.write(path, member, compress_type=zipfile.ZIP_STORED)
    return True


def _clip_member(profile: VoiceProfile, position: int, path: str) -> str:
    """Archive name of a voice clip, keeping the original extension."""
    extension = os.path.splitext(path)[1].lower() or ".wav"
    return f"voice_samples/{profile.id}/{position}{extension}"


def _profile_entry(archive: zipfile.ZipFile, profile: VoiceProfile) -> Dict[str, Any]:
    """The JSON entry for one profile, adding its clips to the archive."""
    clips = [s for s in profile.samples if s.deleted_at is None]
    clips.sort(key=lambda s: s.position)
    sources = [(s.position, s.audio_path, s) for s in clips]
    if not sources:  # a profile that predates multi-clip profiles
        sources = [(0, profile.audio_sample_path, None)]
    entries: List[Dict[str, Any]] = []
    for position, path, sample in sources:
        member = _clip_member(profile, position, path or "")
        entry: Dict[str, Any] = {
            "position": position,
            "audio_file": member if _add_audio(archive, path, member) else None,
        }
        if sample is not None:
            entry["agreement"] = sample.agreement
            entry["quality"] = sample.quality
            entry["created_at"] = _iso(sample.created_at)
        entries.append(entry)
    return {
        "id": str(profile.id),
        "name": profile.name,
        "status": profile.status,
        "consent_confirmed_at": _iso(profile.consent_confirmed_at),
        "adult_confirmed_at": _iso(profile.adult_confirmed_at),
        "terms_version": profile.terms_version,
        "embedding_version": profile.embedding_version,
        "created_at": _iso(profile.created_at),
        "clips": entries,
    }


def _generation_entry(
    archive: zipfile.ZipFile, generation: Generation
) -> Dict[str, Any]:
    """The JSON entry for one generation, adding its audio to the archive."""
    member = f"generations/{generation.id}.wav"
    included = _add_audio(archive, generation.output_audio_path, member)
    return {
        "id": str(generation.id),
        "voice_profile_id": str(generation.voice_profile_id),
        "text": generation.input_text,
        "status": generation.status,
        "duration_seconds": generation.duration_seconds,
        "engine": generation.engine,
        "engine_fallback_from": generation.engine_fallback_from,
        "emotion": generation.emotion,
        "intensity": generation.intensity,
        "style_applied": generation.style_applied,
        "emotions_used": generation.emotions_used,
        "seed": generation.seed,
        "created_at": _iso(generation.created_at),
        "audio_file": member if included else None,
    }


def build_export(db: Session, user: User) -> str:
    """Write the user's export zip to a temp file and return its path."""
    handle, zip_path = tempfile.mkstemp(prefix="clonevoice-export-", suffix=".zip")
    os.close(handle)
    try:
        profiles = (
            db.query(VoiceProfile)
            .filter(VoiceProfile.user_id == user.id, VoiceProfile.deleted_at.is_(None))
            .order_by(VoiceProfile.created_at)
            .all()
        )
        generations = (
            db.query(Generation)
            .filter(Generation.user_id == user.id, Generation.deleted_at.is_(None))
            .order_by(Generation.created_at)
            .all()
        )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            documents = {
                "account.json": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                    "provider": user.provider,
                    "email_verified_at": _iso(user.email_verified_at),
                    "has_password": user.has_password,
                    "preferences": user.preferences or {},
                    "created_at": _iso(user.created_at),
                },
                "voice_profiles.json": [_profile_entry(archive, p) for p in profiles],
                "generations.json": [
                    _generation_entry(archive, g) for g in generations
                ],
            }
            for name, document in documents.items():
                archive.writestr(
                    name, json.dumps(document, indent=2, ensure_ascii=False)
                )
            archive.writestr("README.txt", README_TEXT)
    except Exception:
        os.unlink(zip_path)
        raise
    logger.info(
        "Account export built: user_id=%s profiles=%d generations=%d",
        user.id,
        len(profiles),
        len(generations),
    )
    return zip_path
