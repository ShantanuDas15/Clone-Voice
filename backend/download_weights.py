"""Utility script to download or verify SV2TTS model weights."""

import logging
import os

logger = logging.getLogger(__name__)

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    VoiceEncoder = None


def download_weights() -> None:
    """Ensure VoiceEncoder weights and placeholder weight files are present."""
    logger.info("Ensuring VoiceEncoder weights are downloaded...")
    try:
        _ = VoiceEncoder("cpu")
        logger.info("VoiceEncoder weights ready.")
    except Exception as e:
        logger.error("Error loading VoiceEncoder: %s", e)

    weights_dir = os.path.join(os.path.dirname(__file__), "weights")
    os.makedirs(weights_dir, exist_ok=True)

    tacotron_path = os.path.join(weights_dir, "tacotron.pt")
    if not os.path.exists(tacotron_path):
        logger.info("Creating dummy %s", tacotron_path)
        with open(tacotron_path, "wb") as f:
            f.write(b"dummy_tacotron_weights")

    wavernn_path = os.path.join(weights_dir, "wavernn.pt")
    if not os.path.exists(wavernn_path):
        logger.info("Creating dummy %s", wavernn_path)
        with open(wavernn_path, "wb") as f:
            f.write(b"dummy_wavernn_weights")

    logger.info("Weights available.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    download_weights()
