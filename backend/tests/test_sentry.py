"""Tests for Sentry exception tracking (Hardening Phase 3.3)."""

import sentry_sdk

from backend.core import sentry as sentry_module
from backend.core.config import settings


def test_init_sentry_is_noop_when_dsn_unset(monkeypatch) -> None:
    """With no SENTRY_DSN configured, the SDK must never be initialized."""
    monkeypatch.setattr(settings, "SENTRY_DSN", "")
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    sentry_module.init_sentry()

    assert calls == []


def test_init_sentry_initializes_sdk_when_dsn_set(monkeypatch) -> None:
    """A configured SENTRY_DSN must initialize the SDK with the app's settings."""
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    sentry_module.init_sentry()

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["dsn"] == "https://public@o0.ingest.sentry.io/0"
    assert kwargs["environment"] == "test"
    assert kwargs["traces_sample_rate"] == 0.25
    assert kwargs["before_send"] is sentry_module._before_send
    integration_names = {type(i).__name__ for i in kwargs["integrations"]}
    assert integration_names == {
        "StarletteIntegration",
        "FastApiIntegration",
        "LoggingIntegration",
    }


def test_before_send_tags_event_with_correlation_id() -> None:
    """Every captured event must carry the active request's correlation ID."""
    token = sentry_module.correlation_id.set("req-123")
    try:
        event = sentry_module._before_send({}, {})
    finally:
        sentry_module.correlation_id.reset(token)

    assert event["tags"]["request_id"] == "req-123"


def test_before_send_skips_tag_when_no_active_request() -> None:
    """Outside of a request context (e.g. a background task), no ID is tagged."""
    token = sentry_module.correlation_id.set(None)
    try:
        event = sentry_module._before_send({}, {})
    finally:
        sentry_module.correlation_id.reset(token)

    assert "tags" not in event or "request_id" not in event.get("tags", {})
