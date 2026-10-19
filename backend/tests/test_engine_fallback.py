"""Fallback to the in-process engine and the worker circuit breaker (SPEECH_QUALITY_PLAN.md S4.4)."""

import asyncio
import io

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.core import metrics
from backend.core.config import Settings, settings
from backend.services import tts_engine, tts_pipeline
from backend.services.chatterbox_engine import ChatterboxEngine, CircuitBreaker
from backend.services.tts_engine import (
    EngineBusyError,
    EngineCapabilities,
    EngineRejectedReferenceError,
    EngineUnavailableError,
    SynthesisResult,
    TTSEngine,
    VoiceConditioning,
    WrongEngineError,
    get_engine,
    get_fallback_engine,
)
from backend.tests.test_chatterbox_engine import (
    EMB,
    SR,
    TOKEN,
    _Model,
    _Server,
    _tone,
    _wav,
)

PRIMARY = "chatterbox_nano"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# --- the circuit breaker ----------------------------------------------------


def test_the_breaker_opens_after_the_threshold_and_not_before():
    breaker = CircuitBreaker(3, 30.0, Clock())
    for _ in range(2):
        breaker.failure()
    assert breaker.state == "closed" and breaker.allow()
    breaker.failure()
    assert breaker.state == "open" and not breaker.allow()


def test_a_success_resets_the_count():
    breaker = CircuitBreaker(3, 30.0, Clock())
    breaker.failure()
    breaker.failure()
    breaker.success()
    breaker.failure()
    breaker.failure()
    assert breaker.state == "closed"


def test_after_the_cooldown_exactly_one_probe_is_allowed():
    clock = Clock()
    breaker = CircuitBreaker(1, 30.0, clock)
    breaker.failure()
    clock.now += 29.0
    assert not breaker.allow()
    clock.now += 2.0
    assert breaker.state == "half_open"
    assert breaker.allow()  # the probe
    assert not breaker.allow()  # everyone else still waits


def test_a_successful_probe_closes_it_and_a_failed_one_reopens_it():
    clock = Clock()
    breaker = CircuitBreaker(1, 30.0, clock)
    breaker.failure()
    clock.now += 31.0
    assert breaker.allow()
    breaker.success()
    assert breaker.state == "closed" and breaker.allow()

    breaker.failure()
    clock.now += 31.0
    assert breaker.allow()
    breaker.failure()
    assert breaker.state == "open"
    clock.now += 29.0
    assert not breaker.allow()  # a fresh cooldown started at the failed probe


# --- the engine's classification of replies ---------------------------------


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(settings, "TTS_WORKER_BREAKER_FAILURES", 3)
    monkeypatch.setattr(settings, "TTS_WORKER_BREAKER_COOLDOWN_SECONDS", 30.0)
    monkeypatch.setattr(settings, "TTS_WORKER_URL", "http://worker.invalid")
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    e = ChatterboxEngine(PRIMARY)
    e.breaker.clock = Clock()
    return e


async def _direct(stage, fn, *args):
    return fn(*args)


def _call(engine):
    return asyncio.run(
        engine.synthesize(
            "Hello there.",
            VoiceConditioning(engine.name, engine.version, EMB, _wav(_tone(3.0))),
            None,
            run_stage=_direct,
        )
    )


def _handler(replies):
    """A mock worker that plays ``replies`` (a list of status codes or responses) and counts calls."""
    calls = []

    def handler(request):
        calls.append(request)
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(reply)

    handler.calls = calls
    return handler


def _ok():
    return httpx.Response(200, content=_wav(_tone(1.0, rate=24000), 24000))


def test_three_outages_in_a_row_open_the_circuit_and_the_fourth_call_never_leaves(
    engine,
):
    handler = _handler([500])
    engine.transport = httpx.MockTransport(handler)
    for _ in range(3):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    assert len(handler.calls) == 3
    with pytest.raises(EngineUnavailableError) as error:
        _call(engine)
    assert error.value.reason == "circuit_open"
    assert len(handler.calls) == 3  # skipped: no network wait during an outage


def test_after_the_cooldown_one_call_probes_and_a_success_closes_the_circuit(engine):
    handler = _handler([500, 500, 500, _ok()])
    engine.transport = httpx.MockTransport(handler)
    for _ in range(3):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    engine.breaker.clock.now += 31.0
    assert _call(engine).sample_rate == 24000
    assert engine.breaker.state == "closed"


