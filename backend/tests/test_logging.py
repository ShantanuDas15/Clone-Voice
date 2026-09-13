"""Tests for JSON logging and request ID correlation (Hardening Phase 3.1)."""

import json
import logging

from asgi_correlation_id import correlation_id

from backend.main import configure_logging


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
