"""The inference worker application and its model adapter (SPEECH_QUALITY_PLAN.md S4.3)."""

import asyncio
import io
import logging
import os
import sys
import threading
import types
from unittest.mock import patch

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.services import chatterbox_engine
from tts_worker import app as worker_app
from tts_worker.app import create_app

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeSynthesizer:
    """A model stand-in that returns a tone and records what it was given."""

    model = "nano"
    device = "cpu"
    sample_rate = 24000

    def __init__(self):
        self.calls = []
        self.result = None
        self.error = None

    def synthesize(self, text, reference_wav, truncation_retries):
        self.calls.append((text, reference_wav, truncation_retries))
        if self.error:
            raise self.error
        if self.result is not None:
            return self.result
        t = np.arange(int(self.sample_rate * 0.5)) / self.sample_rate
        return (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), self.sample_rate


def _wav_bytes(seconds=2.0, rate=16000) -> bytes:
    buf = io.BytesIO()
    sf.write(
        buf,
        np.zeros(int(seconds * rate), np.float32),
        rate,
        format="WAV",
        subtype="PCM_16",
    )
    return buf.getvalue()


@pytest.fixture
def synth():
    return FakeSynthesizer()


@pytest.fixture
def client(synth):
    return TestClient(create_app(synth, TOKEN))


def _post(client, headers=AUTH, text="Hello there.", model="nano", ref=None, **extra):
    return client.post(
        "/v1/synthesize",
        headers=headers,
        data={"text": text, "model": model, **extra},
        files={
            "reference": ("r.wav", _wav_bytes() if ref is None else ref, "audio/wav")
        },
    )


# --- health and auth ---------------------------------------------------------


def test_health_names_the_model_and_needs_no_token(client):
    body = client.get("/health").json()
    assert body == {
        "ready": True,
        "model": "nano",
        "device": "cpu",
        "sample_rate": 24000,
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": TOKEN},
        {"Authorization": "Basic x"},
    ],
)
def test_synthesis_needs_the_exact_token(client, synth, headers):
    assert _post(client, headers=headers).status_code == 401
    assert synth.calls == []


