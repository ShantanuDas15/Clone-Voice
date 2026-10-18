"""Chatterbox speech engines, served by a separate inference worker (SPEECH_QUALITY_PLAN.md S4.3).

Chatterbox cannot share this application's Python environment (it pins ``torch==2.6.0``,
``transformers==5.2.0`` and ``gradio``; the app pins ``torch==2.13.0`` and a hash-locked
dependency set), so it runs in its own service, ``tts_worker/``. This module is the app's side:
a ``TTSEngine`` that sends the text and the speaker's reference audio to the worker over HTTP and
returns the waveform, under the same inference slot, timeouts and quality gate as any engine.

The worker is stateless and must not keep user audio; the app sends the reference on every
request. The wire protocol is small and versioned by path (``/v1``): see ``tts_worker/app.py``.
"""

import io
import logging
import threading
import time
from typing import Callable, Optional, Tuple

import httpx
import numpy as np
import soundfile as sf

from backend.core.config import settings
from backend.services.audio_processing import load_reference_audio
from backend.services.tts_engine import (NEUTRAL, EngineBusyError,
                                         EngineCapabilities,
                                         EngineRejectedReferenceError,
                                         EngineUnavailableError, StageRunner,
                                         SynthesisResult, SynthesisStyle,
                                         TTSEngine, VoiceConditioning,
                                         WrongEngineError)

logger = logging.getLogger(__name__)

# The wire protocol, mirrored in tts_worker/app.py (a test keeps the two in step).
PATH_SYNTHESIZE = "/v1/synthesize"
PATH_HEALTH = "/health"
HEADER_SAMPLE_RATE = "X-Sample-Rate"
HEADER_TRUNCATED = "X-Truncated-Decodes"
HEADER_MODEL = "X-Model"
# The worker's 422 detail for a reference clip it cannot use (mirrored in tts_worker/app.py).
REFERENCE_REJECTED_DETAIL = "the reference audio could not be used"

# Engine id (the TTS_ENGINE value) to the model the worker must be serving.
VARIANTS = {
    "chatterbox": "original",
    "chatterbox_turbo": "turbo",
    "chatterbox_nano": "nano",
}
SAMPLE_RATE = 24000
MAX_CHARS = 500
# Sound-event tags the Turbo and Nano models make from the text (SPEECH_QUALITY_STUDY.md,
# Paralinguistic tags); the original model does not.
NONVERBAL = ("laugh", "chuckle", "cough")
HEALTH_TIMEOUT_SECONDS = 2.0


def _detail(response: httpx.Response) -> Optional[str]:
    """The ``detail`` text of a worker error reply, or None when it has none."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) else None


def _is_busy(response: httpx.Response) -> bool:
    """True for the worker's own 'busy' reply (a 503 that says so), not any 503."""
    return _detail(response) == "busy"


