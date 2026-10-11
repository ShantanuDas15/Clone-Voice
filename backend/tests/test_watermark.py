"""The inaudible output watermark (SPEECH_QUALITY_PLAN.md S7.2b).

Most tests use stand-in networks so they run without model weights (CI has none). The last section
runs the real AudioSeal networks and is skipped unless they are provisioned in WEIGHTS_DIR.
"""

import asyncio
import json
import os
import shutil
import subprocess
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from backend import detect_watermark, download_weights
from backend.core.config import Settings, settings
from backend.services import tts_engine, tts_pipeline, watermark
from backend.services.sv2tts.checksum import load_manifest
from backend.services.watermark import (ENGINE_CODES, FRAME, MANIFEST_KEYS,
                                        MODEL_RATE, NBITS, Detection,
                                        Watermarker, message_bits)

SR = 16000
TAG = 0xC10


def _voiced(seconds=2.0, rate=SR, amp=0.2):
    t = np.arange(int(seconds * rate)) / rate
    y = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 12))
    return (amp * y / np.max(np.abs(y))).astype(np.float32)


def _speechlike(seconds=3.0, seed=0, rate=SR):
    """A voice-like signal (moving pitch, three formants, syllables and pauses).

    The real networks read the message reliably from speech but not from a bare harmonic tone, so
    the tests of the real networks use this.
    """
    from scipy.signal import lfilter

    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    f0 = 120 + 25 * np.sin(2 * np.pi * 0.7 * t) + 10 * np.sin(2 * np.pi * 3.1 * t)
    pulses = np.maximum(np.sin(np.cumsum(2 * np.pi * f0 / rate)), 0) ** 6
    source = pulses + 0.02 * rng.standard_normal(n)
    out = np.zeros(n)
    for centre, bandwidth, gain in (
        (700, 110, 1.0),
        (1200, 140, 0.6),
        (2600, 200, 0.35),
    ):
        r = np.exp(-np.pi * bandwidth / rate)
        theta = 2 * np.pi * centre / rate
        out += gain * lfilter([1 - r], [1, -2 * r * np.cos(theta), r * r], source)
    envelope = (0.55 + 0.45 * np.sin(2 * np.pi * 3.5 * t) ** 2) * (
        np.sin(2 * np.pi * 0.9 * t) > -0.6
    )
    y = out * envelope
    return (0.25 * y / np.max(np.abs(y))).astype(np.float32)


class FakeGenerator:
    """Adds a known, quiet tone; records what it was asked."""

    def __init__(self, level=0.01):
        self.level = level
        self.calls = []

    def get_watermark(self, x, rate, message=None):
        import torch

        self.calls.append(
            (x.shape[-1], rate, message[0].tolist() if message is not None else None)
        )
        t = torch.arange(x.shape[-1]) / rate
        return (self.level * torch.sin(2 * torch.pi * 440 * t)).reshape(1, 1, -1)


class FakeDetector:
    """Returns a chosen probability and message bits for every item in the batch."""

    def __init__(self, probability=0.99, bits=None):
        self.probability = probability
        self.bits = bits if bits is not None else message_bits(TAG, "sv2tts")
        self.batches = []

    def detect_watermark(self, x, rate):
        import torch

        self.batches.append(tuple(x.shape))
        n = x.shape[0]
        p = torch.full((n,), self.probability)
        m = torch.tensor(np.tile(self.bits, (n, 1)), dtype=torch.float32)
        return (p if n > 1 else p[0]), m


@pytest.fixture
def marker():
    return Watermarker(FakeGenerator(), FakeDetector(), TAG)


# --- the message ------------------------------------------------------------


def test_the_message_is_a_12_bit_tag_then_a_4_bit_engine_code():
    bits = message_bits(0xABC, "sv2tts")
    assert bits.shape == (NBITS,) and bits.dtype == np.int32
    assert int("".join(map(str, bits)), 2) == (0xABC << 4) | ENGINE_CODES["sv2tts"]


