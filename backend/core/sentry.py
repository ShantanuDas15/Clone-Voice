"""Centralized exception tracking via Sentry.

Silent failures in the ML inference pipeline are hard to diagnose from logs
alone, so every unhandled exception (and any explicitly captured error) is
forwarded to Sentry with the request's correlation ID attached, giving
end-to-end traceability from a user-reported incident back to a stack trace.
"""

import logging

import sentry_sdk
from asgi_correlation_id import correlation_id
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from backend.core.config import settings

logger = logging.getLogger(__name__)


def _before_send(event: dict, hint: dict) -> dict:
    """Tag every outgoing event with the current request's correlation ID."""
    request_id = correlation_id.get()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def init_sentry() -> None:
    """Initialize the Sentry SDK when `SENTRY_DSN` is configured.

    A blank DSN (the default, including in tests) leaves Sentry uninitialized
    so no network calls are attempted and no events are ever sent.
    """
    if not settings.SENTRY_DSN:
        logger.info("SENTRY_DSN not set — exception tracking disabled.")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        before_send=_before_send,
    )
    logger.info(
        "Sentry exception tracking initialized (environment=%s).", settings.APP_ENV
    )
