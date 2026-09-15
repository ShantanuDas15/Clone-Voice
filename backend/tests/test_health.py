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


def test_checksum_verified_false_for_mock_models() -> None:
    """The test suite runs on load_mock_models() — real checkpoints were
    never loaded, so checksum_verified must be False (not True, and not
    silently absent), never mistaken for a verified production deployment
    (HARDENING_PLAN.md Milestone C2.3)."""
    status = get_model_health("cpu")
    assert status["synthesizer"]["checksum_verified"] is False
    assert status["vocoder"]["checksum_verified"] is False


def test_checksum_verified_none_for_encoder() -> None:
    """The encoder's weights come from resemblyzer's own cache, not
    weights_manifest.json — checksum verification doesn't apply to it, and
    must be reported as None, not False (which would read as "checked and
    failed")."""
    status = get_model_health("cpu")
    assert status["encoder"]["checksum_verified"] is None


def test_checksum_verified_none_when_model_not_loaded() -> None:
    with _temporarily(tts_pipeline, "_synthesizer", None):
        status = get_model_health("cpu")
    assert status["synthesizer"]["loaded"] is False
    assert status["synthesizer"]["checksum_verified"] is None


def test_checksum_verified_true_reflects_module_flag_when_loaded() -> None:
    """get_model_health() reports whatever load_models() actually recorded —
    verified here via the module flag directly (real load_models() needs
    real weights, covered separately by the opt-in
    test_real_weights_end_to_end_synthesis in test_sv2tts_vendored.py)."""
    with _temporarily(tts_pipeline, "_synthesizer_checksum_verified", True):
        status = get_model_health("cpu")
    assert status["synthesizer"]["checksum_verified"] is True


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
