"""Best-of-N candidate selection (SPEECH_QUALITY_PLAN.md S2.5a)."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from backend.core import metrics
from backend.core.config import Settings, settings
from backend.services import tts_engine, tts_pipeline
from backend.services.candidate_selection import (UNSCORABLE, pick_best,
                                                  speaker_similarity)
from backend.services.tts_engine import (EngineCapabilities, SynthesisResult,
                                         TTSEngine, VoiceConditioning)

SR = 16000
TEXT = "Hello there my friend today."  # 5 words: expected about 1.7 s
PROFILE = np.eye(256, dtype=np.float32)[0]


def _voiced(seconds: float = 1.8, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


# --- the pure functions -----------------------------------------------------


def test_identical_embeddings_score_one_and_orthogonal_zero():
    other = np.eye(256, dtype=np.float32)[1]
    assert speaker_similarity(PROFILE, PROFILE * 3) == pytest.approx(1.0)
    assert speaker_similarity(PROFILE, other) == pytest.approx(0.0)
    assert speaker_similarity(PROFILE, -PROFILE) == pytest.approx(-1.0)


@pytest.mark.parametrize(
    "bad",
    [None, np.zeros(256), np.full(256, np.nan), np.ones(10)],
    ids=["none", "zeros", "nan", "wrong-length"],
)
def test_an_unusable_embedding_is_unscorable(bad):
    assert speaker_similarity(PROFILE, bad) == UNSCORABLE


def test_pick_best_takes_the_highest_and_the_earliest_on_a_tie():
    assert pick_best([0.2, 0.9, 0.5]) == 1
    assert pick_best([0.7, 0.7, 0.7]) == 0
    assert pick_best([0.4]) == 0
    assert pick_best([UNSCORABLE, 0.1]) == 1


def test_pick_best_rejects_no_candidates():
    with pytest.raises(ValueError):
        pick_best([])


@pytest.mark.parametrize("bad", [0, 5, -1])
def test_the_candidate_count_is_range_checked(bad):
    with pytest.raises(Exception):
        Settings(TTS_BEST_OF_N=bad)


def test_it_is_off_by_default():
    assert Settings.model_fields["TTS_BEST_OF_N"].default == 1


# --- through the pipeline ---------------------------------------------------


@pytest.fixture
def mock_models():
    tts_pipeline.load_mock_models("cpu")


def _run(user="bon-user"):
    return asyncio.run(tts_pipeline.run_inference_pipeline(TEXT, PROFILE, user))


def _vocoder(*waveforms):
    calls = iter(waveforms)
    seen = []

    def fake(mel):
        seen.append(1)
        return next(calls)

    return fake, seen


def _embedder(table):
    """An encoder double: a waveform's peak amplitude picks its embedding."""

    def fake(waveform):
        return table[round(float(np.max(np.abs(waveform))), 2)]

    return fake


def _alongside(similarity: float) -> np.ndarray:
    """A unit embedding whose cosine with PROFILE is ``similarity``."""
    v = np.zeros(256, np.float32)
    v[0], v[1] = similarity, float(np.sqrt(1.0 - similarity**2))
    return v


def _served_peak(path: str) -> float:
    import soundfile as sf

    data, _ = sf.read(path)
    return round(float(np.max(np.abs(data))), 1)


def _outputs() -> list:
    return [p for p in Path(settings.OUTPUT_DIR).rglob("*") if p.is_file()]


@pytest.fixture
def normalise_off(monkeypatch):
    """Serve the raw waveform so the test can tell which candidate was chosen."""
    monkeypatch.setattr(settings, "OUTPUT_NORMALIZE_ENABLED", False)


def test_n_of_one_synthesizes_once_and_never_scores(mock_models, normalise_off):
    fake, seen = _vocoder(_voiced(amp=0.2))

    def boom(_):
        raise AssertionError("the encoder must not run")

    with patch.object(tts_pipeline, "vocode", fake), patch.object(
        tts_pipeline, "_embed_candidate", boom
    ):
        path, _ = _run()
    assert len(seen) == 1 and os.path.exists(path)


def test_the_candidate_closest_to_the_profile_is_served(
    mock_models, normalise_off, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 3)
    # Peaks 0.2, 0.4, 0.3; the 0.3 candidate is the closest to the profile.
    fake, seen = _vocoder(_voiced(amp=0.2), _voiced(amp=0.4), _voiced(amp=0.3))
    table = {0.2: _alongside(0.6), 0.4: _alongside(0.5), 0.3: _alongside(0.9)}
    other = metrics.BEST_OF_N.labels("selected_other")._value.get()
    with patch.object(tts_pipeline, "vocode", fake), patch.object(
        tts_pipeline, "_embed_candidate", _embedder(table)
    ):
        path, _ = _run()
    assert len(seen) == 3
    assert _served_peak(path) == 0.3
    assert metrics.BEST_OF_N.labels("selected_other")._value.get() == other + 1
    assert len(_outputs()) == 1


