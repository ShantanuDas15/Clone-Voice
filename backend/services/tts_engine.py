"""The interface every speech engine implements (SPEECH_QUALITY_PLAN.md S4.1).

The API and the inference pipeline talk to a ``TTSEngine`` and never to a model directly, so a
better engine (one that takes emotion, or speaks at a higher sample rate) can be added behind
a setting and the current SV2TTS engine stays as the fallback.

What the pipeline keeps for every engine: the inference slot (queue, wait and per-stage
timeouts, shutdown drain), the output quality gate and its retries, loudness levelling, the
WAV provenance metadata and erasure. What an engine owns: how a voice is captured, and how
text becomes a waveform.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Awaitable, Callable, Optional, Tuple

import numpy as np

from backend.core.config import settings

# Runs one blocking stage of an engine on a worker thread, under the inference slot and its
# timeout, and records the stage's metrics: ``await run_stage("vocoder", fn, *args)``.
StageRunner = Callable[..., Awaitable[Any]]

NEUTRAL = "neutral"


@dataclass(frozen=True)
class EngineCapabilities:
    """What an engine can do, for health checks, request validation and the UI."""

    name: str
    version: str
    sample_rate: int
    max_chars: int
    emotions: Tuple[str, ...]


@dataclass(frozen=True)
class VoiceConditioning:
    """What an engine needs to speak as one voice.

    Tagged with the engine and its version so a profile made for one engine is never fed to
    another (SPEECH_QUALITY_PLAN.md S4.5 stores these per profile). An embedding engine
    (SV2TTS) uses ``embedding``; a reference-audio engine (Chatterbox) uses
    ``reference_audio``, a short clean WAV of the speaker.
    """

    engine: str
    version: str
    embedding: Optional[np.ndarray] = None
    reference_audio: Optional[bytes] = None


@dataclass(frozen=True)
class SynthesisStyle:
    """How to deliver the text. Every engine today is neutral only (S5 adds the rest)."""

    emotion: str = NEUTRAL
    intensity: float = 0.0


@dataclass(frozen=True)
class SynthesisResult:
    """The raw waveform an engine produced, before any gate, levelling or storage."""

    waveform: np.ndarray
    sample_rate: int
    # How many decodes were cut off by the model's length cap (fed to the quality gate).
    truncated_decodes: int = 0


class EngineUnavailableError(RuntimeError):
    """The engine's backend (for example a remote inference worker) cannot be reached or refused.

    ``reason`` names the cause for metrics: ``unavailable``, ``busy`` or ``circuit_open``.
    """

    def __init__(self, message: str, reason: str = "unavailable") -> None:
        """Keep the message and the metric reason."""
        super().__init__(message)
        self.reason = reason


class EngineBusyError(EngineUnavailableError):
    """The backend is up but at capacity: worth a fallback, not a sign of an outage."""

    def __init__(self, message: str) -> None:
        """A busy backend."""
        super().__init__(message, reason="busy")


class UnsupportedStyleError(ValueError):
    """The requested style is outside the engine's capabilities."""


class WrongEngineError(ValueError):
    """The voice was prepared by a different engine (or engine version)."""


class TTSEngine(ABC):
    """A text-to-speech engine."""

    name: str
    version: str
    # True when the engine conditions on the speaker's reference audio rather than an embedding.
    needs_reference_audio: bool = False

    @abstractmethod
    def capabilities(self) -> EngineCapabilities:
        """Describe what this engine supports."""

    @abstractmethod
    def health(self, expected_device: Optional[str] = None) -> dict:
        """Report whether the engine's models are loaded; ``ready`` is the verdict."""

    @abstractmethod
    def conditioning_from_array(self, embedding: np.ndarray) -> VoiceConditioning:
        """Wrap a stored profile embedding as this engine's conditioning."""

    def conditioning_from_profile(
        self, embedding: np.ndarray, reference_audio_path: Optional[str]
    ) -> VoiceConditioning:
        """Build the conditioning for a stored profile; embedding engines ignore the audio."""
        return self.conditioning_from_array(embedding)

    @abstractmethod
    async def prepare_voice(self, audio: np.ndarray) -> VoiceConditioning:
        """Capture a voice from preprocessed 16 kHz mono audio.

        Raises the inference queue/timeout errors of the pipeline when the engine is busy.
        """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        conditioning: VoiceConditioning,
        style: Optional[SynthesisStyle],
        *,
        run_stage: StageRunner,
        truncation_retries: int = 0,
    ) -> SynthesisResult:
        """Turn ``text`` into a waveform in the voice of ``conditioning``.

        Every blocking model call goes through ``run_stage`` so the pipeline's timeouts and
        metrics apply. ``truncation_retries`` is how many earlier attempts of this request
        were cut off by the model's length cap, so the engine can decode more conservatively.
        """

    def check_request(
        self, conditioning: VoiceConditioning, style: Optional[SynthesisStyle]
    ) -> None:
        """Refuse a voice from another engine or a style this engine cannot deliver."""
        if conditioning.engine != self.name or conditioning.version != self.version:
            raise WrongEngineError(
                f"voice made for {conditioning.engine} v{conditioning.version}, "
                f"not {self.name} v{self.version}"
            )
        wanted = (style.emotion if style else NEUTRAL) or NEUTRAL
        if wanted not in self.capabilities().emotions:
            raise UnsupportedStyleError(
                f"{self.name} cannot speak with emotion {wanted!r}"
            )


@lru_cache(maxsize=None)
def _build(name: str) -> TTSEngine:
    """Create the engine registered under ``name`` (once)."""
    if name == "sv2tts":
        from backend.services.sv2tts_engine import Sv2ttsEngine

        return Sv2ttsEngine()
    if name.startswith("chatterbox"):
        from backend.services.chatterbox_engine import ChatterboxEngine

        return ChatterboxEngine(name)
    raise ValueError(f"unknown TTS engine {name!r}")


def get_engine() -> TTSEngine:
    """Return the engine selected by ``TTS_ENGINE``."""
    return _build(settings.TTS_ENGINE)


def get_fallback_engine(primary: TTSEngine) -> Optional[TTSEngine]:
    """The engine to use when ``primary`` is unavailable, or None.

    None when the fallback is switched off or the primary already is the fallback. Only an
    engine that runs in this process qualifies, so the fallback cannot itself be unavailable.
    """
    name = settings.TTS_FALLBACK_ENGINE
    if name == "none" or name == primary.name:
        return None
    return _build(name)
