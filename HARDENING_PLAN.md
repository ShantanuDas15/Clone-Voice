# CloneVoice Backend — Production-Hardening Audit

**Audit date:** 2026-09-15 · **Audited commit:** `367d671` (main) · **Status:** COMPLETE for backend application code; tests and Alembic migrations NOT reviewed (see §1)

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
| C1 | Failure modes / data | Storage cleanup deletes files in `uploads/` and `outputs/` purely by mtime. It never checks the DB. Every voice profile's audio sample and `_embed.npy` lives in `UPLOAD_DIR`, so cleanup destroys them 24h after creation while the profile stays `ready`. | `services/storage_cleanup.py:48-49`; `main.py:82-86`; `core/config.py:30` (`STORAGE_MAX_AGE_HOURS = 24`); `api/voice.py:47-49` (embedding path derived from upload path); `api/synthesize.py:47-53` (`np.load` failure → 500) | **Critical.** The default config enables deletion on startup (`main.py:81`), and the only embedding copy is the file being deleted. Once a profile is 24h old, the code path is `np.load` → exception → HTTP 500, so the core feature breaks for every profile. | Observed (code path). Not executed end-to-end. |
| C2 | Model loading | The repo contains no loadable synthesizer or vocoder checkpoint. `download_weights.py` writes placeholder bytes, and `load_models()` raises on them, so the app lifespan fails. | `download_weights.py:28-36` (`b"dummy_tacotron_weights"`); `backend/weights/tacotron.pt` = 22 bytes, `wavernn.pt` = 21 bytes; `services/tts_pipeline.py:122-130, 136-144`; `main.py:79` | **Critical.** Executed: both files fail `torch.jit.load`. With the only weights this repo can provision, the server cannot start. | Observed (executed). Whether real weights exist elsewhere via `WEIGHTS_DIR` → §4. |
| C3 | Config / repo hygiene | Uploaded voice recordings, speaker embeddings, and synthesized outputs are committed and pushed to `origin/main`. They were added before the ignore rule existed, and `.gitignore` does not untrack files. | 130 files under `uploads/` on `origin/main`; added in `1d73633`, `5c5ea10`, `4765cb4`, `8d74f37`; ignore rules added later in `fd7c02e` (`.gitignore:27-28`) | **High, or Critical if the recordings are real people's voices.** Speaker embeddings are biometric identifiers and are now in remote git history, which a later deletion does not remove. | Observed (git). Whether the audio is real → §4. |
| H1 | Inference path | Input tensors are built on CPU and never moved to the model device, while models are loaded with `map_location=device`. | `services/tts_pipeline.py:190-193`, `:217` (no `.to(...)`); `:123`, `:137` (`map_location=device`); `core/config.py:22` (`DEVICE` configurable) | **High.** Grep confirms no `.to(` on inputs anywhere in production code. The GPU configuration is exposed but unusable. | Inferred: with `DEVICE=cuda`, every forward pass raises a device-mismatch `RuntimeError`. |
| H2 | Inference path | Text is tokenised as raw Unicode code points, a placeholder that the code's own comment says does not match any real checkpoint interface. The schema limits length only, not the character set. | `services/tts_pipeline.py:189-190`; `schemas/synthesize.py:10` | **High.** The comment at `:189` admits the model interface is unknown. Combined with C2, the pipeline has never run against a real Tacotron checkpoint. | Inferred: non-ASCII code points (e.g. emoji, >100k) exceed any symbol-embedding table, causing `IndexError`. ASCII input would still use the wrong symbol IDs. |
| H3 | Failure modes | Inference errors, including CUDA OOM, are not caught in the route. No failed `Generation` row is written, and nothing anywhere handles `OutOfMemoryError`. | `api/synthesize.py:62-64` (no try/except); `api/synthesize.py:78` (status is only ever `"completed"`); grep: no `OutOfMemoryError` in backend | **High.** Violates CLAUDE.md §9 ("Never let unhandled exceptions propagate"). No audit record of failed syntheses exists. | Observed. Inferred: client gets a generic 500 with no recovery or retry signal. |
| H4 | Request handling | WEBM uploads, or any extension other than lowercase `.wav`/`.mp3` (e.g. `.WAV`), create profiles marked `ready` that can never be synthesized. The embedding path is left identical to the audio path, `np.save` appends `.npy`, and synthesis later calls `np.load` on the audio file. | `services/audio_processing.py:21` (webm allowed); `:63` (extension taken from client filename); `api/voice.py:47-49` (replaces only `.wav`/`.mp3`); `:88` (stores that path); `api/synthesize.py:48` | **High.** Reproduced: `np.save("x.webm")` → `x.webm.npy`; `np.load("x.webm")` → `ValueError` → 500. An advertised format is permanently broken. | Observed (executed). |
| H5 | Event loop | `async def` handlers run blocking CPU and disk work directly on the event loop: reading and copying the upload, librosa decode, resample, and trim of up to 25 MB, plus synchronous SQLAlchemy queries, commits, and `np.load`. | `api/voice.py:41-45` → `services/audio_processing.py:28-42, 70-71, 79-80`; `core/config.py:23` (25 MB); `api/synthesize.py:35-37, 48, 80-82`; `core/database.py:8` (sync engine) | **High.** Only the model forward passes are offloaded (`tts_pipeline.py:267-268, 291`). A 25 MB MP3 decode runs inline. | Inferred: while a large upload decodes, every other request stalls, including `/health`, which could fail LB probes. |
| H6 | Concurrency | The inference semaphore has no acquisition timeout and no queue-depth cap, and forward passes have no timeout. The limiter is per-IP (5/min), which does not bound the global queue behind a single slot. | `services/tts_pipeline.py:263`, `:290` (bare `async with`); `api/synthesize.py:27`; grep: no `wait_for`/`timeout` in backend | **High.** All synthesis and embedding traffic funnels through one permit (`tts_pipeline.py:28`) with unbounded waiting. | Inferred: under load, requests queue until client or proxy timeouts fire, while queued work still runs afterward. |
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
- **C1:** Stop age-pruning referenced files. Exclude any path referenced by a non-deleted `voice_profiles` or `generations` row, or prune only after soft-delete. Store embeddings outside the pruned tree.
- **C2:** Provision real TorchScript synthesizer/vocoder checkpoints (download plus checksum verification). Delete the placeholder-writing code and fail loudly if the files are missing.
- **C3:** Remove `uploads/`, `outputs/`, and `test_output.wav` from the index. If the audio is real, purge it from history (`git filter-repo`) and coordinate with anyone who has cloned the repo.

