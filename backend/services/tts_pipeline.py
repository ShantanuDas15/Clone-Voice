"""Core text-to-speech inference pipeline."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import torch

from backend.core.config import settings
from backend.services.sv2tts.checksum import load_manifest, verify_checksum
from backend.services.sv2tts.synthesizer.hparams import \
    hparams as synth_hparams
from backend.services.sv2tts.synthesizer.models.tacotron import Tacotron
from backend.services.sv2tts.synthesizer.utils.symbols import \
    symbols as sv2tts_symbols
from backend.services.sv2tts.synthesizer.utils.text import text_to_sequence
from backend.services.sv2tts.vocoder import hparams as vocoder_hparams
from backend.services.sv2tts.vocoder.models.fatchord_version import WaveRNN

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    VoiceEncoder = None

logger = logging.getLogger(__name__)

_encoder = None
_synthesizer = None
_vocoder = None

# Set True only when the corresponding model was loaded by load_models()
# *after* its checkpoint's SHA256 matched backend/weights_manifest.json —
# never by load_mock_models(), which loads no checkpoint at all. Surfaced
# via get_model_health()/`/health` so an operator or load balancer can tell
# "some model is loaded" apart from "the specific, verified checkpoint is
# loaded" (HARDENING_PLAN.md Milestone C2.3).
_synthesizer_checksum_verified = False
_vocoder_checksum_verified = False

# Process-wide semaphore: permits exactly one model forward pass at a time.
# Prevents concurrent GPU OOM / CPU thrash when multiple requests arrive
# simultaneously. Replace with a Celery/ARQ task queue for multi-GPU scaling.
_inference_semaphore = asyncio.Semaphore(1)

# Count of requests currently waiting to acquire `_inference_semaphore`
# (HARDENING_PLAN.md finding H6). Only ever mutated from
# `_acquire_inference_slot()`, always between `await` points, so plain
# increment/decrement is safe on asyncio's single-threaded event loop.
_inference_waiters = 0


class InferenceQueueFullError(RuntimeError):
    """Raised when `settings.INFERENCE_MAX_WAITERS` requests are already
    queued for the inference semaphore. Mapped to HTTP 429 by callers."""


class InferenceTimeoutError(RuntimeError):
    """Raised when a request waits longer than
    `settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS` for a free inference slot,
    or an acquired forward pass runs longer than
    `settings.INFERENCE_CALL_TIMEOUT_SECONDS`. Mapped to HTTP 503 by
    callers."""


@asynccontextmanager
async def _acquire_inference_slot():
    """Acquire `_inference_semaphore` with a bounded wait queue and timeout.

    Without this, every synthesis/embedding request funnels through the one
    process-wide permit with unbounded waiting (HARDENING_PLAN.md finding
    H6): under load, requests would queue silently until a client or proxy
    timeout fires, while the queued work still ran afterward. This bounds
    both the number of requests allowed to queue and how long any one of
    them waits.

    Raises:
        InferenceQueueFullError: `settings.INFERENCE_MAX_WAITERS` requests
            are already waiting — this one is rejected immediately without
            joining the queue.
        InferenceTimeoutError: This request waited but did not get a slot
            within `settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS`.
    """
    global _inference_waiters
    if _inference_waiters >= settings.INFERENCE_MAX_WAITERS:
        raise InferenceQueueFullError(
            f"Inference queue is full ({settings.INFERENCE_MAX_WAITERS} "
            "requests already waiting for a slot)."
        )
    _inference_waiters += 1
    try:
        try:
            await asyncio.wait_for(
                _inference_semaphore.acquire(),
                timeout=settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise InferenceTimeoutError(
                "Timed out waiting for a free inference slot."
            ) from None
    finally:
        _inference_waiters -= 1

    try:
        yield
    finally:
        _inference_semaphore.release()


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


def free_gpu_memory() -> None:
    """Public entry point for callers outside this module (e.g. API error paths)."""
    _free_gpu_memory()


def _module_device(module: torch.nn.Module) -> "torch.device | None":
    """Return the torch device a module's parameters live on.

    Falls back to ``None`` for parameter-less modules (e.g. the mock test
    doubles below), since such a module has no device of its own to report.
    """
    try:
        return next(module.parameters()).device
    except StopIteration:
        return None


def _inference_device(module: torch.nn.Module) -> torch.device:
    """Return the device to place inference inputs on for ``module``.

    Reads the real device from the module's own parameters
    (HARDENING_PLAN.md finding H1 — never assume or guess) and falls back to
    CPU only for the parameter-less mock test doubles, which have no device
    of their own.
    """
    return _module_device(module) or torch.device("cpu")


def get_model_health(expected_device: str | None = None) -> dict:
    """Report whether each SV2TTS model is loaded and on the expected device.

    Backs the ``/health`` endpoint so a load balancer only routes traffic
    once inference is actually possible, instead of trusting a static "ok".

    Args:
        expected_device: The device (e.g. ``"cpu"``, ``"cuda"``) models are
            expected to run on, typically ``settings.DEVICE``. When omitted,
            device placement is not checked — only presence is.

    Returns:
        A dict with one entry per model (``loaded``, ``device``,
        ``device_ok``, ``checksum_verified``) plus a top-level ``ready``
        flag that is ``True`` only when every model is loaded and correctly
        placed. ``checksum_verified`` is ``None`` when the model isn't
        loaded or checksum verification doesn't apply to it (the encoder —
        its weights come from resemblyzer's own cache, not
        `weights_manifest.json`); otherwise it is ``True`` only for a
        synthesizer/vocoder loaded by `load_models()` with a checksum match,
        and ``False`` for one loaded by `load_mock_models()` (test doubles,
        never checksum-verified) — this is diagnostic, not part of
        ``ready``, so the test suite's mock-backed `/health` checks are
        unaffected (HARDENING_PLAN.md Milestone C2.3).
    """
    expected = torch.device(expected_device) if expected_device else None
    checksum_verified = {
        "encoder": None,
        "synthesizer": _synthesizer_checksum_verified,
        "vocoder": _vocoder_checksum_verified,
    }

    status: dict = {}
    for name, model in (
        ("encoder", _encoder),
        ("synthesizer", _synthesizer),
        ("vocoder", _vocoder),
    ):
        loaded = model is not None
        device = getattr(model, "device", None) if loaded else None
        if loaded and device is None:
            device = _module_device(model)

        device_ok = True
        if loaded and expected is not None and device is not None:
            device_ok = torch.device(device).type == expected.type

        status[name] = {
            "loaded": loaded,
            "device": str(device) if device is not None else None,
            "device_ok": device_ok,
            "checksum_verified": checksum_verified[name] if loaded else None,
        }

    status["ready"] = all(s["loaded"] and s["device_ok"] for s in status.values())
    return status


def load_models(device: str = "cpu") -> None:
    """Load all SV2TTS models into memory for inference.

    The synthesizer and vocoder are real Tacotron2/WaveRNN checkpoints
    (vendored architecture: `backend/services/sv2tts/`, see
    `THIRD_PARTY_NOTICE.md` there) loaded as raw ``state_dict``s — not
    TorchScript. Each checkpoint's SHA256 is verified against
    `backend/weights_manifest.json` *before* ``torch.load`` ever touches the
    file, so a corrupted download or a tampered file is rejected before any
    deserialization is attempted (HARDENING_PLAN.md finding C2).

    Raises:
        RuntimeError: If resemblyzer is not installed, the checksum manifest
            is missing/malformed, a checkpoint file is missing, its checksum
            does not match, or it fails to load into the real model
            architecture. The server must not start in a degraded state.
    """
    global _encoder, _synthesizer, _vocoder
    global _synthesizer_checksum_verified, _vocoder_checksum_verified
    logger.info("Loading SV2TTS models on %s...", device)
    _synthesizer_checksum_verified = False
    _vocoder_checksum_verified = False

    if VoiceEncoder is None:
        raise RuntimeError(
            "resemblyzer is not installed. " "Run: pip install resemblyzer"
        )
    _encoder = VoiceEncoder(device=device)
    logger.info("Speaker encoder loaded.")

    weights_dir = settings.WEIGHTS_DIR
    manifest = load_manifest()

    synth_path = os.path.join(weights_dir, "synthesizer.pt")
    if not os.path.exists(synth_path):
        raise RuntimeError(
            f"Synthesizer checkpoint not found at '{synth_path}'. Run "
            "`python -m backend.download_weights` for provisioning guidance "
            "(see README.md 'Model Weights')."
        )
    try:
        verify_checksum(synth_path, "synthesizer.pt", manifest)
        _synthesizer = Tacotron(
            embed_dims=synth_hparams.tts_embed_dims,
            num_chars=len(sv2tts_symbols),
            encoder_dims=synth_hparams.tts_encoder_dims,
            decoder_dims=synth_hparams.tts_decoder_dims,
            n_mels=synth_hparams.num_mels,
            fft_bins=synth_hparams.num_mels,
            postnet_dims=synth_hparams.tts_postnet_dims,
            encoder_K=synth_hparams.tts_encoder_K,
            lstm_dims=synth_hparams.tts_lstm_dims,
            postnet_K=synth_hparams.tts_postnet_K,
            num_highways=synth_hparams.tts_num_highways,
            dropout=synth_hparams.tts_dropout,
            stop_threshold=synth_hparams.tts_stop_threshold,
            speaker_embedding_size=synth_hparams.speaker_embedding_size,
        ).to(device)
        checkpoint = torch.load(synth_path, map_location=device, weights_only=True)
        _synthesizer.load_state_dict(checkpoint["model_state"])
        _synthesizer.eval()
        _synthesizer_checksum_verified = True
        logger.info(
            "Synthesizer loaded from %s (checksum verified, trained to step %d).",
            synth_path,
            int(checkpoint["model_state"]["step"].item()),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load synthesizer from '{synth_path}': {exc}. "
            "Ensure a valid, checksum-verified checkpoint is present in the "
            "weights directory."
        ) from exc

    voc_path = os.path.join(weights_dir, "vocoder.pt")
    if not os.path.exists(voc_path):
        raise RuntimeError(
            f"Vocoder checkpoint not found at '{voc_path}'. Run "
            "`python -m backend.download_weights` for provisioning guidance "
            "(see README.md 'Model Weights')."
        )
    try:
        verify_checksum(voc_path, "vocoder.pt", manifest)
        _vocoder = WaveRNN(
            rnn_dims=vocoder_hparams.voc_rnn_dims,
            fc_dims=vocoder_hparams.voc_fc_dims,
            bits=vocoder_hparams.bits,
            pad=vocoder_hparams.voc_pad,
            upsample_factors=vocoder_hparams.voc_upsample_factors,
            feat_dims=vocoder_hparams.num_mels,
            compute_dims=vocoder_hparams.voc_compute_dims,
            res_out_dims=vocoder_hparams.voc_res_out_dims,
            res_blocks=vocoder_hparams.voc_res_blocks,
            hop_length=vocoder_hparams.hop_length,
            sample_rate=vocoder_hparams.sample_rate,
            mode=vocoder_hparams.voc_mode,
        ).to(device)
        checkpoint = torch.load(voc_path, map_location=device, weights_only=True)
        _vocoder.load_state_dict(checkpoint["model_state"])
        _vocoder.eval()
        _vocoder_checksum_verified = True
        logger.info("Vocoder loaded from %s (checksum verified).", voc_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load vocoder from '{voc_path}': {exc}. "
            "Ensure a valid, checksum-verified checkpoint is present in the "
            "weights directory."
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

    Text is converted to model input IDs via the vendored SV2TTS symbol
    table and cleaner pipeline (`sv2tts.synthesizer.utils.text`), matching
    the real Tacotron2 checkpoint's embedding table — not a placeholder
    (HARDENING_PLAN.md finding H2). Input tensors are moved to the
    synthesizer's own device before the forward pass, not assumed
    (HARDENING_PLAN.md finding H1).

    Raises:
        RuntimeError: If the synthesizer has not been loaded.
    """
    if _synthesizer is None:
        raise RuntimeError(
            "Synthesizer is not loaded. Call load_models() before inference."
        )

    device = _inference_device(_synthesizer)
    sequence = text_to_sequence(text, synth_hparams.tts_cleaner_names)

    with torch.no_grad():
        text_tensor = torch.tensor(sequence, dtype=torch.long, device=device).unsqueeze(
            0
        )
        emb_tensor = torch.from_numpy(embedding).float().to(device).unsqueeze(0)
        _, mel_tensor, _ = _synthesizer.generate(text_tensor, emb_tensor)
        result = mel_tensor.squeeze(0).cpu().numpy().astype(np.float32)

    # Explicitly drop references to the GPU tensors before releasing cached
    # memory — Python's refcounting won't free them promptly otherwise since
    # they're still bound to these local variables.
    del text_tensor, emb_tensor, mel_tensor
    _free_gpu_memory()

    # Trim trailing frames the model marked as silence via its stop token —
    # matches CorentinJ's reference Synthesizer.synthesize_spectrograms
    # behavior exactly (see THIRD_PARTY_NOTICE.md).
    stop_threshold = synth_hparams.tts_stop_threshold
    while result.shape[1] > 1 and np.max(result[:, -1]) < stop_threshold:
        result = result[:, :-1]

    return result


