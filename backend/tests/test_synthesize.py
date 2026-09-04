import os

import numpy as np
import pytest

from backend.services.tts_pipeline import (embed_speaker, load_models,
                                           save_output, synthesize_speech,
                                           vocode)


@pytest.fixture(scope="module", autouse=True)
def setup_models():
    load_models("cpu")


def test_embed_speaker_output_shape():
    audio = np.random.randn(16000).astype(np.float32)
    emb = embed_speaker(audio)
    assert emb.shape == (256,)


def test_save_output_creates_file():
    wav = np.random.randn(16000).astype(np.float32)
    path, duration = save_output(wav, 16000, "test_user")

    assert os.path.exists(path)
    assert duration == 1.0
    os.remove(path)


def test_save_output_returns_duration():
    wav = np.random.randn(8000).astype(np.float32)
    path, duration = save_output(wav, 16000, "test_user")

    assert duration == 0.5
    os.remove(path)
