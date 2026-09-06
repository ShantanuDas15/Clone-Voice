# CloneVoice — Phase 2: Backend Hardening & Gap-Fill Plan

> **Status**: 🟡 In Progress
> **Scope**: Backend hardening only. Fills all gaps identified in the post-Phase-1 audit.
> **Last Reviewed**: 2026-09-05
> **Prerequisite**: Phase 1 (`PHASE_1_BACKEND_PLAN.md`) marked 🟢 Complete.
> **Target**: A fully hardened, production-grade FastAPI backend with real SV2TTS inference, rotating refresh tokens, structured logging, complete test coverage, and zero PEP 8 violations — ready for Phase 3 (Frontend).

---

## 📋 Progress Tracker

| Milestone | Description | Status | Commit Hash |
|-----------|-------------|--------|-------------|
| B.1 | Security hardening — refresh token rotation, JWT secret validation, passlib migration, CORS fix | 🔴 Not Started | — |
| B.2 | Data integrity — `server_default` ORM fix, index on FK, schema path leak fix | 🔴 Not Started | — |
| B.3 | Real SV2TTS integration — wire `embed_speaker()`, implement Tacotron 2 + WaveRNN inference | 🔴 Not Started | — |
| B.4 | Structured logging — replace all `print()` with `logging`, configure `dictConfig` in `main.py` | 🔴 Not Started | — |
| B.5 | Test suite completion — add missing tests, fix fixture scopes, add security test file | 🔴 Not Started | — |
| B.6 | Code quality pass — PEP 8 cleanup, module docstrings, `black` + `isort` zero-diff | 🔴 Not Started | — |

**Legend**: 🔴 Not Started · 🟡 In Progress · 🟢 Complete · ❌ Blocked

---

## 🔍 Audit Findings Summary

Full audit of every file in `backend/` against the GEMINI.md rulebook and industry
production-grade standards. **18 findings** across 7 categories.

### Severity Legend

| Symbol | Meaning |
|--------|---------|
| 🔴 P0 | Critical — security regression, must fix immediately |
| 🟠 P1 | High — broken feature, data integrity risk, or missing required test |
| 🟡 P2 | Medium — code quality, performance, or observability issue |

---

### Category 1 — Security

| ID | Sev | File | Finding |
|----|-----|------|---------|
| S1 | 🔴 P0 | `api/auth.py` | **Refresh token never rotated.** `/api/auth/refresh` issues a new access token but the old refresh cookie is never replaced. A stolen cookie is permanently valid for its full 7-day TTL. |
| S2 | 🔴 P0 | `core/config.py` | `JWT_SECRET_KEY` defaults to the literal string `"secret"`. If `.env` is missing or misconfigured the app boots with an insecure key. Must raise `ValueError` at startup if < 32 chars. |
| S3 | 🟠 P1 | `core/security.py` | Raw `import bcrypt` is used alongside `passlib[bcrypt]` from `requirements.txt`. bcrypt 4.x breaks passlib's internal calls and causes `AttributeError` at runtime. Migrate to `passlib.context.CryptContext`. |
| S4 | 🟠 P1 | `api/voice.py` | `import uuid` and `from sqlalchemy.sql import func` are placed **inside the `delete_profile()` function body**. Anti-pattern and PEP 8 violation. |
| S5 | 🟠 P1 | `api/auth.py` | `from backend.schemas.auth import UpdateUserRequest` is at **line 161**, after all function definitions. Import placed mid-module. |
| S6 | 🟠 P1 | `main.py` | `allow_origins=["http://localhost:3000"]` is hardcoded. Must be driven by a `ALLOWED_ORIGINS` env var for production deployments. |

---

### Category 2 — Missing Features / Business Logic

| ID | Sev | File | Finding |
|----|-----|------|---------|
| F1 | 🟠 P1 | `api/voice.py` | `upload_audio` saves `np.zeros(256)` as the speaker embedding. **`embed_speaker()` is never called** — the pre-processed audio `y_processed` is computed but discarded. |
| F2 | 🟠 P1 | `api/voice.py` | No `status='failed'` path exists. If preprocessing or embedding extraction raises, no audit record is written to the DB — the error propagates as a raw 422/500. |
| F3 | 🟠 P1 | `services/tts_pipeline.py` | `synthesize_speech()` returns `np.random.randn(...)` and `vocode()` returns random noise. Milestone 1.6 (SV2TTS integration) was never completed. |
| F4 | 🟡 P2 | `api/synthesize.py` | `sample_rate = 16000` is a magic number. Vocoder output SR (typically 22050 Hz for WaveRNN) must match. Should be a named constant or `settings` value. |

