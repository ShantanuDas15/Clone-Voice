"""Tests for cross-chunk continuity (SPEECH_QUALITY_PLAN.md S1.6)."""

import numpy as np
import pytest
import torch
from pydantic import ValidationError

from backend.core.config import Settings, settings
from backend.services import tts_pipeline
from backend.services.sv2tts.synthesizer.models.tacotron import Tacotron
from backend.services.sv2tts.synthesizer.utils.symbols import symbols

EMB = np.zeros(256, dtype=np.float32)
TEXT = "First sentence here. Second one follows! And a third?"


def _tiny_tacotron() -> Tacotron:
    """A small randomly initialised Tacotron: enough to exercise the decoder state."""
    model = Tacotron(
        embed_dims=16,
        num_chars=len(symbols),
        encoder_dims=16,
        decoder_dims=16,
        n_mels=80,
        fft_bins=80,
        postnet_dims=16,
        encoder_K=2,
        lstm_dims=24,
        postnet_K=2,
        num_highways=1,
        dropout=0.0,
        stop_threshold=-3.4,
        speaker_embedding_size=8,
    )
    model.r = 2
    return model


def _inputs() -> tuple[torch.Tensor, torch.Tensor]:
    return torch.randint(1, len(symbols), (1, 12)), torch.randn(1, 8)


# ---- model: the decoder accepts and returns state ----------------------------


def test_generate_default_return_is_unchanged() -> None:
    torch.manual_seed(0)
    x, emb = _inputs()
    out = _tiny_tacotron().generate(x, emb, steps=20)
    assert len(out) == 3


def test_generate_returns_state_when_asked() -> None:
    torch.manual_seed(0)
    x, emb = _inputs()
    mel, _, _, state = _tiny_tacotron().generate(x, emb, steps=20, return_state=True)
    assert state["frame"].shape == (1, 80)
    assert torch.equal(state["frame"], mel[:, :, -1])
    assert [tuple(t.shape) for t in state["rnn"]] == [(1, 24)] * 4


def test_empty_prior_equals_no_prior() -> None:
    """A cold-start prior must not change the decode."""
    x, emb = _inputs()
    model = _tiny_tacotron()
    torch.manual_seed(1)
    plain = model.generate(x, emb, steps=20)[1]
    torch.manual_seed(1)
    empty = model.generate(x, emb, steps=20, prior_state={})[1]
    assert torch.equal(plain, empty)


@pytest.mark.parametrize("part", ["frame", "rnn"])
def test_each_prior_part_changes_the_decode(part: str) -> None:
    x, emb = _inputs()
    model = _tiny_tacotron()
    _, _, _, state = model.generate(x, emb, steps=20, return_state=True)
    state["frame"] = state["frame"] + 1.0
    state["rnn"] = tuple(t + 1.0 for t in state["rnn"])
    torch.manual_seed(2)
    plain = model.generate(x, emb, steps=20)[1]
    torch.manual_seed(2)
    seeded = model.generate(x, emb, steps=20, prior_state={part: state[part]})[1]
    assert not torch.equal(plain, seeded)


# ---- setting -----------------------------------------------------------------


def test_continuity_defaults_off() -> None:
    assert Settings.model_fields["TTS_CHUNK_CONTINUITY"].default == "off"


def test_continuity_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(TTS_CHUNK_CONTINUITY="everything")


# ---- pipeline ----------------------------------------------------------------


class _Recorder(torch.nn.Module):
    """Stands in for the synthesizer: records each call's prior and returns a mel."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    def generate(self, text_ids, emb, steps=2000, prior_state=None, return_state=False):
        self.calls.append({"prior": prior_state, "return_state": return_state})
        mel = torch.full((1, 80, 30), float(len(self.calls)))
        if not return_state:
            return None, mel, None
        state = {"frame": mel[:, :, -1], "rnn": tuple(torch.ones(1, 4) for _ in "abcd")}
        return None, mel, None, state


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(tts_pipeline, "_synthesizer", rec)
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 25)
    return rec


def test_off_never_passes_state(recorder, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "off")
    tts_pipeline.synthesize_speech(TEXT, EMB)
    assert len(recorder.calls) >= 3
    assert all(c == {"prior": None, "return_state": False} for c in recorder.calls)


def test_frame_mode_carries_only_the_frame(recorder, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "frame")
    tts_pipeline.synthesize_speech(TEXT, EMB)
    first, *rest = recorder.calls
    assert first["prior"] == {} and first["return_state"]
    for call in rest:
        assert set(call["prior"]) == {"frame"}
        assert call["return_state"]


def test_state_mode_carries_frame_and_rnn(recorder, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "state")
    tts_pipeline.synthesize_speech(TEXT, EMB)
    for call in recorder.calls[1:]:
        assert set(call["prior"]) == {"frame", "rnn"}


def test_carried_frame_is_the_last_frame_the_listener_hears(
    recorder, monkeypatch
) -> None:
    """Frames the stop-token trim drops must not seed the next chunk."""
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "frame")
    monkeypatch.setattr(
        recorder,
        "generate",
        lambda ids, emb, steps=2000, prior_state=None, return_state=False: (
            None,
            _mel_with_silent_tail(),
            None,
            {"frame": torch.zeros(1, 80), "rnn": ()},
        ),
    )
    seen: list[dict] = []
    real = tts_pipeline._decode_chunk
    monkeypatch.setattr(
        tts_pipeline,
        "_decode_chunk",
        lambda text, emb, prior: seen.append(prior) or real(text, emb, prior),
    )
    tts_pipeline.synthesize_speech(TEXT, EMB)
    assert float(seen[1]["frame"].max()) == pytest.approx(0.5)


def _mel_with_silent_tail() -> torch.Tensor:
    """20 audible frames (value 0.5) then 10 frames below the stop threshold."""
    mel = torch.full((1, 80, 30), -4.0)
    mel[:, :, :20] = 0.5
    return mel


def test_single_chunk_text_is_unaffected(monkeypatch) -> None:
    """With one chunk there is nothing to carry: the mel matches the plain path."""
    text = "Hello world."
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "state")
    chained = tts_pipeline.synthesize_speech(text, EMB)
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "off")
    assert np.array_equal(chained, tts_pipeline.synthesize_speech(text, EMB))


def test_mel_layout_is_unchanged_by_continuity(monkeypatch) -> None:
    """Continuity changes how chunks sound, never how many frames or pauses there are."""
    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 25)
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "off")
    plain = tts_pipeline.synthesize_speech(TEXT, EMB)
    for mode in ("frame", "state"):
        monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", mode)
        assert tts_pipeline.synthesize_speech(TEXT, EMB).shape == plain.shape


def test_truncation_still_counted_in_chained_mode(monkeypatch) -> None:
    """The quality gate's truncation count must keep working on the new path."""
    from backend.services.sv2tts.synthesizer.hparams import hparams as hp

    monkeypatch.setattr(settings, "TTS_CHUNK_MAX_CHARS", 25)
    monkeypatch.setattr(settings, "TTS_CHUNK_CONTINUITY", "frame")
    monkeypatch.setattr(hp, "max_mel_frames", 5)
    _, truncated = tts_pipeline._synthesize_counting_truncation(TEXT, EMB)
    assert truncated >= 3
