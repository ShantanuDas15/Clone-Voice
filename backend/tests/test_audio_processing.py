"""Unit tests for backend.services.audio_processing: the preprocessing
concurrency bound (HARDENING_PLAN.md finding P2-L10) and the encoder-level
normalisation (PREPROCESSING_STUDY.md)."""

import asyncio

import numpy as np
import pytest
import soundfile as sf
from resemblyzer.audio import normalize_volume
from resemblyzer.hparams import audio_norm_target_dBFS

from backend.services import audio_processing


def test_preprocess_semaphore_is_initialized():
    """Semaphore must exist and be unlocked at rest, before any upload."""
    assert not audio_processing.preprocess_semaphore.locked()


def test_preprocess_semaphore_bounds_concurrency(monkeypatch):
    """HARDENING_PLAN.md P2-L10: no more than the configured number of
    callers may hold the preprocessing permit at once, so concurrent uploads
    can no longer decode/resample audio in unbounded parallel with the model
    forward pass `_inference_semaphore` protects."""
    fresh_semaphore = asyncio.Semaphore(2)
    monkeypatch.setattr(audio_processing, "preprocess_semaphore", fresh_semaphore)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def _worker():
        nonlocal in_flight, max_in_flight
        async with audio_processing.preprocess_semaphore:
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1

    async def _run():
        await asyncio.gather(*(_worker() for _ in range(6)))

    asyncio.run(_run())
    assert max_in_flight == 2, (
        f"Expected at most 2 concurrent holders of preprocess_semaphore, "
        f"observed {max_in_flight}"
    )


# --- Encoder level (PREPROCESSING_STUDY.md) ----------------------------------


def _rms_dbfs(y: np.ndarray) -> float:
    return 20.0 * np.log10(np.sqrt(np.mean(np.square(y, dtype=np.float64))))


def _tone(amplitude: float, seconds: float = 3.0) -> np.ndarray:
    t = np.arange(int(seconds * 16000)) / 16000
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_target_level_is_resemblyzers_own():
    """The encoder was trained at this level; a change upstream must be seen."""
    assert audio_processing.ENCODER_TARGET_DBFS == audio_norm_target_dBFS


@pytest.mark.parametrize("amplitude", [0.001, 0.01, 0.03, 0.1, 0.5, 1.0])
def test_matches_resemblyzers_increase_only_normalisation(amplitude):
    y = _tone(amplitude)
    ours = audio_processing.raise_to_encoder_level(y)
    theirs = normalize_volume(y, audio_norm_target_dBFS, increase_only=True)
    assert np.allclose(ours, theirs, atol=1e-6)


def test_quiet_audio_is_raised_to_the_target_level():
    out = audio_processing.raise_to_encoder_level(_tone(0.001))
    assert _rms_dbfs(out) == pytest.approx(-30.0, abs=0.01)


def test_loud_audio_is_left_exactly_as_it_is():
    """Not scaled to full scale, and not turned down either."""
    y = _tone(0.4)  # about -11 dBFS RMS, louder than the target
    out = audio_processing.raise_to_encoder_level(y)
    assert np.array_equal(out, y)
    assert np.max(np.abs(out)) == pytest.approx(0.4, abs=1e-3)


def test_audio_already_at_the_target_is_unchanged():
    y = _tone(0.001)
    once = audio_processing.raise_to_encoder_level(y)
    assert np.allclose(audio_processing.raise_to_encoder_level(once), once, atol=1e-6)


def test_silence_and_empty_input_come_back_untouched():
    zeros = np.zeros(1000, dtype=np.float32)
    assert np.array_equal(audio_processing.raise_to_encoder_level(zeros), zeros)
    empty = np.array([], dtype=np.float32)
    assert len(audio_processing.raise_to_encoder_level(empty)) == 0


def test_result_stays_float32_one_dimensional_and_finite():
    out = audio_processing.raise_to_encoder_level(_tone(0.002))
    assert out.dtype == np.float32 and out.ndim == 1
    assert np.all(np.isfinite(out))


def _write(path, y: np.ndarray) -> str:
    sf.write(path, y, 16000, subtype="PCM_16")
    return str(path)


def test_preprocess_audio_raises_a_quiet_upload_to_the_target_level(tmp_path):
    out = audio_processing.preprocess_audio(_write(tmp_path / "q.wav", _tone(0.005)))
    assert _rms_dbfs(out) == pytest.approx(-30.0, abs=0.2)


def test_preprocess_audio_no_longer_peak_normalises_a_loud_upload(tmp_path):
    """Regression for the change: a 0.4-peak upload used to come back at 1.0."""
    out = audio_processing.preprocess_audio(_write(tmp_path / "l.wav", _tone(0.4)))
    assert np.max(np.abs(out)) == pytest.approx(0.4, abs=0.01)


def test_preprocess_audio_still_rejects_silence(tmp_path):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        audio_processing.preprocess_audio(
            _write(tmp_path / "s.wav", np.zeros(48000, dtype=np.float32))
        )
    assert exc.value.status_code == 422
