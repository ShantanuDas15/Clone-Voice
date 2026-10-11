"""Erasure of voice data and accounts (SEC-2).

Rows are soft-deleted, never removed (CLAUDE.md §6), so the audit trail
survives; what erasure guarantees is that the *data* is gone: the audio,
the speaker embeddings and the cloned outputs are deleted from disk at once
(not left for age-based pruning), and on account erasure the personal fields
are scrubbed in place.

Callers commit the session, then call `remove_files` / `remove_user_storage`,
so a failed commit never deletes files a surviving row still points at.
"""

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Iterable, List

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.user_identity import UserIdentity
from backend.models.voice_profile import VoiceProfile
from backend.models.voice_profile_sample import VoiceProfileSample
from backend.services.refresh_tokens import revoke_all_for_user

logger = logging.getLogger(__name__)

ERASED_NAME = "Deleted user"
ERASED_TEXT = "[erased]"
# `.invalid` is reserved (RFC 2606): it can never be a real mailbox, and it is
# lower case, so it satisfies the users.email CHECK constraint.
ERASED_EMAIL_DOMAIN = "deleted.invalid"


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def _within_storage(path: str) -> bool:
    """True only for a path inside the upload or output directory."""
    real = os.path.realpath(path)
    for root in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
        base = os.path.realpath(root)
        if real.startswith(base + os.sep):
            return True
    return False


def erase_voice_profile(db: Session, profile: VoiceProfile) -> List[str]:
    """Soft-delete a profile and its generations; return the files to remove.

    Soft-deleting the generations too takes their outputs out of the retention
    protection (`get_protected_paths`), so nothing cloned from the deleted
    voice outlives it. The caller commits.
    """
    now = _now()
    outputs = [
        path
        for (path,) in db.query(Generation.output_audio_path).filter(
            Generation.voice_profile_id == profile.id,
            Generation.output_audio_path.isnot(None),
        )
    ]
    db.execute(
        update(Generation)
        .where(Generation.voice_profile_id == profile.id)
        .values(deleted_at=now)
    )
    # Every enrolment clip of a multi-clip profile (S2.1b), audio and embedding.
    clips = [
        path
        for audio_path, embedding_path in db.query(
            VoiceProfileSample.audio_path, VoiceProfileSample.embedding_path
        ).filter(
            VoiceProfileSample.voice_profile_id == profile.id,
            VoiceProfileSample.deleted_at.is_(None),
        )
        for path in (audio_path, embedding_path)
    ]
    db.execute(
        update(VoiceProfileSample)
        .where(VoiceProfileSample.voice_profile_id == profile.id)
        .values(deleted_at=now)
    )
    profile.deleted_at = now
    return [profile.audio_sample_path, profile.embedding_path, *clips, *outputs]


def remove_files(paths: Iterable[str]) -> int:
    """Delete files that lie inside the storage directories; return the count.

    Best-effort: a missing file is fine and a failure is logged, never raised,
    because the rows are already erased and the periodic cleanup is a backstop.
    """
    removed = 0
    for path in paths:
        if not path or not _within_storage(path):
            continue
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("Failed to remove erased file: %s", path)
    return removed


def erase_account(db: Session, user: User) -> None:
    """Soft-delete the account and all its voice data, scrubbing personal fields.

    Also revokes every refresh token. Commits (through the revocation), so the
    whole erasure lands in one transaction. The caller then calls
    `remove_user_storage`.
    """
    now = _now()
    placeholder = f"{user.id}@{ERASED_EMAIL_DOMAIN}"

    for profile in db.query(VoiceProfile).filter(
        VoiceProfile.user_id == user.id, VoiceProfile.deleted_at.is_(None)
    ):
        erase_voice_profile(db, profile)
    # Every generation of the user: the typed text is personal data, and this
    # also covers rows of profiles deleted earlier.
    db.execute(
        update(Generation)
        .where(Generation.user_id == user.id)
        .values(input_text=ERASED_TEXT, output_audio_path=None, deleted_at=now)
    )
    db.execute(
        update(UserIdentity)
        .where(UserIdentity.user_id == user.id)
        .values(email=placeholder, deleted_at=now)
    )

    user.email = placeholder
    user.name = ERASED_NAME
    user.avatar_url = None
    user.hashed_password = None
    user.preferences = {}
    user.deleted_at = now
    # Commits everything above together with the revocation.
    revoked = revoke_all_for_user(db, user.id)
    logger.info("Account erased, revoked %d session(s): user_id=%s", revoked, user.id)


def remove_user_storage(user_id: uuid.UUID) -> None:
    """Delete the user's whole upload and output directories (incl. orphans)."""
    for root in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
        shutil.rmtree(os.path.join(root, str(user_id)), ignore_errors=True)
