# CloneVoice Backend — Production-Hardening Audit

**Audit date:** 2026-09-15 · **Audited commit:** `367d671` (main) · **Status:** COMPLETE for backend application code; tests and Alembic migrations NOT reviewed (see §1)
**Last reviewed:** 2026-09-18 (H6 fix landed same day)

## Progress Overview

**32 findings total — 10 Fixed · 0 Partial · 22 Not Started** (as of 2026-09-18). This is the
current-state dashboard; the **Task Status Log** below it is the commit-by-commit history of how
each fix landed, and **§3 Fix Plan** has the fuller action description for every not-started item.

### ✅ Completed (10)

| # | Finding | Commit(s) |
|---|---------|-----------|
| C1 | Storage cleanup deleted files still referenced by active voice profiles/generations | `9bb1922` |
| C2 | No loadable model checkpoint — real weights (C2.1), fetch tooling (C2.2), health/smoke-test (C2.3), all 3 milestones done | `f253d3d`, `9a2d8c7`, `5e641e8`, `6bd0017` |
| C3 | User audio committed to git history on `origin/main` — index cleanup + history purge | `c6cbc25` (index cleanup), history rewritten to `830e215` via `git filter-repo` |
| H1 | Inference tensors never moved to the model's device | `9a2d8c7` |
| H2 | Text tokenized as raw Unicode code points instead of the real symbol set | `9a2d8c7` |
| H3 | Inference errors (incl. OOM) not caught in the route; no failed-generation record | `c8392f1` |
| H4 | WEBM/mixed-case uploads create profiles that can never be synthesized | `249d485` |
| H5 | Blocking upload/preprocessing/DB work ran directly on the event loop | `31c186c` |
| H6 | Inference semaphore had no acquisition timeout or queue-depth cap | `471da2b` |
| L8 | `download_weights.py` ignored `settings.WEIGHTS_DIR` (resolved incidentally by the C2 rewrite) | `f253d3d` |

### ⚠️ Partial / In Progress (0)

None currently — every finding below is either fully fixed above or not started yet.

### ❌ Not Started (22)

| # | Sev. | Finding | Planned fix (§3 has detail) |
|---|------|---------|------------------------------|
| H7 | High | No Dockerfile/container definition; documented start path can't start the API | Add a backend Dockerfile + compose service, single-worker uvicorn command |
| M1 | Medium | Refresh tokens are usable as access tokens (no `type` claim) | Add a `type` claim, enforce it in `get_current_user`/`/refresh` |
| M2 | Medium | Google OAuth links/creates accounts without checking `email_verified` | Require `email_verified is True` before linking |
| M3 | Medium | No rate limit on `/login`/`/signup`; limiter uses in-memory, per-process storage | Rate-limit auth endpoints; configure a shared `storage_uri` |
| M4 | Medium | Zero-duration trimmed audio silently accepted and saved as `ready` | Reject below a minimum voiced duration, cap maximum |
| M5 | Medium | Upload size checked only after the full multipart body is received | Enforce a body-size limit before multipart parsing |
| M6 | Medium | Semaphore release doesn't wait for the worker thread to actually finish | Shield the thread future; drain in-flight inference on shutdown |
| M7 | Medium | `/health` checks model presence only, never the DB | Split liveness/readiness; readiness adds a DB `SELECT 1` |
| M8 | Medium | No latency/queue-depth metrics around inference | Emit per-stage latency, semaphore wait time, queue depth |
| M9 | Medium | `UPLOAD_DIR`/`OUTPUT_DIR` relative to process CWD, unlike `WEIGHTS_DIR` | Anchor to `BASE_DIR` or require absolute paths |
| M10 | Medium | `python-jose==3.3.0` — possible CVE-2024-33663/33664 (unverified) | Run `pip-audit`; upgrade or migrate to `PyJWT` |
| L1 | Low | Orphaned upload + raw exception text returned on preprocessing failure | Delete the saved file, return a generic error detail |
| L2 | Low | Wrong status code (500, not 4xx) for a non-`ready` voice profile | Return 409/422 when `profile.status != "ready"` |
| L3 | Low | `/history` `limit`/`offset` unvalidated at the lower bound | Add `Query(ge=...)` bounds |
| L4 | Low | Storage cleanup's directory walk runs synchronously inside the async task | Run `cleanup_stale_files` via `asyncio.to_thread` |
| L5 | Low | DB engine has no `pool_pre_ping`, pool sizing, or connect timeout | Set `pool_pre_ping=True`, pool size, connect timeout |
| L6 | Low | JWT signing secret reused as the session-cookie secret | Use a separate `SESSION_SECRET_KEY` |
| L7 | Low | Dev/test tools (`pytest`, `black`, `isort`) in runtime `requirements.txt` | Split into `requirements-dev.txt`; pin `bcrypt` exactly |
| L9 | Low | OAuth2 `tokenUrl` still points to the pre-versioning path | Set `tokenUrl` to `api/v1/auth/login` |
| L10 | Low | Raw email (PII) logged on failed login / duplicate signup | Log a user ID or hashed email instead |
| L11 | Low | `generations` table has no `updated_at`/`deleted_at` (CLAUDE.md §6) | Add both via an Alembic migration |
| L12 | Low | `docker-compose.yml` hardcodes the DB password, exposes 5432 on all interfaces | Move credentials to env, bind to `127.0.0.1` |