def vocode(mel: np.ndarray) -> np.ndarray:
    """Convert a mel spectrogram to a raw audio waveform.

    The mel is normalized the same way the reference vocoder inference code
    does (`sv2tts.vocoder.hparams.mel_max_abs_value`) and moved to the
    vocoder's own device before the forward pass, not assumed
    (HARDENING_PLAN.md finding H1). Output is clipped to [-1, 1] before
    return: real (in-distribution) speaker embeddings stay comfortably
    within that range, but de-emphasis on out-of-distribution input can
    occasionally push samples slightly outside it, and clipping here is the
    single place that protects every caller and every downstream `.wav`
    write.

    Raises:
        RuntimeError: If the vocoder has not been loaded.
    """
    if _vocoder is None:
        raise RuntimeError(
            "Vocoder is not loaded. Call load_models() before inference."
        )

    device = _inference_device(_vocoder)
    mel_normalized = mel / vocoder_hparams.mel_max_abs_value

    with torch.no_grad():
        mel_tensor = torch.from_numpy(mel_normalized[None, ...]).float().to(device)
        # WaveRNN.generate() already returns a plain numpy array (not a
        # tensor) — see backend/services/sv2tts/vocoder/models/fatchord_version.py.
        # progress_callback is a no-op: the reference implementation's default
        # writes a carriage-return progress bar to stdout on every ~100
        # samples, which is fine interactively but spams a server's logs.
        result = _vocoder.generate(
            mel_tensor,
            True,  # batched: realtime+ generation via fold/xfade-unfold
            8000,  # target samples per batch entry (reference default)
            800,  # crossfade overlap in samples (reference default)
            vocoder_hparams.mu_law,
            lambda *_args: None,
        )

    del mel_tensor
    _free_gpu_memory()
    return np.clip(result, -1.0, 1.0).astype(np.float32)


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

    The acquisition itself is bounded (queue-depth cap + wait timeout) and
    the two forward passes together are bounded by a single per-call
    timeout (HARDENING_PLAN.md finding H6), so a stuck or overloaded
    inference run fails fast instead of blocking indefinitely.

    Args:
        text: Input text to synthesise.
        embedding: 256-dim speaker embedding produced by the encoder.
        user_id: Owner of this generation; used for output directory routing.

    Returns:
        Tuple of (absolute output WAV path, duration in seconds).

    Raises:
        InferenceQueueFullError: The inference queue is already at capacity.
        InferenceTimeoutError: The slot wait, or the forward passes
            themselves, exceeded their configured timeout.
    """
    async with _acquire_inference_slot():
        logger.debug(
            "Inference semaphore acquired — starting synthesizer forward pass."
        )
        try:
            mel = await asyncio.wait_for(
                asyncio.to_thread(synthesize_speech, text, embedding),
                timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS,
            )
            wav = await asyncio.wait_for(
                asyncio.to_thread(vocode, mel),
                timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise InferenceTimeoutError(
                "Inference forward pass exceeded the per-call timeout."
            ) from None
        logger.debug("Inference semaphore releasing — forward passes complete.")

    out_path, duration = await asyncio.to_thread(
        save_output, wav, settings.VOCODER_SAMPLE_RATE, user_id
    )
    return out_path, duration


async def embed_speaker_async(audio: np.ndarray) -> np.ndarray:
    """Async wrapper for ``embed_speaker`` serialised by the inference semaphore.

    The encoder forward pass shares the same hardware resources as the
    synthesizer and vocoder, so it is gated by the same semaphore to prevent
    concurrent model execution during voice-profile upload. Subject to the
    same bounded queue and per-call timeout as ``run_inference_pipeline``
    (HARDENING_PLAN.md finding H6).

    Args:
        audio: Preprocessed, normalised audio array at 16 kHz.

    Returns:
        256-dim float32 speaker embedding.

    Raises:
        InferenceQueueFullError: The inference queue is already at capacity.
        InferenceTimeoutError: The slot wait, or the forward pass itself,
            exceeded its configured timeout.
    """
    async with _acquire_inference_slot():
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(embed_speaker, audio),
                timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise InferenceTimeoutError(
                "Embedding extraction exceeded the per-call timeout."
            ) from None


# ---------------------------------------------------------------------------
# Test utilities — NOT for production use
# ---------------------------------------------------------------------------


class _MockSynthesizer(torch.nn.Module):
    """Lightweight Tacotron-2 test double.

    Exposes the same ``generate(text_ids, speaker_emb) -> (_, mel, _)``
    interface as the real vendored
    ``backend.services.sv2tts.synthesizer.models.tacotron.Tacotron``, so
    ``synthesize_speech()`` runs unmodified against either. Returns a zero
    mel spectrogram of shape ``(1, 80, text_len * 5)`` — mel-channels-first,
    matching the real model's output layout — with no trained weights
    needed.
    """

    def generate(self, text_ids: torch.Tensor, speaker_emb: torch.Tensor):
        """Return ``(None, mel, None)``, a deterministic zero mel spectrogram."""
        T = text_ids.shape[1] * 5
        return None, torch.zeros(1, 80, T), None


class _MockVocoder(torch.nn.Module):
    """Lightweight WaveRNN test double.

    Exposes the same ``generate(mel, batched, target, overlap, mu_law,
    progress_callback) -> np.ndarray`` interface as the real vendored
    ``backend.services.sv2tts.vocoder.models.fatchord_version.WaveRNN``
    (which itself returns a numpy array, not a tensor), so ``vocode()`` runs
    unmodified against either. Accepts a mel of shape ``(1, 80, T)`` and
    returns a zero waveform of length ``T * 200`` (``hop_length`` in the
    real vocoder hparams), with no trained weights needed.
    """

    def generate(self, mel, batched, target, overlap, mu_law, progress_callback=None):
        """Return a deterministic zero waveform as a numpy float64 array."""
        return np.zeros(mel.shape[-1] * 200, dtype=np.float64)


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
    global _synthesizer_checksum_verified, _vocoder_checksum_verified
    if VoiceEncoder is None:
        raise RuntimeError(
            "resemblyzer is not installed — cannot load mock models for tests."
        )
    _encoder = VoiceEncoder(device=device)
    _synthesizer = _MockSynthesizer().to(device).eval()
    _vocoder = _MockVocoder().to(device).eval()
    # No checkpoint is ever loaded here, so neither is ever checksum-verified
    # — explicit, not just "happens to still be False", so get_model_health()
    # never reports a mock as a verified real checkpoint.
    _synthesizer_checksum_verified = False
    _vocoder_checksum_verified = False
    logger.debug("Mock TTS models loaded for testing (device=%s).", device)
