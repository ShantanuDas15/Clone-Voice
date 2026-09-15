"""Unit tests for the weights-provisioning script (HARDENING_PLAN Critical
finding C2 — no fake checkpoint may ever be written, and missing real
checkpoints must be reported loudly, not masked; Milestone C2.2 — the
`--fetch` download path must be idempotent, network-frugal, and never
silently accept a corrupted download)."""

import os
from unittest.mock import patch

from backend.download_weights import (REQUIRED_CHECKPOINTS,
                                      _check_synthesizer_and_vocoder,
                                      _ensure_encoder_weights,
                                      download_weights,
                                      fetch_and_verify_checkpoints,
                                      fetch_weights, main)


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


# ---------------------------------------------------------------------------
# --fetch mode (HARDENING_PLAN.md Milestone C2.2)
# ---------------------------------------------------------------------------


def test_fetch_checkpoint_calls_hf_hub_download_with_expected_args(tmp_path):
    from backend.download_weights import HF_REPO_ID, _fetch_checkpoint

    with patch(
        "backend.download_weights.hf_hub_download",
        return_value=str(tmp_path / "synthesizer.pt"),
    ) as mock_hf:
        result = _fetch_checkpoint("synthesizer.pt", str(tmp_path))

    mock_hf.assert_called_once_with(
        repo_id=HF_REPO_ID, filename="synthesizer.pt", local_dir=str(tmp_path)
    )
    assert result == str(tmp_path / "synthesizer.pt")


def test_fetch_and_verify_checkpoints_skips_download_when_already_verified(
    tmp_path,
):
    """A file already present and checksum-verified must never trigger a
    network call — idempotent and network-frugal by design."""
    (tmp_path / "synthesizer.pt").write_bytes(b"already good")
    (tmp_path / "vocoder.pt").write_bytes(b"already good")

    with patch("backend.download_weights.verify_checksum", return_value=None):
        with patch("backend.download_weights.hf_hub_download") as mock_hf:
            result = fetch_and_verify_checkpoints(str(tmp_path))

    assert result is True
    mock_hf.assert_not_called()


def test_fetch_and_verify_checkpoints_downloads_missing_files(tmp_path):
    def fake_hf_hub_download(repo_id, filename, local_dir):
        path = os.path.join(local_dir, filename)
        with open(path, "wb") as f:
            f.write(b"downloaded stub")
        return path

    with patch(
        "backend.download_weights.hf_hub_download", side_effect=fake_hf_hub_download
    ) as mock_hf:
        with patch("backend.download_weights.verify_checksum", return_value=None):
            result = fetch_and_verify_checkpoints(str(tmp_path))

    assert result is True
    assert mock_hf.call_count == len(REQUIRED_CHECKPOINTS)
    for name in REQUIRED_CHECKPOINTS:
        assert (tmp_path / name).exists()


def test_fetch_and_verify_checkpoints_false_on_download_failure(tmp_path):
    with patch(
        "backend.download_weights.hf_hub_download",
        side_effect=ConnectionError("network unreachable"),
    ):
        result = fetch_and_verify_checkpoints(str(tmp_path))

    assert result is False


def test_fetch_and_verify_checkpoints_false_on_checksum_mismatch_after_download(
    tmp_path,
):
    """A download that completes but doesn't match the pinned manifest must
    not be silently accepted (HARDENING_PLAN.md finding C2 — corrupted or
    tampered checkpoints are always rejected, download tooling included)."""

    def fake_hf_hub_download(repo_id, filename, local_dir):
        path = os.path.join(local_dir, filename)
        with open(path, "wb") as f:
            f.write(b"corrupted or tampered download")
        return path

    with patch(
        "backend.download_weights.hf_hub_download", side_effect=fake_hf_hub_download
    ):
        result = fetch_and_verify_checkpoints(str(tmp_path))

    assert result is False


def test_fetch_and_verify_checkpoints_redownloads_corrupted_local_copy(tmp_path):
    """A local file that fails checksum verification is treated as absent
    and re-fetched — it must not be left in place to make every future
    load_models() call fail with the same stale error."""
    (tmp_path / "synthesizer.pt").write_bytes(b"corrupted local copy")
    (tmp_path / "vocoder.pt").write_bytes(b"corrupted local copy")

    freshly_downloaded = set()

    def fake_verify(path, filename, manifest):
        # Fails until *that specific file* has been (re)downloaded, so each
        # checkpoint's pre-download check fails and its own post-download
        # check succeeds, independent of the other checkpoint's state.
        if filename not in freshly_downloaded:
            raise RuntimeError("Checksum mismatch (pre-download check)")
        return None

    def fake_hf_hub_download(repo_id, filename, local_dir):
        freshly_downloaded.add(filename)
        path = os.path.join(local_dir, filename)
        with open(path, "wb") as f:
            f.write(b"freshly downloaded, valid")
        return path

    with patch("backend.download_weights.verify_checksum", side_effect=fake_verify):
        with patch(
            "backend.download_weights.hf_hub_download",
            side_effect=fake_hf_hub_download,
        ) as mock_hf:
            result = fetch_and_verify_checkpoints(str(tmp_path))

    assert result is True
    assert mock_hf.call_count == len(REQUIRED_CHECKPOINTS)


def test_fetch_weights_true_when_encoder_and_checkpoints_ready():
    with patch("backend.download_weights._ensure_encoder_weights", return_value=True):
        with patch(
            "backend.download_weights.fetch_and_verify_checkpoints",
            return_value=True,
        ):
            assert fetch_weights() is True


def test_fetch_weights_false_when_encoder_unavailable():
    with patch("backend.download_weights._ensure_encoder_weights", return_value=False):
        with patch(
            "backend.download_weights.fetch_and_verify_checkpoints",
            return_value=True,
        ):
            assert fetch_weights() is False


# ---------------------------------------------------------------------------
# CLI dispatch (main())
# ---------------------------------------------------------------------------


def test_main_default_calls_download_weights_not_fetch_weights():
    with patch("backend.download_weights.download_weights", return_value=True) as dw:
        with patch("backend.download_weights.fetch_weights") as fw:
            exit_code = main([])

    assert exit_code == 0
    dw.assert_called_once()
    fw.assert_not_called()


def test_main_fetch_flag_calls_fetch_weights_not_download_weights():
    with patch("backend.download_weights.fetch_weights", return_value=True) as fw:
        with patch("backend.download_weights.download_weights") as dw:
            exit_code = main(["--fetch"])

    assert exit_code == 0
    fw.assert_called_once()
    dw.assert_not_called()


def test_main_returns_nonzero_when_not_ready():
    with patch("backend.download_weights.download_weights", return_value=False):
        assert main([]) == 1
