"""Unit tests for the SV2TTS TTS pipeline service functions.

These tests load models once at module scope and are fully isolated from the
database — no fixtures from conftest.py are needed.
"""

import os
from unittest.mock import patch

import numpy as np
import pytest
import torch

from backend.services import tts_pipeline
from backend.services.tts_pipeline import (embed_speaker, load_mock_models,
                                           load_models, save_output,
                                           synthesize_speech, vocode)


@pytest.fixture(scope="module", autouse=True)
def setup_models():
    """Inject lightweight mock models once for the entire module.

    Uses load_mock_models() so tests are not gated on valid checkpoint files
    being present, while still exercising the real VoiceEncoder.
    """
    load_mock_models("cpu")


def test_embed_speaker_output_shape():
    """embed_speaker must return a 256-dim float32 embedding."""
    audio = np.random.randn(16000).astype(np.float32)
    emb = embed_speaker(audio)
    assert emb.shape == (256,)
    assert emb.dtype == np.float32


def test_embed_speaker_none_audio_returns_zeros():
    """embed_speaker with None input must return safe zero-vector fallback."""
    emb = embed_speaker(None)
    assert emb.shape == (256,)
    assert np.all(emb == 0.0)


def test_embed_speaker_empty_audio_returns_zeros():
    """embed_speaker with empty array must return safe zero-vector fallback."""
    emb = embed_speaker(np.array([], dtype=np.float32))
    assert emb.shape == (256,)
    assert np.all(emb == 0.0)


def test_synthesize_speech_returns_mel():
    """synthesize_speech must return a 2D float32 mel spectrogram array."""
    emb = np.random.randn(256).astype(np.float32)
    mel = synthesize_speech("Hello world.", emb)
    assert mel.ndim == 2
    assert mel.dtype == np.float32


def test_vocode_returns_1d_waveform():
    """vocode must return a 1D float32 audio waveform."""
    mel = np.random.randn(60, 80).astype(np.float32)
    wav = vocode(mel)
    assert wav.ndim == 1
    assert wav.dtype == np.float32


def test_save_output_creates_file():
    """save_output must write a WAV file to disk and return its path."""
    wav = np.random.randn(16000).astype(np.float32)
    path, duration = save_output(wav, 16000, "test_user")
    assert os.path.exists(path)
    assert duration == pytest.approx(1.0, rel=1e-3)
    os.remove(path)


def test_save_output_returns_duration():
    """save_output duration must match waveform length / sample rate."""
    wav = np.random.randn(8000).astype(np.float32)
    path, duration = save_output(wav, 16000, "test_user")
    assert duration == pytest.approx(0.5, rel=1e-3)
    os.remove(path)


# ---------------------------------------------------------------------------
# Concurrency / semaphore tests
# ---------------------------------------------------------------------------


def test_inference_semaphore_is_initialized():
    """Semaphore must exist and be unlocked (value=1) before any inference."""
    from backend.services.tts_pipeline import _inference_semaphore

    assert (
        not _inference_semaphore.locked()
    ), "Semaphore must not be locked at rest — nothing is currently holding it."


def test_run_inference_pipeline_returns_valid_output():
    """run_inference_pipeline must return an existing WAV path and positive duration."""
    import asyncio

    from backend.services.tts_pipeline import run_inference_pipeline

    embedding = np.zeros(256, dtype=np.float32)
    path, duration = asyncio.run(
        run_inference_pipeline("Hello world.", embedding, "test_pipeline_user")
    )

    assert os.path.exists(path), f"Output file not found: {path}"
    assert duration > 0.0, "Duration must be positive"
    os.remove(path)