def test_busy_replies_are_a_fallback_reason_but_never_open_the_circuit(engine):
    busy = httpx.Response(503, json={"detail": "busy"}, headers={"Retry-After": "1"})
    handler = _handler([busy])
    engine.transport = httpx.MockTransport(handler)
    for _ in range(10):
        with pytest.raises(EngineBusyError) as error:
            _call(engine)
        assert error.value.reason == "busy"
    assert engine.breaker.state == "closed" and len(handler.calls) == 10


def test_a_plain_503_is_an_outage_not_busy(engine):
    engine.transport = httpx.MockTransport(_handler([503]))
    with pytest.raises(EngineUnavailableError) as error:
        _call(engine)
    assert not isinstance(error.value, EngineBusyError)
    assert error.value.reason == "unavailable"


@pytest.mark.parametrize("status", [409, 422])
def test_a_rejected_request_is_the_requests_fault_not_the_workers(engine, status):
    engine.transport = httpx.MockTransport(_handler([status]))
    for _ in range(5):
        with pytest.raises(RuntimeError, match="rejected"):
            _call(engine)
    assert engine.breaker.state == "closed"


def test_a_refused_token_counts_as_an_outage(engine):
    engine.transport = httpx.MockTransport(_handler([401]))
    for _ in range(3):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    assert engine.breaker.state == "open"


def test_a_timeout_and_an_unreachable_host_count_as_outages(engine):
    def boom(request):
        raise httpx.ConnectTimeout("no route", request=request)

    engine.transport = httpx.MockTransport(boom)
    for _ in range(3):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    assert engine.breaker.state == "open"


def test_health_reports_the_circuit_state(engine):
    engine.transport = httpx.MockTransport(_handler([500]))
    for _ in range(3):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    assert engine.health()["worker"]["circuit"] == "open"


# --- choosing the fallback --------------------------------------------------


def test_the_fallback_is_sv2tts_for_a_worker_engine(monkeypatch):
    primary = ChatterboxEngine(PRIMARY)
    assert get_fallback_engine(primary).name == "sv2tts"


def test_no_fallback_when_it_is_switched_off_or_the_primary_is_the_fallback(
    monkeypatch,
):
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "none")
    assert get_fallback_engine(ChatterboxEngine(PRIMARY)) is None
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "sv2tts")
    monkeypatch.setattr(settings, "TTS_ENGINE", "sv2tts")
    assert get_fallback_engine(get_engine()) is None


def test_fallback_and_breaker_settings_have_safe_bounds():
    s = Settings()
    assert (s.TTS_FALLBACK_ENGINE, s.TTS_WORKER_BREAKER_FAILURES) == ("sv2tts", 3)
    assert s.TTS_WORKER_BREAKER_COOLDOWN_SECONDS == 30.0
    for bad in (
        {"TTS_FALLBACK_ENGINE": "chatterbox"},
        {"TTS_WORKER_BREAKER_FAILURES": 0},
        {"TTS_WORKER_BREAKER_FAILURES": 21},
        {"TTS_WORKER_BREAKER_COOLDOWN_SECONDS": 0.5},
    ):
        with pytest.raises(Exception):
            Settings(**bad)


# --- the pipeline -----------------------------------------------------------


class _FlakyEngine(TTSEngine):
    """A worker-style engine whose backend fails in a way the test chooses."""

    name = PRIMARY
    version = "1"
    needs_reference_audio = False  # keeps these tests free of stored samples

    def __init__(self, error=None, wave=None):
        self.error = error
        self.wave = wave
        self.calls = 0

    def capabilities(self):
        return EngineCapabilities(self.name, "1", 24000, 500, ("neutral",))

    def health(self, expected_device=None):
        return {"ready": True}

    def conditioning_from_array(self, embedding):
        return VoiceConditioning(self.name, self.version, embedding)

    async def prepare_voice(self, audio):
        return self.conditioning_from_array(EMB)

    async def synthesize(
        self, text, conditioning, style, *, run_stage, truncation_retries=0
    ):
        self.calls += 1
        if self.error:
            raise self.error
        return SynthesisResult(self.wave, 24000)


