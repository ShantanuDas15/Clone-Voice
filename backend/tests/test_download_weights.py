"""Unit tests for the weights-provisioning script (HARDENING_PLAN Critical
finding C2 — no fake checkpoint may ever be written, and missing real
checkpoints must be reported loudly, not masked)."""

import os
from unittest.mock import patch

from backend.download_weights import (_check_synthesizer_and_vocoder,
                                      _ensure_encoder_weights,
                                      download_weights)


def test_check_synthesizer_and_vocoder_true_when_present_and_checksum_verified(
    tmp_path,
):
    (tmp_path / "synthesizer.pt").write_bytes(b"not empty")
    (tmp_path / "vocoder.pt").write_bytes(b"not empty")

    with patch("backend.download_weights.verify_checksum", return_value=None):
        assert _check_synthesizer_and_vocoder(str(tmp_path)) is True


def test_check_synthesizer_and_vocoder_false_on_checksum_mismatch(tmp_path):
    """Real, unmocked checksum path: dummy bytes will never match the
    pinned manifest hash for the real checkpoint (HARDENING_PLAN.md finding
    C2 — corrupted/tampered files must be reported, not just missing ones)."""
    (tmp_path / "synthesizer.pt").write_bytes(b"not the real checkpoint")
    (tmp_path / "vocoder.pt").write_bytes(b"not the real checkpoint")

    assert _check_synthesizer_and_vocoder(str(tmp_path)) is False


def test_check_synthesizer_and_vocoder_false_when_missing(tmp_path):
    assert _check_synthesizer_and_vocoder(str(tmp_path)) is False


def test_check_synthesizer_and_vocoder_false_when_only_one_present(tmp_path):
    (tmp_path / "synthesizer.pt").write_bytes(b"not empty")

    assert _check_synthesizer_and_vocoder(str(tmp_path)) is False


def test_check_never_creates_any_file(tmp_path):
    """The presence check must be read-only — it must never write a
    placeholder checkpoint into an empty weights directory."""
    _check_synthesizer_and_vocoder(str(tmp_path))

    assert os.listdir(tmp_path) == []


def test_download_weights_never_writes_placeholder_files(tmp_path):
    """End-to-end: download_weights() must not create tacotron.pt/wavernn.pt
    or any other file under an empty weights directory, even when
    checkpoints are absent."""
    with patch("backend.download_weights.settings.WEIGHTS_DIR", str(tmp_path)):
        result = download_weights()

    assert result is False
    assert os.listdir(tmp_path) == []


def test_download_weights_true_when_encoder_and_checkpoints_ready(tmp_path):
    (tmp_path / "synthesizer.pt").write_bytes(b"stub")
    (tmp_path / "vocoder.pt").write_bytes(b"stub")

    with patch("backend.download_weights.settings.WEIGHTS_DIR", str(tmp_path)):
        with patch(
            "backend.download_weights._ensure_encoder_weights", return_value=True
        ):
            with patch("backend.download_weights.verify_checksum", return_value=None):
                result = download_weights()

    assert result is True


def test_download_weights_false_when_encoder_unavailable(tmp_path):
    (tmp_path / "synthesizer.pt").write_bytes(b"stub")
    (tmp_path / "vocoder.pt").write_bytes(b"stub")

    with patch("backend.download_weights.settings.WEIGHTS_DIR", str(tmp_path)):
        with patch(
            "backend.download_weights._ensure_encoder_weights", return_value=False
        ):
            result = download_weights()

    assert result is False


def test_ensure_encoder_weights_false_on_exception():
    with patch(
        "backend.download_weights.VoiceEncoder", side_effect=RuntimeError("boom")
    ):
        assert _ensure_encoder_weights() is False


def test_ensure_encoder_weights_false_when_resemblyzer_missing():
    with patch("backend.download_weights.VoiceEncoder", None):
        assert _ensure_encoder_weights() is False