def test_concurrent_inference_completes_without_error():
    """Three simultaneous gather() coroutines must all complete under the semaphore.

    This validates that the semaphore serialises without deadlocking.
    """
    import asyncio

    from backend.services.tts_pipeline import run_inference_pipeline

    async def _run_all() -> list[tuple[str, float]]:
        embedding = np.zeros(256, dtype=np.float32)
        tasks = [
            run_inference_pipeline(
                f"Concurrent request {i}", embedding, "test_conc_user"
            )
            for i in range(3)
        ]
        return await asyncio.gather(*tasks)

    results = asyncio.run(_run_all())

    assert len(results) == 3, "All three concurrent calls must return results"
    for path, duration in results:
        assert os.path.exists(path), f"Expected output file missing: {path}"
        assert duration > 0.0
        os.remove(path)


def _patch_fresh_inference_semaphore(monkeypatch):
    """Swap in a brand-new, unbound `asyncio.Semaphore` for the duration of
    a test.

    `_inference_semaphore` is a process-wide module global, shared by every
    test in this file. Contending on it (a waiter actually has to block)
    binds it to the current test's event loop (an asyncio.Semaphore lazily
    binds to whichever loop first has to queue a waiter on it); a later
    test's own `asyncio.run()` call then gets a fresh loop and would crash
    with "bound to a different event loop" trying to reuse it. Patching in a
    fresh instance keeps each contention test's binding local to itself.
    """
    import asyncio

    fresh_semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(
        "backend.services.tts_pipeline._inference_semaphore", fresh_semaphore
    )
    return fresh_semaphore


def test_acquire_inference_slot_rejects_when_max_waiters_reached(monkeypatch):
    """HARDENING_PLAN.md H6: once `INFERENCE_MAX_WAITERS` requests are
    already queued, a new request must be rejected with
    InferenceQueueFullError immediately — never joining the queue."""
    import asyncio

    from backend.services.tts_pipeline import (InferenceQueueFullError,
                                               _acquire_inference_slot)

    fresh_semaphore = _patch_fresh_inference_semaphore(monkeypatch)
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_MAX_WAITERS", 1
    )
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS",
        5.0,
    )

    async def _run():
        async with fresh_semaphore:  # hold the only slot
            waiter_entered = asyncio.Event()

            async def _wait_for_slot():
                async with _acquire_inference_slot():
                    pass  # pragma: no cover - never reached, slot stays held

            task = asyncio.ensure_future(_wait_for_slot())
            # Let the waiter actually start awaiting the semaphore before we
            # count it as "queued".
            await asyncio.sleep(0.05)
            waiter_entered.set()

            with pytest.raises(InferenceQueueFullError):
                async with _acquire_inference_slot():
                    pass  # pragma: no cover - must raise before entering

            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


def test_acquire_inference_slot_times_out_waiting_for_free_slot(monkeypatch):
    """HARDENING_PLAN.md H6: a request must give up with
    InferenceTimeoutError, not wait forever, when the semaphore stays held
    past `INFERENCE_ACQUIRE_TIMEOUT_SECONDS`."""
    import asyncio

    from backend.services.tts_pipeline import (InferenceTimeoutError,
                                               _acquire_inference_slot)

    fresh_semaphore = _patch_fresh_inference_semaphore(monkeypatch)
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS",
        0.05,
    )
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_MAX_WAITERS", 10
    )

    async def _run():
        async with fresh_semaphore:  # hold the only slot for the test
            with pytest.raises(InferenceTimeoutError):
                async with _acquire_inference_slot():
                    pass  # pragma: no cover - must time out before entering

    asyncio.run(_run())


def test_acquire_inference_slot_decrements_waiters_after_timeout(monkeypatch):
    """A timed-out waiter must not permanently occupy a queue slot — the
    waiters counter must drop back down so later requests can still queue."""
    import asyncio

    import backend.services.tts_pipeline as tts_pipeline_module
    from backend.services.tts_pipeline import (InferenceTimeoutError,
                                               _acquire_inference_slot)

    fresh_semaphore = _patch_fresh_inference_semaphore(monkeypatch)
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS",
        0.05,
    )
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_MAX_WAITERS", 10
    )

    async def _run():
        async with fresh_semaphore:
            with pytest.raises(InferenceTimeoutError):
                async with _acquire_inference_slot():
                    pass

        assert tts_pipeline_module._inference_waiters == 0

    asyncio.run(_run())