def test_a_refused_request_is_refused_before_its_body_is_parsed(client):
    response = client.post(
        "/v1/synthesize",
        content=b"this is not multipart",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 401


def test_a_short_token_is_refused_at_construction(synth):
    with pytest.raises(ValueError):
        create_app(synth, "short")


def test_the_docs_pages_are_not_served(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# --- input checks -----------------------------------------------------------


def test_a_request_for_another_model_is_a_409(client, synth):
    assert _post(client, model="turbo").status_code == 409
    assert synth.calls == []


@pytest.mark.parametrize("text", ["", "   ", "x" * (worker_app.MAX_TEXT_CHARS + 1)])
def test_blank_or_overlong_text_is_a_422(client, text):
    assert _post(client, text=text).status_code == 422


def test_a_reference_that_is_not_a_wav_is_a_422(client):
    assert _post(client, ref=b"ID3" + b"\x00" * 100).status_code == 422


def test_an_oversized_body_is_a_413_without_calling_the_model(client, synth):
    big = _wav_bytes(seconds=100, rate=16000)  # 3.2 MB of PCM
    assert len(big) > worker_app.MAX_REFERENCE_BYTES
    assert _post(client, ref=big).status_code == 413
    assert synth.calls == []


# --- success and failure ----------------------------------------------------


def test_success_returns_a_float_wav_with_the_protocol_headers(client, synth):
    response = _post(client, truncation_retries="2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers[worker_app.HEADER_SAMPLE_RATE] == "24000"
    assert response.headers[worker_app.HEADER_TRUNCATED] == "0"
    assert response.headers[worker_app.HEADER_MODEL] == "nano"
    wave, rate = sf.read(io.BytesIO(response.content), dtype="float32")
    assert (
        rate == 24000
        and len(wave) == 12000
        and np.max(np.abs(wave)) == pytest.approx(0.3, abs=0.01)
    )
    text, reference, retries = synth.calls[0]
    assert (text, retries) == ("Hello there.", 2) and reference[:4] == b"RIFF"


def test_negative_retries_are_clamped(client, synth):
    _post(client, truncation_retries="-5")
    assert synth.calls[0][2] == 0


def test_the_models_own_complaint_about_input_is_a_422(client, synth):
    synth.error = ValueError("the reference audio could not be used")
    response = _post(client)
    assert response.status_code == 422 and "reference" in response.json()["detail"]


def test_a_model_crash_is_a_generic_500_that_never_logs_the_text(client, synth, caplog):
    synth.error = RuntimeError("cuda exploded on SECRET-SENTENCE")
    with caplog.at_level(logging.DEBUG, logger="tts_worker"):
        response = _post(client, text="SECRET-SENTENCE")
    assert response.status_code == 500 and response.json() == {
        "detail": "synthesis failed"
    }
    assert "SECRET-SENTENCE" not in response.text
    assert "Synthesis failed" in caplog.text


@pytest.mark.parametrize(
    "bad", [np.array([], np.float32), np.array([0.1, np.nan], np.float32)]
)
def test_an_empty_or_nonfinite_waveform_is_a_500(client, synth, bad):
    synth.result = (bad, 24000)
    assert _post(client).status_code == 500


def test_requests_beyond_the_queue_get_a_503_with_retry_after():
    gate, started = threading.Event(), threading.Event()

    class Slow(FakeSynthesizer):
        def synthesize(self, text, reference_wav, truncation_retries):
            started.set()
            gate.wait(5)
            return super().synthesize(text, reference_wav, truncation_retries)

    app = create_app(Slow(), TOKEN, max_waiting=2)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://w") as http:

            def send():
                return http.post(
                    "/v1/synthesize",
                    headers=AUTH,
                    data={"text": "Hi.", "model": "nano"},
                    files={"reference": ("r.wav", _wav_bytes(), "audio/wav")},
                )

            first = asyncio.ensure_future(send())
            await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
            second = asyncio.ensure_future(send())
            await asyncio.sleep(0.2)
            third = await send()  # one running, one waiting: no room
            gate.set()
            return third, await first, await second

    third, first, second = asyncio.run(scenario())
    assert third.status_code == 503 and third.headers["retry-after"] == "1"
    assert first.status_code == second.status_code == 200


# --- the protocol is the same on both sides ---------------------------------


def test_client_and_worker_agree_on_the_protocol():
    for name in (
        "PATH_SYNTHESIZE",
        "PATH_HEALTH",
        "HEADER_SAMPLE_RATE",
        "HEADER_TRUNCATED",
        "HEADER_MODEL",
    ):
        assert getattr(chatterbox_engine, name) == getattr(worker_app, name), name


# --- the Chatterbox adapter (model library faked) ---------------------------


class _FakeTensor:
    def __init__(self, array):
        self.array = array

    def squeeze(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


class _FakeModel:
    sr = 24000
    instances = []

    def __init__(self, nano=False):
        self.nano = nano
        self.prepared = []
        self.fail_prepare = False
        _FakeModel.instances.append(self)

    @classmethod
    def from_pretrained(cls, device, nano=False):
        model = cls(nano)
        model.device = device
        return model

    def prepare_conditionals(self, path):
        if self.fail_prepare:
            raise RuntimeError("bad audio")
        assert os.path.exists(path)
        with open(path, "rb") as f:
            self.prepared.append((path, f.read(4)))

    def generate(self, text):
        return _FakeTensor(np.full(2400, 0.1, np.float32))


@pytest.fixture
def fake_chatterbox(monkeypatch):
    _FakeModel.instances.clear()
    pkg = types.ModuleType("chatterbox")
    tts = types.ModuleType("chatterbox.tts")
    turbo = types.ModuleType("chatterbox.tts_turbo")
    tts.ChatterboxTTS = _FakeModel
    turbo.ChatterboxTurboTTS = _FakeModel
    monkeypatch.setitem(sys.modules, "chatterbox", pkg)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", tts)
    monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", turbo)
    from tts_worker.chatterbox_synth import ChatterboxSynthesizer

    return ChatterboxSynthesizer


@pytest.mark.parametrize(
    "model,nano", [("original", False), ("turbo", False), ("nano", True)]
)
def test_the_adapter_loads_the_right_model(fake_chatterbox, model, nano):
    synth = fake_chatterbox(model, "cpu")
    assert (synth.model, synth.device, synth.sample_rate) == (model, "cpu", 24000)
    if model != "original":
        assert _FakeModel.instances[0].nano is nano


def test_the_adapter_rejects_an_unknown_model(fake_chatterbox):
    with pytest.raises(ValueError):
        fake_chatterbox("huge", "cpu")


def test_the_adapter_returns_float32_and_leaves_no_temp_file(
    fake_chatterbox, tmp_path, monkeypatch
):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    synth = fake_chatterbox("nano", "cpu")
    wave, rate = synth.synthesize("Hi.", _wav_bytes(), 0)
    assert wave.dtype == np.float32 and wave.shape == (2400,) and rate == 24000
    assert _FakeModel.instances[0].prepared[0][1] == b"RIFF"  # the model saw the audio
    assert list(tmp_path.iterdir()) == []


def test_the_adapter_removes_the_temp_file_even_when_the_model_fails(
    fake_chatterbox, tmp_path, monkeypatch
):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    synth = fake_chatterbox("nano", "cpu")
    _FakeModel.instances[0].fail_prepare = True
    with pytest.raises(ValueError):
        synth.synthesize("Hi.", _wav_bytes(), 0)
    assert list(tmp_path.iterdir()) == []


# --- the exaggeration control (S5.2b) ----------------------------------------


class _Recording(FakeSynthesizer):
    """Accepts the optional control and records it."""

    def synthesize(self, text, reference_wav, truncation_retries, exaggeration=None):
        self.exaggeration = exaggeration
        return super().synthesize(text, reference_wav, truncation_retries)


def test_exaggeration_reaches_the_model_only_when_sent():
    synth = _Recording()
    client = TestClient(create_app(synth, TOKEN))
    assert _post(client).status_code == 200 and synth.exaggeration is None
    assert _post(client, exaggeration="0.75").status_code == 200
    assert synth.exaggeration == 0.75


def test_a_model_without_the_parameter_still_works_when_none_is_sent(client, synth):
    assert _post(client).status_code == 200  # FakeSynthesizer takes three arguments


@pytest.mark.parametrize("value", ["-0.1", "2.5", "nan", "inf"])
def test_an_out_of_range_exaggeration_is_a_422_and_never_reaches_the_model(value):
    synth = _Recording()
    client = TestClient(create_app(synth, TOKEN))
    assert _post(client, exaggeration=value).status_code == 422
    assert synth.calls == []


def test_the_bounds_are_accepted():
    synth = _Recording()
    client = TestClient(create_app(synth, TOKEN))
    for value in ("0", "2"):
        assert _post(client, exaggeration=value).status_code == 200


def test_the_original_model_receives_the_value(fake_chatterbox):
    calls = []

    def generate(self, text, **options):
        calls.append(options)
        return _FakeTensor(np.full(2400, 0.1, np.float32))

    synth = fake_chatterbox("original", "cpu")
    with patch.object(_FakeModel, "generate", generate):
        synth.synthesize("Hi.", _wav_bytes(), 0, exaggeration=0.8)
        synth.synthesize("Hi.", _wav_bytes(), 0, exaggeration=None)
    assert calls == [{"exaggeration": 0.8}, {}]


def test_turbo_and_nano_never_receive_it(fake_chatterbox):
    calls = []

    def generate(self, text, **options):
        calls.append(options)
        return _FakeTensor(np.full(2400, 0.1, np.float32))

    for model in ("turbo", "nano"):
        synth = fake_chatterbox(model, "cpu")
        with patch.object(_FakeModel, "generate", generate):
            synth.synthesize("Hi.", _wav_bytes(), 0, exaggeration=0.8)
    assert calls == [{}, {}]


# --- the container definition (static: Docker is not run here) ---------------

WORKER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "tts_worker")


def _read(name: str) -> str:
    with open(os.path.join(WORKER_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def test_the_worker_image_is_not_root_and_carries_no_secret():
    docker = _read("Dockerfile")
    assert "USER worker" in docker and "--uid 10001" in docker
    assert "TTS_WORKER_TOKEN=" not in docker
    assert "ENV TTS_WORKER_TOKEN" not in docker
    assert "EXPOSE 8100" in docker and "HEALTHCHECK" in docker


def test_the_worker_image_installs_from_the_lock_and_copies_only_the_worker():
    docker = _read("Dockerfile")
    assert (
        "requirements.lock.txt" in docker
        and "COPY tts_worker /app/tts_worker" in docker
    )
    assert "COPY backend" not in docker  # the worker never ships the application


def test_the_lock_keeps_the_dependencies_the_application_cannot_have():
    lock = _read("requirements.lock.txt")
    assert "torch==2.6.0" in lock and "transformers==5.2.0" in lock
    assert "chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git@" in lock
    assert "setuptools==" in lock and "setuptools==81" not in lock


def test_the_worker_does_not_share_the_applications_requirements():
    app_reqs = os.path.join(WORKER_DIR, "..", "backend", "requirements.txt")
    with open(app_reqs, encoding="utf-8") as handle:
        text = handle.read()
    assert "chatterbox" not in text and "transformers" not in text


def test_a_rejected_reference_logs_only_the_kind_of_failure(fake_chatterbox, caplog):
    """A 422 with no trace is undiagnosable; the audio, the text and the message must stay out."""
    synth = fake_chatterbox("nano", "cpu")
    _FakeModel.instances[0].fail_prepare = True
    with caplog.at_level("WARNING", logger="tts_worker"):
        with pytest.raises(ValueError):
            synth.synthesize("A private sentence.", _wav_bytes(), 0)

    assert "RuntimeError" in caplog.text
    assert "bad audio" not in caplog.text  # the library's message is not logged
    assert "private sentence" not in caplog.text