---

## Task Status Log

| Finding | Status | Commit | Notes |
|---------|--------|--------|-------|
| C1 — Storage cleanup deletes live user data | ✅ Fixed | `9bb1922` | `get_protected_paths()` queries active voice-profile and generation paths from the DB each pass; `cleanup_stale_files()` skips them regardless of age. Soft-deleted profiles remain eligible for pruning. Validated: 13/13 tests in `test_storage_cleanup.py` pass (6 new), full suite 103/103 pass, zero errors/failures. |
| C2 — No loadable model checkpoints | ✅ Fixed (3/3 milestones) | `f253d3d`, `9a2d8c7`, `5e641e8`, `6bd0017` | **C2.1** (`9a2d8c7`): real Tacotron2/WaveRNN architecture vendored (`backend/services/sv2tts/`, MIT, provenance in `THIRD_PARTY_NOTICE.md`), `load_models()` verifies each checkpoint's SHA256 against a pinned manifest (`backend/weights_manifest.json`) before `torch.load` ever touches the file, then loads the real `state_dict`. H1/H2 folded in since real weights cannot run without them. **C2.2** (`5e641e8`): `python -m backend.download_weights --fetch` downloads missing/corrupted checkpoints from the pinned HF repo via `huggingface_hub`, idempotent and self-healing. **C2.3** (`6bd0017`): `get_model_health()`/`/health` report a `checksum_verified` field per model (diagnostic only — never gates `ready`, so the mock-backed test suite's `/health` expectations are unaffected); `--verify-inference` loads the real models and runs one short end-to-end synthesis as a deliberate post-deploy smoke test, composable as `--fetch --verify-inference`. All three milestones validated against the real Hugging Face repo and real downloaded weights, not just mocks — specific runs and timings are in each milestone's commit message (`9a2d8c7`, `5e641e8`, `6bd0017`). Full suite: 158/158 pass + 1 opt-in real-weights test (correctly skipped by default per CLAUDE.md §4.2), zero errors. |
| C3 — User audio committed to git history | ✅ Fixed | `c6cbc25`, history rewritten to `830e215` | 154 previously-tracked files under `uploads/`, `outputs/`, `test_output.wav` untracked from the index (kept locally, already/newly gitignored) in `c6cbc25`; merged to main and pushed as `3886705`. Investigation (`backend/tests/test_repo_hygiene.py` + manual waveform analysis) found nearly all committed audio was synthetic zero-amplitude test fixtures, except one real recording confirmed by the user as their own dev-testing voice (`uploads/64470944.../61e40feb....wav`, its `_embed.npy`, the matching `outputs/64470944.../f2ecf5cf....wav`, and root `test_output.wav`, all traced to commit `5c5ea10`). Per user confirmation there is only one clone of this repo (no coordination needed), those 4 real-audio paths were purged from all 83 rewritten commits via `git filter-repo --invert-paths` (verified via `git fsck --unreachable` — zero leftover blobs), `origin/main` force-pushed to the rewritten history (`830e215`), and 6 stale-but-fully-merged feature branches that still held the un-purged history were deleted from both origin and local per CLAUDE.md §3.7. `git ls-remote`/`git log --all --remotes` confirm the real audio no longer exists anywhere on origin. Validated: 161/161 tests pass (1 pre-existing opt-in skip), zero errors, including the 3 new `test_repo_hygiene.py` tests. |
| H1 | ✅ Fixed | `9a2d8c7` | Folded into C2.1 — real checkpoint cannot run without it. See findings table row H1 below. |
| H2 | ✅ Fixed | `9a2d8c7` | Folded into C2.1 — real checkpoint cannot run without it. See findings table row H2 below. |
| H3 — Inference errors uncaught, no failed-generation record | ✅ Fixed | `c8392f1` | `api/synthesize.py` wraps `run_inference_pipeline(...)` in `try`/`except`: `torch.cuda.OutOfMemoryError` (a `RuntimeError` subclass, caught first) maps to 503 with a generic "temporarily overloaded" detail; any other exception maps to 500 with a generic "synthesis failed" detail — neither leaks internal exception text to the client. Both paths call a new `_record_failed_generation()` helper that persists a `Generation` row with `status="failed"`, `output_audio_path=None`, `duration_seconds=None` (both nullable columns), then free cached CUDA memory via a new public `tts_pipeline.free_gpu_memory()` wrapper around the existing private `_free_gpu_memory()` before re-raising as an `HTTPException`. Validated: 2 new tests in `test_synthesize.py` (mocking `run_inference_pipeline` to raise `OutOfMemoryError` and a plain `RuntimeError`) assert the mapped status code, that `free_gpu_memory()` was called, that sensitive exception text does not appear in the response `detail`, and that a `status="failed"` row shows up in `/history` with a null duration and empty output filename. Full suite: 163/163 pass (1 pre-existing opt-in skip), zero errors. |
| H4 — Storage extension trusted client filename, not magic bytes | ✅ Fixed | `249d485` | `audio_processing.validate_audio_file()` now returns the extension implied by the already-verified magic bytes (`.wav`/`.mp3`/`.webm`) instead of `None`; `save_upload()` takes that extension as an explicit parameter instead of deriving it from `file.filename` (which is fully attacker-controlled and previously left uppercase/mismatched extensions like `.WAV` or a `.mp3`-named WAV file untouched). `api/voice.py` builds `embedding_path` via `os.path.splitext(file_path)[0] + "_embed.npy"` against the now-correct saved path instead of a `.replace(".wav", ...).replace(".mp3", ...)` chain that silently no-op'd on any other extension (including `.webm`, `.WAV`). Validated: 2 new tests in `test_voice.py` — a unit test asserting `validate_audio_file()` returns `.wav` for real WAV magic bytes even when the client sends `not_actually.mp3`, and an API-level test uploading real WAV bytes under a `voice.MP3` filename, then asserting on disk that exactly one `.wav` audio file and one matching `_embed.npy` were written and no `.mp3` file exists. Full suite: 165/165 pass (1 pre-existing opt-in skip), zero errors. |
| H5 — Blocking work ran on the event loop | ✅ Fixed | `31c186c` | `api/voice.py` `upload_audio()` wraps `validate_audio_file`, `save_upload`, `preprocess_audio`, `np.save`, `os.remove`, and the profile DB commit (via a new `_persist_profile()` helper) in `asyncio.to_thread`. `api/synthesize.py` `synthesize()` wraps the `VoiceProfile` DB lookup, `np.load` of the embedding, `_record_failed_generation()`, and the generation DB commit (via a new `_persist_generation()` helper) the same way. Both handlers stay `async def` because they also `await` genuinely async work (`embed_speaker_async`, `run_inference_pipeline`), so "make the handler sync `def`" (the plan's other option) wasn't applicable to them; `get_profiles`, `delete_profile`, and `get_history` were already plain sync `def`, so FastAPI was already running them in its threadpool and needed no change. Validated: 2 new tests in `test_event_loop_offload.py` patch each blocking call to record which OS thread executed it, and compare against a reference thread id captured from an inline (never-offloaded) `logger.info()` call in the same request — proving each targeted call ran on a worker thread, not the event-loop thread. Confirmed the tests are not vacuous by temporarily reverting the `asyncio.to_thread` wrapping and re-running them: both failed deterministically (`assert thread_id != event_loop_thread_id` → same thread id on both sides) before the fix, then reapplied the fix and re-verified they pass. Full suite: 167/167 pass (1 pre-existing opt-in skip), zero errors. |
| H6 — Inference semaphore had no acquisition timeout or queue-depth cap | ✅ Fixed | `471da2b` | New `_acquire_inference_slot()` async context manager in `tts_pipeline.py` wraps `_inference_semaphore`: rejects immediately with `InferenceQueueFullError` once `settings.INFERENCE_MAX_WAITERS` (default 10) requests are already queued, and raises `InferenceTimeoutError` if a queued request doesn't get a slot within `settings.INFERENCE_ACQUIRE_TIMEOUT_SECONDS` (default 10s) — tracked via a module-level `_inference_waiters` counter, safe to mutate without a lock since it's only ever touched between `await` points on the single-threaded event loop. `run_inference_pipeline()` (synthesizer + vocoder forward passes) and `embed_speaker_async()` (encoder forward pass) additionally wrap their held work in `asyncio.wait_for(..., timeout=settings.INFERENCE_CALL_TIMEOUT_SECONDS)` (default 30s), raising `InferenceTimeoutError` on expiry. `api/synthesize.py` and `api/voice.py` map `InferenceQueueFullError` → 429 and `InferenceTimeoutError` → 503, with the same `status="failed"` `Generation`/`VoiceProfile` audit-row behavior already used for H3's OOM path (timeouts persist a failed row since work was actually attempted; queue-full rejections don't, since no inference was ever attempted). Job queue migration remains the longer-term fix, left for a future milestone as the plan notes. Validated: 4 new tests in `test_tts_pipeline.py` (queue-full rejection, acquisition timeout, waiters-counter cleanup after timeout, per-call forward-pass timeout — the first three patch in a fresh, test-local `asyncio.Semaphore` since contending on the real module-global one binds it to that test's event loop, which would break later tests' own `asyncio.run()` calls) plus 2 new tests each in `test_synthesize.py` and `test_voice.py` asserting the 429/503 status codes and audit-row behavior at the API layer. Also manually exercised all three new failure paths plus the success path end-to-end via a throwaway script against the mock models — all four behaved as expected. Full suite: 175/175 pass (1 pre-existing opt-in skip), zero errors. |
| M1–M10 | ❌ Open | — | Unchanged. |
| L1–L12 | ❌ Open | — | Unchanged. L8 (download_weights.py ignoring `settings.WEIGHTS_DIR`) incidentally resolved by `f253d3d` as a side effect of the C2 rewrite. |

