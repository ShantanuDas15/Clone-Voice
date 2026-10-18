"""The Chatterbox engine client, the reference-audio loader and their wiring (S4.3).

The worker application runs for real in a thread on a loopback port (its model faked), so the
engine's HTTP client is tested against the actual protocol, authentication and error replies.
"""

import asyncio
import io
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
import pytest
import soundfile as sf
import uvicorn
from fastapi.testclient import TestClient

from backend.core.config import Settings, settings
from backend.services import audio_processing, tts_engine, tts_pipeline
from backend.services.chatterbox_engine import (
    MAX_CHARS,
    REFERENCE_REJECTED_DETAIL,
    SAMPLE_RATE,
    VARIANTS,
    ChatterboxEngine,
)
from backend.services.tts_engine import (
    EngineRejectedReferenceError,
    EngineUnavailableError,
    SynthesisStyle,
    UnsupportedStyleError,
    VoiceConditioning,
    WrongEngineError,
    get_engine,
)
from tts_worker.app import create_app

SR = 16000
TOKEN = "k" * 40
EMB = np.ones(256, np.float32) / 16.0


def _tone(seconds, freq=180.0, rate=SR, amp=0.3):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _wav(y, rate=SR) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, y, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class _Model:
    model = "nano"
    device = "cpu"
    sample_rate = 24000

    def __init__(self):
        self.calls = []
        self.error = None
        self.output = _tone(1.8, rate=24000)

    def synthesize(self, text, reference_wav, truncation_retries):
        self.calls.append((text, len(reference_wav), truncation_retries))
        if self.error:
            raise self.error
        return self.output, 24000


class _Server:
    def __init__(self, model, token=TOKEN):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(create_app(model, token), log_level="error", ws="none")
        )
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(5)


@pytest.fixture
def model():
    return _Model()


@pytest.fixture
def worker(model, monkeypatch):
    server = _Server(model)
    monkeypatch.setattr(settings, "TTS_ENGINE", "chatterbox_nano")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    yield server
    server.stop()


@pytest.fixture
def engine():
    return ChatterboxEngine("chatterbox_nano")


async def _direct(stage, fn, *args):
    return fn(*args)


def _conditioning(engine, seconds=3.0):
    return VoiceConditioning(engine.name, engine.version, EMB, _wav(_tone(seconds)))


def _synth(engine, text="Hello there.", conditioning=None, retries=0, style=None):
    return asyncio.run(
        engine.synthesize(
            text,
            conditioning or _conditioning(engine),
            style,
            run_stage=_direct,
            truncation_retries=retries,
        )
    )


# --- identity ---------------------------------------------------------------


def test_the_three_variants_map_to_worker_models():
    assert VARIANTS == {
        "chatterbox": "original",
        "chatterbox_turbo": "turbo",
        "chatterbox_nano": "nano",
    }
    assert ChatterboxEngine("chatterbox_turbo").model == "turbo"
    with pytest.raises(ValueError):
        ChatterboxEngine("chatterbox_huge")


def test_capabilities_are_24khz_english_neutral(engine):
    caps = engine.capabilities()
    assert (caps.name, caps.sample_rate, caps.max_chars, caps.emotions) == (
        "chatterbox_nano",
        SAMPLE_RATE,
        MAX_CHARS,
        ("neutral",),
    )
    assert engine.needs_reference_audio is True


def test_every_selectable_variant_builds_through_the_registry(monkeypatch):
    for name in VARIANTS:
        monkeypatch.setattr(settings, "TTS_ENGINE", name)
        assert isinstance(get_engine(), ChatterboxEngine) and get_engine().name == name


# --- settings validation ----------------------------------------------------


def _worker_settings(**over):
    base = dict(
        TTS_ENGINE="chatterbox_nano",
        TTS_WORKER_URL="https://worker.example.com",
        TTS_WORKER_TOKEN="x" * 32,
    )
    return Settings(**{**base, **over})


def test_sv2tts_needs_no_worker_settings():
    assert Settings(TTS_ENGINE="sv2tts").TTS_WORKER_URL == ""


def test_a_valid_worker_configuration_is_accepted():
    assert _worker_settings().TTS_WORKER_URL.startswith("https://")
    assert _worker_settings(TTS_WORKER_URL="http://localhost:8100").TTS_WORKER_URL
    assert _worker_settings(TTS_WORKER_URL="http://127.0.0.1:8100").TTS_WORKER_URL


