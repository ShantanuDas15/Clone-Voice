"""Unit tests for the SV2TTS TTS pipeline service functions.

These tests load models once at module scope and are fully isolated from the
database — no fixtures from conftest.py are needed.
"""

import os

import numpy as np
import pytest

from backend.services.tts_pipeline import (
    embed_speaker,
    load_models,
    save_output,
    synthesize_speech,
    vocode,
)


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
