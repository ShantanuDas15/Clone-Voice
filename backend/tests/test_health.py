"""Tests for real ML-aware health checks (Hardening Phase 3.2)."""

import contextlib

import torch
from fastapi.testclient import TestClient

from backend.services import tts_pipeline
from backend.services.tts_pipeline import get_model_health


@contextlib.contextmanager
def _temporarily(module, attr, value):
    """Set `module.attr = value` for the duration of the block, then restore it."""
    original = getattr(module, attr)
    setattr(module, attr, value)
    try:
        yield
    finally:
        setattr(module, attr, original)


def test_get_model_health_ready_when_all_models_loaded() -> None:
    """With the (mock) models loaded by the session fixture, health is ready."""
    status = get_model_health("cpu")
    assert status["ready"] is True
    for name in ("encoder", "synthesizer", "vocoder"):
        assert status[name]["loaded"] is True
        assert status[name]["device_ok"] is True


def test_get_model_health_not_ready_when_a_model_is_missing() -> None:
    """A model that failed to load (None) must flip `ready` to False."""
    with _temporarily(tts_pipeline, "_synthesizer", None):
        status = get_model_health("cpu")
    assert status["synthesizer"]["loaded"] is False
    assert status["ready"] is False


def test_get_model_health_not_ready_on_device_mismatch() -> None:
    """A model reporting a device other than the configured one is not ready."""
    with _temporarily(tts_pipeline._encoder, "device", torch.device("cuda")):
        status = get_model_health("cpu")
    assert status["encoder"]["loaded"] is True
    assert status["encoder"]["device_ok"] is False
    assert status["ready"] is False


def test_get_model_health_skips_device_check_when_unspecified() -> None:
    """Omitting `expected_device` checks presence only, not placement."""
    with _temporarily(tts_pipeline._encoder, "device", torch.device("cuda")):
        status = get_model_health(None)
    assert status["encoder"]["device_ok"] is True
    assert status["ready"] is True


def test_health_endpoint_returns_200_when_ready(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_endpoint_returns_503_when_a_model_is_missing(
    client: TestClient,
) -> None:
    """The endpoint must surface a 503 (not a false 200) when a model is down."""
    with _temporarily(tts_pipeline, "_vocoder", None):
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["models"]["vocoder"]["loaded"] is False
