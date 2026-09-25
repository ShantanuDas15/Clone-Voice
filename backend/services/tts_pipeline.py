"""Core text-to-speech inference pipeline."""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional, Set, TypeVar

import numpy as np
import soundfile as sf
import torch

from backend.core import metrics
from backend.core.config import settings
from backend.services.sv2tts.checksum import load_manifest, verify_checksum
from backend.services.sv2tts.synthesizer.hparams import hparams as synth_hparams
from backend.services.sv2tts.synthesizer.models.tacotron import Tacotron
from backend.services.sv2tts.synthesizer.utils import cleaners
from backend.services.sv2tts.synthesizer.utils.symbols import symbols as sv2tts_symbols
from backend.services.sv2tts.synthesizer.utils.text import text_to_sequence
from backend.services.sv2tts.vocoder import hparams as vocoder_hparams
from backend.services.sv2tts.vocoder.models.fatchord_version import WaveRNN
from backend.services.text_chunking import split_into_chunks

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

# Worker-thread tasks that are still executing a model forward pass
# (HARDENING_PLAN.md finding M6). A task stays here until its thread actually
# returns — even if the awaiting request was cancelled or timed out — so the
# shutdown drain can wait on real work rather than on request handlers.
_inflight_tasks: Set["asyncio.Future[Any]"] = set()

_T = TypeVar("_T")

# Outcome of the one-time startup warm-up forward pass (HARDENING_PLAN.md
# finding M7): "disabled" | "pending" | "ok" | "failed". Cached so readiness
# probes never take the inference permit themselves.
_warmup_status = "disabled"


# Gauges read live state at scrape time (HARDENING_PLAN.md finding M8). The
# lambdas look the names up on each call, so a test-swapped semaphore is seen.
metrics.bind_gauges(
    queue_depth=lambda: _inference_waiters,
    in_flight=lambda: 1 if _inference_semaphore.locked() else 0,
)


class InferenceQueueFullError(RuntimeError):
    """Raised when `settings.INFERENCE_MAX_WAITERS` requests are already
    queued for the inference semaphore. Mapped to HTTP 429 by callers."""


class InferenceTimeoutError(RuntimeError):
    """Raised when a request waits longer than
    `settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS` for a free inference slot,
    or an acquired forward pass runs longer than
    `settings.INFERENCE_CALL_TIMEOUT_SECONDS`. Mapped to HTTP 503 by
    callers."""


class _InferenceSlot:
    """Handle for one held inference permit (HARDENING_PLAN.md finding M6).

    ``run()`` executes a blocking call on a worker thread but *shields* the
    thread's future from cancellation/timeout of the awaiting request. If the
    request gives up while the thread is still running, the permit is not
    released until the thread finishes (see ``_acquire_inference_slot``), so
    a second forward pass can never overlap an abandoned one.
    """

    def __init__(self) -> None:
        """Start with no worker call in flight."""
        self._pending: Optional["asyncio.Future[Any]"] = None

    async def run(
        self, fn: Callable[..., _T], *args: Any, timeout: float, stage: str = "other"
    ) -> _T:
        """Run ``fn(*args)`` in a worker thread, raising TimeoutError past ``timeout``.

        ``stage`` labels the latency metric (HARDENING_PLAN.md finding M8);
        it is timed inside the worker thread so an abandoned call still
        records its true compute time when it eventually finishes.
        """

        def _timed() -> _T:
            """Run ``fn`` and record its duration under ``stage``."""
            with metrics.observe_stage(stage):
                return fn(*args)

        task = asyncio.ensure_future(asyncio.to_thread(_timed))
        self._pending = task
        _inflight_tasks.add(task)
        task.add_done_callback(_inflight_tasks.discard)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            metrics.INFERENCE_REJECTIONS.labels(reason="call_timeout").inc()
            raise

    def unfinished_task(self) -> Optional["asyncio.Future[Any]"]:
        """Return the worker task if its thread has not yet returned."""
        if self._pending is not None and not self._pending.done():
            return self._pending
        return None


def _release_after(task: "asyncio.Future[Any]") -> None:
    """Release the inference permit once an abandoned worker task finishes."""

    def _on_done(done: "asyncio.Future[Any]") -> None:
        """Consume the result (nobody awaits it) and free the permit."""
        if not done.cancelled() and done.exception() is not None:
            logger.warning(
                "Abandoned inference call failed after its request gave up: %r",
                done.exception(),
            )
        _inference_semaphore.release()

    task.add_done_callback(_on_done)


def get_warmup_status() -> str:
    """Return the cached warm-up outcome: disabled, pending, ok or failed."""
    return _warmup_status


def _warmup_forward_pass() -> None:
    """Run one tiny synthesizer + vocoder pass, discarding the output."""
    mel = synthesize_speech("Ready.", np.zeros(256, dtype=np.float32))
    vocode(mel)


async def warmup_inference() -> bool:
    """Run a single warm-up forward pass under the inference permit.

    Records the outcome for ``get_warmup_status()`` (HARDENING_PLAN.md finding
    M7). Never raises: a failure just leaves readiness reporting not-ready.
    """
    global _warmup_status
    _warmup_status = "pending"
    try:
        async with _acquire_inference_slot() as slot:
            await slot.run(
                _warmup_forward_pass, timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS
            )
    except Exception:
        logger.exception("Inference warm-up failed; service will report not ready.")
        _warmup_status = "failed"
        return False
    logger.info("Inference warm-up forward pass succeeded.")
    _warmup_status = "ok"
    return True


