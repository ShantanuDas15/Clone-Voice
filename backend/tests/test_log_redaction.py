"""The History search text never reaches the access log (H1)."""

import logging

import pytest

from backend.core.config import settings
from backend.core.log_redaction import REDACTED, RedactSearchFilter, redact_search
from backend.main import configure_logging


@pytest.mark.parametrize(
    "path, expected",
    [
        (
            "/api/v1/synthesize/history?q=birthday",
            f"/api/v1/synthesize/history?q={REDACTED}",
        ),
        (
            "/api/v1/synthesize/history?limit=5&q=my%20secret&offset=0",
            f"/api/v1/synthesize/history?limit=5&q={REDACTED}&offset=0",
        ),
        ("/history?q=", f"/history?q={REDACTED}"),
        ("/history?voice_profile_id=abc", "/history?voice_profile_id=abc"),
        ("/history?faq=keep", "/history?faq=keep"),
        ("/health/live", "/health/live"),
    ],
)
def test_redact_search_hides_only_the_q_value(path, expected):
    assert redact_search(path) == expected


def _access_record(path: str) -> logging.LogRecord:
    """A record shaped like uvicorn's access line."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", path, "1.1", 200),
        None,
    )


def test_the_filter_rewrites_the_path_and_keeps_the_record():
    record = _access_record("/history?q=very-private-needle")

    assert RedactSearchFilter().filter(record) is True

    assert "very-private-needle" not in record.getMessage()
    assert REDACTED in record.getMessage() and record.args[4] == 200


def test_the_filter_tolerates_unexpected_argument_shapes():
    for args in (None, (), ("only",), {"k": "v"}, ("a", "b", 3)):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
        record.args = args
        assert RedactSearchFilter().filter(record) is True


def test_configured_access_logging_redacts_what_the_handlers_receive(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    configure_logging()
    seen = []

    class Capture(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    capture = Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1",
            "GET",
            "/api/v1/synthesize/history?q=very-private-needle",
            "1.1",
            200,
        )
    finally:
        root.removeHandler(capture)

    assert len(seen) == 1
    assert "very-private-needle" not in seen[0] and REDACTED in seen[0]
