"""Tests for the ASGI request body-size limit (HARDENING_PLAN.md finding M5)."""

import asyncio
import io
from typing import List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.core.body_limit import TOO_LARGE_DETAIL, BodySizeLimitMiddleware
from backend.core.config import settings
from backend.main import app as real_app

LIMIT = 1000


@pytest.fixture
def parsed() -> List[int]:
    """Record how many bodies the downstream handler actually consumed."""
    return []


@pytest.fixture
def small_client(parsed: List[int]) -> TestClient:
    """Tiny app wrapped in the middleware with a 1000-byte limit."""
    small = FastAPI()
    small.add_middleware(BodySizeLimitMiddleware, max_body_bytes=LIMIT)

    @small.post("/echo")
    async def echo(request: Request) -> dict:
        """Read the whole body and report its size."""
        body = await request.body()
        parsed.append(len(body))
        return {"size": len(body)}

    return TestClient(small)


def test_body_at_limit_is_accepted(small_client: TestClient) -> None:
    resp = small_client.post("/echo", content=b"x" * LIMIT)
    assert resp.status_code == 200
    assert resp.json() == {"size": LIMIT}


def test_declared_oversize_rejected_before_handler(
    small_client: TestClient, parsed: List[int]
) -> None:
    resp = small_client.post("/echo", content=b"x" * (LIMIT + 1))
    assert resp.status_code == 413
    assert resp.json() == {"detail": TOO_LARGE_DETAIL}
    assert parsed == []  # handler never ran


def test_chunked_oversize_without_content_length_rejected(
    small_client: TestClient, parsed: List[int]
) -> None:
    def chunks():
        for _ in range(5):
            yield b"x" * 400  # 2000 bytes total, no Content-Length header

    resp = small_client.post("/echo", content=chunks())
    assert resp.status_code == 413
    assert resp.json() == {"detail": TOO_LARGE_DETAIL}
    assert parsed == []


def test_lying_content_length_cannot_bypass_limit(small_client: TestClient) -> None:
    resp = small_client.post(
        "/echo", content=b"x" * 2000, headers={"Content-Length": "10"}
    )
    # Either the server layer or the middleware must refuse it; never a 200.
    assert resp.status_code != 200


def test_invalid_content_length_falls_back_to_streaming_count() -> None:
    assert (
        BodySizeLimitMiddleware._declared_length(
            {"headers": [(b"content-length", b"abc")]}
        )
        is None
    )


def test_non_http_scope_passes_through() -> None:
    calls = []

    async def inner(scope, receive, send):
        calls.append(scope["type"])

    mw = BodySizeLimitMiddleware(inner, max_body_bytes=1)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert calls == ["lifespan"]


def test_real_app_configured_limit_matches_settings() -> None:
    expected = (
        settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
        + settings.REQUEST_BODY_OVERHEAD_KB * 1024
    )
    layers = [m for m in real_app.user_middleware if m.cls is BodySizeLimitMiddleware]
    assert len(layers) == 1
    assert layers[0].kwargs["max_body_bytes"] == expected


def test_upload_endpoint_rejects_oversized_body_before_parsing(
    client: TestClient,
) -> None:
    """A multipart body past the limit is 413'd without auth or parsing."""
    limit = (
        settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
        + settings.REQUEST_BODY_OVERHEAD_KB * 1024
    )
    big = io.BytesIO(b"\0" * (limit + 1024))
    resp = client.post(
        "/api/v1/voice/upload",
        files={"file": ("big.wav", big, "audio/wav")},
        data={"name": "x"},
    )
    assert resp.status_code == 413
    assert resp.json() == {"detail": TOO_LARGE_DETAIL}


def test_chunked_multipart_oversize_is_413_not_framework_400() -> None:
    """FastAPI wraps mid-parse aborts as 400; the middleware must return 413."""
    from fastapi import File, UploadFile

    small = FastAPI()
    small.add_middleware(BodySizeLimitMiddleware, max_body_bytes=LIMIT)

    @small.post("/up")
    async def up(file: UploadFile = File(...)) -> dict:
        """Accept a multipart upload."""
        return {"ok": True}

    boundary = "testboundary"

    def body():
        yield (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="file"; filename="a.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode()
        for _ in range(5):
            yield b"\0" * 400
        yield f"\r\n--{boundary}--\r\n".encode()

    resp = TestClient(small).post(
        "/up",
        content=body(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert resp.status_code == 413
    assert resp.json() == {"detail": TOO_LARGE_DETAIL}
