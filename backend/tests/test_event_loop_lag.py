"""Tests for the event-loop lag measurement tool (HARDENING_PLAN.md P2-M6)."""

import asyncio
import logging
import time

import numpy as np
import pytest

from backend import measure_event_loop_lag as lag_tool
from backend.measure_event_loop_lag import LagStats, measure_lag, summarize
from backend.services import tts_pipeline

# ---- unit: summarize ---------------------------------------------------------


def test_summarize_reports_mean_p99_and_max() -> None:
    stats = summarize([1.0, 2.0, 3.0, 4.0, 100.0])
    assert stats.samples == 5
    assert stats.max_ms == 100.0
    assert stats.mean_ms == pytest.approx(22.0)
    assert stats.p99_ms == 100.0


def test_summarize_is_order_independent() -> None:
    assert summarize([9.0, 1.0, 5.0]) == summarize([1.0, 5.0, 9.0])


def test_summarize_single_sample() -> None:
    stats = summarize([2.5])
    assert (stats.samples, stats.mean_ms, stats.p99_ms, stats.max_ms) == (
        1,
        2.5,
        2.5,
        2.5,
    )


def test_summarize_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        summarize([])


# ---- unit: measure_lag detects blocking, and only blocking -------------------


def test_work_in_a_worker_thread_does_not_delay_the_loop() -> None:
    """A sleep in a worker thread leaves the loop free: lag stays tiny."""

    async def scenario():
        return await measure_lag(lambda: asyncio.to_thread(time.sleep, 0.4))

    stats, wall, _ = asyncio.run(scenario())
    assert wall >= 0.4
    assert stats.samples >= 10  # the heartbeat kept running the whole time
    assert stats.max_ms < 100


def test_work_that_blocks_the_loop_is_detected() -> None:
    """Non-vacuous: the same 0.4 s, run on the loop itself, shows up as lag."""

    async def blocking() -> None:
        time.sleep(0.4)

    async def scenario():
        return await measure_lag(blocking)

    stats, wall, _ = asyncio.run(scenario())
    assert wall >= 0.4
    assert stats.max_ms >= 300


def test_measure_lag_returns_the_work_result() -> None:
    async def scenario():
        return await measure_lag(lambda: asyncio.to_thread(lambda: 42))

    assert asyncio.run(scenario())[2] == 42


def test_measure_lag_stops_the_heartbeat_when_work_raises() -> None:
    async def failing() -> None:
        raise RuntimeError("boom")

    async def scenario() -> int:
        with pytest.raises(RuntimeError):
            await measure_lag(failing)
        await asyncio.sleep(0)
        return len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()])

    assert asyncio.run(scenario()) == 0  # no leaked heartbeat task


# ---- integration: the CLI with mock models -----------------------------------


def test_main_with_mock_models_runs_both_stages_and_passes(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=lag_tool.logger.name):
        code = lag_tool.main(["--mock", "--text-chars", "80"])
    assert code == 0
    assert "synthesizer" in caplog.text and "vocoder" in caplog.text
    assert "is within" in caplog.text


def test_main_exits_nonzero_when_lag_exceeds_the_limit(monkeypatch, caplog) -> None:
    async def slow_loop(work, *args, **kwargs):
        return LagStats(10, 5.0, 900.0, 999.0), 1.0, await work()

    monkeypatch.setattr(lag_tool, "measure_lag", slow_loop)
    with caplog.at_level(logging.ERROR, logger=lag_tool.logger.name):
        code = lag_tool.main(["--mock", "--text-chars", "80"])
    assert code == 1
    assert "separate process" in caplog.text


def test_main_honours_max_lag_ms(monkeypatch) -> None:
    async def fixed(work, *args, **kwargs):
        return LagStats(10, 1.0, 5.0, 50.0), 1.0, await work()

    monkeypatch.setattr(lag_tool, "measure_lag", fixed)
    assert lag_tool.main(["--mock", "--max-lag-ms", "60"]) == 0
    assert lag_tool.main(["--mock", "--max-lag-ms", "40"]) == 1


def test_main_without_mock_loads_the_real_models(monkeypatch) -> None:
    """The real path calls load_models() and derives an embedding from it."""
    loaded = []
    monkeypatch.setattr(
        tts_pipeline, "load_models", lambda device="cpu": loaded.append(device)
    )
    monkeypatch.setattr(
        lag_tool, "_derive_embedding", lambda: np.zeros(256, dtype=np.float32)
    )
    assert lag_tool.main(["--text-chars", "60"]) == 0
    assert loaded == [lag_tool.settings.DEVICE]