### High
- **H1:** Move every input tensor to the model's device inside `synthesize_speech`/`vocode`, and add a GPU test gated on CUDA availability.
- **H2:** Replace `ord(c)` with the checkpoint's actual text frontend (symbol set plus cleaners). Validate or normalise the allowed characters in `SynthesizeRequest`.
- **H3:** Wrap the pipeline call. Map OOM and model errors to 503/500 with a controlled detail message, persist a `status="failed"` generation, and free CUDA cache on the error path.
- **H4:** Derive the storage extension from the validated magic bytes, not the client filename. Build `embedding_path` explicitly with `os.path.splitext(...)[0] + "_embed.npy"`.
- **H5:** Offload validation, save, and preprocessing via `asyncio.to_thread`, or make the handlers sync `def`. Move DB work off the loop in `synthesize`.
- **H6:** Add an acquisition timeout and max-waiters cap that return 503/429, plus a per-call inference timeout. Longer term, move to a job queue.
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

1. **C2 — real weights:** Do valid TorchScript checkpoints exist outside the repo (a custom `WEIGHTS_DIR` in `.env`, which was not opened)? If yes, C2 downgrades to a provisioning/documentation issue. H1 and H2 still apply.
2. **C3 — nature of the committed audio:** Are the 130 files on `origin/main` real people's voices or synthetic test audio? This decides Critical vs High and whether a history purge is required.
3. **Deployment topology:** Worker count, reverse proxy, and GPU vs CPU target are defined nowhere in the reviewed files. H6, H7, M3, and M6 severities depend on these answers.
4. **M10 — CVE status:** CVE applicability to `python-jose==3.3.0` is from prior knowledge, not a scan. Confirm with `pip-audit -r backend/requirements.txt`.
5. **Tests not reviewed:** Whether tests write into repo-root `uploads/`/`outputs/` (supporting M9 → C3) is based only on a grep of `conftest.py` that found no directory override. Coverage of C1, H4, and M4 by existing tests is unknown.
6. **Migrations not reviewed:** Whether `alembic/versions/*` matches the ORM (e.g. L11, soft-delete columns, indexes) was not checked.
7. **Model-quality questions not verifiable without real weights:**
   - `preprocess_audio` uses librosa trim plus peak normalisation instead of resemblyzer's own `preprocess_wav`.
   - `VOCODER_SAMPLE_RATE=22050` (`core/config.py:28`) may not match the eventual checkpoint's sample rate.

   Neither can be assessed until a real checkpoint is chosen.
8. **Logging under uvicorn:** Whether uvicorn's own access/error loggers emit JSON alongside the root `dictConfig` (`main.py:27-66`) was not run or verified.
