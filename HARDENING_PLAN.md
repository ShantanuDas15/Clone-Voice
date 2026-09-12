# CloneVoice Backend Hardening Plan

## Executive Summary
The CloneVoice backend provides a solid structural foundation, utilizing FastAPI, Pydantic, SQLAlchemy, and well-organized route separation. Basic security measures like JWT authentication and path traversal protections are correctly implemented, and test coverage for the synthesis endpoints is commendable. However, the system is **not ready for production traffic**. The most critical risks stem from the ML inference architecture: (1) model inference is completely synchronous and unbounded, which will lead to immediate CPU thrashing or GPU Out-Of-Memory (OOM) crashes under concurrent load; (2) failing model loads silently fall back to "mock" models that return random noise to end users; (3) there is a lack of resource cleanup (temporary audio files and GPU memory), leading to guaranteed eventual disk and memory exhaustion. Addressing the ML execution model and resource management are absolute ship-blockers before deploying this API.

---

## Findings Table

| Category | Item | Status | Severity | Evidence (file:line) | Risk if unaddressed |
|----------|------|--------|----------|----------------------|---------------------|
| **B. ML/Inference** | Concurrency & Threading | ✅ Fixed | **Critical** | `services/tts_pipeline.py` — `_inference_semaphore`, `run_inference_pipeline()`, `embed_speaker_async()` · commit `9782213` | Resolved: process-wide `asyncio.Semaphore(1)` serialises all model forward passes; `async def synthesize` prevents event-loop blocking. |
| **C. Resilience** | Circuit Breaker / Fallback | ✅ Fixed | **Critical** | `services/tts_pipeline.py` — `load_models()`, `embed_speaker()`, `synthesize_speech()`, `vocode()` · commit `46ba28f` | Resolved: `load_models()` now raises `RuntimeError` on any checkpoint failure; inference functions raise instead of returning random noise; `_MockSynthesizer`, `_MockVocoder`, `load_mock_models()` added for test isolation. |
| **B. ML/Inference** | GPU Memory Management | ❌ Missing | **High** | `services/tts_pipeline.py:82-90` | Missing explicit `del` or `torch.cuda.empty_cache()`. Over time, VRAM fragmentation will cause OOM errors. |
| **C. Resilience** | Resource Cleanup Guarantees | ✅ Fixed | **High** | `services/storage_cleanup.py` — `cleanup_stale_files()`, `periodic_cleanup()`; `main.py` — lifespan background task; `api/voice.py` — `except` block · commit `a596055` | Resolved: hourly background task prunes files older than 24h from `uploads/` and `outputs/`; `api/voice.py` now deletes the uploaded file in the `except` block when embedding extraction fails. |
| **H. Deployment** | Dockerfile & Resources | ❌ Missing | **High** | `backend/` directory | Lack of containerization and documented VRAM requirements prevents reproducible and stable production deployment. |
| **A. API Layer** | Rate Limiting | ✅ Fixed | **High** | `core/rate_limit.py` — `Limiter(key_func=get_remote_address)`; `api/synthesize.py` — `@limiter.limit("5/minute")`; `api/voice.py` — `@limiter.limit("10/minute")` · commit `83e8dd1` | Resolved: `slowapi` integrated; 5 req/min on synthesize, 10 req/min on upload; disabled in test suite via `conftest.py`; 3 new rate-limit tests added. |
| **B. ML/Inference** | Model Warm-up / Health | ❌ Missing | **Medium** | `main.py:75` | `/health` returns "ok" statically. Load balancers might route traffic before heavy models are actually ready or if models crashed. |
| **D. Observability** | Structured Logging | ⚠️ Partial | **Medium** | `main.py:25` | Uses standard text logging. Missing JSON formatting and request/correlation IDs makes debugging concurrent ML issues in production very hard. |
| **D. Observability** | Metrics & Exceptions | ❌ Missing | **Medium** | `main.py` | No visibility into inference latency, GPU utilization, or queue depth. No centralized error tracking (e.g., Sentry). |
| **C. Resilience** | Graceful Shutdown | ❌ Missing | **Medium** | `main.py:55` | Shutdown does not wait for in-flight requests or safely release GPU memory. |
| **A. API Layer** | API Versioning | ❌ Missing | **Low** | `main.py:70-72` | Routes are mounted at `/api/...` rather than `/api/v1/...`, making future breaking changes difficult. |
| **B. ML/Inference** | Reproducibility | ❌ Missing | **Low** | `services/tts_pipeline.py` | No mechanisms to enforce deterministic output via seeds for debugging or testing. |
| **F. Config** | Hardcoded Paths | ⚠️ Partial | **Low** | `services/tts_pipeline.py:35` | Model weights directory is hardcoded relative to `__file__`, rather than driven by environment variables. |