---

### Category 3 — Data Integrity & ORM

| ID | Sev | File | Finding |
|----|-----|------|---------|
| D1 | 🟠 P1 | `models/user.py` | `default=func.now()` on `created_at`/`updated_at` is a **Python-side default evaluated at class-definition time**, not at row-insert time. Must use `server_default=func.now()` for DB-side timestamping. |
| D2 | 🟠 P1 | `models/voice_profile.py` | Same `func.now()` issue as D1. |
| D3 | 🟡 P2 | `models/generation.py` | `voice_profile_id` FK column has no `index=True`. This column is the join key in every history query. |
| D4 | 🟡 P2 | `schemas/synthesize.py` | `GenerationOut.output_audio_path` exposes a raw OS filesystem path to API clients — an information leak. Replace with a filename basename only. |

---

### Category 4 — Logging & Observability

| ID | Sev | File | Finding |
|----|-----|------|---------|
| L1 | 🟠 P1 | `services/tts_pipeline.py` | `print()` used in `load_models()`. GEMINI.md explicitly forbids `print()` in production code. |
| L2 | 🟠 P1 | `main.py` | No structured logging is configured. No `logging.basicConfig` or `dictConfig` call. Production logs are unstructured and unfilterable. |

---

### Category 5 — Rate Limiting / DOS Protection

| ID | Sev | File | Finding |
|----|-----|------|---------|
| R1 | 🟠 P1 | `main.py` | No rate limiting on any endpoint. `/api/auth/login` and `/api/auth/signup` are fully open to credential-stuffing. `/api/synthesize` is an expensive ML inference call with no per-user throttle. |

---

### Category 6 — Code Quality / PEP 8

| ID | Sev | File | Finding |
|----|-----|------|---------|
| Q1 | 🟡 P2 | `api/auth.py` | Mid-module import at line 161 (see S5 above). |
| Q2 | 🟡 P2 | `api/voice.py` | In-function imports (see S4 above). |
| Q3 | 🟡 P2 | Multiple test files | `import uuid` inside test function bodies. |
| Q4 | 🟡 P2 | All modules | No module-level docstrings in any `api/`, `services/`, or `core/` file — required per GEMINI.md §9. |

---

### Category 7 — Test Coverage Gaps

| ID | Sev | File | Finding |
|----|-----|------|---------|
| T1 | 🟠 P1 | `tests/test_voice.py` | `test_delete_profile_wrong_user` is **missing** despite being listed in the Phase 1 Plan test specification. Cross-user authorization on delete is completely untested. |
| T2 | 🟠 P1 | `tests/test_voice.py` | `test_librosa_preprocess_shape` is **missing** (per Phase 1 spec §1.5). `preprocess_audio` has no dedicated unit test. |
| T3 | 🟡 P2 | `tests/conftest.py` | `db_session` fixture recreates all tables on every test function. Refactor to session-scoped engine + function-scoped transaction rollback (SAVEPOINT strategy) for faster test runs. |
| T4 | 🟡 P2 | `tests/test_synthesize.py` | `setup_models` fixture is `scope="module"` while `client` is `scope="function"`. This mismatch can cause fixture teardown ordering bugs. |

---

## 🏗️ Milestone B.1 — Security Hardening *(🔴 Not Started)*

> **Priority**: Execute first — P0 findings block all deployment.

### Tasks

- [ ] `core/config.py` — Add `@field_validator('JWT_SECRET_KEY')` raising `ValueError` if value is shorter than 32 characters or equals `"secret"`.
- [ ] `core/config.py` — Add `ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]` setting.
- [ ] `core/config.py` — Add `VOCODER_SAMPLE_RATE: int = 22050` constant.
- [ ] `core/security.py` — Replace raw `import bcrypt` with `passlib.context.CryptContext(schemes=["bcrypt"], deprecated="auto")`. Keep `hash_password()` / `verify_password()` signatures unchanged.
- [ ] `api/auth.py` — Move `UpdateUserRequest` import to the top of the file.
- [ ] `api/auth.py` — `POST /refresh`: after validating old refresh token, issue a **new refresh token** and set it as the updated `httpOnly` cookie in the response object.
- [ ] `main.py` — Replace `allow_origins=["http://localhost:3000"]` with `allow_origins=settings.ALLOWED_ORIGINS`.

