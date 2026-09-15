"""Utility script to provision SV2TTS model weights before startup.

The speaker encoder's pretrained weights ship inside the `resemblyzer`
package and download automatically on first use — this script just warms
that cache so the first real `load_models()` call doesn't pay the download
cost at request time.

The synthesizer and vocoder checkpoints are real Tacotron2/WaveRNN weights,
loaded via the architecture vendored at `backend/services/sv2tts/` (see
`THIRD_PARTY_NOTICE.md` there — MIT licensed, sourced from
https://huggingface.co/CorentinJ/SV2TTS). Two modes are available:

  - Default (no flags): presence + checksum check only. Makes no network
    calls for synthesizer.pt/vocoder.pt — safe to run in CI or as a
    pre-deploy gate without pulling ~424 MB every time.
  - `--fetch`: additionally downloads any missing or checksum-failing
    checkpoint from the pinned Hugging Face repo via `huggingface_hub`
    (resumable, retried, and idempotent — a file already present and
    checksum-verified is never re-downloaded).

Either way, `load_models()` (`backend.services.tts_pipeline`) is the
authoritative gate: it re-verifies each checksum itself and refuses to
start the server on anything missing, corrupted, tampered with, or
otherwise unable to load into the real model architecture
(HARDENING_PLAN.md, Critical finding C2). Neither mode of this script is
ever invoked automatically by the running server — provisioning is a
separate, explicit step from starting the app.

This script previously wrote placeholder byte strings to
`weights/tacotron.pt` and `weights/wavernn.pt` so the app *appeared* to have
checkpoints provisioned. That masked the missing-weights problem instead of
surfacing it. This script never creates or overwrites a checkpoint file
except via an explicit, checksum-verified `--fetch` download.
"""

import argparse
import logging
import os
import sys
from typing import List, Optional

from huggingface_hub import hf_hub_download

from backend.core.config import settings
from backend.services.sv2tts.checksum import load_manifest, verify_checksum

logger = logging.getLogger(__name__)

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    VoiceEncoder = None

REQUIRED_CHECKPOINTS = ("synthesizer.pt", "vocoder.pt")

# Real checkpoints only, MIT licensed — see THIRD_PARTY_NOTICE.md and
# weights_manifest.json for the pinned SHA256 of each file this repo trusts.
# encoder.pt in this same HF repo is NOT used: the speaker encoder's weights
# come from the resemblyzer package instead (_ensure_encoder_weights below).
HF_REPO_ID = "CorentinJ/SV2TTS"


def _ensure_encoder_weights() -> bool:
    """Download resemblyzer's pretrained VoiceEncoder weights into its cache.

    Returns:
        True on success; False if resemblyzer is missing or the download
        fails.
    """
    if VoiceEncoder is None:
        logger.error("resemblyzer is not installed. Run: pip install resemblyzer")
        return False
    try:
        VoiceEncoder("cpu")
        logger.info("VoiceEncoder weights ready.")
        return True
    except Exception:
        logger.exception("Failed to download/load VoiceEncoder weights.")
        return False


def _check_synthesizer_and_vocoder(weights_dir: str) -> bool:
    """Report whether synthesizer/vocoder checkpoints are present *and
    checksum-verified* at ``weights_dir``.

    Uses the same pinned manifest and verification routine as
    `load_models()` (`backend.services.tts_pipeline`,
    `backend.services.sv2tts.checksum`) so a provisioning or CI step fails
    with the same diagnosis the running server would hit at startup —
    before the server is even started, and before a large checkpoint file
    is ever deserialized. Makes no network calls.

    Args:
        weights_dir: Directory expected to hold both checkpoint files,
            typically ``settings.WEIGHTS_DIR``.

    Returns:
        True if both checkpoints are present at ``weights_dir`` and match
        their pinned SHA256 in `backend/weights_manifest.json`.
    """
    missing = [
        name
        for name in REQUIRED_CHECKPOINTS
        if not os.path.exists(os.path.join(weights_dir, name))
    ]
    if missing:
        logger.error(
            "Missing required checkpoint(s) in %s: %s. Run with --fetch to "
            "download them, or supply your own — see README.md 'Model "
            "Weights'. The server will refuse to start without them "
            "(backend.services.tts_pipeline.load_models).",
            weights_dir,
            ", ".join(missing),
        )
        return False

    try:
        manifest = load_manifest()
        for name in REQUIRED_CHECKPOINTS:
            verify_checksum(os.path.join(weights_dir, name), name, manifest)
    except RuntimeError as exc:
        logger.error("Checkpoint verification failed: %s", exc)
        return False

    logger.info(
        "Synthesizer and vocoder checkpoints found and checksum-verified in %s.",
        weights_dir,
    )
    return True