@pytest.fixture
def mock_sv2tts():
    tts_pipeline.load_mock_models("cpu")


def _run(text="Hello there my friend today."):
    return asyncio.run(tts_pipeline.run_inference_pipeline(text, EMB, "fallback-user"))


def _count(reason):
    return metrics.ENGINE_FALLBACKS.labels(PRIMARY, "sv2tts", reason)._value.get()


def _install(monkeypatch, engine):
    monkeypatch.setattr(tts_engine, "get_engine", lambda: engine)


@pytest.mark.parametrize(
    "error,reason",
    [
        (EngineUnavailableError("down"), "unavailable"),
        (EngineBusyError("busy"), "busy"),
        (EngineUnavailableError("skipped", reason="circuit_open"), "circuit_open"),
        (EngineRejectedReferenceError("too short"), "reference"),
    ],
)
def test_an_unavailable_primary_is_served_by_sv2tts_and_counted(
    monkeypatch, mock_sv2tts, error, reason
):
    primary = _FlakyEngine(error)
    _install(monkeypatch, primary)
    before = _count(reason)
    path, duration = _run()
    assert (
        sf.info(path).samplerate == settings.VOCODER_SAMPLE_RATE
    )  # SV2TTS's rate, not 24 kHz
    assert primary.calls == 1 and duration > 0
    assert _count(reason) == before + 1


def test_with_the_fallback_off_the_outage_reaches_the_caller(monkeypatch, mock_sv2tts):
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "none")
    _install(monkeypatch, _FlakyEngine(EngineUnavailableError("down")))
    with pytest.raises(EngineUnavailableError):
        _run()


def test_a_healthy_primary_is_never_replaced(monkeypatch, mock_sv2tts):
    primary = _FlakyEngine(wave=_tone(1.8, rate=24000))
    _install(monkeypatch, primary)
    before = _count("unavailable")
    path, _ = _run()
    assert sf.info(path).samplerate == 24000 and _count("unavailable") == before


def test_a_quality_refusal_is_not_an_outage_and_does_not_fall_back(
    monkeypatch, mock_sv2tts
):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    primary = _FlakyEngine(wave=np.zeros(24000 * 2, np.float32))
    _install(monkeypatch, primary)
    before = _count("unavailable")
    with pytest.raises(tts_pipeline.OutputQualityError):
        _run()
    assert (
        primary.calls == settings.TTS_QUALITY_MAX_ATTEMPTS
        and _count("unavailable") == before
    )


def test_a_bad_request_is_not_an_outage_and_does_not_fall_back(
    monkeypatch, mock_sv2tts
):
    _install(monkeypatch, _FlakyEngine(WrongEngineError("no reference")))
    with pytest.raises(WrongEngineError):
        _run()


def test_the_gate_judges_the_fallbacks_audio_too(monkeypatch, mock_sv2tts):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    _install(monkeypatch, _FlakyEngine(EngineUnavailableError("down")))
    with pytest.raises(
        tts_pipeline.OutputQualityError
    ):  # the mock vocoder returns silence
        _run()


# --- the whole path: a real worker that goes away ---------------------------


def _real_worker(monkeypatch):
    model = _Model()
    server = _Server(model)
    monkeypatch.setattr(settings, "TTS_ENGINE", PRIMARY)
    monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    return model, server


def test_the_worker_going_away_moves_requests_to_the_fallback_then_skips_it(
    monkeypatch, mock_sv2tts, tmp_path
):
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), _tone(6.0), SR)
    model, server = _real_worker(monkeypatch)
    run = lambda: asyncio.run(  # noqa: E731
        tts_pipeline.run_inference_pipeline(
            "Hello.", EMB, "u", reference_audio_path=str(ref)
        )
    )
    path, _ = run()
    assert sf.info(path).samplerate == 24000  # served by the worker
    server.stop()
    served = [sf.info(run()[0]).samplerate for _ in range(5)]
    assert served == [settings.VOCODER_SAMPLE_RATE] * 5  # every one still answered
    engine = get_engine()
    assert (
        engine.breaker.state == "open"
    )  # three real failures, then the last two skipped the network