def test_each_engine_has_its_own_nonzero_code_and_unknown_is_zero():
    codes = list(ENGINE_CODES.values())
    assert len(set(codes)) == len(codes) and 0 not in codes and max(codes) < 16
    assert int("".join(map(str, message_bits(TAG, "mystery"))), 2) & 0xF == 0
    assert int("".join(map(str, message_bits(TAG, None))), 2) & 0xF == 0


def test_every_engine_the_app_can_run_has_a_code():
    from backend.services.chatterbox_engine import VARIANTS

    assert set(ENGINE_CODES) == {"sv2tts", *VARIANTS}


@pytest.mark.parametrize("tag", [-1, 4096])
def test_a_tag_that_does_not_fit_is_refused(tag):
    with pytest.raises(ValueError):
        message_bits(tag, "sv2tts")


# --- adding the watermark ---------------------------------------------------


def test_the_output_keeps_its_length_rate_and_type_and_gains_the_residual(marker):
    y = _voiced()
    out = marker.apply(y, SR, "sv2tts")
    assert out.shape == y.shape and out.dtype == np.float32
    assert np.max(np.abs(out - y)) == pytest.approx(0.01, abs=0.002)
    assert marker.generator.calls[0] == (
        len(y),
        SR,
        message_bits(TAG, "sv2tts").tolist(),
    )


def test_the_input_is_not_modified(marker):
    y = _voiced()
    before = y.copy()
    marker.apply(y, SR, "sv2tts")
    assert np.array_equal(y, before)


def test_other_sample_rates_are_marked_at_16khz_and_keep_their_own_bandwidth(marker):
    y = _voiced(1.5, rate=24000)
    out = marker.apply(y, 24000, "chatterbox_nano")
    assert out.shape == y.shape
    assert marker.generator.calls[0][1] == MODEL_RATE
    assert marker.generator.calls[0][0] == pytest.approx(len(y) * 2 / 3, abs=2)
    # The residual that was added is band-limited below 8 kHz (a windowed spectrum, to avoid
    # leakage): the 24 kHz signal keeps its own top octave untouched.
    residual = (out - y) * np.hanning(len(y))
    power = np.abs(np.fft.rfft(residual)) ** 2
    above = power[int(len(residual) * 8000 / 24000) + 20 :].sum()
    assert above / power.sum() < 1e-6


def test_peaks_are_kept_inside_full_scale():
    marker = Watermarker(FakeGenerator(level=0.1), FakeDetector(), TAG)
    y = _voiced(amp=0.98)
    out = marker.apply(y, SR, "sv2tts")
    assert np.max(np.abs(out)) <= watermark.PEAK_LIMIT + 1e-6


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((2, 100), np.float32),
        np.array([], np.float32),
        np.array([0.1, np.nan], np.float32),
    ],
)
def test_audio_that_cannot_be_marked_is_refused(marker, bad):
    with pytest.raises(ValueError):
        marker.apply(bad, SR, "sv2tts")


def test_a_very_short_clip_can_still_be_marked(marker):
    assert marker.apply(np.full(160, 0.1, np.float32), SR, "sv2tts").shape == (160,)


# --- finding it -------------------------------------------------------------


def test_detection_reads_the_tag_and_the_engine(marker):
    result = marker.detect(_voiced(), SR)
    assert result.probability == pytest.approx(0.99, abs=1e-6)
    assert (result.watermarked, result.tag_matches, result.engine) == (
        True,
        True,
        "sv2tts",
    )
    assert result.bit_accuracy_vs_expected_tag == 1.0


def test_a_low_probability_is_not_a_watermark():
    d = Watermarker(FakeGenerator(), FakeDetector(probability=0.03), TAG).detect(
        _voiced(), SR
    )
    assert d.watermarked is False


