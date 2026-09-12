"""Unit tests for the SV2TTS TTS pipeline service functions.

These tests load models once at module scope and are fully isolated from the
database — no fixtures from conftest.py are needed.
"""

import os
from unittest.mock import patch

import numpy as np
import pytest
import torch

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


def test_load_models_raises_on_bad_synthesizer_weights():
    """load_models() must raise RuntimeError when synthesizer checkpoint is invalid.

    Mocks torch.jit.load to raise on the first call (synthesizer), verifying
    that no silent fallback occurs and a descriptive error propagates up.
    """
    call_count = {"n": 0}
    original_jit_load = torch.jit.load

    def mock_jit_load(path: str, map_location=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("mocked bad checkpoint")
        return original_jit_load(path, map_location=map_location)

    with patch(
        "backend.services.tts_pipeline.torch.jit.load", side_effect=mock_jit_load
    ):
        with pytest.raises(RuntimeError, match="Failed to load synthesizer"):
            load_models("cpu")


def test_load_models_raises_on_bad_vocoder_weights():
    """load_models() must raise RuntimeError when vocoder checkpoint is invalid.

    Mocks torch.jit.load to raise only on the second call (vocoder), ensuring
    the synthesizer path is irrelevant and the vocoder path is still guarded.
    """
    call_count = {"n": 0}

    def mock_jit_load(path: str, map_location=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("mocked bad vocoder checkpoint")
        raise RuntimeError("mocked bad synthesizer checkpoint")

    with patch(
        "backend.services.tts_pipeline.torch.jit.load", side_effect=mock_jit_load
    ):
        with pytest.raises(RuntimeError, match="Failed to load"):
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