---

## Phased Implementation Plan

### Phase 1: Critical (Ship-Blockers)
1. **Fix Unbounded Inference Concurrency**: 
   - *Why*: Without queueing, concurrent requests will immediately crash the GPU.
   - *How*: Wrap the TTS inference functions with an `asyncio.Lock()` (if staying synchronous on a single worker) or move inference into a background worker queue (e.g., Celery/ARQ) and have the API poll for status.
2. **Remove Silent Mock Fallbacks**: 
   - *Why*: Failing to load a model should halt the server, not serve random noise to users.
   - *How*: Remove the `try/except` blocks in `services/tts_pipeline.py` that fallback to `"Tacotron2_Mock"`. Allow the application to crash on startup if models are unavailable.
3. **Add Rate Limiting**:
   - *Why*: ML endpoints are expensive. Unauthenticated or basic-auth endpoints must be protected.
   - *How*: Integrate `slowapi` in `main.py` and apply strict rate limits (e.g., 5 requests/minute) to the `/api/synthesize` endpoint.

### Phase 2: High (Reliability & Deployment)
1. **Implement Storage Cleanup**:
   - *Why*: Prevent the server's disk from filling up with old files.
   - *How*: Use a background task or cron job to prune files in `uploads/` and `outputs/` older than 24 hours. Ensure `api/voice.py` deletes the file in the `except` block if embedding fails.
2. **Explicit GPU Memory Management**:
   - *Why*: Prevent VRAM fragmentation and creeping OOMs.
   - *How*: In `tts_pipeline.py`, ensure tensors are explicitly deleted and `torch.cuda.empty_cache()` is called periodically or after large inferences.
3. **Containerization**:
   - *Why*: Required for scalable, reproducible production deployments.
   - *How*: Create a multi-stage `Dockerfile` using an official NVIDIA PyTorch base image, running the app as a non-root user.

### Phase 3: Medium (Observability)
1. **Introduce JSON Logging & Request IDs**:
   - *Why*: Tracing an error through concurrent ML requests requires request isolation in logs.
   - *How*: Use `asgi-correlation-id` middleware and configure Python logging to output JSON (e.g., using `python-json-logger`).
2. **Real Health Checks**:
   - *Why*: The load balancer needs to know if the model is actually capable of serving requests.
   - *How*: Update `GET /health` to verify that `_encoder`, `_synthesizer`, and `_vocoder` are not `None` and are assigned to the correct torch device.
3. **Exception Tracking**:
   - *Why*: Silent failures in the ML pipeline are hard to diagnose from logs alone.
   - *How*: Integrate Sentry via `sentry-sdk` with FastAPI integration.

### Phase 4: Low (Polish)
1. **API Versioning**:
   - *Why*: Future-proof the API design.
   - *How*: Move routers to `/api/v1/auth`, `/api/v1/voice`, etc.
2. **Configuration Cleanup**:
   - *Why*: Improves environment flexibility.
   - *How*: Add `WEIGHTS_DIR` to `core/config.py` instead of the hardcoded `os.path.join` in `tts_pipeline.py`.

---

## Suggested Architecture Adjustments

### Moving Inference to a Job Queue
**Current Flow (Synchronous):**
Request -> Router (`/api/synthesize`) -> Block Thread -> Run ML Pipeline -> Save to Disk -> Return Audio Response. 
*Issues: HTTP timeouts on large text, OOM crashes on concurrent requests.*

**Proposed Flow (Asynchronous Job Queue):**
1. Request -> Router (`/api/synthesize`) -> Insert Job to Redis/DB -> Return `job_id` (HTTP 202).
2. Separate Worker Process (Celery/ARQ) -> Pulls Job -> Runs ML Pipeline strictly sequentially (or batched) -> Updates DB to `completed`.
3. Client polls `GET /api/synthesize/{job_id}` until ready, then downloads the file.
*Benefit: Guarantees GPU stability, eliminates HTTP timeouts, scales horizontally easily.*

---

## Open Questions for the Human

1. **UX Acceptability of Async Polling**: Does the frontend require instant audio response (streaming), or is a loading state with polling acceptable? This determines whether we must implement WebSockets/streaming or a standard task queue.
2. **Target Hardware**: Will this be deployed to instances with GPUs (and if so, how much VRAM), or CPU-only? This heavily impacts the concurrency limits and batching strategy we need to set up.
3. **Expected Traffic**: What is the expected concurrent load? If it's single-tenant/local, a simple `asyncio.Lock` in the FastAPI app might suffice instead of full Celery architecture.