def test_run_inference_pipeline_raises_timeout_on_slow_forward_pass(monkeypatch):
    """HARDENING_PLAN.md H6: a forward pass slower than
    `INFERENCE_CALL_TIMEOUT_SECONDS` must raise InferenceTimeoutError rather
    than run unbounded."""
    import asyncio
    import time

    from backend.services.tts_pipeline import (InferenceTimeoutError,
                                               run_inference_pipeline)

    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.INFERENCE_CALL_TIMEOUT_SECONDS",
        0.05,
    )

    def _slow_synthesize(text, embedding):
        time.sleep(0.5)
        return np.zeros((80, 10), dtype=np.float32)

    with patch(
        "backend.services.tts_pipeline.synthesize_speech",
        side_effect=_slow_synthesize,
    ):
        with pytest.raises(InferenceTimeoutError):
            asyncio.run(
                run_inference_pipeline(
                    "Hello world.",
                    np.zeros(256, dtype=np.float32),
                    "test_timeout_user",
                )
            )


def test_embed_speaker_async_returns_correct_shape():
    """embed_speaker_async must return a 256-dim float32 embedding under the semaphore."""
    import asyncio

    from backend.services.tts_pipeline import embed_speaker_async

    audio = np.random.randn(16000).astype(np.float32)
    embedding = asyncio.run(embed_speaker_async(audio))

    assert embedding.shape == (256,), f"Expected (256,), got {embedding.shape}"
    assert embedding.dtype == np.float32


# ---------------------------------------------------------------------------
# Failure-path tests — verify mock fallbacks are fully removed
# ---------------------------------------------------------------------------


def test_load_models_raises_when_no_checkpoints_present(tmp_path, monkeypatch):
    """load_models() must raise RuntimeError — not silently succeed or fall
    back to a mock — when WEIGHTS_DIR contains no checkpoint files at all.

    Regression test for HARDENING_PLAN.md Critical finding C2:
    `download_weights.py` used to write placeholder bytes into `weights/`,
    making the directory *look* provisioned. This test uses a genuinely
    empty directory (no file written to `tmp_path`) and exercises the real
    filesystem lookup in `load_models()`.
    """
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.WEIGHTS_DIR", str(tmp_path)
    )
    with pytest.raises(RuntimeError, match="Synthesizer checkpoint not found"):
        load_models("cpu")


def test_load_models_raises_on_synthesizer_checksum_mismatch(tmp_path, monkeypatch):
    """load_models() must reject a synthesizer.pt whose SHA256 doesn't match
    the pinned manifest — and must never pass that file to torch.load.

    This is the security-relevant property from HARDENING_PLAN.md finding
    C2: a corrupted download or a tampered checkpoint is rejected before any
    deserialization is attempted, not after. Uses the real, unmocked
    checksum path against `backend/weights_manifest.json` — the pinned
    SHA256 for the real file will never match these garbage bytes.

    Spies on (rather than replaces) torch.load: resemblyzer's VoiceEncoder
    also calls torch.load internally to load its own pretrained weights, and
    since `patch("...tts_pipeline.torch.load", ...)` patches the process-wide
    torch module (not a private copy), a bare replacement would break that
    unrelated call too. `wraps=` lets real calls through so we can assert on
    which *paths* were ever loaded, not a raw call count.
    """
    (tmp_path / "synthesizer.pt").write_bytes(b"not a real checkpoint")
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.WEIGHTS_DIR", str(tmp_path)
    )
    real_torch_load = torch.load
    with patch(
        "backend.services.tts_pipeline.torch.load", wraps=real_torch_load
    ) as spy_torch_load:
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            load_models("cpu")
        loaded_paths = [str(call.args[0]) for call in spy_torch_load.call_args_list]
        assert not any("synthesizer.pt" in p for p in loaded_paths)


