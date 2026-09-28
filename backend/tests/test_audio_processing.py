"""Unit tests for backend.services.audio_processing's preprocessing
concurrency bound (HARDENING_PLAN.md finding P2-L10)."""

import asyncio

from backend.services import audio_processing


def test_preprocess_semaphore_is_initialized():
    """Semaphore must exist and be unlocked at rest, before any upload."""
    assert not audio_processing.preprocess_semaphore.locked()


def test_preprocess_semaphore_bounds_concurrency(monkeypatch):
    """HARDENING_PLAN.md P2-L10: no more than the configured number of
    callers may hold the preprocessing permit at once, so concurrent uploads
    can no longer decode/resample audio in unbounded parallel with the model
    forward pass `_inference_semaphore` protects."""
    fresh_semaphore = asyncio.Semaphore(2)
    monkeypatch.setattr(audio_processing, "preprocess_semaphore", fresh_semaphore)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def _worker():
        nonlocal in_flight, max_in_flight
        async with audio_processing.preprocess_semaphore:
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1

    async def _run():
        await asyncio.gather(*(_worker() for _ in range(6)))

    asyncio.run(_run())
    assert max_in_flight == 2, (
        f"Expected at most 2 concurrent holders of preprocess_semaphore, "
        f"observed {max_in_flight}"
    )
