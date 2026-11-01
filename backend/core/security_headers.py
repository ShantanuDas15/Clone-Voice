"""ASGI middleware that adds baseline security headers to every HTTP response."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# One year. No includeSubDomains/preload: those are commitments for the whole domain.
HSTS_VALUE = "max-age=31536000"


class SecurityHeadersMiddleware:
    """Set ``Strict-Transport-Security`` (when ``hsts``) and ``nosniff`` on responses."""

    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        """Store the wrapped app and whether to send HSTS (off for plain-http dev)."""
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap ``send`` so the headers are added to the response start message."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            """Add the headers to the response start message."""
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
            await send(message)

        await self.app(scope, receive, send_with_headers)
