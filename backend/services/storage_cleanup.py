"""Background pruning of stale files in the uploads/ and outputs/ directories.

Uploaded audio samples and synthesized outputs accumulate on local disk with
no natural expiry.  Left unchecked this guarantees eventual disk exhaustion
(HARDENING_PLAN.md, Phase 2 — Storage Cleanup).  `cleanup_stale_files` prunes
anything older than a configurable age threshold; `periodic_cleanup` runs it
on a fixed interval for the lifetime of the application.

Age-based pruning alone is unsafe: a voice profile's audio sample and speaker
embedding live in `uploads/`, and a generation's synthesized output lives in
`outputs/`, with no separate long-term copy anywhere else.  Once those files
cross the age threshold while still referenced by an active (non
soft-deleted) database row, pruning them breaks the feature the row
represents (HARDENING_PLAN.md, Critical finding C1).  `get_protected_paths`
collects every file path still referenced by the database so
`cleanup_stale_files` can exclude them regardless of age.
"""

import asyncio
import logging
import os
import time
from typing import Callable, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_protected_paths(db: Session) -> Set[str]:
    """Return the absolute paths of every file still referenced by the database.

    A file is protected from age-based pruning when it is:
      - the audio sample or speaker embedding of a voice profile that has not
        been soft-deleted (``deleted_at IS NULL``), or
      - the synthesized output of any generation. `Generation` has a
        `deleted_at` column (HARDENING_PLAN.md finding L11), but no route
        ever sets it — it's an append-only audit trail per CLAUDE.md §6
        ("audit trails are never hard-deleted"), so unlike voice profiles,
        every generation's output stays protected regardless of that column
        until a future feature actually defines what soft-deleting one
        means for pruning.

    A soft-deleted voice profile's files fall out of this set and become
    eligible for ordinary age-based pruning, which is the intended way to
    reclaim space after a user deletes a profile.

    Args:
        db: An open database session used for read-only queries.

    Returns:
        A set of absolute filesystem paths. Blank paths (e.g. a `voice
        profile with ``status="failed"`` and no embedding) are omitted.
    """
    # Imported here, not at module scope, to avoid a circular import: the
    # models package imports `backend.core.database`, which has no
    # dependency on this module, but keeping the dependency local makes this
    # module safely importable from anywhere without ordering concerns.
    from backend.models.generation import Generation
    from backend.models.voice_profile import VoiceProfile

    protected: Set[str] = set()

    active_profiles = (
        db.query(VoiceProfile.audio_sample_path, VoiceProfile.embedding_path)
        .filter(VoiceProfile.deleted_at.is_(None))
        .all()
    )
    for audio_path, embedding_path in active_profiles:
        if audio_path:
            protected.add(os.path.abspath(audio_path))
        if embedding_path:
            protected.add(os.path.abspath(embedding_path))

    generation_outputs = db.query(Generation.output_audio_path).all()
    for (output_path,) in generation_outputs:
        if output_path:
            protected.add(os.path.abspath(output_path))

    return protected


def _run_cleanup_pass(
    directories: Iterable[str],
    max_age_hours: float,
    session_factory: Optional[Callable[[], Session]],
) -> int:
    """Compute protected paths and run one cleanup pass, synchronously.

    Bundles the DB query (`get_protected_paths`) and the directory walk
    (`cleanup_stale_files`) into a single blocking call so `periodic_cleanup`
    can offload the whole pass to a worker thread in one `asyncio.to_thread`
    call (HARDENING_PLAN.md, Low finding L4) instead of running either part
    directly on the event loop.

    Args:
        directories: Root directories to scan.
        max_age_hours: Age threshold passed through to `cleanup_stale_files`.
        session_factory: See `periodic_cleanup`.

    Returns:
        The number of files deleted.
    """
    protected_paths: Set[str] = set()
    if session_factory is not None:
        db = session_factory()
        try:
            protected_paths = get_protected_paths(db)
        finally:
            db.close()
    return cleanup_stale_files(
        directories, max_age_hours, protected_paths=protected_paths
    )


def cleanup_stale_files(
    directories: Iterable[str],
    max_age_hours: float,
    protected_paths: Iterable[str] = (),
) -> int:
    """Delete files older than ``max_age_hours`` under each directory.

    Walks each directory tree bottom-up so that subdirectories left empty by
    deleted files (e.g. a per-user `uploads/<user_id>/` folder) are removed
    too. Missing directories are skipped silently — there is nothing to
    prune. A single file or directory that cannot be removed (permissions,
    a concurrent delete) is logged and skipped rather than aborting the run.

    Any file whose absolute path appears in ``protected_paths`` is never
    deleted, regardless of age, and a directory containing only protected
    files is left in place.

    Args:
        directories: Root directories to scan (e.g. `uploads/`, `outputs/`).
        max_age_hours: Age threshold in hours; files last modified longer
            ago than this are deleted.
        protected_paths: Absolute paths of files that must never be pruned
            because they are still referenced by an active database row.
            See ``get_protected_paths``.

    Returns:
        The number of files deleted.
    """
    cutoff = time.time() - (max_age_hours * 3600)
    protected = set(protected_paths)
    deleted_count = 0

    for directory in directories:
        if not os.path.isdir(directory):
            logger.debug("Storage cleanup: %s does not exist, skipping.", directory)
            continue

        for root, dirnames, filenames in os.walk(directory, topdown=False):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                if os.path.abspath(file_path) in protected:
                    logger.debug(
                        "Storage cleanup: skipping %s — referenced by an active "
                        "database row.",
                        file_path,
                    )
                    continue
                try:
                    if os.path.getmtime(file_path) < cutoff:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.info("Storage cleanup: removed stale file %s", file_path)
                except OSError:
                    logger.exception("Storage cleanup: failed to remove %s", file_path)

            for dirname in dirnames:
                dir_path = os.path.join(root, dirname)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.debug(
                            "Storage cleanup: removed empty directory %s", dir_path
                        )
                except OSError:
                    logger.exception(
                        "Storage cleanup: failed to remove directory %s", dir_path
                    )

    if deleted_count:
        logger.info("Storage cleanup: removed %d stale file(s).", deleted_count)

    return deleted_count


async def periodic_cleanup(
    directories: List[str],
    interval_seconds: float,
    max_age_hours: float,
    session_factory: Optional[Callable[[], Session]] = None,
) -> None:
    """Run `cleanup_stale_files` on a fixed interval until cancelled.

    Intended to be launched as an `asyncio.Task` from the application
    lifespan and cancelled on shutdown. A failure in one pass is logged and
    swallowed so a single bad run doesn't kill the background loop.

    Args:
        directories: Root directories to scan on every pass.
        interval_seconds: Delay between passes.
        max_age_hours: Age threshold passed through to `cleanup_stale_files`.
        session_factory: A zero-argument callable that returns a new
            database session (typically ``backend.core.database.SessionLocal``),
            used each pass to compute the current set of protected paths via
            ``get_protected_paths`` before pruning. When omitted, no
            protection is applied — callers that skip this (e.g. unit tests
            exercising the loop in isolation) are responsible for the
            consequences.
    """
    try:
        while True:
            try:
                await asyncio.to_thread(
                    _run_cleanup_pass, directories, max_age_hours, session_factory
                )
            except Exception:
                logger.exception("Storage cleanup pass failed unexpectedly.")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Storage cleanup background task stopped.")
        raise