@pytest.mark.parametrize(
    "over",
    [
        {"TTS_WORKER_URL": ""},
        {"TTS_WORKER_URL": "not a url"},
        {"TTS_WORKER_URL": "ftp://worker.example.com"},
        {"TTS_WORKER_URL": "http://worker.example.com"},
        {"TTS_WORKER_TOKEN": ""},
        {"TTS_WORKER_TOKEN": "short"},
        {"TTS_WORKER_TIMEOUT_SECONDS": 30.0},
        {"TTS_WORKER_TIMEOUT_SECONDS": 60.0},
    ],
)
def test_an_unsafe_or_incomplete_worker_configuration_fails_at_startup(over):
    with pytest.raises(Exception):
        _worker_settings(**over)


# --- the reference-audio loader --------------------------------------------


def test_the_reference_is_trimmed_capped_and_16khz_pcm16(tmp_path):
    y = np.concatenate([np.zeros(SR), _tone(30.0), np.zeros(SR)])
    path = tmp_path / "s.wav"
    sf.write(str(path), y, SR)
    data, rate = sf.read(
        io.BytesIO(audio_processing.load_reference_audio(str(path))), dtype="float32"
    )
    assert rate == SR and data.ndim == 1
    assert len(data) / SR == pytest.approx(
        audio_processing.REFERENCE_MAX_SECONDS, abs=0.01
    )
    assert (
        sf.info(io.BytesIO(audio_processing.load_reference_audio(str(path)))).subtype
        == "PCM_16"
    )


def test_silence_around_the_speech_is_trimmed(tmp_path):
    y = np.concatenate([np.zeros(5 * SR), _tone(3.0), np.zeros(5 * SR)])
    path = tmp_path / "s.wav"
    sf.write(str(path), y, SR)
    data, _ = sf.read(io.BytesIO(audio_processing.load_reference_audio(str(path))))
    assert (
        3.0 <= len(data) / SR <= 3.4
    )  # the 13 s file keeps its 3 s of speech, within a frame or two


def test_a_short_reference_is_kept_whole(tmp_path):
    path = tmp_path / "s.wav"
    sf.write(str(path), _tone(4.0), SR)
    data, _ = sf.read(io.BytesIO(audio_processing.load_reference_audio(str(path))))
    assert len(data) / SR == pytest.approx(4.0, abs=0.05)


@pytest.mark.parametrize("y", [np.zeros(SR * 5, np.float32), _tone(0.4)])
def test_a_reference_with_almost_no_speech_is_an_error(tmp_path, y):
    path = tmp_path / "s.wav"
    sf.write(str(path), y, SR)
    with pytest.raises(ValueError):
        audio_processing.load_reference_audio(str(path))


# --- conditioning -----------------------------------------------------------


def test_conditioning_from_a_profile_reads_the_stored_sample(engine, tmp_path):
    path = tmp_path / "s.wav"
    sf.write(str(path), _tone(5.0), SR)
    c = engine.conditioning_from_profile(EMB, str(path))
    assert (c.engine, c.version) == ("chatterbox_nano", "1")
    assert c.reference_audio[:4] == b"RIFF" and np.array_equal(c.embedding, EMB)


def test_a_profile_without_a_stored_sample_is_refused(engine):
    with pytest.raises(WrongEngineError):
        engine.conditioning_from_profile(EMB, None)


def test_prepare_voice_keeps_the_sv2tts_embedding(engine):
    async def fake(audio):
        return EMB

    with patch.object(tts_pipeline, "embed_speaker_async", fake):
        c = asyncio.run(engine.prepare_voice(np.zeros(16000, np.float32)))
    assert c.engine == "chatterbox_nano" and np.array_equal(c.embedding, EMB)


# --- the client against a real worker --------------------------------------


def test_synthesis_round_trip_over_real_http(worker, model, engine):
    result = _synth(engine, "Hello there.", retries=1)
    assert result.sample_rate == 24000 and result.truncated_decodes == 0
    assert result.waveform.dtype == np.float32 and len(result.waveform) == int(
        1.8 * 24000
    )
    assert model.calls[0][0] == "Hello there." and model.calls[0][2] == 1
    assert model.calls[0][1] > 1000  # the reference travelled