def test_the_api_serves_a_user_while_the_worker_is_down(
    client: TestClient, db_session, monkeypatch, tmp_path
):
    from backend.models.generation import Generation

    client.post(
        "/api/v1/auth/signup",
        json={"email": "fb@example.com", "password": "Password123!", "name": "F"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "fb@example.com", "password": "Password123!"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "F", "consent_confirmed": "true"},
        files={"file": ("a.wav", _wav(_tone(4.0, amp=0.5)), "audio/wav")},
    ).json()["id"]
    monkeypatch.setattr(settings, "TTS_ENGINE", PRIMARY)
    monkeypatch.setattr(
        settings, "TTS_WORKER_URL", "http://127.0.0.1:9"
    )  # nothing listens
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    response = client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"voice_profile_id": profile, "text": "Served anyway"},
    )
    assert response.status_code == 200
    assert (
        sf.info(io.BytesIO(response.content)).samplerate == settings.VOCODER_SAMPLE_RATE
    )
    rows = (
        db_session.query(Generation)
        .filter(Generation.input_text == "Served anyway")
        .all()
    )
    assert [r.status for r in rows] == ["completed"]


# --- S7.3a: per-engine RTF and outcomes ----------------------------------------


def _sample(name, **labels):
    return metrics.registry.get_sample_value(name, labels) or 0.0


def test_the_rtf_is_synthesis_seconds_over_audio_seconds(monkeypatch, mock_sv2tts):
    clock = {"now": 100.0}

    class Slow(_FlakyEngine):
        async def synthesize(self, *args, **kwargs):
            clock["now"] += 3.0  # three seconds of work ...
            return await super().synthesize(*args, **kwargs)

    monkeypatch.setattr(tts_pipeline.time, "perf_counter", lambda: clock["now"])
    _install(monkeypatch, Slow(wave=_tone(2.0, rate=24000)))  # ... for two of audio
    before = _sample("clonevoice_engine_rtf_sum", engine=PRIMARY)
    _run()
    assert _sample("clonevoice_engine_rtf_sum", engine=PRIMARY) - before == (
        pytest.approx(1.5)
    )


def test_an_unavailable_engine_is_counted_for_that_engine_and_the_fallback_ok(
    monkeypatch, mock_sv2tts
):
    _install(monkeypatch, _FlakyEngine(EngineUnavailableError("down")))
    down = _sample(
        "clonevoice_engine_synthesis_total", engine=PRIMARY, outcome="unavailable"
    )
    ok = _sample("clonevoice_engine_synthesis_total", engine="sv2tts", outcome="ok")
    _run()
    assert (
        _sample(
            "clonevoice_engine_synthesis_total", engine=PRIMARY, outcome="unavailable"
        )
        == down + 1
    )
    assert (
        _sample("clonevoice_engine_synthesis_total", engine="sv2tts", outcome="ok")
        == ok + 1
    )


def test_a_refused_attempt_is_counted_as_retried_then_refused(monkeypatch, mock_sv2tts):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "TTS_QUALITY_MAX_ATTEMPTS", 2)
    _install(monkeypatch, _FlakyEngine(wave=np.zeros(24000 * 2, np.float32)))
    count = lambda o: _sample(
        "clonevoice_engine_synthesis_total", engine=PRIMARY, outcome=o
    )
    retried, refused = count("gate_retried"), count("gate_refused")
    with pytest.raises(Exception):
        _run()
    assert count("gate_retried") == retried + 1
    assert count("gate_refused") == refused + 1


# --- R0.5: a voice the engine cannot use falls back, and is not an outage ---------


REFERENCE_REPLY = httpx.Response(
    422, json={"detail": "the reference audio could not be used"}
)


def test_a_rejected_reference_never_opens_the_circuit(engine):
    handler = _handler([REFERENCE_REPLY])
    engine.transport = httpx.MockTransport(handler)
    for _ in range(10):
        with pytest.raises(EngineRejectedReferenceError) as error:
            _call(engine)
        assert error.value.reason == "reference"
    assert engine.breaker.state == "closed" and len(handler.calls) == 10


def test_a_rejected_reference_resets_the_failure_count(engine):
    """The worker answered, so earlier outages must not add up with later rejections."""
    engine.transport = httpx.MockTransport(
        _handler([503, 503, REFERENCE_REPLY, 503, 503, 503])
    )
    for _ in range(2):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    with pytest.raises(EngineRejectedReferenceError):
        _call(engine)
    for _ in range(2):
        with pytest.raises(EngineUnavailableError):
            _call(engine)
    assert engine.breaker.state == "closed"  # 2 + 2 outages, never 3 in a row