def _fetch_checkpoint(filename: str, weights_dir: str) -> str:
    """Download one checkpoint file from the pinned Hugging Face repo.

    Delegates to `huggingface_hub.hf_hub_download`, which provides
    resumable downloads (an interrupted transfer resumes from where it left
    off on the next attempt — no partial file is ever exposed at the final
    path) and automatic retry with backoff on transient network errors,
    rather than hand-rolled HTTP streaming.

    Args:
        filename: e.g. ``"synthesizer.pt"``.
        weights_dir: Destination directory; ``local_dir`` places the file
            at exactly ``weights_dir/filename``, matching what
            `load_models()` expects — not a symlink into an internal cache.

    Returns:
        The downloaded file's path (equal to ``os.path.join(weights_dir,
        filename)``).
    """
    return hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=filename,
        local_dir=weights_dir,
    )


def fetch_and_verify_checkpoints(weights_dir: str) -> bool:
    """Ensure synthesizer.pt/vocoder.pt are present and checksum-verified at
    ``weights_dir``, downloading whichever are missing or fail verification.

    Idempotent and network-frugal: a file already present and matching the
    pinned manifest is used as-is, never re-downloaded. A file that's
    present but fails checksum verification (corrupted, truncated, or
    tampered with) is treated as absent and re-fetched, since a known-bad
    local copy left in place would just make the next `load_models()` call
    fail with the same error this function exists to prevent.

    Args:
        weights_dir: Destination directory for both checkpoint files,
            created if it doesn't exist.

    Returns:
        True if both checkpoints end up present and checksum-verified.
    """
    os.makedirs(weights_dir, exist_ok=True)
    manifest = load_manifest()

    for name in REQUIRED_CHECKPOINTS:
        local_path = os.path.join(weights_dir, name)

        if os.path.exists(local_path):
            try:
                verify_checksum(local_path, name, manifest)
                logger.info(
                    "'%s' already present and checksum-verified — skipping "
                    "download.",
                    name,
                )
                continue
            except RuntimeError:
                logger.warning(
                    "'%s' is present but failed checksum verification — "
                    "re-downloading.",
                    name,
                )

        try:
            downloaded_path = _fetch_checkpoint(name, weights_dir)
        except Exception:
            logger.exception(
                "Failed to download '%s' from Hugging Face repo '%s'.",
                name,
                HF_REPO_ID,
            )
            return False

        try:
            verify_checksum(downloaded_path, name, manifest)
        except RuntimeError as exc:
            logger.error("Downloaded '%s' failed checksum verification: %s", name, exc)
            return False

        logger.info("Downloaded and checksum-verified: %s", downloaded_path)

    return True


def download_weights() -> bool:
    """Provision what can be automated without a network call, and report
    what's missing.

    Returns:
        True only if the speaker encoder is ready AND real synthesizer and
        vocoder checkpoints are already present and checksum-verified at
        ``settings.WEIGHTS_DIR``. No placeholder or fake checkpoint is ever
        written by this function (HARDENING_PLAN.md, Critical finding C2).
    """
    encoder_ready = _ensure_encoder_weights()
    checkpoints_ready = _check_synthesizer_and_vocoder(settings.WEIGHTS_DIR)
    return encoder_ready and checkpoints_ready


def fetch_weights() -> bool:
    """Provision everything, downloading synthesizer/vocoder checkpoints
    from Hugging Face if needed (`--fetch` mode).

    This is the only code path in this module that makes network calls for
    synthesizer.pt/vocoder.pt. It is never triggered automatically by the
    running server: `main.py`'s lifespan calls `load_models()` directly,
    which never fetches anything over the network — provisioning is always
    a separate, explicit, operator-initiated step.

    Returns:
        True if the speaker encoder is ready and both checkpoints end up
        present and checksum-verified at ``settings.WEIGHTS_DIR``.
    """
    encoder_ready = _ensure_encoder_weights()
    checkpoints_ready = fetch_and_verify_checkpoints(settings.WEIGHTS_DIR)
    return encoder_ready and checkpoints_ready


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list to parse instead of ``sys.argv[1:]`` — lets
            tests exercise the dispatch logic directly.

    Returns:
        A process exit code: ``0`` if everything is ready, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help=(
            "Download synthesizer.pt/vocoder.pt from Hugging Face "
            f"({HF_REPO_ID}, MIT licensed) into WEIGHTS_DIR if missing or "
            "checksum-invalid, then verify them. Without this flag, only "
            "checks presence/checksum of files already there — no network "
            "calls are made for these two files unless --fetch is passed."
        ),
    )
    args = parser.parse_args(argv)

    ready = fetch_weights() if args.fetch else download_weights()
    return 0 if ready else 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
