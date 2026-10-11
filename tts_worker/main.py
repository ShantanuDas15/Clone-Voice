"""Entry point: ``uvicorn tts_worker.main:app --host 0.0.0.0 --port 8100`` (S4.3).

Settings come from the environment: ``TTS_WORKER_TOKEN`` (required, 32+ characters),
``TTS_WORKER_MODEL`` (``original``, ``turbo`` or ``nano``; default ``nano``) and
``TTS_WORKER_DEVICE`` (``cuda`` or ``cpu``; default ``cuda`` when available).
"""

import logging
import os

from tts_worker.app import create_app
from tts_worker.chatterbox_synth import ChatterboxSynthesizer

logging.basicConfig(level=logging.INFO)


def _device() -> str:
    """The configured device, else cuda when torch can see a GPU, else cpu."""
    configured = os.environ.get("TTS_WORKER_DEVICE")
    if configured:
        return configured
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


app = create_app(
    ChatterboxSynthesizer(os.environ.get("TTS_WORKER_MODEL", "nano"), _device()),
    os.environ.get("TTS_WORKER_TOKEN", ""),
)