def test_a_wrong_token_is_unavailable_not_a_crash(worker, engine, monkeypatch):
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", "z" * 40)
    with pytest.raises(EngineUnavailableError):
        _synth(engine)


def test_a_worker_serving_another_model_is_a_rejection(worker, model, monkeypatch):
    with pytest.raises(RuntimeError, match="rejected"):
        _synth(ChatterboxEngine("chatterbox_turbo"))
    assert model.calls == []


def test_a_model_crash_in_the_worker_is_unavailable(worker, model, engine):
    model.error = RuntimeError("boom")
    with pytest.raises(EngineUnavailableError):
        _synth(engine)


def test_a_reference_the_model_cannot_use_asks_for_a_fallback(worker, model, engine):
    """R0.5: a real worker's 422 for an unusable reference is a fallback reason, not a failure."""
    model.error = ValueError(REFERENCE_REJECTED_DETAIL)
    with pytest.raises(EngineRejectedReferenceError) as error:
        _synth(engine)
    assert isinstance(error.value, EngineUnavailableError)
    assert error.value.reason == "reference"


def test_any_other_bad_request_is_still_a_plain_rejection(worker, model, engine):
    model.error = ValueError("some other complaint")
    with pytest.raises(RuntimeError, match="rejected") as error:
        _synth(engine)
    assert not isinstance(error.value, EngineUnavailableError)


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(422),  # no body
        httpx.Response(422, content=b"not json"),
        httpx.Response(422, json={"detail": 7}),
        httpx.Response(422, json={"detail": ["a", "list"]}),
        httpx.Response(422, json={"detail": "reference must be a WAV file"}),
        httpx.Response(409, json={"detail": REFERENCE_REJECTED_DETAIL}),
    ],
)
def test_only_the_workers_exact_reference_message_triggers_a_fallback(
    engine, monkeypatch, reply
):
    """Anything else (other 422s, other statuses, odd bodies) stays a plain rejection."""
    _mock(lambda request: reply, engine, monkeypatch)
    with pytest.raises(RuntimeError, match="rejected") as error:
        _synth(engine)
    assert not isinstance(error.value, EngineUnavailableError)


def test_the_mock_transport_reference_reply_is_recognised(engine, monkeypatch):
    reply = httpx.Response(422, json={"detail": REFERENCE_REJECTED_DETAIL})
    _mock(lambda request: reply, engine, monkeypatch)
    with pytest.raises(EngineRejectedReferenceError):
        _synth(engine)


def test_a_worker_that_is_down_is_unavailable(engine, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(settings, "TTS_WORKER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    with pytest.raises(EngineUnavailableError):
        _synth(engine)


def test_health_reports_the_worker_and_its_model(worker, engine):
    health = engine.health()
    assert health["ready"] is True
    assert health["worker"] == {
        "reachable": True,
        "model": "nano",
        "device": "cpu",
        "circuit": "closed",
    }
    assert (
        ChatterboxEngine("chatterbox_turbo").health()["ready"] is False
    )  # serves nano


def test_health_never_raises_when_the_worker_is_down(engine, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(settings, "TTS_WORKER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    assert engine.health() == {
        "ready": False,
        "worker": {"reachable": False, "circuit": "closed"},
    }


# --- the client's handling of replies (mock transport) ---------------------


def _mock(handler, engine, monkeypatch):
    monkeypatch.setattr(settings, "TTS_WORKER_URL", "http://worker.invalid")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    engine.transport = httpx.MockTransport(handler)


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, EngineUnavailableError),
        (403, EngineUnavailableError),
        (500, EngineUnavailableError),
        (503, EngineUnavailableError),
        (409, RuntimeError),
        (422, RuntimeError),
    ],
)
def test_status_codes_map_to_the_right_error(engine, monkeypatch, status, expected):
    _mock(lambda request: httpx.Response(status), engine, monkeypatch)
    with pytest.raises(expected) as error:
        _synth(engine)
    assert (expected is EngineUnavailableError) == isinstance(
        error.value, EngineUnavailableError
    )


