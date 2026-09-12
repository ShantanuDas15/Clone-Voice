"""Background pruning of stale files in the uploads/ and outputs/ directories.

Uploaded audio samples and synthesized outputs accumulate on local disk with
no natural expiry.  Left unchecked this guarantees eventual disk exhaustion
(HARDENING_PLAN.md, Phase 2 — Storage Cleanup).  `cleanup_stale_files` prunes
anything older than a configurable age threshold; `periodic_cleanup` runs it
on a fixed interval for the lifetime of the application.
"""

import asyncio
import logging
import os
import time
from typing import Iterable, List

logger = logging.getLogger(__name__)


def cleanup_stale_files(directories: Iterable[str], max_age_hours: float) -> int:
    """Delete files older than ``max_age_hours`` under each directory.

    Walks each directory tree bottom-up so that subdirectories left empty by
    deleted files (e.g. a per-user `uploads/<user_id>/` folder) are removed
    too. Missing directories are skipped silently — there is nothing to
    prune. A single file or directory that cannot be removed (permissions,
    a concurrent delete) is logged and skipped rather than aborting the run.

    Args:
        directories: Root directories to scan (e.g. `uploads/`, `outputs/`).
        max_age_hours: Age threshold in hours; files last modified longer
            ago than this are deleted.

    Returns:
        The number of files deleted.
    """
    cutoff = time.time() - (max_age_hours * 3600)
    deleted_count = 0

    for directory in directories:
        if not os.path.isdir(directory):
            logger.debug("Storage cleanup: %s does not exist, skipping.", directory)
            continue

        for root, dirnames, filenames in os.walk(directory, topdown=False):
            for filename in filenames:
                file_path = os.path.join(root, filename)
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
    directories: List[str], interval_seconds: float, max_age_hours: float
) -> None:
    """Run `cleanup_stale_files` on a fixed interval until cancelled.

    Intended to be launched as an `asyncio.Task` from the application
    lifespan and cancelled on shutdown. A failure in one pass is logged and
    swallowed so a single bad run doesn't kill the background loop.
    """
    try:
        while True:
            try:
                cleanup_stale_files(directories, max_age_hours)
            except Exception:
                logger.exception("Storage cleanup pass failed unexpectedly.")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Storage cleanup background task stopped.")
        raise