> This file replaces the previous hardening tracker (last version at commit `07299f1`, recoverable with `git show 07299f1:HARDENING_PLAN.md`).
> That tracker marked "Resource Cleanup Guarantees" as ✅ Fixed (`a596055`). This audit finds that the fix itself deletes live user data (finding **C1**).

---

## 1. Coverage Note

**Opened and read in full:**

| Area | Files |
|------|-------|
| Entrypoint | `backend/main.py` |
| Inference / model loading | `backend/services/tts_pipeline.py`, `backend/download_weights.py` |
| Routers | `backend/api/synthesize.py`, `backend/api/voice.py`, `backend/api/auth.py` |
| Services | `backend/services/audio_processing.py`, `backend/services/storage_cleanup.py` |
| Core / config | `backend/core/config.py`, `backend/core/database.py`, `backend/core/security.py`, `backend/core/rate_limit.py`, `backend/core/sentry.py` |
| Schemas / ORM | `backend/schemas/{auth,synthesize,voice}.py`, `backend/models/{user,voice_profile,generation}.py` |
| Deploy / deps | `backend/requirements.txt`, `docker-compose.yml`, `backend/.env.example`, `.gitignore`, `backend/alembic/env.py` |
| Other | `README.md` lines 40–69 only; previous `HARDENING_PLAN.md` |

