"""Core text-to-speech inference pipeline."""

import asyncio
import logging
import os
import uuid

import numpy as np
import soundfile as sf
import torch

from backend.core.config import settings

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    VoiceEncoder = None

logger = logging.getLogger(__name__)

_encoder = None
_synthesizer = None
_vocoder = None

# Process-wide semaphore: permits exactly one model forward pass at a time.
# Prevents concurrent GPU OOM / CPU thrash when multiple requests arrive
# simultaneously. Replace with a Celery/ARQ task queue for multi-GPU scaling.
_inference_semaphore = asyncio.Semaphore(1)


def _free_gpu_memory() -> None:
    """Return cached GPU memory to the driver after a model forward pass.

    PyTorch's caching allocator keeps freed tensor memory reserved for reuse
    rather than releasing it back to the driver, which fragments VRAM under
    sustained load. Called after each inference-heavy operation (encoder,
    synthesizer, vocoder) once their intermediate tensors are no longer
    referenced. No-op on CPU-only deployments.
    """
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def load_models(device: str = "cpu") -> None:
    """Load all SV2TTS models into memory for inference.

    Raises:
        RuntimeError: If resemblyzer is not installed or any model checkpoint
            fails to load.  The server must not start in a degraded state.
    """
    global _encoder, _synthesizer, _vocoder
    logger.info("Loading SV2TTS models on %s...", device)

    if VoiceEncoder is None:
        raise RuntimeError(
            "resemblyzer is not installed. " "Run: pip install resemblyzer"
        )
    _encoder = VoiceEncoder(device=device)
    logger.info("Speaker encoder loaded.")

    weights_dir = os.path.join(os.path.dirname(__file__), "..", "weights")

    synth_path = os.path.join(weights_dir, "synthesizer.pt")
    if not os.path.exists(synth_path):
        synth_path = os.path.join(weights_dir, "tacotron.pt")

    try:
        _synthesizer = torch.jit.load(synth_path, map_location=device)
        _synthesizer.eval()
        logger.info("Synthesizer loaded from %s.", synth_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load synthesizer from '{synth_path}': {exc}. "
            "Ensure valid TorchScript weights are present in the weights/ directory."
        ) from exc

    voc_path = os.path.join(weights_dir, "vocoder.pt")
    if not os.path.exists(voc_path):
        voc_path = os.path.join(weights_dir, "wavernn.pt")

    try:
        _vocoder = torch.jit.load(voc_path, map_location=device)
        _vocoder.eval()
        logger.info("Vocoder loaded from %s.", voc_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load vocoder from '{voc_path}': {exc}. "
            "Ensure valid TorchScript weights are present in the weights/ directory."
        ) from exc

    logger.info("All SV2TTS models loaded successfully.")


def embed_speaker(audio: np.ndarray) -> np.ndarray:
    """Extract a 256-dim speaker embedding from a preprocessed audio array.

    Args:
        audio: Normalised float32 audio array at 16 kHz.  Returns a zero
            embedding (not an error) when the array is None or empty — this
            can legitimately occur after aggressive silence trimming.

    Raises:
        RuntimeError: If the speaker encoder has not been loaded via
            ``load_models()`` or ``load_mock_models()``.
    """
    if _encoder is None:
        raise RuntimeError(
            "Speaker encoder is not loaded. Call load_models() before inference."
        )
    if audio is None or len(audio) == 0:
        logger.warning(
            "embed_speaker: received None or empty audio — returning zero embedding."
        )
        return np.zeros(256, dtype=np.float32)

    try:
        return _encoder.embed_utterance(audio)
    finally:
        _free_gpu_memory()


def synthesize_speech(text: str, embedding: np.ndarray) -> np.ndarray:
    """Generate a mel spectrogram from text and a speaker embedding.

    Raises:
        RuntimeError: If the synthesizer has not been loaded.
    """
    if _synthesizer is None:
        raise RuntimeError(
            "Synthesizer is not loaded. Call load_models() before inference."
        )

    with torch.no_grad():
        # Minimal conversion; actual model interface varies by checkpoint.
        text_tensor = torch.tensor([ord(c) for c in text], dtype=torch.long).unsqueeze(
            0
        )
        emb_tensor = torch.from_numpy(embedding).unsqueeze(0)
        mel = _synthesizer(text_tensor, emb_tensor)
        result = mel.squeeze(0).cpu().numpy()

    # Explicitly drop references to the GPU tensors before releasing cached
    # memory — Python's refcounting won't free them promptly otherwise since
    # they're still bound to these local variables.
    del text_tensor, emb_tensor, mel
    _free_gpu_memory()
    return result