### Files Changed

| File | Change Type |
|------|------------|
| `backend/core/config.py` | Modify |
| `backend/core/security.py` | Modify |
| `backend/api/auth.py` | Modify |
| `backend/main.py` | Modify |

### Verification Gateway B.1

```bash
# JWT secret validation
PYTHONPATH=. python -c "
from pydantic import ValidationError
from backend.core.config import Settings
try:
    Settings(JWT_SECRET_KEY='short', DATABASE_URL='sqlite://')
    print('FAIL — no error raised')
except (ValidationError, ValueError) as e:
    print('PASS — short secret rejected:', e)
"

# Full auth test suite
PYTHONPATH=. pytest backend/tests/test_auth.py -v
# Expected: ALL PASSED

# Refresh token rotation
PYTHONPATH=. pytest backend/tests/test_security.py::test_refresh_token_rotated -v
```

---

## 🏗️ Milestone B.2 — Data Integrity & Schema Fixes *(🔴 Not Started)*

### Tasks

- [ ] `models/user.py` — Change `created_at` to `server_default=func.now()`. Change `updated_at` to `server_default=func.now(), onupdate=func.now()`.
- [ ] `models/voice_profile.py` — Apply same `server_default` fix as above.
- [ ] `models/generation.py` — Add `index=True` to the `voice_profile_id` FK column.
- [ ] `schemas/synthesize.py` — Replace `output_audio_path: str` in `GenerationOut` with `output_filename: str`. Compute `os.path.basename(generation.output_audio_path)` in `api/synthesize.py` before returning.
- [ ] `schemas/synthesize.py` — Make `duration_seconds: Optional[float]` (column is nullable in DB).
- [ ] Generate and apply new Alembic migration for the `server_default` and index changes.

### Files Changed

| File | Change Type |
|------|------------|
| `backend/models/user.py` | Modify |
| `backend/models/voice_profile.py` | Modify |
| `backend/models/generation.py` | Modify |
| `backend/schemas/synthesize.py` | Modify |
| `backend/api/synthesize.py` | Modify |
| `backend/alembic/versions/` | New migration file |

### Verification Gateway B.2

```bash
# Apply the new migration
cd backend && alembic upgrade head

# Verify server_default on timestamps (PostgreSQL)
sudo docker exec -it $(sudo docker ps -q -f name=db) psql -U clonevoice -d clonevoice \
  -c "\d users"
# created_at and updated_at must show server defaults

# Verify voice_profile_id index
sudo docker exec -it $(sudo docker ps -q -f name=db) psql -U clonevoice -d clonevoice \
  -c "\d generations"

# Ensure GenerationOut no longer leaks filesystem paths
PYTHONPATH=. pytest backend/tests/test_synthesize.py::test_synthesize_success -v -s
```

---

## 🏗️ Milestone B.3 — Real SV2TTS Integration *(🔴 Not Started)*

> **Blocked on**: `backend/weights/encoder.pt`, `synthesizer.pt`, `vocoder.pt` must exist.
> Run `python backend/download_weights.py` before starting this milestone.

### Tasks

- [ ] `services/tts_pipeline.py` — Replace all `print()` with `logging.getLogger(__name__)`.
- [ ] `services/tts_pipeline.py` — Implement real `synthesize_speech()` using the Tacotron 2 synthesizer loaded from `weights/synthesizer.pt`.
- [ ] `services/tts_pipeline.py` — Implement real `vocode()` using WaveRNN loaded from `weights/vocoder.pt`.
- [ ] `services/tts_pipeline.py` — Update `save_output()` to use `settings.VOCODER_SAMPLE_RATE`.
- [ ] `api/voice.py` — Replace `np.zeros(256)` mock with `embed_speaker(y_processed)`.
- [ ] `api/voice.py` — Add `status='failed'` guard: wrap embedding extraction in `try/except`; on failure, persist `VoiceProfile(status='failed', embedding_path=None)` and raise `HTTPException(500, ...)`.
- [ ] `api/synthesize.py` — Replace `sample_rate = 16000` with `settings.VOCODER_SAMPLE_RATE`.