def test_another_services_tag_is_recognised_as_not_ours():
    other = message_bits(0x123, "sv2tts")
    d = Watermarker(FakeGenerator(), FakeDetector(bits=other), TAG).detect(
        _voiced(), SR
    )
    assert d.watermarked and not d.tag_matches and d.bit_accuracy_vs_expected_tag < 1.0


def test_an_unknown_engine_code_reports_none():
    bits = message_bits(TAG, "sv2tts").copy()
    bits[-4:] = [1, 1, 1, 1]
    d = Watermarker(FakeGenerator(), FakeDetector(bits=bits), TAG).detect(_voiced(), SR)
    assert d.engine is None and d.tag_matches


def test_searching_alignments_tries_every_offset_in_one_batch(marker):
    marker.detect(_voiced(3.0), SR, search_alignment=True)
    assert marker.detector.batches[-1][0] == FRAME
    marker.detect(_voiced(3.0), SR)
    assert marker.detector.batches[-1][0] == 1


def test_a_clip_too_short_to_search_falls_back_to_one_alignment(marker):
    marker.detect(np.full(FRAME * 3, 0.1, np.float32), SR, search_alignment=True)
    assert marker.detector.batches[-1][0] == 1
    marker.detect(np.full(FRAME * 4, 0.1, np.float32), SR, search_alignment=True)
    assert marker.detector.batches[-1][0] == FRAME


class PerOffsetDetector:
    """Confident at every offset, but the message is only right in a small cluster of them."""

    def __init__(self, good, good_bits, bad_bits_for):
        self.good = good
        self.good_bits = good_bits
        self.bad = bad_bits_for

    def detect_watermark(self, x, rate):
        import torch

        n = x.shape[0]
        bits = np.array(
            [self.good_bits if i in self.good else self.bad(i) for i in range(n)],
            dtype=np.float32,
        )
        return torch.ones(n), torch.from_numpy(bits)


def test_after_a_search_the_message_is_read_from_the_cluster_that_carries_our_tag():
    tag = message_bits(TAG, "chatterbox_nano")
    wrong = lambda i: message_bits(
        0x123 + i, "sv2tts"
    )  # confident but garbled elsewhere
    detector = PerOffsetDetector(set(range(221, 228)), tag, wrong)
    d = Watermarker(FakeGenerator(), detector, TAG).detect(
        _voiced(3.0), SR, search_alignment=True
    )
    assert d.watermarked and d.tag_matches and d.engine == "chatterbox_nano"
    assert d.bit_accuracy_vs_expected_tag == 1.0


def test_a_lone_chance_match_loses_to_a_real_cluster():
    tag = message_bits(TAG, "chatterbox_nano")
    other_engine = message_bits(
        TAG, "sv2tts"
    )  # a chance tag match elsewhere, different engine
    detector = PerOffsetDetector(
        set(range(100, 106)),
        tag,
        lambda i: other_engine if i == 7 else message_bits(0x555, None),
    )
    d = Watermarker(FakeGenerator(), detector, TAG).detect(
        _voiced(3.0), SR, search_alignment=True
    )
    assert d.engine == "chatterbox_nano"


def test_no_offset_carrying_our_tag_means_no_engine_is_claimed():
    detector = PerOffsetDetector(set(), None, lambda i: message_bits(0x123, "sv2tts"))
    d = Watermarker(FakeGenerator(), detector, TAG).detect(
        _voiced(3.0), SR, search_alignment=True
    )
    assert d.watermarked and not d.tag_matches and d.engine is None


def test_a_clip_under_40_ms_cannot_be_checked(marker):
    with pytest.raises(ValueError):
        marker.detect(np.full(FRAME, 0.1, np.float32), SR)


# --- loading and status -----------------------------------------------------


def test_the_manifest_pins_both_networks_with_hashes_and_sizes():
    files = load_manifest()["files"]
    for key in MANIFEST_KEYS.values():
        assert len(files[key]["sha256"]) == 64 and files[key]["size_bytes"] > 1_000_000