def _write_real_shaped_synthesizer_checkpoint(path) -> None:
    """Save a full-size, correctly-shaped (but randomly-initialized) Tacotron
    state_dict to ``path``, using the exact hparams `load_models()` builds
    its Tacotron with — so `load_state_dict()` succeeds against it without
    needing the real trained (and not-network-fetchable-in-tests) weights.
    """
    from backend.services.sv2tts.synthesizer.hparams import hparams as synth_hp
    from backend.services.sv2tts.synthesizer.models.tacotron import Tacotron
    from backend.services.sv2tts.synthesizer.utils.symbols import symbols

    real_shaped = Tacotron(
        embed_dims=synth_hp.tts_embed_dims,
        num_chars=len(symbols),
        encoder_dims=synth_hp.tts_encoder_dims,
        decoder_dims=synth_hp.tts_decoder_dims,
        n_mels=synth_hp.num_mels,
        fft_bins=synth_hp.num_mels,
        postnet_dims=synth_hp.tts_postnet_dims,
        encoder_K=synth_hp.tts_encoder_K,
        lstm_dims=synth_hp.tts_lstm_dims,
        postnet_K=synth_hp.tts_postnet_K,
        num_highways=synth_hp.tts_num_highways,
        dropout=synth_hp.tts_dropout,
        stop_threshold=synth_hp.tts_stop_threshold,
        speaker_embedding_size=synth_hp.speaker_embedding_size,
    )
    torch.save({"model_state": real_shaped.state_dict()}, path)


def test_load_models_raises_on_vocoder_checksum_mismatch(tmp_path, monkeypatch):
    """Same guarantee as the synthesizer checksum test, for vocoder.pt.

    Requires the synthesizer path to succeed first so the vocoder check is
    actually reached: a real-shaped (untrained) synthesizer checkpoint plus
    a mocked checksum pass gets past the synthesizer step, isolating the
    vocoder checksum mismatch as the only remaining failure.
    """
    _write_real_shaped_synthesizer_checkpoint(tmp_path / "synthesizer.pt")
    (tmp_path / "vocoder.pt").write_bytes(b"not a real checkpoint")
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.WEIGHTS_DIR", str(tmp_path)
    )

    def fake_verify(path, filename, manifest):
        if filename == "synthesizer.pt":
            return  # accept the untrained-but-real-shaped test checkpoint
        raise RuntimeError(f"Checksum mismatch for '{filename}'")

    real_torch_load = torch.load
    with patch(
        "backend.services.tts_pipeline.verify_checksum", side_effect=fake_verify
    ):
        # wraps=real_torch_load: synthesizer's load must genuinely succeed
        # (against the real-shaped file on disk) for this test to prove
        # anything about the *vocoder* path specifically.
        with patch(
            "backend.services.tts_pipeline.torch.load", wraps=real_torch_load
        ) as spy_torch_load:
            with pytest.raises(RuntimeError, match="Checksum mismatch"):
                load_models("cpu")
            loaded_paths = [str(call.args[0]) for call in spy_torch_load.call_args_list]
            # The synthesizer (which passed its mocked checksum check) *was*
            # loaded — proving this test actually reached the vocoder step —
            # but the rejected vocoder.pt never was.
            assert any("synthesizer.pt" in p for p in loaded_paths)
            assert not any("vocoder.pt" in p for p in loaded_paths)


def _write_real_shaped_vocoder_checkpoint(path) -> None:
    """Save a full-size, correctly-shaped (but randomly-initialized) WaveRNN
    state_dict to ``path`` — the vocoder counterpart of
    `_write_real_shaped_synthesizer_checkpoint` above."""
    from backend.services.sv2tts.vocoder import hparams as voc_hp
    from backend.services.sv2tts.vocoder.models.fatchord_version import WaveRNN

    real_shaped = WaveRNN(
        rnn_dims=voc_hp.voc_rnn_dims,
        fc_dims=voc_hp.voc_fc_dims,
        bits=voc_hp.bits,
        pad=voc_hp.voc_pad,
        upsample_factors=voc_hp.voc_upsample_factors,
        feat_dims=voc_hp.num_mels,
        compute_dims=voc_hp.voc_compute_dims,
        res_out_dims=voc_hp.voc_res_out_dims,
        res_blocks=voc_hp.voc_res_blocks,
        hop_length=voc_hp.hop_length,
        sample_rate=voc_hp.sample_rate,
        mode=voc_hp.voc_mode,
    )
    torch.save({"model_state": real_shaped.state_dict()}, path)