### Files Changed

| File | Change Type |
|------|------------|
| `backend/services/tts_pipeline.py` | Modify |
| `backend/api/voice.py` | Modify |
| `backend/api/synthesize.py` | Modify |

### Verification Gateway B.3

```bash
# Speaker encoder smoke test
PYTHONPATH=. python -c "
from backend.services.audio_processing import preprocess_audio
from backend.services.tts_pipeline import embed_speaker, load_models
load_models('cpu')
audio = preprocess_audio('backend/tests/fixtures/sample_5sec.wav')
emb = embed_speaker(audio)
assert emb.shape == (256,), f'Got {emb.shape}'
print('Speaker encoder OK:', emb.shape)
"

# Full pipeline smoke test (30–90s on CPU)
PYTHONPATH=. python -c "
from backend.services.tts_pipeline import load_models, synthesize_speech, vocode, save_output
import numpy as np
load_models('cpu')
emb = np.random.randn(256).astype(np.float32)
mel = synthesize_speech('Hello world.', emb)
wav = vocode(mel)
path, dur = save_output(wav, 22050, 'smoke_test')
print(f'Output: {path}, Duration: {dur:.2f}s')
"

# Integration tests
PYTHONPATH=. pytest backend/tests/test_synthesize.py -v
```

---

## 🏗️ Milestone B.4 — Structured Logging *(🔴 Not Started)*

### Tasks

- [ ] `main.py` — Add `logging.config.dictConfig` call at module startup.
  - Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
  - Level: `DEBUG` when `settings.APP_ENV == "development"`, `INFO` in production.
- [ ] `services/tts_pipeline.py` — Replace all `print()` with `logger = logging.getLogger(__name__)`.
- [ ] All `api/`, `services/`, `core/` files — Add `logger = logging.getLogger(__name__)` and emit `INFO`/`DEBUG` log entries at key operations (model load, file save, synthesis start/end).

### Files Changed

| File | Change Type |
|------|------------|
| `backend/main.py` | Modify |
| `backend/services/tts_pipeline.py` | Modify |
| `backend/api/auth.py` | Modify |
| `backend/api/voice.py` | Modify |
| `backend/api/synthesize.py` | Modify |

### Verification Gateway B.4

```bash
# Verify no print() in production code
grep -rn "print(" backend/ --include="*.py" --exclude-dir=tests --exclude-dir=.venv
# Expected: zero matches

# Confirm structured log output on startup
PYTHONPATH=. uvicorn backend.main:app --reload 2>&1 | head -20
# Expected: timestamped, structured log lines
```

---

## 🏗️ Milestone B.5 — Test Suite Completion & Hardening *(🔴 Not Started)*

### Tasks

- [ ] `tests/test_voice.py` — Add `test_delete_profile_wrong_user`: create profile as User A, attempt delete as User B → assert `403 Forbidden`.
- [ ] `tests/test_voice.py` — Add `test_librosa_preprocess_shape`: call `preprocess_audio('backend/tests/fixtures/sample_5sec.wav')`, assert dtype is `float32`, shape is 1D, max absolute value ≤ 1.0.
- [ ] `tests/test_synthesize.py` — Fix `setup_models` fixture scope mismatch. Move TTS pipeline unit tests to a new `tests/test_tts_pipeline.py` file with `scope="module"`.
- [ ] `tests/conftest.py` — Refactor to session-scoped engine + function-scoped transaction rollback (SAVEPOINT strategy) for faster, isolated test runs.
- [ ] `tests/test_security.py` — **Create new file** with the following tests:
  - `test_jwt_secret_too_short_raises` — assert `ValidationError` on startup with short secret.
  - `test_refresh_token_rotated` — assert cookie value changes after `/refresh`.
  - `test_deleted_user_token_rejected` — soft-delete user, use old token → `401`.
  - `test_path_not_in_generation_response` — assert `GenerationOut` JSON contains no OS path separator.

### Files Changed

| File | Change Type |
|------|------------|
| `backend/tests/test_voice.py` | Modify |
| `backend/tests/test_synthesize.py` | Modify |
| `backend/tests/conftest.py` | Modify |
| `backend/tests/test_security.py` | **New** |
| `backend/tests/test_tts_pipeline.py` | **New** |

