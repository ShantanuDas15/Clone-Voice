"""Tests for inference metrics (HARDENING_PLAN.md finding M8)."""

import asyncio
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

import backend.services.tts_pipeline as tts
from backend.core import metrics
from backend.main import app

EMB = np.zeros(256, dtype=np.float32)


def _sample(name: str, labels: dict | None = None) -> float:
    """Read one sample value from our registry (0.0 if absent)."""
    value = metrics.registry.get_sample_value(name, labels or {})
    return 0.0 if value is None else value


@pytest.fixture
def fresh_semaphore(monkeypatch):
    """Test-local semaphore so loop binding never leaks between tests."""
    sem = asyncio.Semaphore(1)
    monkeypatch.setattr(tts, "_inference_semaphore", sem)
    monkeypatch.setattr(tts, "_inference_waiters", 0)
    return sem


def test_stage_histograms_recorded_by_full_pipeline(
    fresh_semaphore, tmp_path, monkeypatch
):
    monkeypatch.setattr(tts.settings, "OUTPUT_DIR", str(tmp_path))
    before = {
        s: _sample("clonevoice_inference_stage_seconds_count", {"stage": s})
        for s in ("synthesizer", "vocoder", "save_output")
    }
    wait_before = _sample("clonevoice_inference_semaphore_wait_seconds_count")

    asyncio.run(tts.run_inference_pipeline("hello there", EMB, "u1"))

    for stage, prev in before.items():
        now = _sample("clonevoice_inference_stage_seconds_count", {"stage": stage})
        assert now == prev + 1, stage
        assert _sample("clonevoice_inference_stage_seconds_sum", {"stage": stage}) > 0
    assert (
        _sample("clonevoice_inference_semaphore_wait_seconds_count") == wait_before + 1
    )


def test_encoder_stage_recorded(fresh_semaphore):
    before = _sample("clonevoice_inference_stage_seconds_count", {"stage": "encoder"})
    audio = (0.1 * np.sin(np.linspace(0, 200, 16000))).astype(np.float32)
    asyncio.run(tts.embed_speaker_async(audio))
    assert (
        _sample("clonevoice_inference_stage_seconds_count", {"stage": "encoder"})
        == before + 1
    )


def test_stage_latency_reflects_real_duration(fresh_semaphore):
    def slow():
        time.sleep(0.2)

    async def go():
        async with tts._acquire_inference_slot() as slot:
            await slot.run(slow, timeout=5, stage="unit_slow")

    asyncio.run(go())
    total = _sample("clonevoice_inference_stage_seconds_sum", {"stage": "unit_slow"})
    assert 0.2 <= total < 1.0


def test_semaphore_wait_time_measured(fresh_semaphore):
    async def go():
        async with fresh_semaphore:
            waiter = asyncio.ensure_future(_take_slot())
            await asyncio.sleep(0.25)
        await waiter

    async def _take_slot():
        async with tts._acquire_inference_slot():
            pass

    sum_before = _sample("clonevoice_inference_semaphore_wait_seconds_sum")
    asyncio.run(go())
    assert (
        _sample("clonevoice_inference_semaphore_wait_seconds_sum") - sum_before >= 0.2
    )


def test_queue_depth_and_in_flight_gauges_are_live(fresh_semaphore):
    gate = threading.Event()
    seen = {}

    async def go():
        async def holder():
            async with tts._acquire_inference_slot() as slot:
                await slot.run(gate.wait, 5, timeout=10, stage="unit_hold")

        async def queued():
            async with tts._acquire_inference_slot():
                pass

        h = asyncio.ensure_future(holder())
        await asyncio.sleep(0.1)
        waiters = [asyncio.ensure_future(queued()) for _ in range(3)]
        await asyncio.sleep(0.1)
        seen["depth"] = _sample("clonevoice_inference_queue_depth")
        seen["in_flight"] = _sample("clonevoice_inference_in_flight")
        gate.set()
        await asyncio.gather(h, *waiters)
        seen["depth_after"] = _sample("clonevoice_inference_queue_depth")
        seen["in_flight_after"] = _sample("clonevoice_inference_in_flight")

    asyncio.run(go())
    assert seen == {
        "depth": 3.0,
        "in_flight": 1.0,
        "depth_after": 0.0,
        "in_flight_after": 0.0,
    }


def test_rejection_counters(fresh_semaphore, monkeypatch):
    monkeypatch.setattr(tts.settings, "INFERENCE_MAX_WAITERS", 0)
    q0 = _sample("clonevoice_inference_rejections_total", {"reason": "queue_full"})

    async def full():
        with pytest.raises(tts.InferenceQueueFullError):
            async with tts._acquire_inference_slot():
                pass

    asyncio.run(full())
    assert (
        _sample("clonevoice_inference_rejections_total", {"reason": "queue_full"})
        == q0 + 1
    )

    monkeypatch.setattr(tts.settings, "INFERENCE_MAX_WAITERS", 10)
    monkeypatch.setattr(tts.settings, "INFERENCE_ACQUIRE_TIMEOUT_SECONDS", 0.05)
    a0 = _sample("clonevoice_inference_rejections_total", {"reason": "acquire_timeout"})

    async def timed_out():
        async with fresh_semaphore:
            with pytest.raises(tts.InferenceTimeoutError):
                async with tts._acquire_inference_slot():
                    pass

    asyncio.run(timed_out())
    assert (
        _sample("clonevoice_inference_rejections_total", {"reason": "acquire_timeout"})
        == a0 + 1
    )
    # a timed-out wait is still observed in the wait histogram
    assert _sample("clonevoice_inference_semaphore_wait_seconds_sum") > 0

    release = threading.Event()
    c0 = _sample("clonevoice_inference_rejections_total", {"reason": "call_timeout"})

    async def call_timeout():
        with pytest.raises(asyncio.TimeoutError):
            async with tts._acquire_inference_slot() as slot:
                await slot.run(release.wait, 5, timeout=0.05, stage="unit_stuck")
        release.set()
        await asyncio.sleep(0.1)

    asyncio.run(call_timeout())
    assert (
        _sample("clonevoice_inference_rejections_total", {"reason": "call_timeout"})
        == c0 + 1
    )


def test_metrics_endpoint_exposes_all_series(client: TestClient):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    for name in (
        "clonevoice_inference_stage_seconds",
        "clonevoice_inference_semaphore_wait_seconds",
        "clonevoice_inference_rejections_total",
        "clonevoice_inference_queue_depth",
        "clonevoice_inference_in_flight",
    ):
        assert name in resp.text
    # our dedicated registry only: no default python/process collectors
    assert "python_gc_objects" not in resp.text


def test_metrics_disabled_returns_404(client: TestClient, monkeypatch):
    from backend.main import settings

    monkeypatch.setattr(settings, "METRICS_ENABLED", False)
    assert client.get("/metrics").status_code == 404


def test_metrics_token_required_when_configured(client: TestClient, monkeypatch):
    from backend.main import settings

    monkeypatch.setattr(settings, "METRICS_AUTH_TOKEN", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    ok = client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_metrics_endpoint_reflects_pipeline_activity(
    client: TestClient, tmp_path, monkeypatch
):
    monkeypatch.setattr(tts.settings, "OUTPUT_DIR", str(tmp_path))
    asyncio.run(tts.run_inference_pipeline("metrics scrape", EMB, "u2"))
    body = client.get("/metrics").text
    assert 'clonevoice_inference_stage_seconds_count{stage="vocoder"}' in body
