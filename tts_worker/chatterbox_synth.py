"""The Chatterbox model behind the worker (SPEECH_QUALITY_PLAN.md S4.3).

Imports the model library lazily so the rest of the worker can be tested without it. Needs the
GitHub master branch of ``chatterbox-tts`` for the Nano model (the 0.1.7 release lacks it).
"""

import logging
import os
import tempfile
import threading
from typing import Tuple

import numpy as np

logger = logging.getLogger("tts_worker")

MODELS = ("original", "turbo", "nano")


class ChatterboxSynthesizer:
    """One Chatterbox model on one device."""

    def __init__(self, model: str, device: str) -> None:
        """Load ``model`` (original, turbo or nano) onto ``device`` (cuda or cpu)."""
        if model not in MODELS:
            raise ValueError(f"model must be one of {MODELS}")
        self.model = model
        self.device = device
        if model == "original":
            from chatterbox.tts import ChatterboxTTS

            self._tts = ChatterboxTTS.from_pretrained(device=device)
        else:
            from chatterbox.tts_turbo import ChatterboxTurboTTS

            self._tts = ChatterboxTurboTTS.from_pretrained(
                device=device, nano=(model == "nano")
            )
        self.sample_rate = int(self._tts.sr)
        # The model keeps per-speaker state (the prepared conditioning): one call at a time.
        self._lock = threading.Lock()

    def synthesize(
        self, text: str, reference_wav: bytes, truncation_retries: int
    ) -> Tuple[np.ndarray, int]:
        """Clone the reference voice for ``text``.

        ``truncation_retries`` is accepted for protocol compatibility; Chatterbox has no
        frame cap to truncate against, so it is unused.
        """
        # The model library reads the reference from a path; the file lives only for this call.
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(reference_wav)
            with self._lock:
                try:
                    self._tts.prepare_conditionals(path)
                except Exception as error:
                    raise ValueError("the reference audio could not be used") from error
                wav = self._tts.generate(text)
        finally:
            try:
                os.remove(path)
            except OSError:
                logger.warning("Could not remove a temporary reference file")
        waveform = np.asarray(wav.squeeze().cpu().numpy(), dtype=np.float32)
        return waveform, self.sample_rate