def vocode(mel: np.ndarray) -> np.ndarray:
    """Convert a mel spectrogram to a raw audio waveform.

    Raises:
        RuntimeError: If the vocoder has not been loaded.
    """
    if _vocoder is None:
        raise RuntimeError(
            "Vocoder is not loaded. Call load_models() before inference."
        )

    with torch.no_grad():
        mel_tensor = torch.from_numpy(mel).unsqueeze(0)
        wav = _vocoder(mel_tensor)
        result = wav.squeeze(0).cpu().numpy()

    del mel_tensor, wav
    _free_gpu_memory()
    return result


def save_output(
    waveform: np.ndarray, sample_rate: int, user_id: str
) -> tuple[str, float]:
    """Save synthesized waveform to disk and return path and duration."""
    out_dir = os.path.join(settings.OUTPUT_DIR, user_id)
    os.makedirs(out_dir, exist_ok=True)

    filename = f"{uuid.uuid4()}.wav"
    file_path = os.path.join(out_dir, filename)

    if waveform.ndim > 1:
        waveform = waveform.squeeze()

    sf.write(file_path, waveform, sample_rate)

    duration = len(waveform) / sample_rate
    return file_path, float(duration)


async def run_inference_pipeline(
    text: str, embedding: np.ndarray, user_id: str
) -> tuple[str, float]:
    """Run the full TTS inference pipeline serialised by the inference semaphore.

    Acquires ``_inference_semaphore`` before executing the two model forward
    passes (synthesizer and vocoder) so that concurrent HTTP requests cannot
    trigger simultaneous GPU/CPU inference.  File I/O (``save_output``) runs
    outside the semaphore because it is disk-bound and safe to parallelise.

    Args:
        text: Input text to synthesise.
        embedding: 256-dim speaker embedding produced by the encoder.
        user_id: Owner of this generation; used for output directory routing.

    Returns:
        Tuple of (absolute output WAV path, duration in seconds).
    """
    async with _inference_semaphore:
        logger.debug(
            "Inference semaphore acquired — starting synthesizer forward pass."
        )
        mel = await asyncio.to_thread(synthesize_speech, text, embedding)
        wav = await asyncio.to_thread(vocode, mel)
        logger.debug("Inference semaphore releasing — forward passes complete.")

    out_path, duration = await asyncio.to_thread(
        save_output, wav, settings.VOCODER_SAMPLE_RATE, user_id
    )
    return out_path, duration


async def embed_speaker_async(audio: np.ndarray) -> np.ndarray:
    """Async wrapper for ``embed_speaker`` serialised by the inference semaphore.

    The encoder forward pass shares the same hardware resources as the
    synthesizer and vocoder, so it is gated by the same semaphore to prevent
    concurrent model execution during voice-profile upload.

    Args:
        audio: Preprocessed, normalised audio array at 16 kHz.

    Returns:
        256-dim float32 speaker embedding.
    """
    async with _inference_semaphore:
        return await asyncio.to_thread(embed_speaker, audio)


# ---------------------------------------------------------------------------
# Test utilities — NOT for production use
# ---------------------------------------------------------------------------


class _MockSynthesizer(torch.nn.Module):
    """Lightweight Tacotron-2 test double.

    Returns a zero mel spectrogram of the correct shape
    ``(1, text_len * 5, 80)`` so that downstream shape assertions hold without
    loading real model weights.
    """

    def forward(
        self, text_ids: torch.Tensor, speaker_emb: torch.Tensor
    ) -> torch.Tensor:
        """Return a deterministic zero mel spectrogram."""
        T = text_ids.shape[1] * 5
        return torch.zeros(1, T, 80)


class _MockVocoder(torch.nn.Module):
    """Lightweight WaveRNN/HiFi-GAN test double.

    Accepts a mel spectrogram of shape ``(1, T, 80)`` and returns a zero
    waveform of shape ``(1, T * 200)`` so that duration and shape assertions
    hold without loading real model weights.
    """

    def forward(self, mel: torch.Tensor) -> torch.Tensor:
        """Return a deterministic zero waveform."""
        return torch.zeros(1, mel.shape[1] * 200)


def load_mock_models(device: str = "cpu") -> None:
    """Inject lightweight mock models for unit and integration tests.

    Loads the real ``VoiceEncoder`` from resemblyzer's cached pre-trained
    weights (so encoder-facing tests remain realistic) but replaces the
    synthesizer and vocoder with ``_MockSynthesizer`` and ``_MockVocoder``
    instances that return correctly-shaped zero tensors.

    Warning:
        This function must **never** be called in production.  Use
        ``load_models()`` for all deployment contexts.
    """
    global _encoder, _synthesizer, _vocoder
    if VoiceEncoder is None:
        raise RuntimeError(
            "resemblyzer is not installed — cannot load mock models for tests."
        )
    _encoder = VoiceEncoder(device=device)
    _synthesizer = _MockSynthesizer().to(device).eval()
    _vocoder = _MockVocoder().to(device).eval()
    logger.debug("Mock TTS models loaded for testing (device=%s).", device)
