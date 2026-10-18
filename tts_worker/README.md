# CloneVoice inference worker

A small, separate service that runs one Chatterbox speech model for the main application
(`SPEECH_QUALITY_PLAN.md` S4.3). It exists because Chatterbox cannot share the application's Python
environment: it pins `torch==2.6.0` and `transformers==5.2.0` (and needs `gradio`), while the
application pins `torch==2.13.0` and a hash-locked dependency set.

The application talks to it through `backend/services/chatterbox_engine.py`. The default engine,
`TTS_ENGINE=sv2tts`, does not use this service at all.

## What it does and does not do

* Holds one model: `original` (0.5B), `turbo` (350M) or `nano` (110M), chosen by `TTS_WORKER_MODEL`.
* One synthesis at a time; up to two requests may wait, the next gets `503` with `Retry-After`.
* **Stateless.** The speaker's reference clip arrives with each request and is written to a temporary
  file for the one model call, then deleted. Nothing is stored, and the text and audio are never logged.
* The model watermarks every output (Resemble's PerTh). It cannot be turned off.
* It does not decide anything about consent, quotas or users: the application does that before calling it.

## Protocol (version in the path)

| Request | Reply |
|---|---|
| `GET /health` (no token) | `{"ready", "model", "device", "sample_rate"}` |
| `POST /v1/synthesize`, `Authorization: Bearer <token>`, multipart form: `text`, `model`, `truncation_retries`, optional `exaggeration` (0 to 2; the original model only, others ignore it), `reference` (WAV) | `200 audio/wav` (32-bit float) with `X-Sample-Rate`, `X-Truncated-Decodes`, `X-Model` |

Errors: `401` bad token (checked before the body is read), `409` the worker serves another model,
`413` too large (reference over 2 MB), `422` bad text or reference, `503` busy, `500` model failure.

## Running it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r tts_worker/requirements.lock.txt
export TTS_WORKER_TOKEN=$(openssl rand -hex 24)      # 32+ characters; the application gets the same value
TTS_WORKER_MODEL=nano TTS_WORKER_DEVICE=cuda \
  .venv/bin/python -m uvicorn tts_worker.main:app --host 127.0.0.1 --port 8100
```

The first start downloads the model weights from Hugging Face (tens of seconds to minutes). Then, in the
application's `.env`:

```
TTS_ENGINE=chatterbox_nano
TTS_WORKER_URL=http://127.0.0.1:8100        # https:// unless the worker is on the same machine
TTS_WORKER_TOKEN=<the same value>
```

`TTS_WORKER_DEVICE=cpu` works for `nano` (cap threads to the real core count, for example `OMP_NUM_THREADS=8`:
more threads were slower in the S4.2b measurements).

## When the worker is unavailable

The application does not fail the request. If the worker is down, timing out, refusing the token or busy,
the request is served by the in-process SV2TTS engine (`TTS_FALLBACK_ENGINE`, on by default), logged and
counted in `clonevoice_engine_fallback_total`. SV2TTS is lower quality (16 kHz) and, on a CPU, several times
slower. After `TTS_WORKER_BREAKER_FAILURES` (3) outages in a row the app skips the worker for
`TTS_WORKER_BREAKER_COOLDOWN_SECONDS` (30), then sends one probe request; its success restores normal service.
A busy reply falls back but never opens the circuit. Set `TTS_FALLBACK_ENGINE=none` to get a `503` instead.

## Dependencies

`requirements.txt` holds the direct pins; `requirements.lock.txt` is the resolved set (no hashes, because
two requirements install from Git commits, which pip cannot hash-check). Install it with `pip install --no-deps -r`
followed by `pip check`: pip cannot *resolve* it (chatterbox-tts asks for resemble-perth from Git `master` while the
lock pins a commit, `ResolutionImpossible`), but nothing needs resolving, since every package is pinned. Regenerate with
`uv pip compile tts_worker/requirements.txt --python-version 3.11 --python-platform linux -o tts_worker/requirements.lock.txt`.
Nano is not in the PyPI release of `chatterbox-tts`, so it is installed from a pinned commit.

## Not yet verified

* ~~The Docker image has not been built~~: `.github/workflows/worker-docker-build.yml` builds it and runs it on every change to `tts_worker/` (and weekly): non-root, no baked token, pinned libraries, the Nano model loading on CPU, health, authentication, one real synthesis, and no request text, token or temporary file left behind. **Still unverified:** a GPU run (`TTS_WORKER_DEVICE=cuda`), and any model other than Nano.
* The image is **6.4 GB** because the lock pulls PyPI's CUDA torch; a CPU-only worker (the plan's Railway option) would be far smaller but is not built.
* **A reference clip must be longer than 5 seconds** for Turbo and Nano (the model asserts it). The worker answers a refused reference with `422` and the detail `the reference audio could not be used`; the application turns exactly that into a fallback to SV2TTS (S4.4b), so a short voice is served, but by the lower-quality engine.
* The fallback was exercised against a killed and restarted worker, not against a network that drops packets.
* No hosting provider has been chosen (plan question Q1); nothing here is deployed.
* The model's training data is undisclosed (`SPEECH_QUALITY_STUDY.md`), an owner decision before it serves real users.