def test_missing_weights_say_how_to_fetch_them(tmp_path):
    with pytest.raises(RuntimeError, match="download_weights --fetch"):
        Watermarker.from_weights(str(tmp_path), TAG)


def test_a_tampered_checkpoint_is_refused_before_it_is_loaded(tmp_path):
    folder = tmp_path / watermark.SUBDIR
    folder.mkdir()
    for name in MANIFEST_KEYS:
        (folder / name).write_bytes(b"not the real network")
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        Watermarker.from_weights(str(tmp_path), TAG)


def test_loading_never_needs_the_network_or_a_compiler():
    assert os.environ.get("NO_TORCH_COMPILE") == "1"


def test_status_when_off_when_loaded_and_when_loading_fails(monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    assert watermark.watermark_status() == {"enabled": False, "loaded": False}
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    watermark.get_watermarker.cache_clear()
    with patch.object(Watermarker, "from_weights", side_effect=RuntimeError("missing")):
        assert watermark.watermark_status() == {"enabled": True, "loaded": False}
    with patch.object(Watermarker, "from_weights", return_value="ok"):
        assert watermark.watermark_status() == {"enabled": True, "loaded": True}
    watermark.get_watermarker.cache_clear()


def test_settings_bounds_for_the_tag():
    assert Settings().WATERMARK_ENABLED is True and Settings().WATERMARK_TAG == 0xC10
    for bad in (-1, 4096):
        with pytest.raises(Exception):
            Settings(WATERMARK_TAG=bad)


# --- in the pipeline --------------------------------------------------------


@pytest.fixture
def wm_on(monkeypatch):
    fake = Watermarker(FakeGenerator(), FakeDetector(), TAG)
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    monkeypatch.setattr(watermark, "get_watermarker", lambda: fake)
    return fake


def _saved(path):
    return sf.read(path, dtype="float32")


def test_every_saved_output_carries_the_residual_and_names_the_engine(
    wm_on, monkeypatch
):
    monkeypatch.setattr(settings, "OUTPUT_NORMALIZE_ENABLED", False)
    y = _voiced(1.0, amp=0.3)
    path, _ = tts_pipeline.finish_and_save(y, SR, "wm-user", "chatterbox_nano")
    saved, rate = _saved(path)
    assert rate == SR and np.max(np.abs(saved - y)) > 0.005
    assert wm_on.generator.calls[0][2] == message_bits(TAG, "chatterbox_nano").tolist()


def test_it_is_added_after_levelling_so_levelling_cannot_undo_it(wm_on):
    path, _ = tts_pipeline.finish_and_save(
        _voiced(2.0, amp=0.01), SR, "wm-user", "sv2tts"
    )
    marked_input = wm_on.generator.calls[0]
    assert marked_input[0] == 2 * SR  # the whole clip, once, at its final level


def test_when_it_cannot_be_applied_nothing_is_saved(wm_on, tmp_path):
    wm_on.generator = type(
        "Broken",
        (),
        {
            "get_watermark": lambda *a, **k: (_ for _ in ()).throw(
                RuntimeError("no model")
            )
        },
    )()
    with pytest.raises(RuntimeError):
        tts_pipeline.finish_and_save(_voiced(1.0), SR, "failclosed-user", "sv2tts")
    out_dir = os.path.join(settings.OUTPUT_DIR, "failclosed-user")
    assert not os.path.exists(out_dir) or os.listdir(out_dir) == []


def test_switched_off_the_pipeline_does_not_touch_the_networks(monkeypatch):
    called = []
    monkeypatch.setattr(watermark, "get_watermarker", lambda: called.append(1))
    tts_pipeline.finish_and_save(_voiced(1.0), SR, "off-user", "sv2tts")
    assert called == []


def test_the_pipeline_names_the_engine_that_actually_spoke(wm_on):
    tts_pipeline.load_mock_models("cpu")
    asyncio.run(
        tts_pipeline.run_inference_pipeline("Hello.", np.ones(256, np.float32), "who")
    )
    assert wm_on.generator.calls[-1][2] == message_bits(TAG, "sv2tts").tolist()


def test_a_fallback_response_is_marked_as_the_fallback_engine(wm_on, monkeypatch):
    from backend.services.tts_engine import EngineUnavailableError
    from backend.tests.test_engine_fallback import _FlakyEngine

    tts_pipeline.load_mock_models("cpu")
    monkeypatch.setattr(
        tts_engine, "get_engine", lambda: _FlakyEngine(EngineUnavailableError("down"))
    )
    asyncio.run(
        tts_pipeline.run_inference_pipeline("Hello.", np.ones(256, np.float32), "who")
    )
    assert wm_on.generator.calls[-1][2] == message_bits(TAG, "sv2tts").tolist()


# --- readiness --------------------------------------------------------------


def test_readiness_reports_the_watermark_and_needs_it_when_on(client, monkeypatch):
    assert client.get("/health/ready").json()["watermark"] == {
        "enabled": False,
        "loaded": False,
    }
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    watermark.get_watermarker.cache_clear()
    with patch.object(Watermarker, "from_weights", side_effect=RuntimeError("missing")):
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["watermark"] == {"enabled": True, "loaded": False}
    with patch.object(Watermarker, "from_weights", return_value="ok"):
        response = client.get("/health/ready")
    assert (
        response.status_code == 200 and response.json()["watermark"]["loaded"] is True
    )
    watermark.get_watermarker.cache_clear()


# --- provisioning -----------------------------------------------------------


def test_provisioning_skips_the_watermark_when_it_is_off(tmp_path):
    with patch.object(download_weights, "hf_hub_download") as fetch:
        assert download_weights.fetch_watermark_weights(str(tmp_path)) is True
    fetch.assert_not_called()


def test_provisioning_downloads_what_is_missing_and_verifies_it(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    seen = []

    def fake_fetch(repo_id, filename, local_dir):
        seen.append((repo_id, filename))
        path = os.path.join(local_dir, filename)
        open(path, "wb").write(b"x")
        return path

    with patch.object(download_weights, "hf_hub_download", fake_fetch), patch.object(
        download_weights, "verify_checksum"
    ):
        assert download_weights.fetch_watermark_weights(str(tmp_path)) is True
    assert sorted(seen) == [("facebook/audioseal", f) for f in sorted(MANIFEST_KEYS)]


def test_provisioning_keeps_a_file_that_already_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    folder = tmp_path / watermark.SUBDIR
    folder.mkdir()
    for name in MANIFEST_KEYS:
        (folder / name).write_bytes(b"x")
    with patch.object(download_weights, "hf_hub_download") as fetch, patch.object(
        download_weights, "verify_checksum"
    ):
        assert download_weights.fetch_watermark_weights(str(tmp_path)) is True
    fetch.assert_not_called()


def test_provisioning_fails_when_a_download_does_not_verify(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    fake = lambda repo_id, filename, local_dir: os.path.join(local_dir, filename)
    with patch.object(download_weights, "hf_hub_download", fake), patch.object(
        download_weights,
        "verify_checksum",
        side_effect=RuntimeError("Checksum mismatch"),
    ):
        assert download_weights.fetch_watermark_weights(str(tmp_path)) is False


def test_the_offline_check_needs_both_networks_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", True)
    assert download_weights._check_watermark_weights(str(tmp_path)) is False
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    assert download_weights._check_watermark_weights(str(tmp_path)) is True


# --- the review tool --------------------------------------------------------


def test_the_review_tool_reports_and_sets_its_exit_status(
    tmp_path, capsys, monkeypatch
):
    clip = tmp_path / "c.wav"
    sf.write(str(clip), _voiced(), SR)
    monkeypatch.setattr(
        watermark,
        "get_watermarker",
        lambda: Watermarker(FakeGenerator(), FakeDetector(), TAG),
    )
    assert detect_watermark.main([str(clip)]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict == {
        "watermarked": True,
        "probability": 0.99,
        "tag_matches": True,
        "engine": "sv2tts",
    }
    monkeypatch.setattr(
        watermark,
        "get_watermarker",
        lambda: Watermarker(FakeGenerator(), FakeDetector(probability=0.01), TAG),
    )
    assert detect_watermark.main([str(clip)]) == 1
    capsys.readouterr()
    assert detect_watermark.main([str(tmp_path / "missing.wav")]) == 2
    assert "error" in capsys.readouterr().err


# --- the real networks (skipped unless provisioned) --------------------------

REAL = all(
    os.path.isfile(os.path.join(settings.WEIGHTS_DIR, watermark.SUBDIR, f))
    for f in MANIFEST_KEYS
)
needs_weights = pytest.mark.skipif(
    not REAL, reason="AudioSeal weights are not provisioned"
)


@pytest.fixture(scope="module")
def real():
    watermark.get_watermarker.cache_clear()
    return Watermarker.from_weights(settings.WEIGHTS_DIR, TAG)


@needs_weights
def test_real_marked_audio_is_found_with_its_engine_and_clean_audio_is_not(real):
    y = _speechlike(3.0)
    marked = real.apply(y, SR, "chatterbox_nano")
    found = real.detect(marked, SR)
    assert found.watermarked and found.tag_matches and found.engine == "chatterbox_nano"
    assert real.detect(y, SR).watermarked is False


@needs_weights
def test_real_the_watermark_is_quiet(real):
    y = _speechlike(3.0)
    residual = real.apply(y, SR, "sv2tts") - y
    snr = 10 * np.log10(np.mean(y**2) / np.mean(residual**2))
    assert snr > 15


@needs_weights
def test_real_24khz_output_keeps_its_bandwidth_and_is_found(real):
    y = _speechlike(3.0, rate=24000)
    marked = real.apply(y, 24000, "chatterbox_turbo")
    assert marked.shape == y.shape
    assert real.detect(marked, 24000).watermarked


@needs_weights
def test_real_it_survives_16_bit_quantisation_and_a_wav_round_trip(real, tmp_path):
    marked = real.apply(_speechlike(3.0), SR, "sv2tts")
    path = tmp_path / "m.wav"
    sf.write(str(path), marked, SR, subtype="PCM_16")
    again, rate = sf.read(str(path), dtype="float32")
    assert real.detect(again, rate).watermarked


@needs_weights
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_real_it_survives_mp3_compression(real, tmp_path):
    marked = real.apply(_speechlike(3.0), SR, "sv2tts")
    wav, mp3, back = tmp_path / "a.wav", tmp_path / "a.mp3", tmp_path / "b.wav"
    sf.write(str(wav), marked, SR, subtype="PCM_16")
    run = lambda *a: subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", *a], check=True
    )
    run("-i", str(wav), "-b:a", "64k", str(mp3))
    run("-i", str(mp3), "-ar", str(SR), str(back))
    decoded, rate = sf.read(str(back), dtype="float32")
    assert real.detect(decoded, rate).watermarked


@needs_weights
def test_real_trimming_at_an_odd_sample_needs_the_alignment_search(real):
    marked = real.apply(_speechlike(3.0), SR, "sv2tts")
    trimmed = marked[7777:]  # not a multiple of the 320-sample frame
    plain = real.detect(trimmed, SR)
    searched = real.detect(trimmed, SR, search_alignment=True)
    # Usually the plain detector misses it (a statistical property: one in eight such clips still
    # scores above 0.5), but the search always does better and finds it.
    assert searched.probability > plain.probability
    assert searched.watermarked and searched.tag_matches and searched.engine == "sv2tts"
