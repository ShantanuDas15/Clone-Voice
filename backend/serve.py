"""Container entrypoint: prepare storage, provision weights, run uvicorn.

``python -m backend.serve`` is the image's CMD. It exists because the platforms
this runs on need three things a bare ``uvicorn`` command cannot do:

* listen on the port the platform injects (``$PORT``);
* cope with a persistent volume that is mounted root-owned, while the app
  itself stays unprivileged (uid 1000): when started as root it chowns the
  storage directories, then drops to that user before doing anything else;
* on a fresh volume, download the checksum-verified model checkpoints first
  (only when ``FETCH_WEIGHTS_ON_START`` is set).

It ends in ``os.execvp``, so uvicorn replaces this process and keeps PID 1:
SIGTERM reaches uvicorn directly and the graceful-shutdown path
(HARDENING_PLAN.md P2-L4) is unchanged.
"""

import argparse
import logging
import os
import shlex
import sys
from typing import List, Mapping, Optional

from backend.core.config import settings

logger = logging.getLogger("backend.serve")

DEFAULT_PORT = 8000
# uvicorn's wait for open requests on SIGTERM. Together with
# INFERENCE_SHUTDOWN_DRAIN_TIMEOUT_SECONDS (30) it sets how long the platform
# must wait before SIGKILL: docker-compose stop_grace_period and Railway's
# drainingSeconds are both 70 (HARDENING_PLAN.md P2-L4).
GRACEFUL_SHUTDOWN_SECONDS = 30

# The unprivileged user the Dockerfile creates (`useradd --uid 1000`).
APP_UID = 1000
APP_GID = 1000
APP_HOME = "/home/appuser"


def json_log_handler() -> logging.Handler:
    """A stderr handler emitting the same JSON shape as the app's own logs
    (timestamp, level, logger, message), so the lines this entrypoint prints
    before uvicorn starts don't break a JSON log pipeline."""
    from pythonjsonlogger.json import JsonFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    return handler


def resolve_port(environ: Mapping[str, str]) -> int:
    """Return the port to listen on: ``$PORT`` if set, else 8000."""
    raw = environ.get("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"PORT must be an integer, got {raw!r}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"PORT must be between 1 and 65535, got {port}")
    return port


def uvicorn_command(port: int) -> List[str]:
    """Build the uvicorn argv.

    Runs uvicorn as ``<this interpreter> -m uvicorn`` rather than resolving a
    ``uvicorn`` executable through PATH, which could belong to a different
    environment than the one this entrypoint (and the app's dependencies) is in.

    ``--workers 1`` is load-bearing: the inference semaphore and the rate
    limiter are process-local (HARDENING_PLAN.md H6, M3, H7).
    """
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--workers",
        "1",
        "--timeout-graceful-shutdown",
        str(GRACEFUL_SHUTDOWN_SECONDS),
    ]


def storage_dirs() -> List[str]:
    """The three directories the app writes to."""
    return [settings.UPLOAD_DIR, settings.OUTPUT_DIR, settings.WEIGHTS_DIR]


def _chown_if_needed(path: str, uid: int, gid: int) -> None:
    """chown `path` (never following a symlink) unless it is already ours."""
    stat = os.lstat(path)
    if stat.st_uid != uid or stat.st_gid != gid:
        os.lchown(path, uid, gid)


def chown_storage(dirs: List[str], uid: int = APP_UID, gid: int = APP_GID) -> None:
    """Create the storage directories and hand them, and their contents, to
    the app user. Only called while running as root."""
    for directory in dirs:
        os.makedirs(directory, exist_ok=True)
    # A volume mount point (DATA_DIR) is root-owned on first boot; the
    # directories inside it are chowned below, the mount point itself only here.
    if settings.DATA_DIR.strip():
        _chown_if_needed(settings.DATA_DIR, uid, gid)
    for directory in dirs:
        _chown_if_needed(directory, uid, gid)
        for root, subdirs, files in os.walk(directory):
            for name in subdirs + files:
                _chown_if_needed(os.path.join(root, name), uid, gid)


def drop_privileges(uid: int = APP_UID, gid: int = APP_GID) -> None:
    """Permanently become the unprivileged app user."""
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.geteuid() != uid:
        raise RuntimeError("failed to drop root privileges")
    os.environ["HOME"] = APP_HOME
    os.environ["USER"] = "appuser"


def ensure_writable(dirs: List[str]) -> None:
    """Create the storage directories and fail clearly if they can't be used."""
    for directory in dirs:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass  # reported by the access check just below
        if not os.access(directory, os.W_OK | os.X_OK):
            raise PermissionError(
                f"Storage directory '{directory}' is not writable by uid "
                f"{os.geteuid()}. A freshly mounted volume is owned by root: "
                "start the container as root (on Railway, set the variable "
                "RAILWAY_RUN_UID=0) and this entrypoint will chown it and "
                "drop to the app user."
            )


def provision_weights() -> bool:
    """Download missing or corrupt checkpoints when FETCH_WEIGHTS_ON_START."""
    if not settings.FETCH_WEIGHTS_ON_START:
        return True
    # Imported here: huggingface_hub is only needed on this path.
    from backend.download_weights import fetch_and_verify_checkpoints

    logger.info("Provisioning model weights in %s", settings.WEIGHTS_DIR)
    return fetch_and_verify_checkpoints(settings.WEIGHTS_DIR)


def prepare(dirs: Optional[List[str]] = None) -> None:
    """Storage, privileges and weights, in that order. Raises on failure."""
    dirs = storage_dirs() if dirs is None else dirs
    if os.geteuid() == 0:
        chown_storage(dirs)
        drop_privileges()
    ensure_writable(dirs)
    if not provision_weights():
        raise RuntimeError(
            "Model weights could not be provisioned; see the errors above."
        )


def main(argv: Optional[List[str]] = None) -> int:
    """Prepare the container, then replace this process with uvicorn."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="prepare storage and print the uvicorn command, without starting it",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, handlers=[json_log_handler()])
    try:
        command = uvicorn_command(resolve_port(os.environ))
        prepare()
    except (ValueError, OSError, RuntimeError) as error:
        logger.error("%s", error)
        return 1

    if args.dry_run:
        print(shlex.join(command))
        return 0
    logger.info("Starting: %s", shlex.join(command))
    os.execvp(command[0], command)
    return 0  # pragma: no cover - execvp does not return


if __name__ == "__main__":
    sys.exit(main())
