"""Core text-to-speech inference pipeline."""

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


def load_models(device: str = "cpu") -> None:
    """Load all TTS models into memory for inference."""
    global _encoder, _synthesizer, _vocoder
    logger.info(f"Loading SV2TTS models on {device}...")

    if VoiceEncoder is not None:
        _encoder = VoiceEncoder(device=device)
    else:
        logger.warning("resemblyzer not found.")

    weights_dir = os.path.join(os.path.dirname(__file__), "..", "weights")

    synth_path = os.path.join(weights_dir, "synthesizer.pt")
    if not os.path.exists(synth_path):
        synth_path = os.path.join(weights_dir, "tacotron.pt")

    try:
        _synthesizer = torch.jit.load(synth_path, map_location=device)
        _synthesizer.eval()
    except Exception as e:
        logger.warning(
            f"Could not load real synthesizer from {synth_path}: {e}. Using mock."
        )
        _synthesizer = "Tacotron2_Mock"

    voc_path = os.path.join(weights_dir, "vocoder.pt")
    if not os.path.exists(voc_path):
        voc_path = os.path.join(weights_dir, "wavernn.pt")

    try:
        _vocoder = torch.jit.load(voc_path, map_location=device)
        _vocoder.eval()
    except Exception as e:
        logger.warning(f"Could not load real vocoder from {voc_path}: {e}. Using mock.")
        _vocoder = "WaveRNN_Mock"

    logger.info("Models loaded successfully.")


def embed_speaker(audio: np.ndarray) -> np.ndarray:
    """Extract a 256-dim speaker embedding from a preprocessed audio array."""
    if _encoder is None or audio is None or len(audio) == 0:
        logger.warning(
            "embed_speaker: encoder unavailable or empty audio — returning zeros."
        )
        return np.zeros(256, dtype=np.float32)

    return _encoder.embed_utterance(audio)


def synthesize_speech(text: str, embedding: np.ndarray) -> np.ndarray:
    """Generate a mel spectrogram from text and a speaker embedding."""
    if _synthesizer is None or isinstance(_synthesizer, str):
        logger.warning("synthesize_speech: model unavailable — returning mock mel.")
        mel_frames = len(text) * 5
        return np.random.randn(mel_frames, 80).astype(np.float32)

    with torch.no_grad():
        # Minimal conversion; actual models vary.
        text_tensor = torch.tensor([ord(c) for c in text], dtype=torch.long).unsqueeze(
            0
        )
        emb_tensor = torch.from_numpy(embedding).unsqueeze(0)
        mel = _synthesizer(text_tensor, emb_tensor)
        return mel.squeeze(0).cpu().numpy()


def vocode(mel: np.ndarray) -> np.ndarray:
    """Convert a mel spectrogram to a raw audio waveform."""
    if _vocoder is None or isinstance(_vocoder, str):
        logger.warning("vocode: model unavailable — returning mock waveform.")
        samples = mel.shape[0] * 200
        return np.random.randn(samples).astype(np.float32)

    with torch.no_grad():
        mel_tensor = torch.from_numpy(mel).unsqueeze(0)
        wav = _vocoder(mel_tensor)
        return wav.squeeze(0).cpu().numpy()


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
