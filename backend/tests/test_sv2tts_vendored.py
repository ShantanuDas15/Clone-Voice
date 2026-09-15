"""Unit tests for the vendored SV2TTS package (`backend/services/sv2tts/`) —
the real model architecture, text frontend, and checksum verification
introduced to close HARDENING_PLAN.md Critical finding C2 and High findings
H1/H2. See `backend/services/sv2tts/THIRD_PARTY_NOTICE.md` for provenance.
"""

import hashlib
import json
import os
import re

import numpy as np
import pytest

from backend.core.config import settings
from backend.services.sv2tts.checksum import load_manifest, verify_checksum
from backend.services.sv2tts.synthesizer.hparams import \
    hparams as synth_hparams
from backend.services.sv2tts.synthesizer.utils.text import (sequence_to_text,
                                                            text_to_sequence)
from backend.services.sv2tts.vocoder import hparams as vocoder_hparams

# ---------------------------------------------------------------------------
# Text frontend (H2 — replaces ord(c) tokenization)
# ---------------------------------------------------------------------------


def test_text_to_sequence_known_mapping():
    """A known ASCII string must map to a stable, non-trivial ID sequence
    ending in the EOS token, and round-trip losslessly through the cleaners'
    lowercase transform."""
    seq = text_to_sequence("Hello world.", synth_hparams.tts_cleaner_names)
    assert len(seq) > 1
    assert seq == text_to_sequence("Hello world.", synth_hparams.tts_cleaner_names)
    assert sequence_to_text(seq) == "hello world.~"  # english_cleaners lowercases


def test_text_to_sequence_expands_digits_via_cleaners():
    """Digits are not themselves symbols, but english_cleaners expands them
    to words before symbol mapping — "5" must not be silently dropped."""
    seq = text_to_sequence("I have 5 cats.", synth_hparams.tts_cleaner_names)
    text = sequence_to_text(seq)
    assert "five" in text
    assert "5" not in text


def test_text_to_sequence_transliterates_accented_latin():
    """english_cleaners' unidecode step transliterates accented Latin text
    to plain ASCII before symbol mapping — "café" must be representable,
    not silently mangled."""
    seq = text_to_sequence("café", synth_hparams.tts_cleaner_names)
    assert sequence_to_text(seq) == "cafe~"


def test_text_to_sequence_drops_unrepresentable_characters():
    """Characters unidecode cannot transliterate to anything (e.g. emoji)
    are silently dropped, not raised — this is exactly why
    schemas.synthesize.SynthesizeRequest validates against the same symbol
    set at the API boundary instead of relying on this function to reject
    bad input."""
    seq = text_to_sequence("hi \U0001F600 there", synth_hparams.tts_cleaner_names)
    assert sequence_to_text(seq) == "hi there~"


# ---------------------------------------------------------------------------
# Checksum verification (C2 integrity)
# ---------------------------------------------------------------------------


def test_load_manifest_has_synthesizer_and_vocoder_entries():
    manifest = load_manifest()
    assert set(manifest["files"].keys()) >= {"synthesizer.pt", "vocoder.pt"}
    for entry in manifest["files"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])


def test_verify_checksum_accepts_matching_hash(tmp_path):
    content = b"some checkpoint bytes"
    path = tmp_path / "synthesizer.pt"
    path.write_bytes(content)
    manifest = {
        "files": {"synthesizer.pt": {"sha256": hashlib.sha256(content).hexdigest()}}
    }

    verify_checksum(str(path), "synthesizer.pt", manifest)  # must not raise


def test_verify_checksum_rejects_mismatched_hash(tmp_path):
    path = tmp_path / "synthesizer.pt"
    path.write_bytes(b"tampered or corrupted bytes")
    manifest = {"files": {"synthesizer.pt": {"sha256": "0" * 64}}}

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        verify_checksum(str(path), "synthesizer.pt", manifest)


def test_verify_checksum_rejects_missing_manifest_entry(tmp_path):
    path = tmp_path / "unknown.pt"
    path.write_bytes(b"data")

    with pytest.raises(RuntimeError, match="No checksum entry"):
        verify_checksum(str(path), "unknown.pt", {"files": {}})


def test_load_manifest_raises_on_missing_file(monkeypatch):
    monkeypatch.setattr(
        "backend.services.sv2tts.checksum.MANIFEST_PATH", "/nonexistent/manifest.json"
    )
    with pytest.raises(RuntimeError, match="Could not read checksum manifest"):
        load_manifest()


# ---------------------------------------------------------------------------
# Regression guard for the H1 device-placement patch
# ---------------------------------------------------------------------------


def test_vocoder_model_has_no_hardcoded_cuda_branching():
    """Static-analysis regression guard: the vendored WaveRNN must never
    reintroduce `torch.cuda.is_available()`-branched device selection
    (HARDENING_PLAN.md finding H1 — reproduced and patched this hardening
    pass; see THIRD_PARTY_NOTICE.md "Deviations from upstream"). A future
    re-vendor from upstream that pastes the file back verbatim would
    silently reintroduce a CPU/GPU device-mismatch crash — this test fails
    loudly instead.
    """
    import backend.services.sv2tts.vocoder.models.fatchord_version as fatchord_module

    with open(fatchord_module.__file__, encoding="utf-8") as f:
        code_lines = [
            line for line in f if not line.strip().startswith("#")
        ]  # excludes this hardening pass's own "# PATCHED" explanatory
        # comments, which quote the very pattern they removed
    source = "".join(code_lines)
    assert "torch.cuda.is_available()" not in source
    assert ".cuda()" not in source


# ---------------------------------------------------------------------------
# Sample-rate consistency (verified during hardening: real hparams say
# 16000, not the previously-guessed 22050 — see core/config.py)
# ---------------------------------------------------------------------------


def test_synthesizer_and_vocoder_sample_rates_match():
    assert synth_hparams.sample_rate == vocoder_hparams.sample_rate == 16000


# ---------------------------------------------------------------------------
# Opt-in real-weights integration test (HARDENING_PLAN.md Milestone C2.1
# verification step). Skipped unless SV2TTS_REAL_WEIGHTS_DIR points at a
# directory with real, checksum-matching synthesizer.pt/vocoder.pt (see
# README.md "Model Weights") — CLAUDE.md §4.2 requires the default test run
# stay network-free and deterministic, so this never runs automatically.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("SV2TTS_REAL_WEIGHTS_DIR"),
    reason="Set SV2TTS_REAL_WEIGHTS_DIR to a directory with real, "
    "checksum-verified synthesizer.pt/vocoder.pt to run this opt-in "
    "end-to-end synthesis test against the real checkpoints.",
)
def test_real_weights_end_to_end_synthesis(monkeypatch):
    """Load the real checkpoints and run one full synthesis, proving H1
    (device placement) and H2 (text frontend) actually make the real model
    produce audio — not just load without crashing."""
    import asyncio

    from backend.services.tts_pipeline import (load_models,
                                               run_inference_pipeline,
                                               synthesize_speech, vocode)

    monkeypatch.setattr(settings, "WEIGHTS_DIR", os.environ["SV2TTS_REAL_WEIGHTS_DIR"])
    load_models("cpu")

    mel = synthesize_speech(
        "This is a real end to end test.", np.zeros(256, dtype=np.float32)
    )
    assert mel.ndim == 2 and mel.shape[0] == 80

    wav = vocode(mel)
    assert wav.ndim == 1
    assert len(wav) > 0
    assert np.max(np.abs(wav)) <= 1.0  # defensive clip in vocode() held