def test_the_first_candidate_wins_when_it_is_the_closest(
    mock_models, normalise_off, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 2)
    fake, _ = _vocoder(_voiced(amp=0.2), _voiced(amp=0.4))
    table = {0.2: _alongside(0.9), 0.4: _alongside(0.1)}
    first = metrics.BEST_OF_N.labels("selected_first")._value.get()
    with patch.object(tts_pipeline, "vocode", fake), patch.object(
        tts_pipeline, "_embed_candidate", _embedder(table)
    ):
        path, _ = _run()
    assert _served_peak(path) == 0.2
    assert metrics.BEST_OF_N.labels("selected_first")._value.get() == first + 1


def test_a_candidate_that_fails_the_gate_is_never_served(
    mock_models, normalise_off, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 3)
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    # The second candidate is silent (it would score best if it were let in).
    fake, seen = _vocoder(
        _voiced(amp=0.2), np.zeros(SR * 2, np.float32), _voiced(amp=0.3)
    )
    table = {0.2: _alongside(0.5), 0.3: _alongside(0.7), 0.0: _alongside(1.0)}
    failed = metrics.BEST_OF_N.labels("gate_failed")._value.get()
    with patch.object(tts_pipeline, "vocode", fake), patch.object(
        tts_pipeline, "_embed_candidate", _embedder(table)
    ):
        path, _ = _run()
    assert len(seen) == 3
    assert _served_peak(path) == 0.3
    assert metrics.BEST_OF_N.labels("gate_failed")._value.get() == failed + 1


def test_when_every_extra_candidate_fails_the_gate_the_first_is_served(
    mock_models, normalise_off, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 2)
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    fake, _ = _vocoder(_voiced(amp=0.2), np.zeros(SR * 2, np.float32))

    def boom(_):
        raise AssertionError("a lone candidate needs no scoring")

    with patch.object(tts_pipeline, "vocode", fake), patch.object(
        tts_pipeline, "_embed_candidate", boom
    ):
        path, _ = _run()
    assert _served_peak(path) == 0.2


def test_unscorable_candidates_leave_the_first_in_place(
    mock_models, normalise_off, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 2)
    fake, _ = _vocoder(_voiced(amp=0.2), _voiced(amp=0.4))
    unscored = metrics.BEST_OF_N.labels("unscored")._value.get()
    with patch.object(tts_pipeline, "vocode", fake), patch.object(
        tts_pipeline, "_embed_candidate", lambda w: np.zeros(256, np.float32)
    ):
        path, _ = _run()
    assert _served_peak(path) == 0.2
    assert metrics.BEST_OF_N.labels("unscored")._value.get() == unscored + 1


def test_a_timeout_while_searching_serves_the_first_candidate(
    mock_models, normalise_off, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 2)
    calls = []

    def fake(mel):
        calls.append(1)
        if len(calls) == 2:
            raise asyncio.TimeoutError
        return _voiced(amp=0.2)

    timed_out = metrics.BEST_OF_N.labels("timed_out")._value.get()
    with patch.object(tts_pipeline, "vocode", fake):
        path, _ = _run()
    assert _served_peak(path) == 0.2
    assert metrics.BEST_OF_N.labels("timed_out")._value.get() == timed_out + 1


def test_another_engine_is_not_searched(mock_models, monkeypatch):
    """The setting is for SV2TTS; any other engine keeps its single call."""
    monkeypatch.setattr(settings, "TTS_BEST_OF_N", 3)
    calls = []

    class Other(TTSEngine):
        name = "other"
        version = "9"

        def capabilities(self):
            return EngineCapabilities("other", "9", SR, 500, ("neutral",))

        def health(self, expected_device=None):
            return {"ready": True}

        def conditioning_from_array(self, embedding):
            return VoiceConditioning("other", "9", embedding)

        async def prepare_voice(self, audio):
            return self.conditioning_from_array(PROFILE)

        async def synthesize(
            self, text, conditioning, style, *, run_stage, truncation_retries=0
        ):
            calls.append(1)
            return SynthesisResult(_voiced(), SR, 0)

    with patch.object(tts_engine, "get_engine", lambda: Other()):
        path, _ = _run()
    assert len(calls) == 1 and os.path.exists(path)
