"""Validates HARDENING_PLAN.md finding H5: blocking upload/preprocessing/DB
work must run off the event loop via `asyncio.to_thread`, not directly inside
an `async def` route handler.

Method: each blocking call under test is wrapped to record which OS thread
actually executed it, and compared against a *reference* thread id captured
from a call inline in the same handler (e.g. a `logger.info(...)` that is
never wrapped in `to_thread`) — i.e. the real event-loop thread for that
request, not the pytest test's own thread. `TestClient` runs the ASGI app on
its own anyio "blocking portal" thread, which is *not* the thread the test
function itself executes on, so comparing against the test's thread would be
wrong regardless of whether the handler offloads correctly. Comparing
against an inline call captured in the same request sidesteps that and
avoids flaky wall-clock timing races entirely.
"""

import io
import threading
import wave
from unittest.mock import patch

import numpy as np

from backend.api import synthesize as synthesize_module
from backend.api import voice as voice_module
from backend.services.audio_processing import \
    preprocess_audio as real_preprocess_audio
from backend.services.audio_processing import save_upload as real_save_upload
from backend.services.audio_processing import \
    validate_audio_file as real_validate_audio_file


def _create_dummy_wav(seconds: float = 3.0) -> bytes:
    """Build a voiced (3 s, 220 Hz tone) 16 kHz mono WAV that passes M4's duration checks."""
    t = np.arange(int(16000 * seconds)) / 16000
    samples = (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())
    buf.seek(0)
    return buf.read()


def _signup_and_login(client, email):
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "name": "Offload User"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_offloads_validate_save_preprocess_and_db_to_worker_threads(
    client,
):
    """/voice/upload must run `validate_audio_file`, `save_upload`,
    `preprocess_audio`, and the profile DB commit off the event-loop thread."""
    auth_headers = _signup_and_login(client, "offload-upload@example.com")

    call_threads = {}
    real_persist_profile = voice_module._persist_profile
    real_logger_info = voice_module.logger.info

    def tracking_validate(file):
        call_threads["validate_audio_file"] = threading.get_ident()
        return real_validate_audio_file(file)

    def tracking_save(file, user_id, ext):
        call_threads["save_upload"] = threading.get_ident()
        return real_save_upload(file, user_id, ext)

    def tracking_preprocess(file_path):
        call_threads["preprocess_audio"] = threading.get_ident()
        return real_preprocess_audio(file_path)

    def tracking_persist(db, profile):
        call_threads["_persist_profile"] = threading.get_ident()
        real_persist_profile(db, profile)

    def tracking_logger_info(*args, **kwargs):
        # Inline call, never wrapped in to_thread: the true event-loop thread.
        call_threads.setdefault("_event_loop_reference", threading.get_ident())
        return real_logger_info(*args, **kwargs)

    with patch(
        "backend.api.voice.validate_audio_file", side_effect=tracking_validate
    ), patch("backend.api.voice.save_upload", side_effect=tracking_save), patch(
        "backend.api.voice.preprocess_audio", side_effect=tracking_preprocess
    ), patch(
        "backend.api.voice._persist_profile", side_effect=tracking_persist
    ), patch.object(
        voice_module.logger, "info", side_effect=tracking_logger_info
    ):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={"name": "Thread Check Voice"},
            files={"file": ("test.wav", _create_dummy_wav(), "audio/wav")},
        )

    assert response.status_code == 201
    expected_calls = {
        "validate_audio_file",
        "save_upload",
        "preprocess_audio",
        "_persist_profile",
        "_event_loop_reference",
    }
    assert set(call_threads) == expected_calls, f"Missing calls: {call_threads}"

    event_loop_thread_id = call_threads.pop("_event_loop_reference")
    for name, thread_id in call_threads.items():
        assert thread_id != event_loop_thread_id, (
            f"{name} ran on the event-loop thread instead of a worker thread "
            f"(H5 regression) — it must be wrapped in asyncio.to_thread."
        )


def test_synthesize_offloads_db_query_embedding_load_and_persist_to_worker_threads(
    client,
):
    """/synthesize must run the profile lookup, `np.load` of the embedding,
    and the generation DB commit off the event-loop thread."""
    auth_headers = _signup_and_login(client, "offload-synth@example.com")

    upload_resp = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "Synth Thread Voice"},
        files={"file": ("test.wav", _create_dummy_wav(), "audio/wav")},
    )
    profile_id = upload_resp.json()["id"]

    call_threads = {}
    real_np_load = np.load
    real_persist_generation = synthesize_module._persist_generation
    real_logger_info = synthesize_module.logger.info

    def tracking_np_load(path, *args, **kwargs):
        call_threads["np.load"] = threading.get_ident()
        return real_np_load(path, *args, **kwargs)

    def tracking_persist_generation(db, generation):
        call_threads["_persist_generation"] = threading.get_ident()
        real_persist_generation(db, generation)

    def tracking_logger_info(*args, **kwargs):
        call_threads.setdefault("_event_loop_reference", threading.get_ident())
        return real_logger_info(*args, **kwargs)

    with patch("backend.api.synthesize.np.load", side_effect=tracking_np_load), patch(
        "backend.api.synthesize._persist_generation",
        side_effect=tracking_persist_generation,
    ), patch.object(synthesize_module.logger, "info", side_effect=tracking_logger_info):
        response = client.post(
            "/api/v1/synthesize",
            headers=auth_headers,
            json={"text": "hello world", "voice_profile_id": profile_id},
        )

    assert response.status_code == 200
    expected_calls = {"np.load", "_persist_generation", "_event_loop_reference"}
    assert set(call_threads) == expected_calls, f"Missing calls: {call_threads}"

    event_loop_thread_id = call_threads.pop("_event_loop_reference")
    for name, thread_id in call_threads.items():
        assert thread_id != event_loop_thread_id, (
            f"{name} ran on the event-loop thread instead of a worker thread "
            f"(H5 regression) — it must be wrapped in asyncio.to_thread."
        )