def test_load_models_sets_checksum_verified_flags_on_success(tmp_path, monkeypatch):
    """load_models() must record checksum_verified=True for each model it
    successfully loads (HARDENING_PLAN.md Milestone C2.3) — and
    load_mock_models() must leave both False again afterward, so this test
    doesn't leak a "verified" state into any test that runs after it.
    """
    _write_real_shaped_synthesizer_checkpoint(tmp_path / "synthesizer.pt")
    _write_real_shaped_vocoder_checkpoint(tmp_path / "vocoder.pt")
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.WEIGHTS_DIR", str(tmp_path)
    )

    import backend.services.tts_pipeline as tts_pipeline_module

    try:
        with patch("backend.services.tts_pipeline.verify_checksum", return_value=None):
            load_models("cpu")

        assert tts_pipeline_module._synthesizer_checksum_verified is True
        assert tts_pipeline_module._vocoder_checksum_verified is True

        status = tts_pipeline_module.get_model_health("cpu")
        assert status["synthesizer"]["checksum_verified"] is True
        assert status["vocoder"]["checksum_verified"] is True
    finally:
        # Restore the module-scoped mock fixture's state for every test that
        # runs after this one in the file.
        load_mock_models("cpu")


def test_load_models_raises_on_malformed_synthesizer_checkpoint(tmp_path, monkeypatch):
    """A checksum-verified synthesizer.pt that doesn't match the real Tacotron
    architecture must still fail loudly (missing/mismatched state_dict keys),
    not load partially or silently.
    """
    torch.save(
        {"model_state": {"bogus_key": torch.zeros(1)}}, tmp_path / "synthesizer.pt"
    )
    monkeypatch.setattr(
        "backend.services.tts_pipeline.settings.WEIGHTS_DIR", str(tmp_path)
    )
    with patch("backend.services.tts_pipeline.verify_checksum", return_value=None):
        with pytest.raises(RuntimeError, match="Failed to load synthesizer"):
            load_models("cpu")


def test_synthesize_speech_raises_if_synthesizer_not_loaded(monkeypatch):
    """synthesize_speech() must raise RuntimeError when _synthesizer is None.

    Verifies the string-sentinel mock path has been removed — the function
    must fail loudly rather than return random noise.
    """
    monkeypatch.setattr("backend.services.tts_pipeline._synthesizer", None)
    with pytest.raises(RuntimeError, match="Synthesizer is not loaded"):
        synthesize_speech("hello", np.zeros(256, dtype=np.float32))


def test_vocode_raises_if_vocoder_not_loaded(monkeypatch):
    """vocode() must raise RuntimeError when _vocoder is None.

    Verifies the string-sentinel mock path has been removed — the function
    must fail loudly rather than return random noise.
    """
    monkeypatch.setattr("backend.services.tts_pipeline._vocoder", None)
    with pytest.raises(RuntimeError, match="Vocoder is not loaded"):
        vocode(np.zeros((60, 80), dtype=np.float32))


def test_embed_speaker_raises_if_encoder_not_loaded(monkeypatch):
    """embed_speaker() must raise RuntimeError when _encoder is None.

    Verifies that the encoder-missing case is no longer silently swallowed
    and blended with the audio-input guard.
    """
    monkeypatch.setattr("backend.services.tts_pipeline._encoder", None)
    with pytest.raises(RuntimeError, match="Speaker encoder is not loaded"):
        embed_speaker(np.random.randn(16000).astype(np.float32))


# ---------------------------------------------------------------------------
# GPU memory management — HARDENING_PLAN Phase 2
# ---------------------------------------------------------------------------


