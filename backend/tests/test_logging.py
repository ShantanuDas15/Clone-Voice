"""Tests for JSON logging and request ID correlation (Hardening Phase 3.1)."""

import json
import logging

from asgi_correlation_id import correlation_id

from backend.core.config import settings
from backend.main import configure_logging


def test_configure_logging_uses_info_level_in_production(monkeypatch) -> None:
    """P2-L7: DEBUG logs include per-request user ids and file paths, so the
    root logger must stay at INFO unless APP_ENV is explicitly "development"."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    configure_logging()

    assert logging.getLogger().level == logging.INFO


def test_configure_logging_uses_debug_level_in_development(monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "development")
    configure_logging()

    assert logging.getLogger().level == logging.DEBUG


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _simulate_uvicorn_default_logging() -> None:
    """Reproduce what uvicorn does before it imports the app: its own
    plain-text handler on each of its loggers, with propagation switched off."""
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [logging.StreamHandler()]
        uvicorn_logger.propagate = False


def test_uvicorn_loggers_are_routed_to_the_json_root_handler() -> None:
    """Pass 1 §4.11: uvicorn's own startup/error/access lines used to be plain
    text next to the JSON records. After configure_logging() none of its
    loggers may keep a handler of its own, and all must reach the root."""
    _simulate_uvicorn_default_logging()

    configure_logging()

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        assert uvicorn_logger.handlers == [], name
        assert uvicorn_logger.propagate is True, name


def test_uvicorn_access_lines_are_emitted_as_json(capsys) -> None:
    """End to end through the real handler: an access-log record is one JSON
    object on stderr, carrying the standard fields."""
    _simulate_uvicorn_default_logging()
    configure_logging()

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:1234",
        "GET",
        "/health/live",
        "1.1",
        200,
    )

    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert payload["logger"] == "uvicorn.access"
    assert payload["level"] == "INFO"
    assert payload["message"] == '127.0.0.1:1234 - "GET /health/live HTTP/1.1" 200'
    assert "request_id" in payload


def test_health_response_includes_request_id_header(client) -> None:
    """The correlation ID middleware must echo a request ID back to the client."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_ids_are_unique_per_request(client) -> None:
    """Each request must be tagged with its own distinct correlation ID."""
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]
    assert first != second


def test_log_records_are_valid_json_with_request_id_field(client) -> None:
    """Every log record emitted during a request must serialize to JSON and
    carry a `request_id` field populated with the request's correlation ID."""
    configure_logging()
    logger = logging.getLogger("backend.tests.test_logging")

    response = client.get("/health")
    request_id = response.headers["X-Request-ID"]

    # Emit a log line directly through the configured root handler and
    # capture its formatted (JSON) output rather than relying on caplog's
    # own formatter, since caplog bypasses the configured handlers.
    root_logger = logging.getLogger()
    console_handler = next(
        h for h in root_logger.handlers if h.__class__.__name__ == "StreamHandler"
    )
    formatter = console_handler.formatter

    token = correlation_id.set(request_id)
    try:
        record = logger.makeRecord(
            name="backend.tests.test_logging",
            level=logging.INFO,
            fn=__file__,
            lno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        for log_filter in console_handler.filters:
            log_filter.filter(record)
        formatted = formatter.format(record)
    finally:
        correlation_id.reset(token)

    payload = json.loads(formatted)
    assert payload["message"] == "test message"
    assert payload["request_id"] == request_id
    assert payload["level"] == "INFO"
    assert "timestamp" in payload
