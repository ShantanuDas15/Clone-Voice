"""The inference worker's HTTP application (SPEECH_QUALITY_PLAN.md S4.3).

A stateless service in its own Python environment, so a model whose dependencies conflict with
the main application's (Chatterbox) can still serve it. It holds one model, runs one synthesis at
a time, and never writes user audio anywhere it keeps: the reference clip arrives with each
request and is handled in memory or a temporary file the model adapter deletes.

This module needs only FastAPI and soundfile; the model is supplied as a ``Synthesizer``, so the
service logic is tested without loading any model.

Protocol (version in the path), mirrored by ``backend/services/chatterbox_engine.py``:

* ``GET  /health``           unauthenticated: ``{"ready", "model", "device", "sample_rate"}``
* ``POST /v1/synthesize``    ``Authorization: Bearer <token>``; multipart form with ``text``,
  ``model`` (must equal the model served), ``truncation_retries``, an optional ``exaggeration``
  (0 to 2, the original Chatterbox's delivery intensity; other models ignore it) and a ``reference`` WAV file.
  Replies ``audio/wav`` (32-bit float) with ``X-Sample-Rate``, ``X-Truncated-Decodes``, ``X-Model``.
  401 bad token, 409 wrong model, 413 too large, 422 bad input, 503 busy (with ``Retry-After``).
"""

import asyncio
import hmac
import io
import logging
import math
from typing import Optional, Protocol, Tuple

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("tts_worker")

PATH_SYNTHESIZE = "/v1/synthesize"
PATH_HEALTH = "/health"
HEADER_SAMPLE_RATE = "X-Sample-Rate"
HEADER_TRUNCATED = "X-Truncated-Decodes"
HEADER_MODEL = "X-Model"
# The 422 `detail` for a reference clip the model cannot use (too short, undecodable). The client
# turns exactly this into a fallback instead of a failed request; a test keeps both sides in step.
REFERENCE_REJECTED_DETAIL = "the reference audio could not be used"

MAX_TEXT_CHARS = 1000
MAX_REFERENCE_BYTES = 2_000_000
# Room for the multipart framing and the text field on top of the reference.
MAX_BODY_BYTES = MAX_REFERENCE_BYTES + 64 * 1024
MAX_WAITING = 2
MIN_TOKEN_CHARS = 32
EXAGGERATION_MAX = 2.0


class Synthesizer(Protocol):
    """One loaded speech model."""

    model: str
    device: str
    sample_rate: int

    def synthesize(
        self,
        text: str,
        reference_wav: bytes,
        truncation_retries: int,
        exaggeration: Optional[float] = None,
    ) -> Tuple[np.ndarray, int]:
        """Return a mono float32 waveform and its sample rate.

        ``exaggeration`` is passed only when the request carried one; a model without the control
        ignores it.

        Raise ``ValueError`` for input the model cannot use (for example a reference with no speech).
        """


def create_app(
    synthesizer: Synthesizer, token: str, max_waiting: int = MAX_WAITING
) -> FastAPI:
    """Build the worker application around ``synthesizer``.

    Args:
        synthesizer: The loaded model.
        token: The shared bearer token; at least 32 characters.
        max_waiting: How many requests may wait for the model before others get a 503.
    """
    if len(token) < MIN_TOKEN_CHARS:
        raise ValueError(
            f"the worker token must be at least {MIN_TOKEN_CHARS} characters"
        )

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    lock = asyncio.Lock()
    state = {"waiting": 0}
    expected = f"Bearer {token}"

    @app.middleware("http")
    async def authenticate_and_bound(request: Request, call_next):
        """Check the token and the declared size before the body is read or parsed."""
        if request.url.path.startswith("/v1/"):
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            declared = request.headers.get("content-length")
            if (
                declared is None
                or not declared.isdigit()
                or int(declared) > MAX_BODY_BYTES
            ):
                return JSONResponse({"detail": "request too large"}, status_code=413)
        return await call_next(request)

    @app.get(PATH_HEALTH)
    async def health() -> dict:
        """Liveness and which model this worker serves."""
        return {
            "ready": True,
            "model": synthesizer.model,
            "device": synthesizer.device,
            "sample_rate": synthesizer.sample_rate,
        }

    @app.post(PATH_SYNTHESIZE)
    async def synthesize(
        text: str = Form(...),
        model: str = Form(...),
        truncation_retries: int = Form(0),
        exaggeration: Optional[float] = Form(None),
        reference: UploadFile = File(...),
    ) -> Response:
        """Synthesize ``text`` in the voice of ``reference``."""
        if model != synthesizer.model:
            raise HTTPException(
                409, f"this worker serves {synthesizer.model!r}, not {model!r}"
            )
        if not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise HTTPException(422, f"text must be 1 to {MAX_TEXT_CHARS} characters")
        if exaggeration is not None and not (
            math.isfinite(exaggeration) and 0.0 <= exaggeration <= EXAGGERATION_MAX
        ):
            raise HTTPException(
                422, f"exaggeration must be between 0 and {EXAGGERATION_MAX}"
            )
        audio = await reference.read(MAX_REFERENCE_BYTES + 1)
        if len(audio) > MAX_REFERENCE_BYTES:
            raise HTTPException(413, "reference audio too large")
        if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise HTTPException(422, "reference must be a WAV file")

        if state["waiting"] >= max_waiting:
            return JSONResponse(
                {"detail": "busy"}, status_code=503, headers={"Retry-After": "1"}
            )
        state["waiting"] += 1
        try:
            async with lock:
                try:
                    controls = (
                        {} if exaggeration is None else {"exaggeration": exaggeration}
                    )
                    waveform, rate = await run_in_threadpool(
                        synthesizer.synthesize,
                        text,
                        audio,
                        max(0, truncation_retries),
                        **controls,
                    )
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
                except Exception:
                    # Never log the text or the audio: only that it failed.
                    logger.exception("Synthesis failed")
                    raise HTTPException(500, "synthesis failed") from None
        finally:
            state["waiting"] -= 1

        waveform = np.asarray(waveform, dtype=np.float32).reshape(-1)
        if waveform.size == 0 or not np.all(np.isfinite(waveform)):
            logger.error("The model returned an empty or non-finite waveform")
            raise HTTPException(500, "synthesis failed")
        buffer = io.BytesIO()
        sf.write(buffer, waveform, int(rate), format="WAV", subtype="FLOAT")
        return Response(
            buffer.getvalue(),
            media_type="audio/wav",
            headers={
                HEADER_SAMPLE_RATE: str(int(rate)),
                HEADER_TRUNCATED: "0",
                HEADER_MODEL: synthesizer.model,
            },
        )

    return app