**Runtime checks executed (read-only, in `backend/.venv`, Python 3.11.15, torch 2.3.0+cu121):**
- `torch.jit.load` on `backend/weights/tacotron.pt` / `wavernn.pt` → both raise `RuntimeError: PytorchStreamReader failed reading zip archive`.
- `np.save("x.webm", ...)` writes `x.webm.npy`, leaving `x.webm` untouched. `np.load("x.webm")` on the audio file then raises `ValueError: Cannot load file containing pickled data when allow_pickle=False`.
- `pip freeze` matches every pin in `requirements.txt`. `bcrypt<4.0.0` resolved to `3.2.2`.
- `git ls-tree origin/main -- uploads` → 130 tracked files. `git ls-files uploads outputs test_output.wav` → 154 files.
- `grep` across `backend/**/*.py` (excluding tests/.venv) for `print(`, `OutOfMemoryError`, `pool_pre_ping`, `storage_uri`, `email_verified`, `wait_for`, `timeout`, `.to(` found only `.to(device)` on the mock models (`tts_pipeline.py:346-347`).
- `find` for `Dockerfile*` → none in repo.
- `grep` for `UPLOAD_DIR|OUTPUT_DIR|tmp_path|environ` in `backend/tests/conftest.py` → no matches. The rest of the file was not opened.

**NOT reviewed:**
- `backend/tests/**` (apart from the single grep above)
- `backend/alembic/versions/*.py`, `backend/alembic.ini`, `backend/models/__init__.py`
- `README.md` outside lines 40–69; `DATABASE_DESIGN.md`, `PHASE_*_PLAN.md`, `project_description.md`
- `backend/.env`, deliberately not opened because it holds secrets (confirmed untracked)
- Third-party library internals (resemblyzer, slowapi, uvicorn)

---

## 2. Findings Table

Severity key: **C** Critical · **H** High · **M** Medium · **L** Low.

