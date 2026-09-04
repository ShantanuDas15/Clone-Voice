import os
import uuid

import numpy as np
import soundfile as sf

from backend.core.config import settings

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    VoiceEncoder = None

_encoder = None
_synthesizer = None
_vocoder = None


def load_models(device: str = "cpu") -> None:
    global _encoder, _synthesizer, _vocoder
    print(f"Loading SV2TTS models on {device}...")

    if VoiceEncoder is not None:
        _encoder = VoiceEncoder(device=device)
    else:
        print("Warning: resemblyzer not found.")

    _synthesizer = "Tacotron2_Mock"
    _vocoder = "WaveRNN_Mock"

    print("Models loaded successfully.")


def embed_speaker(audio: np.ndarray) -> np.ndarray:
    if _encoder is None:
        return np.zeros(256, dtype=np.float32)

    return _encoder.embed_utterance(audio)


def synthesize_speech(text: str, embedding: np.ndarray) -> np.ndarray:
    mel_frames = len(text) * 5
    return np.random.randn(mel_frames, 80).astype(np.float32)


def vocode(mel: np.ndarray) -> np.ndarray:
    samples = mel.shape[0] * 200
    return np.random.randn(samples).astype(np.float32)


def save_output(
    waveform: np.ndarray, sample_rate: int, user_id: str
) -> tuple[str, float]:
    out_dir = os.path.join(settings.OUTPUT_DIR, user_id)
    os.makedirs(out_dir, exist_ok=True)

    filename = f"{uuid.uuid4()}.wav"
    file_path = os.path.join(out_dir, filename)

    if waveform.ndim > 1:
        waveform = waveform.squeeze()

    sf.write(file_path, waveform, sample_rate)

    duration = len(waveform) / sample_rate
    return file_path, float(duration)