class CircuitBreaker:
    """Stops calling a backend that keeps failing, then probes it once after a cooldown.

    Closed: calls go through. ``threshold`` failures in a row open it. Open: ``allow`` is false
    until ``cooldown`` seconds pass; then exactly one caller is allowed through (half-open). That
    probe's success closes the breaker, its failure re-opens it for another cooldown.
    """

    def __init__(
        self,
        threshold: int,
        cooldown: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a closed breaker."""
        self.threshold = threshold
        self.cooldown = cooldown
        self.clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._probing = False

    @property
    def state(self) -> str:
        """``closed``, ``open`` or ``half_open``."""
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._probing or self.clock() - self._opened_at >= self.cooldown:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        """True if a call may go through now."""
        with self._lock:
            if self._opened_at is None:
                return True
            if not self._probing and self.clock() - self._opened_at >= self.cooldown:
                self._probing = True
                return True
            return False

    def success(self) -> None:
        """A call worked: close the breaker."""
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probing = False

    def failure(self) -> None:
        """A call found the backend unavailable."""
        with self._lock:
            self._failures += 1
            if self._probing or self._failures >= self.threshold:
                self._opened_at = self.clock()
                self._probing = False


class ChatterboxEngine(TTSEngine):
    """One Chatterbox model (original, Turbo or Nano) behind the inference worker."""

    version = "1"
    needs_reference_audio = True

    def __init__(self, name: str) -> None:
        """Create the engine registered as ``name`` (a key of ``VARIANTS``)."""
        if name not in VARIANTS:
            raise ValueError(f"unknown Chatterbox engine {name!r}")
        self.name = name
        self.model = VARIANTS[name]
        # Tests inject an httpx transport; production leaves it None.
        self.transport: Optional[httpx.BaseTransport] = None
        self.breaker = CircuitBreaker(
            settings.TTS_WORKER_BREAKER_FAILURES,
            settings.TTS_WORKER_BREAKER_COOLDOWN_SECONDS,
        )

    def capabilities(self) -> EngineCapabilities:
        """24 kHz, English, neutral only (no labelled emotion; intensity is ``exaggeration``)."""
        return EngineCapabilities(
            name=self.name,
            version=self.version,
            sample_rate=SAMPLE_RATE,
            max_chars=MAX_CHARS,
            emotions=(NEUTRAL,),
            nonverbal_tags=NONVERBAL if self.model in ("turbo", "nano") else (),
        )

    def _client(self, timeout: float) -> httpx.Client:
        """An HTTP client for the worker, with its bearer token."""
        return httpx.Client(
            base_url=settings.TTS_WORKER_URL,
            headers={"Authorization": f"Bearer {settings.TTS_WORKER_TOKEN}"},
            timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
            transport=self.transport,
        )

    def health(self, expected_device: Optional[str] = None) -> dict:
        """Ask the worker whether it is up and serving this model; never raises."""
        try:
            with self._client(HEALTH_TIMEOUT_SECONDS) as client:
                response = client.get(PATH_HEALTH)
            body = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {
                "ready": False,
                "worker": {"reachable": False, "circuit": self.breaker.state},
            }
        serving = body.get("model")
        ready = bool(body.get("ready")) and serving == self.model
        return {
            "ready": ready,
            "worker": {
                "reachable": True,
                "model": serving,
                "device": body.get("device"),
                "circuit": self.breaker.state,
            },
        }

    def conditioning_from_array(self, embedding: np.ndarray) -> VoiceConditioning:
        """A conditioning with no reference audio yet (use ``conditioning_from_profile``)."""
        return VoiceConditioning(self.name, self.version, embedding=embedding)

    def conditioning_from_profile(
        self, embedding: np.ndarray, reference_audio_path: Optional[str]
    ) -> VoiceConditioning:
        """Read the profile's retained sample as the speaker reference (blocking)."""
        if not reference_audio_path:
            raise WrongEngineError("this voice has no stored reference audio")
        return VoiceConditioning(
            self.name,
            self.version,
            embedding=embedding,
            reference_audio=load_reference_audio(reference_audio_path),
        )

    async def prepare_voice(self, audio: np.ndarray) -> VoiceConditioning:
        """Capture the voice at upload.

        Every profile keeps the SV2TTS speaker embedding (it drives the multi-clip agreement
        check and the fallback engine); this engine reads the retained audio at synthesis.
        """
        from backend.services.sv2tts_engine import Sv2ttsEngine

        sv2tts = await Sv2ttsEngine().prepare_voice(audio)
        return self.conditioning_from_array(sv2tts.embedding)

    def _call_worker(
        self,
        text: str,
        reference: bytes,
        truncation_retries: int,
        exaggeration: Optional[float] = None,
    ) -> Tuple[np.ndarray, int, int]:
        """Call the worker unless its circuit is open; track outages for the breaker.

        An outage (unreachable, timeout, 5xx, refused token) counts towards opening the circuit;
        a busy reply does not (the worker is up), and neither does a rejected request (the
        request was bad, not the worker).
        """
        if not self.breaker.allow():
            raise EngineUnavailableError(
                "the inference worker is being skipped after repeated failures",
                reason="circuit_open",
            )
        try:
            result = self._post_synthesis(
                text, reference, truncation_retries, exaggeration
            )
        except (EngineBusyError, EngineRejectedReferenceError):
            self.breaker.success()  # it answered, so it is alive
            raise
        except EngineUnavailableError:
            self.breaker.failure()
            raise
        except RuntimeError:
            self.breaker.success()  # it answered; the request was the problem
            raise
        self.breaker.success()
        return result

    def _post_synthesis(
        self,
        text: str,
        reference: bytes,
        truncation_retries: int,
        exaggeration: Optional[float] = None,
    ) -> Tuple[np.ndarray, int, int]:
        """POST one synthesis to the worker; return (waveform, sample rate, truncated decodes)."""
        form = {
            "text": text,
            "model": self.model,
            "truncation_retries": str(truncation_retries),
        }
        if exaggeration is not None:
            form["exaggeration"] = repr(float(exaggeration))
        try:
            with self._client(settings.TTS_WORKER_TIMEOUT_SECONDS) as client:
                response = client.post(
                    PATH_SYNTHESIZE,
                    data=form,
                    files={"reference": ("reference.wav", reference, "audio/wav")},
                )
        except httpx.TimeoutException:
            raise EngineUnavailableError("the inference worker timed out") from None
        except httpx.HTTPError:
            raise EngineUnavailableError(
                "the inference worker is unreachable"
            ) from None

        status = response.status_code
        if status in (401, 403):
            logger.error("The inference worker refused the service token (%d)", status)
            raise EngineUnavailableError("the inference worker refused the request")
        if status == 503 and _is_busy(response):
            raise EngineBusyError("the inference worker is busy")
        if status == 422 and _detail(response) == REFERENCE_REJECTED_DETAIL:
            raise EngineRejectedReferenceError(
                "the inference worker cannot use this voice's reference audio"
            )
        if status >= 500:
            raise EngineUnavailableError(f"the inference worker failed ({status})")
        if status != 200:
            raise RuntimeError(f"the inference worker rejected the request ({status})")

        try:
            waveform, rate = sf.read(io.BytesIO(response.content), dtype="float32")
            truncated = int(response.headers.get(HEADER_TRUNCATED, "0"))
        except (RuntimeError, ValueError):
            raise EngineUnavailableError(
                "the inference worker sent unreadable audio"
            ) from None
        if waveform.ndim != 1:
            waveform = waveform.mean(axis=1)
        return waveform, int(rate), truncated

    async def synthesize(
        self,
        text: str,
        conditioning: VoiceConditioning,
        style: Optional[SynthesisStyle],
        *,
        run_stage: StageRunner,
        truncation_retries: int = 0,
    ) -> SynthesisResult:
        """Send the text and reference to the worker as one timed ``worker`` stage."""
        self.check_request(conditioning, style)
        if not conditioning.reference_audio:
            raise WrongEngineError("this voice has no reference audio")
        # Only the original model has the control; the others would ignore it, so don't send it.
        exaggeration = (
            style.exaggeration if style and self.model == "original" else None
        )
        waveform, rate, truncated = await run_stage(
            "worker",
            self._call_worker,
            text,
            conditioning.reference_audio,
            truncation_retries,
            exaggeration,
        )
        return SynthesisResult(waveform, rate, truncated)