| # | Area | Issue | Evidence (file:line) | Severity + justification | Observed / Inferred |
|---|------|-------|----------------------|--------------------------|---------------------|
| C1 | Failure modes / data | ✅ **Fixed** (`9bb1922`). Storage cleanup deleted files in `uploads/` and `outputs/` purely by mtime, never checking the DB. Every voice profile's audio sample and `_embed.npy` lived in `UPLOAD_DIR`, so cleanup destroyed them 24h after creation while the profile stayed `ready`. | `services/storage_cleanup.py:48-49`; `main.py:82-86`; `core/config.py:30` (`STORAGE_MAX_AGE_HOURS = 24`); `api/voice.py:47-49` (embedding path derived from upload path); `api/synthesize.py:47-53` (`np.load` failure → 500) | **Critical.** The default config enables deletion on startup (`main.py:81`), and the only embedding copy is the file being deleted. Once a profile is 24h old, the code path is `np.load` → exception → HTTP 500, so the core feature breaks for every profile. | Observed (code path). Not executed end-to-end. |
| C2 | Model loading | ⚠️ **Partially fixed** (`f253d3d`, `9a2d8c7`). The repo contains no loadable synthesizer or vocoder checkpoint. `download_weights.py` used to write placeholder bytes, and `load_models()` raised on them, so the app lifespan failed. Real Tacotron2/WaveRNN architecture is now vendored and `load_models()` loads real, checksum-verified checkpoints into it — but they still ship separately from the repo and must be manually provisioned by an operator. | `services/tts_pipeline.py` `load_models()` (real `Tacotron`/`WaveRNN` construction, `verify_checksum()`, `torch.load(..., weights_only=True)`); `services/sv2tts/checksum.py`; `weights_manifest.json`; `download_weights.py` | **Critical, downgraded to High in practice with real weights present.** Confirmed by executing the full pipeline against real downloaded weights this session: loads, checksum-verifies, and produces a valid non-silent, non-crashing waveform end-to-end. | Observed (executed against the real checkpoint, both the failure paths — missing file, checksum mismatch, malformed state_dict — and the success path). |
| C3 | Config / repo hygiene | Uploaded voice recordings, speaker embeddings, and synthesized outputs are committed and pushed to `origin/main`. They were added before the ignore rule existed, and `.gitignore` does not untrack files. | 130 files under `uploads/` on `origin/main`; added in `1d73633`, `5c5ea10`, `4765cb4`, `8d74f37`; ignore rules added later in `fd7c02e` (`.gitignore:27-28`) | **High, or Critical if the recordings are real people's voices.** Speaker embeddings are biometric identifiers and are now in remote git history, which a later deletion does not remove. | Observed (git). Whether the audio is real → §4. |
| H1 | Inference path | ✅ **Fixed** (`9a2d8c7`). Was: input tensors built on CPU and never moved to the model device. | `services/tts_pipeline.py` `_inference_device()`, `synthesize_speech()`, `vocode()`; `services/sv2tts/vocoder/models/fatchord_version.py` (7 sites, marked `# PATCHED`, documented in `THIRD_PARTY_NOTICE.md`) | **High — confirmed by reproduction, not just inference.** The *vendored library itself* (not just this repo's glue code) hardcoded `torch.cuda.is_available()` branching instead of using the model's own device. Reproduced on this session's CUDA-capable machine: a `WaveRNN` explicitly placed on `cpu` still crashed with `RuntimeError: Input type (torch.cuda.FloatTensor) and weight type (torch.FloatTensor) should be the same`. | Observed (executed, both the crash before the fix and success after, on real GPU hardware). |
| H2 | Inference path | ✅ **Fixed** (`9a2d8c7`). Was: text tokenised as raw Unicode code points. | `services/tts_pipeline.py` `synthesize_speech()` (real vendored `text_to_sequence()`); `schemas/synthesize.py` (`SynthesizeRequest.validate_supported_characters`) | **High — confirmed the real behavior differs from what was inferred.** The real `text_to_sequence()` does not raise on unsupported characters (verified empirically) — it silently *drops* them, which is arguably worse (a request "succeeds" while quietly losing content). The schema validator closes this by rejecting, at the API boundary, anything the real cleaner pipeline (`english_cleaners`/`unidecode`) cannot represent — while correctly still accepting digits (cleaner-expanded) and accented Latin text (transliterated), which a naive raw-character check would have wrongly rejected (caught and fixed during this session's own testing). | Observed (executed against the real checkpoint and unit-tested for both acceptance and rejection cases). |
| H3 | Failure modes | ✅ **Fixed** (`c8392f1`). Was: inference errors, including CUDA OOM, not caught in the route; no failed `Generation` row written; nothing anywhere handled `OutOfMemoryError`. | `api/synthesize.py` `synthesize()` (`try`/`except` around `run_inference_pipeline`, `_record_failed_generation()`); `services/tts_pipeline.py` `free_gpu_memory()` | **High — confirmed fixed.** `torch.cuda.OutOfMemoryError` now maps to 503, other pipeline/model errors to 500, both with a generic detail message (CLAUDE.md §9) and a `status="failed"` audit row. | Observed (executed both mocked failure paths and the success path; 2 new tests). |
| H4 | Request handling | ✅ **Fixed** (`249d485`). Was: WEBM uploads, or any extension other than lowercase `.wav`/`.mp3` (e.g. `.WAV`), created profiles marked `ready` that could never be synthesized, because the stored extension came from the client-supplied filename and the embedding path was derived with a `.wav`/`.mp3`-only `.replace()` chain. | `services/audio_processing.py` `validate_audio_file()` (now returns `.wav`/`.mp3`/`.webm` from the verified magic bytes), `save_upload()` (takes that extension as a parameter); `api/voice.py` (`embedding_path = os.path.splitext(file_path)[0] + "_embed.npy"`) | **High — confirmed fixed.** The saved extension and the embedding filename now derive solely from the verified magic bytes, so a mismatched or mixed-case client filename can no longer desync them. | Observed (executed; 2 new tests cover the unit-level extension derivation and the end-to-end mismatched-filename upload). |
| H5 | Event loop | ✅ **Fixed** (`31c186c`). Was: `async def` handlers ran blocking CPU and disk work directly on the event loop: reading and copying the upload, librosa decode, resample, and trim of up to 25 MB, plus synchronous SQLAlchemy queries, commits, and `np.load`. | `api/voice.py` `upload_audio()` (every blocking call now wrapped in `asyncio.to_thread`); `api/synthesize.py` `synthesize()` (profile lookup, `np.load`, and both DB-commit paths now wrapped in `asyncio.to_thread`) | **High — confirmed fixed.** Model forward passes were already offloaded (`tts_pipeline.py`); now every other blocking call in both handlers is too, so a large upload's decode or a synthesis request no longer stalls unrelated concurrent requests such as `/health`. | Observed (executed; 2 new tests assert each targeted call runs on a worker thread rather than the event-loop thread, and were confirmed to fail before the fix). |
| H6 | Concurrency | ✅ **Fixed** (`471da2b`). Was: the inference semaphore had no acquisition timeout and no queue-depth cap, and forward passes had no timeout. The limiter is still per-IP (5/min), which does not bound the global queue behind a single slot on its own — but the queue itself is now bounded directly. | `services/tts_pipeline.py` `_acquire_inference_slot()`, `run_inference_pipeline()`, `embed_speaker_async()`; `api/synthesize.py`, `api/voice.py` (429/503 mapping) | **High — confirmed fixed.** A bounded waiters counter plus `asyncio.wait_for()` on both the semaphore acquisition and the held forward pass(es) means excess queued requests are now rejected with 429 and slow/stuck ones give up with 503, instead of queuing or running unbounded. | Observed (executed; 4 new unit tests plus 4 new API-level tests, and a manual end-to-end script exercising all three new failure paths and the success path). |
| H7 | Deploy | No Dockerfile exists, and the backend has no container or service definition. The README's only start command builds a compose file that defines just `db`. Uvicorn worker count and timeouts are defined nowhere in the reviewed files. | `find` → no `Dockerfile*`; `docker-compose.yml:2-17` (only `db`); `README.md:56` (`docker-compose up --build`) | **High.** The documented start path cannot start the API. Worker count matters because the semaphore (`tts_pipeline.py:28`) and limiter (`core/rate_limit.py:33`) are per-process. | Observed. |
| M1 | Auth | Access and refresh tokens carry identical claims with no `type`, and `get_current_user` accepts any validly signed token. A 7-day refresh token therefore works as a bearer access token. | `core/security.py:35`, `:46`; `core/security.py:69-70`; `api/auth.py:93` | **Medium.** The refresh cookie is `httponly` (`api/auth.py:77`), which limits exposure, but token purpose is not enforced. | Observed. |
| M2 | Auth | The Google callback links to an existing local account by email and switches its provider, without checking `email_verified`. | `api/auth.py:155-166`; grep: no `email_verified` in backend | **Medium.** Account linking rests on an unchecked claim. | Inferred: if the IdP returns an unverified email, the attacker takes over the matching local account. |
| M3 | API layer | The rate limiter keys on the socket peer IP and uses slowapi's default storage (no `storage_uri`). `/signup` and `/login` have no limit. | `core/rate_limit.py:33-36`; `api/auth.py:34-37`, `:58-59` (no `@limiter.limit`) | **Medium.** Login brute force is unthrottled, as the code shows directly. | Inferred: behind a reverse proxy, all users share one bucket. Limits are per-process, so multiple workers multiply them. |
| M4 | Request handling | Audio that trims to nothing yields an all-zero embedding and a profile saved as `ready`. There is no minimum or maximum duration check. | `services/tts_pipeline.py:165-169`; `api/voice.py:84-89`; `services/audio_processing.py:76-88` | **Medium.** Silent success on unusable input. | Inferred: synthesis with a zero embedding produces meaningless speaker identity. |
| M5 | Request handling | Upload size is measured only after the whole multipart body has been received, and no body-size limit middleware exists. | `services/audio_processing.py:28-39`; `main.py:105-128` (middleware list) | **Medium.** The 413 check runs after the bytes have already been accepted. | Inferred: oversized bodies consume disk/tmp space before rejection. |
| M6 | Concurrency / shutdown | If the awaiting task is cancelled, `async with` releases the semaphore, but the `to_thread` forward pass keeps running. Shutdown only cancels the cleanup task. | `services/tts_pipeline.py:263-268`; `main.py:97-101` | **Medium.** Nothing ties the semaphore to thread completion. | Inferred: after a cancellation, a second forward pass can start while the first is still running, the exact contention the semaphore exists to prevent. |
| M7 | Observability | `/health` checks only that the model globals are set. It never checks the DB or runs inference. The globals are never unset after startup, so the docstring's promise to detect models "crashed after startup" cannot hold. | `main.py:141-152`; `services/tts_pipeline.py:75-95` | **Medium.** No DB check is visible. The only writes to `_encoder`/`_synthesizer`/`_vocoder` are the loaders (`:113, :123, :137, :345-347`). | Observed. Inferred: a DB outage returns 200 healthy while every authenticated route fails. |
| M8 | Observability | Inference records no latency, queue wait, or queue depth. Only debug-level logs exist around the semaphore, and no metrics library is installed. | `services/tts_pipeline.py:264-269`; `requirements.txt:1-31` | **Medium.** H6 queue saturation would be invisible. | Observed. |
| M9 | Config | `UPLOAD_DIR`/`OUTPUT_DIR` are relative to the process CWD, unlike `WEIGHTS_DIR`, which is anchored to `BASE_DIR`. The gitignore only anticipates `backend/uploads`. | `core/config.py:24-26`; `.gitignore:13-14` vs `:27-28` | **Medium.** Where user data lands and what cleanup deletes both depend on the launch directory. | Inferred: the likely root cause of C3 (files landed at repo root). `conftest.py` grep shows no directory override. |
| M10 | Dependencies | `python-jose` is pinned at 3.3.0. | `requirements.txt:10` | **Medium, unverified.** | Inferred: this version is affected by CVE-2024-33663 (algorithm confusion) and CVE-2024-33664 (JWE DoS). Not verified with a scanner → §4. |
| L1 | Request handling | When preprocessing fails, the already-saved upload is orphaned, and the raw exception text is returned to the client. | `api/voice.py:42`, `:45` (outside try); `services/audio_processing.py:89-91` | **Low.** Orphans are pruned by cleanup; the leak is limited to library error strings. | Observed. |
| L2 | Request handling | Synthesis does not check `profile.status`. A `failed` profile has `embedding_path=""` and falls through to `np.load("")` → 500 instead of a 4xx. | `api/synthesize.py:39`; `api/voice.py:74` | **Low.** Wrong status code only. | Observed. |
| L3 | Request handling | `/history` caps `limit` at the top but not the bottom, and does not validate `offset`. | `api/synthesize.py:90-98` | **Low.** | Inferred: a negative value makes PostgreSQL reject `LIMIT`/`OFFSET` → 500. |
| L4 | Event loop | The cleanup pass (`os.walk` + deletes) runs synchronously inside the async task. | `services/storage_cleanup.py:86` | **Low.** Runs hourly by default (`core/config.py:31`). | Inferred: stalls the loop in proportion to file count. |
| L5 | DB | The engine is created with no `pool_pre_ping`, pool sizing, or connect timeout. | `core/database.py:8` | **Low.** | Inferred: stale pooled connections error after a DB restart. |
| L6 | Config | The JWT signing secret is reused as the session-cookie secret. | `main.py:114` | **Low.** Key reuse across two purposes. | Observed. |
| L7 | Dependencies | Test and format tools are in the runtime requirements, and `bcrypt` is range-pinned instead of exact. | `requirements.txt:21-24`, `:27` | **Low.** They ship into any runtime image; `bcrypt` currently resolves to 3.2.2. | Observed. |
| L8 | Config | `download_weights.py` ignores `settings.WEIGHTS_DIR` and swallows encoder download failure. | `download_weights.py:23`; `:17-21` | **Low.** It can populate a different directory than `load_models()` reads (`tts_pipeline.py:116`). | Observed. |
| L9 | Auth / docs | The OAuth2 `tokenUrl` still points to the pre-versioning path. | `core/security.py:17` vs `main.py:130-132` | **Low.** Affects the OpenAPI auth flow only. | Observed. |
| L10 | Observability | Email addresses (PII) are logged on failed login and duplicate signup. | `api/auth.py:67`; `api/auth.py:40` | **Low.** | Observed. |
| L11 | Data model | The `generations` table has no `updated_at`/`deleted_at`, contrary to CLAUDE.md §6. | `models/generation.py:13-33` | **Low.** Schema-rule deviation; the migration was not reviewed. | Observed. |
| L12 | Deploy | The compose file hardcodes the DB password and publishes 5432 on all interfaces. | `docker-compose.yml:7`, `:10` | **Low.** Appears dev-only. | Observed. |

---

## 3. Fix Plan (by severity)

### Critical
- **C1:** ✅ Done (`9bb1922`) — Stop age-pruning referenced files. Exclude any path referenced by a non-deleted `voice_profiles` or `generations` row.
- **C2:** ✅ Done (`f253d3d`, `9a2d8c7`, `5e641e8`, `6bd0017`) — Placeholder-writing removed, real vendored architecture loads real checksum-verified checkpoints (C2.1), scripted resumable `--fetch` download tooling (C2.2), `/health` checksum flag + `--verify-inference` post-deploy smoke test (C2.3) — see Task Status Log.
- **C3:** ✅ Done (`c6cbc25`, history rewritten to `830e215`) — Removed from the index; confirmed one recording was real (user's own dev-testing voice), purged it and its embedding from all history via `git filter-repo`, force-pushed the rewritten `main`, and deleted the stale un-purged feature branches. Single-clone repo confirmed by the user, so no further coordination was required.

### High
- **H1:** ✅ Done (`9a2d8c7`) — Every input tensor moved to the model's own device inside `synthesize_speech`/`vocode`; the vendored `WaveRNN`'s own hardcoded CUDA branching patched too. Validated on real GPU hardware.
- **H2:** ✅ Done (`9a2d8c7`) — Replaced `ord(c)` with the real vendored text frontend (symbol set plus `english_cleaners`). `SynthesizeRequest` validates the character set against what the real cleaner pipeline can represent.
- **H3:** ✅ Done (`c8392f1`) — Pipeline call wrapped in `try`/`except`; `torch.cuda.OutOfMemoryError` maps to 503, other errors to 500, both with a controlled detail message; a `status="failed"` generation is persisted and CUDA cache freed on both error paths.
- **H4:** ✅ Done (`249d485`) — `validate_audio_file()` returns the extension from the verified magic bytes; `save_upload()` uses it instead of the client filename; `embedding_path` built explicitly with `os.path.splitext(file_path)[0] + "_embed.npy"`.
- **H5:** ✅ Done (`31c186c`) — Validation, save, preprocessing, `np.save`/`np.load`, and every DB commit/query in `upload_audio()` and `synthesize()` wrapped in `asyncio.to_thread`; `_persist_profile()`/`_persist_generation()` helpers bundle each add/commit/refresh into one thread-offloaded call.
- **H6:** ✅ Done (`471da2b`) — `_acquire_inference_slot()` rejects with 429 past `INFERENCE_MAX_WAITERS` queued requests and gives up with 503 past `INFERENCE_ACQUIRE_TIMEOUT_SECONDS`; forward passes are additionally bounded by `INFERENCE_CALL_TIMEOUT_SECONDS`. Longer term, move to a job queue (not done here — out of scope for this milestone).
- **H7:** Add a backend Dockerfile and compose service with an explicit single-worker uvicorn command (required while the semaphore and limiter are per-process), and document VRAM/CPU requirements.

### Medium
- **M1:** Add a `type` claim (`access`/`refresh`) and enforce it in `get_current_user` and `/refresh`.
- **M2:** Require `email_verified is True` before creating or linking accounts from Google.
- **M3:** Rate-limit `/login` and `/signup`. Configure a shared `storage_uri` (e.g. Redis) and a proxy-aware key function.
- **M4:** Reject audio below a minimum voiced duration after trimming, cap maximum duration, and never persist a zero embedding as `ready`.
- **M5:** Enforce a request body limit at the ASGI or proxy layer before multipart parsing.
- **M6:** Hold the permit until the worker thread finishes (shield the thread future), and drain in-flight inference on shutdown.
- **M7:** Split liveness from readiness. Readiness adds a DB `SELECT 1` and optionally a tiny warm-up forward pass.
- **M8:** Emit per-stage latency, semaphore wait time, and queue depth as metrics.
- **M9:** Anchor `UPLOAD_DIR`/`OUTPUT_DIR` to `BASE_DIR` (or require absolute paths), and give tests temp directories.
- **M10:** Run `pip-audit`, then upgrade `python-jose` or migrate to `PyJWT`.

### Low
- **L1:** Delete the saved file when preprocessing fails and return a generic error detail.
- **L2:** Return 409/422 when `profile.status != "ready"`.
- **L3:** Validate `limit`/`offset` with `Query(ge=...)` bounds.
- **L4:** Run `cleanup_stale_files` via `asyncio.to_thread`.
- **L5:** Set `pool_pre_ping=True`, pool size, and a connect timeout on the engine.
- **L6:** Use a separate `SESSION_SECRET_KEY` setting.
- **L7:** Split `requirements-dev.txt` and pin `bcrypt` exactly.
- **L8:** Use `settings.WEIGHTS_DIR` in `download_weights.py` and exit non-zero on failure.
- **L9:** Set `tokenUrl` to `api/v1/auth/login`.
- **L10:** Log a user ID or hashed email instead of the raw email.
- **L11:** Add `updated_at`/`deleted_at` to `generations` via an Alembic migration.
- **L12:** Move DB credentials to env and bind 5432 to `127.0.0.1`.

---

## 4. Unverified / Needs Human Input

1. **C2 — real weights:** ✅ Resolved (2026-09-15, `9a2d8c7`) — sourced from `https://huggingface.co/CorentinJ/SV2TTS` (MIT licensed, confirmed via the repo's `LICENSE` file), vendored the real Tacotron2/WaveRNN architecture (`backend/services/sv2tts/`), and loaded real, checksum-verified checkpoints end-to-end through the production code path. H1 and H2 landed alongside it since real weights cannot run without them.
2. **C2.2 — ✅ Resolved (2026-09-15, `5e641e8`):** `huggingface_hub==0.26.5` added as a new runtime dependency for `--fetch` mode; validated against the real repo (see Task Status Log).
3. **C2.3 — ✅ Resolved (2026-09-15, `6bd0017`):** `/health` checksum flag and `--verify-inference` post-deploy smoke test landed; validated with a real end-to-end run against the real downloaded weights (produced a real 1.40s waveform in ~8.6s). **C2 is now fully closed** — all three milestones done.
4. **Responsible-use / misuse safeguards (new, unresolved by any commit):** now that real inference actually works, this repo can produce real cloned speech. Deepfake/impersonation risk, consent verification for uploaded voice samples, and any output watermarking are product/legal decisions outside this hardening pass's scope — flagged here so they aren't mistaken for "already handled" now that C2 is closed.
5. **C3 — nature of the committed audio:** ✅ Resolved (2026-09-16, `c6cbc25`/`830e215`) — analysis (551 identical 500-sample zero-amplitude `.wav` fixtures, mostly-empty/ID3-stub `.mp3` fixtures) showed nearly all 154 tracked files were synthetic test fixtures. Exactly one recording was real (waveform variance confirmed non-silent, full-scale amplitude); the user confirmed it was their own dev-testing voice, not a third party's. History purge via `git filter-repo` proceeded as the finding prescribed.
6. **Deployment topology:** Worker count, reverse proxy, and GPU vs CPU target are defined nowhere in the reviewed files. H6, H7, M3, and M6 severities depend on these answers.
7. **M10 — CVE status:** CVE applicability to `python-jose==3.3.0` is from prior knowledge, not a scan. Confirm with `pip-audit -r backend/requirements.txt`.
8. **Tests not reviewed:** Whether tests write into repo-root `uploads/`/`outputs/` (supporting M9 → C3) is based only on a grep of `conftest.py` that found no directory override. Coverage of C1 and M4 by existing tests is unknown. H4 is now covered (`249d485`).
9. **Migrations not reviewed:** Whether `alembic/versions/*` matches the ORM (e.g. L11, soft-delete columns, indexes) was not checked.
10. **Model-quality question — ✅ Answered (2026-09-15):** `VOCODER_SAMPLE_RATE` was corrected from a guessed `22050` to the verified real value `16000` (`core/config.py`). **Still unverified:** `preprocess_audio` uses librosa trim plus peak normalisation instead of resemblyzer's own `preprocess_wav` — whether this materially affects embedding quality against the real encoder was not assessed.
11. **Logging under uvicorn:** Whether uvicorn's own access/error loggers emit JSON alongside the root `dictConfig` (`main.py:27-66`) was not run or verified.