def test_a_timeout_is_unavailable(engine, monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    _mock(handler, engine, monkeypatch)
    with pytest.raises(EngineUnavailableError, match="timed out"):
        _synth(engine)


def test_unreadable_audio_from_the_worker_is_unavailable(engine, monkeypatch):
    _mock(
        lambda request: httpx.Response(200, content=b"not a wav"), engine, monkeypatch
    )
    with pytest.raises(EngineUnavailableError):
        _synth(engine)


def test_the_token_and_the_form_are_sent(engine, monkeypatch):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(
            200,
            content=_wav(_tone(1.0, rate=24000), 24000),
            headers={"X-Truncated-Decodes": "1"},
        )

    _mock(handler, engine, monkeypatch)
    result = _synth(engine, "Say this.", retries=2)
    assert seen["auth"] == f"Bearer {TOKEN}" and seen["path"] == "/v1/synthesize"
    assert b'name="text"' in seen["body"] and b"Say this." in seen["body"]
    assert b'name="model"' in seen["body"] and b"nano" in seen["body"]
    assert result.truncated_decodes == 1


def test_a_stereo_reply_is_mixed_to_mono(engine, monkeypatch):
    stereo = np.stack([_tone(0.5, rate=24000), _tone(0.5, rate=24000)], axis=1)
    buf = io.BytesIO()
    sf.write(buf, stereo, 24000, format="WAV", subtype="FLOAT")
    _mock(
        lambda request: httpx.Response(200, content=buf.getvalue()), engine, monkeypatch
    )
    assert _synth(engine).waveform.ndim == 1


# --- request checks ---------------------------------------------------------


def test_synthesis_needs_reference_audio_and_a_neutral_style(engine):
    with pytest.raises(WrongEngineError):
        _synth(engine, conditioning=VoiceConditioning(engine.name, engine.version, EMB))
    with pytest.raises(UnsupportedStyleError):
        _synth(engine, style=SynthesisStyle("angry", 1.0))
    with pytest.raises(WrongEngineError):
        _synth(engine, conditioning=VoiceConditioning("sv2tts", "1", EMB, b"x"))


# --- the pipeline and the API ----------------------------------------------


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "ref.wav"
    sf.write(str(path), _tone(6.0), SR)
    return str(path)


def test_the_pipeline_uses_the_worker_and_saves_at_its_sample_rate(
    worker, model, sample, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    path, duration = asyncio.run(
        tts_pipeline.run_inference_pipeline(
            "Hello there my friend today.",
            EMB,
            "chatterbox-user",
            reference_audio_path=sample,
        )
    )
    assert duration == pytest.approx(1.8, abs=0.01)
    assert sf.info(path).samplerate == 24000  # not the 16 kHz vocoder rate
    assert model.calls[0][1] > 1000


def test_the_gate_still_judges_worker_audio(worker, model, sample, monkeypatch):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    model.output = np.zeros(24000 * 2, np.float32)  # silence
    with pytest.raises(tts_pipeline.OutputQualityError):
        asyncio.run(
            tts_pipeline.run_inference_pipeline(
                "Hello there my friend today.", EMB, "u", reference_audio_path=sample
            )
        )
    assert len(model.calls) == settings.TTS_QUALITY_MAX_ATTEMPTS


def test_the_pipeline_without_a_stored_sample_is_refused_for_a_reference_engine(worker):
    with pytest.raises(WrongEngineError):
        asyncio.run(tts_pipeline.run_inference_pipeline("Hi there.", EMB, "u"))


def test_sv2tts_calls_are_unchanged_by_the_new_argument(monkeypatch):
    monkeypatch.setattr(settings, "TTS_ENGINE", "sv2tts")
    tts_pipeline.load_mock_models("cpu")
    path, _ = asyncio.run(
        tts_pipeline.run_inference_pipeline("Hello.", EMB, "sv2-user")
    )
    assert sf.info(path).samplerate == settings.VOCODER_SAMPLE_RATE


@pytest.fixture
def auth_headers(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "cb@example.com", "password": "Password123!", "name": "C"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "cb@example.com", "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _profile(client, headers) -> str:
    return client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "C", "consent_confirmed": "true"},
        files={"file": ("a.wav", _wav(_tone(4.0, amp=0.5)), "audio/wav")},
    ).json()["id"]


def test_the_api_passes_the_stored_sample_only_to_a_reference_engine(
    client, auth_headers, monkeypatch
):
    profile = _profile(client, auth_headers)
    captured = {}

    async def fake(*args, **kwargs):
        captured["args"], captured["kwargs"] = args, kwargs
        raise RuntimeError("stop")

    for engine_name, expect in (("sv2tts", False), ("chatterbox_nano", True)):
        monkeypatch.setattr(settings, "TTS_ENGINE", engine_name)
        captured.clear()
        with patch("backend.api.synthesize.run_inference_pipeline", fake):
            client.post(
                "/api/v1/synthesize",
                headers=auth_headers,
                json={"voice_profile_id": profile, "text": "Hi there."},
            )
        assert ("reference_audio_path" in captured["kwargs"]) is expect
        assert len(captured["args"]) == 3


def test_an_unreachable_worker_is_a_503_with_a_failed_audit_row_when_the_fallback_is_off(
    client, auth_headers, db_session, monkeypatch
):
    from backend.models.generation import Generation

    profile = _profile(client, auth_headers)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(settings, "TTS_ENGINE", "chatterbox_nano")
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "none")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers,
        json={"voice_profile_id": profile, "text": "Worker down"},
    )
    assert res.status_code == 503 and "unavailable" in res.json()["detail"]
    rows = (
        db_session.query(Generation)
        .filter(Generation.input_text == "Worker down")
        .all()
    )
    assert [r.status for r in rows] == ["failed"]


