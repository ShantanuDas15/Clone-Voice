"""Tests for permit-held-until-thread-finishes and shutdown drain (finding M6)."""

import asyncio
import threading
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import backend.services.tts_pipeline as tts
from backend.services.tts_pipeline import (InferenceTimeoutError,
                                           _acquire_inference_slot,
                                           drain_inflight_inference)


@pytest.fixture
def fresh_semaphore(monkeypatch):
    """Test-local semaphore so loop binding never leaks into other tests."""
    sem = asyncio.Semaphore(1)
    monkeypatch.setattr(tts, "_inference_semaphore", sem)
    monkeypatch.setattr(tts.settings, "INFERENCE_ACQUIRE_TIMEOUT_SECONDS", 5.0)
    return sem


class _Gate:
    """Blocking worker function that records overlap and waits on an event."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def __call__(self, *_args):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.started.set()
        self.release.wait(timeout=5)
        with self.lock:
            self.active -= 1
        return "done"


async def _wait_until(predicate, timeout: float = 3.0) -> None:
    """Poll until ``predicate()`` is truthy or fail."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        assert loop.time() < end, "condition not reached"
        await asyncio.sleep(0.01)


def test_permit_held_until_thread_finishes_after_timeout(fresh_semaphore):
    gate = _Gate()

    async def scenario():
        with pytest.raises(InferenceTimeoutError):
            async with _acquire_inference_slot() as slot:
                try:
                    await slot.run(gate, timeout=0.05)
                except asyncio.TimeoutError:
                    raise InferenceTimeoutError("t") from None
        # Request has given up, but the thread is still inside the forward pass.
        assert gate.started.is_set() and gate.active == 1
        assert fresh_semaphore.locked(), "permit released while thread running"
        gate.release.set()
        await _wait_until(lambda: not fresh_semaphore.locked())
        assert gate.active == 0

    asyncio.run(scenario())


def test_second_request_cannot_overlap_abandoned_forward_pass(fresh_semaphore):
    gate = _Gate()
    second = _Gate()
    second.release.set()

    async def scenario():
        async def first():
            async with _acquire_inference_slot() as slot:
                await slot.run(gate, timeout=0.05)

        with pytest.raises(asyncio.TimeoutError):
            await first()

        async def next_request():
            async with _acquire_inference_slot() as slot:
                # Must only run once the first thread has returned.
                return gate.active, await slot.run(second, timeout=5)

        waiter = asyncio.ensure_future(next_request())
        await asyncio.sleep(0.2)
        assert not waiter.done(), "second request ran during abandoned pass"
        assert not second.started.is_set()
        gate.release.set()
        active_at_start, result = await asyncio.wait_for(waiter, 5)
        assert active_at_start == 0 and result == "done"

    asyncio.run(scenario())


def test_cancelled_request_keeps_permit_until_thread_finishes(fresh_semaphore):
    gate = _Gate()

    async def scenario():
        async def request():
            async with _acquire_inference_slot() as slot:
                await slot.run(gate, timeout=10)

        task = asyncio.ensure_future(request())
        await _wait_until(gate.started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert fresh_semaphore.locked()
        gate.release.set()
        await _wait_until(lambda: not fresh_semaphore.locked())

    asyncio.run(scenario())


def test_permit_released_immediately_on_normal_completion(fresh_semaphore):
    gate = _Gate()
    gate.release.set()

    async def scenario():
        async with _acquire_inference_slot() as slot:
            assert await slot.run(gate, timeout=5) == "done"
        assert not fresh_semaphore.locked()

    asyncio.run(scenario())


def test_abandoned_thread_exception_still_frees_permit(fresh_semaphore):
    started = threading.Event()
    release = threading.Event()

    def boom():
        started.set()
        release.wait(timeout=5)
        raise ValueError("boom")

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            async with _acquire_inference_slot() as slot:
                await slot.run(boom, timeout=0.05)
        assert fresh_semaphore.locked()
        release.set()
        await _wait_until(lambda: not fresh_semaphore.locked())

    asyncio.run(scenario())


def test_drain_noop_when_idle():
    assert asyncio.run(drain_inflight_inference(0.1)) is True


def test_drain_waits_for_running_inference(fresh_semaphore):
    gate = _Gate()

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            async with _acquire_inference_slot() as slot:
                await slot.run(gate, timeout=0.05)
        asyncio.get_running_loop().call_later(0.2, gate.release.set)
        drained = await drain_inflight_inference(3.0)
        assert drained is True
        assert gate.active == 0

    asyncio.run(scenario())


def test_drain_times_out_when_inference_stuck(fresh_semaphore):
    gate = _Gate()

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            async with _acquire_inference_slot() as slot:
                await slot.run(gate, timeout=0.05)
        assert await drain_inflight_inference(0.1) is False
        gate.release.set()
        assert await drain_inflight_inference(3.0) is True

    asyncio.run(scenario())


def test_run_inference_pipeline_holds_permit_across_timeout(
    fresh_semaphore, monkeypatch, tmp_path
):
    """End-to-end through the real pipeline entrypoint."""
    gate = _Gate()
    monkeypatch.setattr(tts, "synthesize_speech", gate)
    monkeypatch.setattr(tts.settings, "INFERENCE_CALL_TIMEOUT_SECONDS", 0.05)

    async def scenario():
        with pytest.raises(InferenceTimeoutError):
            await tts.run_inference_pipeline("hi", np.zeros(256, dtype=np.float32), "u")
        assert fresh_semaphore.locked()
        gate.release.set()
        await _wait_until(lambda: not fresh_semaphore.locked())

    asyncio.run(scenario())


def test_lifespan_drains_inflight_inference_on_shutdown():
    from backend.main import app

    with patch("backend.main.load_models"), patch(
        "backend.main.drain_inflight_inference"
    ) as drain:

        async def _ok(_timeout):
            return True

        drain.side_effect = _ok
        with TestClient(app):
            drain.assert_not_called()
    drain.assert_called_once()
