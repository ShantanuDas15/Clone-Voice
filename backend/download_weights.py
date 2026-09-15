"""Utility script to provision SV2TTS model weights before startup.

The speaker encoder's pretrained weights ship inside the `resemblyzer`
package and download automatically on first use — this script just warms
that cache so the first real `load_models()` call doesn't pay the download
cost at request time.

The synthesizer and vocoder checkpoints are NOT bundled or auto-downloaded
here. Unlike the encoder, no public, freely licensable TorchScript-serialized
Tacotron2/WaveRNN checkpoint compatible with this pipeline's
`torch.jit.load` interface (`backend.services.tts_pipeline.load_models`) is
available to fetch automatically. An operator must supply real checkpoints
at `WEIGHTS_DIR/synthesizer.pt` and `WEIGHTS_DIR/vocoder.pt` (see README.md,
"Model Weights") before starting the server. `load_models()` raises
`RuntimeError` and the server refuses to start rather than run with missing
or invalid weights (HARDENING_PLAN.md, Critical finding C2).

This script previously wrote placeholder byte strings to
`weights/tacotron.pt` and `weights/wavernn.pt` so the app *appeared* to have
checkpoints provisioned. That masked the missing-weights problem instead of
surfacing it: `torch.jit.load` failed on the garbage bytes at server
startup, but anything checking only `Path.exists()` (this script included)
was fooled into reporting readiness. This script no longer creates or
overwrites any checkpoint file — it only reports what is present.
"""

import logging
import os
import sys

from backend.core.config import settings

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
    """Report whether synthesizer/vocoder checkpoints are present at ``weights_dir``.

    This is a presence check only — it does not attempt to validate that the
    files are loadable TorchScript modules. That check belongs solely to
    ``load_models()`` (`backend.services.tts_pipeline`), which the running
    server calls at startup and which refuses to start on an invalid or
    missing checkpoint. Reporting presence here lets a provisioning or CI
    step fail before the server is even started.

    Args:
        weights_dir: Directory expected to hold both checkpoint files,
            typically ``settings.WEIGHTS_DIR``.

    Returns:
        True if both checkpoints are present at ``weights_dir``.
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
    logger.info("Synthesizer and vocoder checkpoints found in %s.", weights_dir)
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