def test_synthesize_speech_frees_gpu_memory_when_cuda_available():
    """synthesize_speech() must call torch.cuda.empty_cache() when CUDA is present."""
    with patch(
        "backend.services.tts_pipeline.torch.cuda.is_available", return_value=True
    ), patch("backend.services.tts_pipeline.torch.cuda.empty_cache") as mock_empty:
        synthesize_speech("Hello world.", np.random.randn(256).astype(np.float32))
    mock_empty.assert_called_once()


def test_vocode_frees_gpu_memory_when_cuda_available():
    """vocode() must call torch.cuda.empty_cache() when CUDA is present."""
    mel = np.random.randn(60, 80).astype(np.float32)
    with patch(
        "backend.services.tts_pipeline.torch.cuda.is_available", return_value=True
    ), patch("backend.services.tts_pipeline.torch.cuda.empty_cache") as mock_empty:
        vocode(mel)
    mock_empty.assert_called_once()


def test_embed_speaker_frees_gpu_memory_when_cuda_available():
    """embed_speaker() must call torch.cuda.empty_cache() when CUDA is present."""
    audio = np.random.randn(16000).astype(np.float32)
    with patch(
        "backend.services.tts_pipeline.torch.cuda.is_available", return_value=True
    ), patch("backend.services.tts_pipeline.torch.cuda.empty_cache") as mock_empty:
        embed_speaker(audio)
    mock_empty.assert_called_once()


def test_free_gpu_memory_is_noop_without_cuda():
    """_free_gpu_memory() must not touch the cache allocator on CPU-only hosts."""
    from backend.services.tts_pipeline import _free_gpu_memory

    with patch(
        "backend.services.tts_pipeline.torch.cuda.is_available", return_value=False
    ), patch("backend.services.tts_pipeline.torch.cuda.empty_cache") as mock_empty:
        _free_gpu_memory()
    mock_empty.assert_not_called()


def test_embed_speaker_frees_gpu_memory_even_on_encoder_failure(monkeypatch):
    """_free_gpu_memory() must still run if the encoder forward pass raises.

    Guards against a partially-executed inference leaving GPU memory
    unreleased when the model itself errors out mid-pass.
    """
    from backend.services.tts_pipeline import _encoder

    def boom(_audio):
        raise RuntimeError("mocked encoder failure")

    monkeypatch.setattr(_encoder, "embed_utterance", boom)
    with patch(
        "backend.services.tts_pipeline.torch.cuda.is_available", return_value=True
    ), patch("backend.services.tts_pipeline.torch.cuda.empty_cache") as mock_empty:
        with pytest.raises(RuntimeError, match="mocked encoder failure"):
            embed_speaker(np.random.randn(16000).astype(np.float32))
    mock_empty.assert_called_once()


def test_vocode_pads_mels_shorter_than_the_fade_window(monkeypatch):
    """A few-frame mel must reach the vocoder padded to the minimum frame count.

    The real WaveRNN raises ValueError below that length (P2-M3 real-weights run).
    """
    seen = []
    real = tts_pipeline._vocoder.generate

    def spy(mel, *args, **kwargs):
        seen.append(mel.shape[-1])
        return real(mel, *args, **kwargs)

    monkeypatch.setattr(tts_pipeline._vocoder, "generate", spy)
    wav = vocode(np.zeros((80, 5), dtype=np.float32))
    assert seen == [tts_pipeline._VOCODER_MIN_FRAMES]
    assert len(wav) == tts_pipeline._VOCODER_MIN_FRAMES * 200


def test_vocode_leaves_long_mels_unpadded(monkeypatch):
    """Mels at or above the fade window are passed through unchanged."""
    seen = []
    real = tts_pipeline._vocoder.generate

    def spy(mel, *args, **kwargs):
        seen.append(mel.shape[-1])
        return real(mel, *args, **kwargs)

    monkeypatch.setattr(tts_pipeline._vocoder, "generate", spy)
    vocode(np.zeros((80, 45), dtype=np.float32))
    assert seen == [45]