def test_a_voice_the_worker_cannot_use_is_served_by_sv2tts_and_counted_apart(
    monkeypatch, mock_sv2tts, tmp_path
):
    """End to end over HTTP: a real worker app answers 422, the engine maps it, SV2TTS serves."""
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), _tone(3.0), SR)
    model, server = _real_worker(monkeypatch)
    model.error = ValueError("the reference audio could not be used")
    unavailable = _sample(
        "clonevoice_engine_synthesis_total", engine=PRIMARY, outcome="unavailable"
    )
    rejected = _sample(
        "clonevoice_engine_synthesis_total",
        engine=PRIMARY,
        outcome="reference_rejected",
    )
    before = _count("reference")
    try:
        path, duration = asyncio.run(
            tts_pipeline.run_inference_pipeline(
                "Hello.", EMB, "u", reference_audio_path=str(ref)
            )
        )
    finally:
        server.stop()

    assert sf.info(path).samplerate == settings.VOCODER_SAMPLE_RATE and duration > 0
    assert _count("reference") == before + 1
    assert (
        _sample(
            "clonevoice_engine_synthesis_total",
            engine=PRIMARY,
            outcome="reference_rejected",
        )
        == rejected + 1
    )
    assert (  # the worker's health measure is untouched
        _sample(
            "clonevoice_engine_synthesis_total", engine=PRIMARY, outcome="unavailable"
        )
        == unavailable
    )
    assert get_engine().breaker.state == "closed"


def test_with_the_fallback_off_a_rejected_reference_reaches_the_caller(
    monkeypatch, mock_sv2tts
):
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "none")
    _install(monkeypatch, _FlakyEngine(EngineRejectedReferenceError("too short")))
    with pytest.raises(EngineRejectedReferenceError):
        _run()


def _upload_and_headers(client, email):
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "R"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password123!"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "R", "consent_confirmed": "true"},
        files={"file": ("a.wav", _wav(_tone(4.0, amp=0.5)), "audio/wav")},
    ).json()["id"]
    return headers, profile


def test_the_api_serves_a_voice_whose_reference_the_worker_refuses(
    client: TestClient, db_session, monkeypatch
):
    from backend.models.generation import Generation

    headers, profile = _upload_and_headers(client, "ref1@example.com")
    model, server = _real_worker(monkeypatch)
    model.error = ValueError("the reference audio could not be used")
    try:
        response = client.post(
            "/api/v1/synthesize",
            headers=headers,
            json={"voice_profile_id": profile, "text": "Served by the backup"},
        )
    finally:
        server.stop()

    assert response.status_code == 200
    assert (
        sf.info(io.BytesIO(response.content)).samplerate == settings.VOCODER_SAMPLE_RATE
    )
    assert response.headers["X-Voice-Engine"] == "sv2tts"
    assert response.headers["X-Voice-Engine-Fallback"] == PRIMARY
    row = (
        db_session.query(Generation)
        .filter(Generation.input_text == "Served by the backup")
        .one()
    )
    assert (row.status, row.engine, row.engine_fallback_from) == (
        "completed",
        "sv2tts",
        PRIMARY,
    )


def test_the_api_says_what_would_help_when_there_is_no_fallback(
    client: TestClient, db_session, monkeypatch
):
    """Retrying cannot fix a short recording, so the answer is a 422 naming the remedy, not a 503."""
    from backend.models.generation import Generation

    headers, profile = _upload_and_headers(client, "ref2@example.com")
    monkeypatch.setattr(settings, "TTS_FALLBACK_ENGINE", "none")
    model, server = _real_worker(monkeypatch)
    model.error = ValueError("the reference audio could not be used")
    try:
        response = client.post(
            "/api/v1/synthesize",
            headers=headers,
            json={"voice_profile_id": profile, "text": "Nobody to serve this"},
        )
    finally:
        server.stop()

    assert response.status_code == 422
    assert "too short" in response.json()["detail"]
    assert "10 seconds" in response.json()["detail"]
    row = (
        db_session.query(Generation)
        .filter(Generation.input_text == "Nobody to serve this")
        .one()
    )
    assert row.status == "failed"
