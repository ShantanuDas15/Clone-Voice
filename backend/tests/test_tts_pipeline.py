"""Unit tests for the SV2TTS TTS pipeline service functions.

These tests load models once at module scope and are fully isolated from the
database — no fixtures from conftest.py are needed.
"""

import os

import numpy as np
import pytest

from backend.services.tts_pipeline import (embed_speaker, load_models,
                                           save_output, synthesize_speech,
                                           vocode)


@pytest.fixture(scope="module", autouse=True)
def setup_models():
    """Load TTS models once for the entire module to avoid repeated startup cost."""
    load_models("cpu")


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