### Verification Gateway B.5

```bash
# Full test suite — 0 failures, 0 errors
PYTHONPATH=. pytest backend/tests/ -v --tb=short

# New security tests
PYTHONPATH=. pytest backend/tests/test_security.py -v

# New voice authorization tests
PYTHONPATH=. pytest backend/tests/test_voice.py -v -k "wrong_user or preprocess"
```

---

## 🏗️ Milestone B.6 — Code Quality & PEP 8 Pass *(🔴 Not Started)*

### Tasks

- [ ] Move all in-function `import` statements to module top level across all `api/` and `tests/` files.
- [ ] Add one-line module docstrings to all `api/`, `services/`, and `core/` files (required by GEMINI.md §9).
- [ ] Add one-line docstrings to all route handler and service functions missing them.
- [ ] Run `black backend/` — commit only if zero diffs.
- [ ] Run `isort backend/` — commit only if zero diffs.

### Files Changed

| File | Change Type |
|------|------------|
| `backend/api/auth.py` | Modify |
| `backend/api/voice.py` | Modify |
| `backend/api/synthesize.py` | Modify |
| `backend/services/tts_pipeline.py` | Modify |
| `backend/services/audio_processing.py` | Modify |
| `backend/core/security.py` | Modify |
| `backend/core/config.py` | Modify |
| `backend/core/database.py` | Modify |

### Verification Gateway B.6

```bash
# Formatting — zero diffs expected
black --check backend/
isort --check-only backend/

# No print() in production code
grep -rn "print(" backend/ --include="*.py" --exclude-dir=tests --exclude-dir=.venv
# Expected: zero matches

# Final full suite
PYTHONPATH=. pytest backend/tests/ -v --tb=short
```

---

## ✅ Phase 2 Completion Criteria

Phase 2 is **complete** only when ALL of the following are true:

- [ ] All 6 milestones marked 🟢 in the progress tracker above
- [ ] `pytest backend/tests/ -v` → **0 failed, 0 errors**
- [ ] `black --check backend/` → **no diffs**
- [ ] `isort --check-only backend/` → **no diffs**
- [ ] `grep -rn "print(" backend/ --include="*.py" --exclude-dir=tests` → **zero matches**
- [ ] `grep -rn "np.zeros(256)" backend/api/` → **zero matches** (real embedding wired)
- [ ] `GET /health` → `{ "status": "ok" }`
- [ ] Full E2E manual test: signup → upload WAV → synthesize → download real WAV ✅
- [ ] Tag `v0.2.0-backend` pushed to GitHub

Only after this is complete will **Phase 3 (Frontend)** planning begin.

---

## 🔑 New / Updated Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALLOWED_ORIGINS` | ❌ | `["http://localhost:3000"]` | Comma-separated CORS allowed origins |
| `VOCODER_SAMPLE_RATE` | ❌ | `22050` | WaveRNN/HiFi-GAN output sample rate |

> All existing Phase 1 environment variables remain unchanged.
> See `PHASE_1_BACKEND_PLAN.md §Environment Variables Reference`.

---

## 📊 Execution Order & Effort Estimates

| Order | Milestone | Risk | Effort Estimate |
|-------|-----------|------|-----------------|
| 1 | **B.1 — Security Hardening** | 🔴 P0 blocker | ~3 hours |
| 2 | **B.2 — Data Integrity Fixes** | 🟠 P1 | ~1.5 hours |
| 3 | **B.5 — Test Suite Completion** | 🟠 P1 | ~2 hours |
| 4 | **B.4 — Logging & Observability** | 🟠 P1 | ~1 hour |
| 5 | **B.3 — Real SV2TTS Integration** | 🟠 P1, blocked on weights | ~4 hours |
| 6 | **B.6 — Code Quality Pass** | 🟡 P2, automated | ~30 minutes |

> **Note**: Milestones B.1, B.2, B.4, B.5, and B.6 are fully independent of the model
> weights being present. A hardened, fully tested backend can be completed before B.3.
> B.3 is the only milestone gated on external assets (`backend/weights/`).

---

*Plan Version: 1.0 — Drafted 2026-09-05*
*Audited by: Principal Architect + Senior Software Engineer Review*
*Next Phase: `PHASE_3_FRONTEND_PLAN.md` (pending Phase 2 completion)*
