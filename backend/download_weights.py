"""Utility script to provision SV2TTS model weights before startup.

The speaker encoder's pretrained weights ship inside the `resemblyzer`
package and download automatically on first use — this script just warms
that cache so the first real `load_models()` call doesn't pay the download
cost at request time.

The synthesizer and vocoder checkpoints are NOT bundled or auto-downloaded
here yet (that is `--fetch` mode, a follow-up — see HARDENING_PLAN.md
Milestone C2.2). An operator must manually place the real checkpoints —
sourced from https://huggingface.co/CorentinJ/SV2TTS (MIT licensed; only
`synthesizer.pt` and `vocoder.pt` are needed, `encoder.pt` is unused — see
`backend/services/sv2tts/THIRD_PARTY_NOTICE.md`) — at
`WEIGHTS_DIR/synthesizer.pt` and `WEIGHTS_DIR/vocoder.pt` (see README.md,
"Model Weights") before starting the server. `load_models()`
(`backend.services.tts_pipeline`) verifies each file's SHA256 against
`backend/weights_manifest.json` and raises `RuntimeError` — refusing to
start — on anything missing, corrupted, tampered with, or otherwise unable
to load into the real Tacotron2/WaveRNN architecture
(HARDENING_PLAN.md, Critical finding C2).

This script previously wrote placeholder byte strings to
`weights/tacotron.pt` and `weights/wavernn.pt` so the app *appeared* to have
checkpoints provisioned. That masked the missing-weights problem instead of
surfacing it. This script no longer creates or overwrites any checkpoint
file — it only reports what is present and checksum-verified.
"""

import logging
import os
import sys

from backend.core.config import settings
from backend.services.sv2tts.checksum import load_manifest, verify_checksum

logger = logging.getLogger(__name__)

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    VoiceEncoder = None

REQUIRED_CHECKPOINTS = ("synthesizer.pt", "vocoder.pt")


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
    is ever deserialized.

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
            "Missing required checkpoint(s) in %s: %s. These must be supplied "
            "manually — see README.md 'Model Weights' for how to provision "
            "them. The server will refuse to start without them "
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


def download_weights() -> bool:
    """Provision what can be automated and report what still needs a human.

    Returns:
        True only if the speaker encoder is ready AND real synthesizer and
        vocoder checkpoints are already present at ``settings.WEIGHTS_DIR``.
        No placeholder or fake checkpoint is ever written by this function
        (HARDENING_PLAN.md, Critical finding C2) — an operator must supply
        real weights themselves.
    """
    encoder_ready = _ensure_encoder_weights()
    checkpoints_ready = _check_synthesizer_and_vocoder(settings.WEIGHTS_DIR)
    return encoder_ready and checkpoints_ready


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ready = download_weights()
    sys.exit(0 if ready else 1)
