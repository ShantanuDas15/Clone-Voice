"""Content-based upload validation, bounded decoding and safe checkpoint
loading (SEC-4)."""

import ast
import io
import struct
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from backend.services import audio_processing

BACKEND = Path(__file__).resolve().parents[1]

WAV = b"RIFF" + struct.pack("<I", 36) + b"WAVE" + b"fmt " + b"\x00" * 40
AVI = b"RIFF" + struct.pack("<I", 36) + b"AVI " + b"LIST" + b"\x00" * 40
WEBP = b"RIFF" + struct.pack("<I", 36) + b"WEBP" + b"VP8 " + b"\x00" * 40
MP3 = b"ID3\x04\x00\x00" + b"\x00" * 60
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x82\x84webm" + b"\x00" * 50
MATROSKA = b"\x1a\x45\xdf\xa3\x9f\x42\x82\x88matroska" + b"\x00" * 50


def _upload(content: bytes, media_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename="x",
        headers=Headers({"content-type": media_type}),
    )


def _status(content: bytes, media_type: str) -> int:
    try:
        audio_processing.validate_audio_file(_upload(content, media_type))
    except HTTPException as error:
        return error.status_code
    return 200


# --- sniffing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "head, expected",
    [
        (WAV, ".wav"),
        (MP3, ".mp3"),
        (b"\xff\xfb\x90\x00" + b"\x00" * 60, ".mp3"),
        (WEBM, ".webm"),
        (AVI, None),  # also starts with RIFF
        (WEBP, None),  # so does WebP
        (MATROSKA, None),  # same EBML container, but may carry video
        (b"", None),
        (b"RIFF", None),
        (b"MZ\x90\x00" + b"\x00" * 60, None),
    ],
)
def test_the_content_decides_what_a_file_is(head, expected):
    assert audio_processing.sniff_audio_extension(head) == expected


# --- declared type vs content -----------------------------------------------


@pytest.mark.parametrize(
    "content, media_type",
    [
        (WAV, "audio/wav"),
        (WAV, "audio/x-wav"),
        (WAV, "audio/wave"),
        (MP3, "audio/mpeg"),
        (WEBM, "audio/webm"),
        # Browser recorders add parameters; the type is what counts.
        (WEBM, "audio/webm;codecs=opus"),
        (WEBM, "Audio/WebM; codecs=opus"),
    ],
)
def test_matching_type_and_content_is_accepted(content, media_type):
    assert _status(content, media_type) == 200


@pytest.mark.parametrize(
    "content, media_type",
    [
        (MP3, "audio/wav"),
        (WAV, "audio/mpeg"),
        (WEBM, "audio/wav"),
    ],
)
def test_content_that_contradicts_the_declared_type_is_refused(content, media_type):
    assert _status(content, media_type) == 422


@pytest.mark.parametrize("content", [AVI, WEBP, MATROSKA, b"not audio at all"])
def test_non_audio_is_refused_whatever_it_claims(content):
    assert _status(content, "audio/wav") == 422
    assert _status(content, "audio/webm") == 422


@pytest.mark.parametrize("media_type", ["", "video/webm", "application/octet-stream"])
def test_an_unlisted_type_is_refused_before_the_content_is_read(media_type):
    assert _status(WAV, media_type) == 422


# --- bounded decoding ---------------------------------------------------------


def _wav_file(path: Path, seconds: float, rate: int = 16000) -> str:
    t = np.arange(int(seconds * rate)) / rate
    samples = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return str(path)


def test_a_header_that_understates_the_length_cannot_force_a_full_decode(tmp_path):
    """The container says 0.5 s; the audio is 5 s. The cap is enforced on what
    is actually decoded, and the decode itself stops just past the limit."""
    path = _wav_file(tmp_path / "long.wav", 5.0)
    with patch("backend.core.config.settings.MAX_AUDIO_DURATION_SECONDS", 2.0), patch(
        "backend.services.audio_processing.librosa.get_duration", return_value=0.5
    ):
        with patch(
            "backend.services.audio_processing.librosa.load",
            wraps=__import__("librosa").load,
        ) as load:
            with pytest.raises(HTTPException) as exc:
                audio_processing.preprocess_audio(path)
    assert exc.value.status_code == 422 and "too long" in exc.value.detail
    assert load.call_args.kwargs["duration"] == pytest.approx(3.0)


def test_audio_within_the_limit_still_decodes(tmp_path):
    path = _wav_file(tmp_path / "ok.wav", 3.0)
    assert len(audio_processing.preprocess_audio(path)) > 16000


# --- checkpoints are never unpickled ------------------------------------------


def _torch_load_calls():
    """Every `torch.load(...)` call in the backend's own source."""
    for path in BACKEND.rglob("*.py"):
        if any(part in (".venv", "tests", "__pycache__") for part in path.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "load"
                and getattr(node.func.value, "id", "") == "torch"
            ):
                yield path.relative_to(BACKEND), node


def test_the_guard_finds_the_known_torch_load_calls():
    files = {str(path) for path, _ in _torch_load_calls()}
    assert {
        "services/tts_pipeline.py",
        "services/sv2tts/synthesizer/models/tacotron.py",
        "services/sv2tts/vocoder/models/fatchord_version.py",
    } <= files


def test_every_torch_load_refuses_arbitrary_pickles():
    unsafe = [
        f"{path}:{node.lineno}"
        for path, node in _torch_load_calls()
        if not any(
            kw.arg == "weights_only"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
    ]
    assert unsafe == []
