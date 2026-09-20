"""ASGI middleware that caps request body size before multipart parsing."""

import logging
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

TOO_LARGE_DETAIL = "Request body too large."


class _BodyTooLarge(Exception):
    """Raised from the wrapped ``receive`` once the byte budget is spent."""


class BodySizeLimitMiddleware:
    """Reject HTTP requests whose body exceeds ``max_body_bytes`` with a 413."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        """Store the wrapped app and the maximum accepted body size in bytes."""
        self.app = app
        self.max_body_bytes = max_body_bytes

    @staticmethod
    def _declared_length(scope: Scope) -> Optional[int]:
        """Return the parsed Content-Length header, or None if absent/invalid."""
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Enforce the limit via Content-Length, then by counting streamed bytes."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = self._declared_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            logger.warning("Rejected request: declared body %d bytes", declared)
            await self._reject(scope, receive, send)
            return

        received = 0
        exceeded = False
        response_started = False
        rejected = False

        async def limited_receive() -> Message:
            """Count body bytes and abort as soon as the limit is crossed."""
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            """Swap any app response for a 413 once the limit was crossed."""
            nonlocal response_started, rejected
            if exceeded:
                # The framework may have wrapped our abort into its own error
                # response (e.g. 400 "error parsing the body"); replace it.
                if not rejected:
                    rejected = True
                    await self._reject(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            logger.warning("Rejected request: streamed body exceeded limit")
            if not response_started and not rejected:
                await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Send the 413 response without reading any further body bytes."""
        response = JSONResponse(
            status_code=413,
            content={"detail": TOO_LARGE_DETAIL},
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)