async def drain_inflight_inference(timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for running forward passes to finish.

    Called at shutdown (HARDENING_PLAN.md finding M6) so worker threads are
    not killed mid-forward-pass. Returns True if nothing is left running.
    """
    pending = {t for t in _inflight_tasks if not t.done()}
    if not pending:
        return True
    logger.info("Draining %d in-flight inference call(s)...", len(pending))
    _, still_running = await asyncio.wait(pending, timeout=timeout)
    if still_running:
        logger.warning(
            "Shutdown drain timed out with %d inference call(s) still running.",
            len(still_running),
        )
        return False
    return True


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
        metrics.INFERENCE_REJECTIONS.labels(reason="queue_full").inc()
        raise InferenceQueueFullError(
            f"Inference queue is full ({settings.INFERENCE_MAX_WAITERS} "
            "requests already waiting for a slot)."
        )
    _inference_waiters += 1
    wait_started = time.perf_counter()
    try:
        try:
            await asyncio.wait_for(
                _inference_semaphore.acquire(),
                timeout=settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            metrics.INFERENCE_REJECTIONS.labels(reason="acquire_timeout").inc()
            raise InferenceTimeoutError(
                "Timed out waiting for a free inference slot."
            ) from None
    finally:
        _inference_waiters -= 1
        metrics.INFERENCE_WAIT_SECONDS.observe(time.perf_counter() - wait_started)

    slot = _InferenceSlot()
    try:
        yield slot
    finally:
        unfinished = slot.unfinished_task()
        if unfinished is None:
            _inference_semaphore.release()
        else:
            # The request was cancelled or timed out while its thread is
            # still inside a forward pass: keep the permit until it returns.
            _release_after(unfinished)


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


def _clean_for_chunking(text: str) -> str:
    """Run the synthesizer's cleaners so chunk limits count decoded symbols.

    Number expansion turns 120 raw characters into ~250 symbols, which put
    digit-heavy chunks at 857 of the 900-frame cap when measured on raw text
    (HARDENING_PLAN.md finding P2-M3). The cleaners are idempotent, so the
    per-chunk clean inside ``text_to_sequence`` is harmless. Text with
    ARPAbet braces is left raw, since lowercasing would corrupt the phonemes.
    """
    if "{" in text:
        return text
    for name in synth_hparams.tts_cleaner_names:
        text = getattr(cleaners, name)(text)
    return text


def synthesize_speech(text: str, embedding: np.ndarray) -> np.ndarray:
    """Generate a mel spectrogram for text of any supported length.

    The text is split into sentence-sized chunks (``TTS_CHUNK_MAX_CHARS``),
    each decoded separately by ``_synthesize_chunk`` so no single Tacotron
    decode exceeds the checkpoint's training length, then the mels are joined
    with ``TTS_CHUNK_PAUSE_SECONDS`` of silence between chunks — the same idea
    as the reference SV2TTS demo, which synthesizes per line and concatenates
    (HARDENING_PLAN.md finding P2-M3).
    """
    chunks = split_into_chunks(_clean_for_chunking(text), settings.TTS_CHUNK_MAX_CHARS)
    if not chunks:
        chunks = [text]  # let the single-chunk path handle degenerate input
    mels = [_synthesize_chunk(chunk, embedding) for chunk in chunks]
    if len(mels) == 1:
        return mels[0]

    pause_frames = int(
        settings.TTS_CHUNK_PAUSE_SECONDS
        * synth_hparams.sample_rate
        / synth_hparams.hop_size
    )
    # Floor of the symmetric mel range = digital silence for the vocoder.
    pause = np.full(
        (mels[0].shape[0], pause_frames), -synth_hparams.max_abs_value, np.float32
    )
    parts: list[np.ndarray] = []
    for mel in mels:
        if parts:
            parts.append(pause)
        parts.append(mel)
    return np.concatenate(parts, axis=1)


def _synthesize_chunk(text: str, embedding: np.ndarray) -> np.ndarray:
    """Generate a mel spectrogram from one chunk of text and a speaker embedding.

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
        _, mel_tensor, _ = _synthesizer.generate(
            text_tensor, emb_tensor, steps=synth_hparams.max_mel_frames
        )
        result = mel_tensor.squeeze(0).cpu().numpy().astype(np.float32)

    # Reaching the step cap means the stop token never fired, so the decode
    # was cut off mid-speech (HARDENING_PLAN.md finding P2-M3).
    if result.shape[1] >= synth_hparams.max_mel_frames:
        logger.warning(
            "Synthesizer hit the %d-frame cap for a %d-char chunk; audio truncated.",
            synth_hparams.max_mel_frames,
            len(text),
        )

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
    async with _acquire_inference_slot() as slot:
        logger.debug(
            "Inference semaphore acquired — starting synthesizer forward pass."
        )
        try:
            mel = await slot.run(
                synthesize_speech,
                text,
                embedding,
                timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS,
                stage="synthesizer",
            )
            wav = await slot.run(
                vocode,
                mel,
                timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS,
                stage="vocoder",
            )
        except asyncio.TimeoutError:
            raise InferenceTimeoutError(
                "Inference forward pass exceeded the per-call timeout."
            ) from None
        logger.debug("Inference semaphore releasing — forward passes complete.")

    with metrics.observe_stage("save_output"):
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
    async with _acquire_inference_slot() as slot:
        try:
            return await slot.run(
                embed_speaker,
                audio,
                timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS,
                stage="encoder",
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

    def generate(
        self, text_ids: torch.Tensor, speaker_emb: torch.Tensor, steps: int = 2000
    ):
        """Return ``(None, mel, None)``, a zero mel spectrogram capped at ``steps``."""
        T = min(text_ids.shape[1] * 5, steps)
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