def test_end_to_end_through_the_api_with_a_real_worker(
    client, auth_headers, worker, model
):
    profile = _profile(client, auth_headers)
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers,
        json={"voice_profile_id": profile, "text": "Hello there my friend today."},
    )
    assert res.status_code == 200 and res.headers["content-type"] == "audio/wav"
    assert sf.info(io.BytesIO(res.content)).samplerate == 24000
    assert model.calls and model.calls[0][1] > 1000


# --- readiness --------------------------------------------------------------


def test_readiness_names_the_worker_without_failing_when_it_is_down(
    client, monkeypatch
):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(settings, "TTS_ENGINE", "chatterbox_nano")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    body = client.get("/health/ready").json()
    assert body["engine"]["name"] == "chatterbox_nano"
    assert body["engine"]["worker"] == {"reachable": False, "circuit": "closed"}
    assert (
        client.get("/health/ready").status_code == 200
    )  # a down worker does not take the app out


def test_readiness_shows_a_live_worker(client, worker):
    assert client.get("/health/ready").json()["engine"]["worker"]["model"] == "nano"


# --- the exaggeration control (S5.2b) ----------------------------------------


class _Controlled(_Model):
    """A worker model that accepts and records the optional control."""

    def synthesize(self, text, reference_wav, truncation_retries, exaggeration=None):
        self.exaggeration = exaggeration
        return super().synthesize(text, reference_wav, truncation_retries)


def test_the_original_engine_sends_the_style_exaggeration(monkeypatch):
    model = _Controlled()
    model.model = "original"
    server = _Server(model)
    try:
        monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
        monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
        engine = ChatterboxEngine("chatterbox")
        _synth(engine, style=SynthesisStyle(exaggeration=0.8))
        assert model.exaggeration == 0.8
        _synth(engine, style=SynthesisStyle())
        assert model.exaggeration is None
        _synth(engine, style=None)
        assert model.exaggeration is None
    finally:
        server.stop()


def test_turbo_and_nano_engines_do_not_send_it(monkeypatch):
    model = _Controlled()
    server = _Server(model)
    try:
        monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
        monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
        engine = ChatterboxEngine("chatterbox_nano")
        _synth(engine, style=SynthesisStyle(exaggeration=0.8))
        assert model.exaggeration is None
    finally:
        server.stop()


def test_an_invalid_value_is_a_rejection_not_an_outage(monkeypatch):
    model = _Controlled()
    model.model = "original"
    server = _Server(model)
    try:
        monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
        monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
        engine = ChatterboxEngine("chatterbox")
        with pytest.raises(RuntimeError, match="rejected"):
            _synth(engine, style=SynthesisStyle(exaggeration=5.0))
        assert engine.breaker.state == "closed"
    finally:
        server.stop()
