# CloneVoice — Phase 1: Backend Development Plan

> **Status**: 🟡 IN PROGRESS — Milestone 1.10
> **Scope**: Backend only. No frontend code until all milestones here are ✅ complete, tested, and committed.
> **Last Reviewed**: 2026-09-02
> **Target**: A fully functional, tested, and hardened FastAPI backend with SV2TTS inference, JWT auth, Google OAuth, PostgreSQL persistence, and file I/O — ready to be consumed by any frontend client.

---

## 📋 Progress Tracker

| Milestone | Description | Status | Commit Hash |
|-----------|-------------|--------|-------------|
| 1.1 | Project scaffolding, virtual env, `.gitignore`, `requirements.txt`, `docker-compose.yml`, `.env.example` | 🟢 Complete | 866ee09 |
| 1.2 | Core config, database setup, SQLAlchemy models, Alembic migrations | 🔴 Not Started | — |
| 1.3 | Authentication — email/password signup & login (JWT) | 🔴 Not Started | — |
| 1.4 | Authentication — Google OAuth 2.0 backend flow | 🔴 Not Started | — |
| 1.5 | Audio upload endpoint + Librosa preprocessing service | 🔴 Not Started | — |
| 1.6 | SV2TTS inference pipeline integration (Encoder → Synthesizer → Vocoder) | 🔴 Not Started | — |
| 1.7 | Speech synthesis endpoint (`POST /api/synthesize`) | 🔴 Not Started | — |
| 1.8 | History endpoints + soft-delete voice profiles | 🔴 Not Started | — |
| 1.9 | Full test suite (unit + integration) + hardening pass | 🟢 Complete | f7919e0 |
| 1.10 | Git hygiene, `.gitignore` audit, final commit & push | 🔴 Not Started | — |

**Legend**: 🔴 Not Started · 🟡 In Progress · 🟢 Complete · ❌ Blocked

---

## 🗂️ Current Workspace State (Audited: 2026-09-02)

### ✅ Completed
- `.gitignore` created and committed with all required rules
- Full backend directory structure established
- Python 3.11 virtual environment created and activated
- All requirements installed successfully (`torch`, `librosa`, `fastapi`, etc.)
- `docker-compose.yml` created with PostgreSQL service
- `backend/.env.example` created
- Initial `sample_5sec.wav` fixture generated
- Milestone 1.1 committed to `main`

---

## 🧱 System Architecture Constraints (Free-Tier / Solo Dev)

| Constraint | Decision |
|---|---|
| No dedicated GPU in dev | SV2TTS inference runs on CPU. GPU toggled via `DEVICE=cuda` env var for production |
| No cloud object storage in v1.0 | Audio files stored on local filesystem under `uploads/` and `outputs/` |
| PostgreSQL locally via Docker | `docker-compose` runs Postgres 15 on `localhost:5432` |
| SQLite for tests | All automated tests use in-memory SQLite — never touch the dev DB |
| No Redis / task queue in v1.0 | Synthesis is synchronous per request. Async queue is Phase 3 |
| Pre-trained weights only | SV2TTS speaker encoder generates embeddings from uploaded clips — no per-user training |
| Python 3.11 required | PyTorch 2.3, Librosa 0.10, and all ML dependencies are validated against Python 3.11 |

---

## 📦 Complete Dependency Reference

### Python Version
```
Python 3.11.x  (strict requirement — do NOT use 3.12, 3.13, or 3.14)
```

### `requirements.txt` — Full Authoritative Specification

```txt
# === Web Framework ===
fastapi==0.111.0
uvicorn[standard]==0.30.1
python-multipart==0.0.9

# === Data Validation & Settings ===
pydantic==2.7.1
pydantic-settings==2.3.0

# === Database ===
sqlalchemy==2.0.30
alembic==1.13.1
psycopg2-binary==2.9.9
aiosqlite==0.20.0

# === Authentication & Security ===
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
authlib==1.3.1
httpx==0.27.0

# === Audio Processing & ML ===
torch==2.3.0
torchaudio==2.3.0
librosa==0.10.2
numpy==1.26.4
scipy==1.13.1
soundfile==0.12.1
resemblyzer==0.1.4

# === Dev & Testing ===
pytest==8.2.2
pytest-asyncio==0.23.7
black==24.4.2
isort==5.13.2
python-dotenv==1.0.1
```

> **Note on SV2TTS weights**: `resemblyzer` provides the GE2E speaker encoder. The Tacotron 2 synthesizer and WaveRNN vocoder weights are from `CorentinJ/Real-Time-Voice-Cloning` and are downloaded once via a `download_weights.py` script into `backend/weights/` (gitignored).

---

## 📁 Backend Directory Structure (Authoritative Target)

```
backend/
├── main.py                        # FastAPI app entry point, lifespan, CORS, routers
├── download_weights.py            # One-time script to fetch pre-trained model weights
├── api/
│   ├── __init__.py
│   ├── auth.py                    # /api/auth/* routes
│   ├── voice.py                   # /api/voice/* routes
│   └── synthesize.py              # /api/synthesize/* routes
├── core/
│   ├── __init__.py
│   ├── config.py                  # Pydantic Settings — reads .env
│   ├── security.py                # JWT creation/verification, bcrypt hashing, get_current_user
│   └── database.py                # SQLAlchemy engine, session factory, Base, get_db
├── models/
│   ├── __init__.py
│   ├── user.py                    # User ORM model
│   ├── voice_profile.py           # VoiceProfile ORM model
│   └── generation.py              # Generation ORM model
├── schemas/
│   ├── __init__.py
│   ├── auth.py                    # SignupRequest, LoginRequest, TokenResponse, UserOut
│   ├── voice.py                   # VoiceProfileCreate, VoiceProfileOut
│   └── synthesize.py              # SynthesizeRequest, GenerationOut
├── services/
│   ├── __init__.py
│   ├── audio_processing.py        # Librosa pipeline: load → resample → trim → normalize
│   └── tts_pipeline.py            # SV2TTS: embed_speaker(), synthesize_speech(), vocode()
├── weights/                       # Pre-trained model weights — GITIGNORED
│   ├── encoder.pt
│   ├── synthesizer.pt
│   └── vocoder.pt
├── uploads/                       # User audio uploads — GITIGNORED
├── outputs/                       # Generated speech files — GITIGNORED
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Fixtures: in-memory SQLite DB, mock JWT, mock TTS
│   ├── fixtures/
│   │   └── sample_5sec.wav        # Synthetic WAV for unit tests
│   ├── test_auth.py
│   ├── test_voice.py
│   └── test_synthesize.py
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── requirements.txt
├── .env.example                   # Safe to commit — placeholder keys only
└── .env                           # NEVER COMMITTED
```

---

## 🌐 API Endpoint Specification

### Health
| Method | Path | Auth | Response |
|--------|------|------|----------|
| `GET` | `/health` | ❌ | `{ "status": "ok", "version": "1.0.0" }` |

### Auth (`/api/auth`)
| Method | Path | Auth | Request | Response |
|--------|------|------|---------|----------|
| `POST` | `/signup` | ❌ | `{ email, password, name }` | `{ access_token, token_type }` |
| `POST` | `/login` | ❌ | `{ email, password }` | `{ access_token, token_type }` + refresh cookie |
| `POST` | `/refresh` | ❌ (cookie) | — | `{ access_token, token_type }` |
| `GET` | `/me` | ✅ | — | `UserOut` |
| `GET` | `/google` | ❌ | — | Redirect to Google |
| `GET` | `/google/callback` | ❌ | OAuth code | `{ access_token, token_type }` |

### Voice Profiles (`/api/voice`)
| Method | Path | Auth | Request | Response |
|--------|------|------|---------|----------|
| `POST` | `/upload` | ✅ | `multipart: file, name` | `VoiceProfileOut` |
| `GET` | `/profiles` | ✅ | — | `List[VoiceProfileOut]` |
| `DELETE` | `/profiles/{id}` | ✅ | — | `{ "message": "deleted" }` |

### Synthesis (`/api/synthesize`)
| Method | Path | Auth | Request | Response |
|--------|------|------|---------|----------|
| `POST` | `/` | ✅ | `{ voice_profile_id, text }` | `FileResponse` (WAV audio) |
| `GET` | `/history` | ✅ | — | `List[GenerationOut]` |

---

## 🔑 Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `JWT_SECRET_KEY` | ✅ | — | Min 32-char random secret |
| `JWT_ALGORITHM` | ❌ | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | ❌ | `15` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | ❌ | `7` | Refresh token TTL |
| `GOOGLE_CLIENT_ID` | ✅ | — | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | ✅ | — | From Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | ✅ | — | Must match Console config |
| `APP_ENV` | ❌ | `development` | `development` or `production` |
| `DEVICE` | ❌ | `cpu` | `cpu` or `cuda` |
| `MAX_AUDIO_SIZE_MB` | ❌ | `25` | Max upload file size |
| `UPLOAD_DIR` | ❌ | `uploads` | Relative path for uploads |
| `OUTPUT_DIR` | ❌ | `outputs` | Relative path for generated audio |

---

## Milestone 1.1 — Project Scaffolding *(🟢 Complete)*

### Remaining Tasks
- [ ] Fix `.gitignore` — add `backend/.venv/` entry
- [ ] Recreate virtual environment with **Python 3.11**: `python3.11 -m venv backend/.venv`
- [ ] Replace `requirements.txt` with the authoritative specification above (remove `firebase-admin`, add all missing packages)
- [ ] Install all dependencies: `pip install -r requirements.txt`
- [ ] Create `docker-compose.yml` with PostgreSQL 15 service
- [ ] Create `backend/.env.example` with all keys and empty values
- [ ] Create `backend/tests/fixtures/` directory with synthetic `sample_5sec.wav`
- [ ] Verify Docker Compose starts cleanly
- [ ] Verify all packages installed correctly

### Files to Create
- `docker-compose.yml` (project root)
- `backend/.env.example`
- `backend/tests/fixtures/sample_5sec.wav` (generated via script)

### `docker-compose.yml`
```yaml
version: "3.9"
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: clonevoice
      POSTGRES_PASSWORD: clonevoice_dev
      POSTGRES_DB: clonevoice
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U clonevoice"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### Verification Gateway 1.1
```bash
# Verify Python version
python3.11 --version                     # Must be 3.11.x

# Verify all key packages installed
source backend/.venv/bin/activate
pip show fastapi sqlalchemy librosa torch passlib python-jose authlib
# All must show a version — no "not found" errors

# Verify Docker Compose
docker-compose up -d db
docker-compose ps                        # "db" service must show "Up (healthy)"

# Verify gitignore — none of these should appear in git status
git status                               # .env and backend/.venv/ must NOT appear
```

---

## Milestone 1.2 — Core Config, Database & ORM Models *(🟢 Complete)*

### Tasks
- [ ] Implement `core/config.py` — Pydantic `Settings` loading all `.env` variables
- [ ] Implement `core/database.py` — SQLAlchemy async engine, `SessionLocal`, `Base`, `get_db` dependency
- [ ] Implement `models/user.py` — `User` ORM model (id UUID, email, name, provider, hashed_password, avatar_url, preferences JSONB, created_at, updated_at, deleted_at)
- [ ] Implement `models/voice_profile.py` — `VoiceProfile` ORM model (id, user_id FK, name, audio_sample_path, embedding_path, status, created_at, updated_at, deleted_at)
- [ ] Implement `models/generation.py` — `Generation` ORM model (id, user_id FK, voice_profile_id FK, input_text, output_audio_path, duration_seconds, tts_metadata JSONB, status, created_at)
- [ ] Initialize Alembic: `alembic init backend/alembic`
- [ ] Configure `alembic/env.py` to use `DATABASE_URL` from settings and auto-import all models
- [ ] Generate first migration: `alembic revision --autogenerate -m "initial schema"`
- [ ] Apply migration: `alembic upgrade head`
- [ ] Verify all three tables exist in PostgreSQL with correct columns

### Verification Gateway 1.2
```bash
# Apply migrations
cd backend && alembic upgrade head

# Verify tables in PostgreSQL
sudo docker exec -it $(sudo docker ps -q -f name=db) psql -U clonevoice -d clonevoice -c "\dt"
# Expected output: users, voice_profiles, generations

# Column verification
sudo docker exec -it $(sudo docker ps -q -f name=db) psql -U clonevoice -d clonevoice -c "\d users"
sudo docker exec -it $(sudo docker ps -q -f name=db) psql -U clonevoice -d clonevoice -c "\d voice_profiles"
sudo docker exec -it $(sudo docker ps -q -f name=db) psql -U clonevoice -d clonevoice -c "\d generations"
```

---

## Milestone 1.3 — Authentication: Email/Password + JWT *(🟢 Complete)*

### Tasks
- [ ] Implement `core/security.py`:
  - `hash_password(plain: str) -> str`
  - `verify_password(plain: str, hashed: str) -> bool`
  - `create_access_token(data: dict, expires_delta: timedelta) -> str`
  - `create_refresh_token(data: dict) -> str`
  - `decode_token(token: str) -> dict`
  - `get_current_user(token: str, db: Session) -> User` (FastAPI Depends)
- [ ] Implement `schemas/auth.py`: `SignupRequest`, `LoginRequest`, `TokenResponse`, `UserOut`
- [ ] Implement `api/auth.py`:
  - `POST /api/auth/signup`
  - `POST /api/auth/login` — sets `httpOnly` refresh cookie
  - `POST /api/auth/refresh` — reads refresh cookie, issues new access token
  - `GET /api/auth/me`
- [ ] Register auth router in `main.py` with `GET /health`

### Test Specification — `tests/test_auth.py`
```
test_signup_success              → 201, returns access_token
test_signup_duplicate_email      → 409 Conflict
test_signup_invalid_email        → 422 Unprocessable Entity
test_signup_missing_password     → 422 Unprocessable Entity
test_login_success               → 200, returns access_token + sets refresh cookie
test_login_wrong_password        → 401 Unauthorized
test_login_nonexistent_email     → 401 Unauthorized
test_me_authenticated            → 200, returns UserOut shape
test_me_unauthenticated          → 401 Unauthorized
test_me_expired_token            → 401 Unauthorized
test_refresh_valid_cookie        → 200, returns new access_token
test_refresh_missing_cookie      → 401 Unauthorized
test_health_endpoint             → 200, { "status": "ok" }
```

### Verification Gateway 1.3
```bash
# 1. Run tests from project root
PYTHONPATH=. pytest backend/tests/test_auth.py -v
# All 13 tests must PASS

# 2. In a separate terminal, start the server from project root
# PYTHONPATH=. uvicorn backend.main:app --reload

# 3. Test the endpoints
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Password123!","name":"Test User"}'
# → {"access_token":"...","token_type":"bearer"}

curl http://localhost:8000/health
# → {"status":"ok","version":"1.0.0"}
```

---

## Milestone 1.4 — Authentication: Google OAuth 2.0 *(🟢 Complete)*

### Tasks
- [ ] Register OAuth app in Google Cloud Console — obtain `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`
- [ ] Add to `api/auth.py`:
  - `GET /api/auth/google` — redirect to Google consent screen via Authlib
  - `GET /api/auth/google/callback` — exchange code, fetch profile, upsert user, return JWT
- [ ] Upsert logic: if email exists as `provider='local'`, link OAuth (update provider, avatar_url)
- [ ] If email is new, create user with `provider='google'`, `hashed_password=NULL`

### Test Specification — additions to `tests/test_auth.py`
```
test_google_callback_new_user        → 200, creates user with provider='google'
test_google_callback_existing_local  → 200, links OAuth to existing local account
test_google_callback_invalid_code    → 400 Bad Request
```
> All OAuth tests mock `authlib` token exchange — zero real Google calls.

### Verification Gateway 1.4
```bash
PYTHONPATH=. pytest backend/tests/test_auth.py -v -k "google"
# All OAuth tests PASS with mocked responses
```

---

## Milestone 1.5 — Audio Upload & Librosa Preprocessing *(🔴 Not Started)*

### Tasks
- [ ] Implement `services/audio_processing.py`:
  - `validate_audio_file(file: UploadFile) -> None` — check MIME + file magic bytes + size ≤ `MAX_AUDIO_SIZE_MB`
  - `save_upload(file: UploadFile, user_id: str) -> str` — save to `uploads/<user_id>/<uuid>.wav`
  - `preprocess_audio(file_path: str) -> np.ndarray` — load with librosa, resample to 16kHz, trim silence, peak-normalize
- [ ] Implement `schemas/voice.py`: `VoiceProfileOut`
- [ ] Implement `api/voice.py`:
  - `POST /api/voice/upload` — validate → save → preprocess → store VoiceProfile row → return `VoiceProfileOut`
  - `GET /api/voice/profiles` — list non-deleted profiles for current user
  - `DELETE /api/voice/profiles/{id}` — soft-delete (set `deleted_at = NOW()`)
- [ ] Register voice router in `main.py`

### Test Specification — `tests/test_voice.py`
```
test_upload_valid_wav               → 201, VoiceProfileOut shape
test_upload_valid_mp3               → 201, VoiceProfileOut shape
test_upload_invalid_format_txt      → 422 Unprocessable Entity
test_upload_oversized_file          → 413 Payload Too Large
test_upload_empty_file              → 422 Unprocessable Entity
test_upload_unauthenticated         → 401 Unauthorized
test_list_profiles_empty            → 200, []
test_list_profiles_after_upload     → 200, list with 1 item
test_delete_profile_success         → 200, deleted_at is set in DB
test_delete_profile_not_found       → 404 Not Found
test_delete_profile_wrong_user      → 403 Forbidden
test_librosa_preprocess_shape       → unit test: output.shape == (n_samples,), dtype float32
```

### Verification Gateway 1.5
```bash
# 1. Run tests from project root
PYTHONPATH=. pytest backend/tests/test_voice.py -v

# 2. Start server in a separate terminal if testing manually
# PYTHONPATH=. uvicorn backend.main:app --reload

# 3. Test the endpoints
curl -X POST http://localhost:8000/api/voice/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@tests/fixtures/sample_5sec.wav;type=audio/wav" \
  -F "name=Test Voice"
# → {"id":"...","name":"Test Voice","status":"ready","created_at":"..."}
```

---

## Milestone 1.6 — SV2TTS Inference Pipeline *(🔴 Not Started)*

### Tasks
- [ ] Create `backend/download_weights.py` — script to download Tacotron 2 + WaveRNN weights into `backend/weights/`
- [ ] Implement `services/tts_pipeline.py`:
  - Module-level singletons: `_encoder`, `_synthesizer`, `_vocoder` (loaded once at startup)
  - `load_models(device: str) -> None` — called at FastAPI lifespan startup
  - `embed_speaker(audio: np.ndarray) -> np.ndarray` — 256-dim embedding via `resemblyzer.VoiceEncoder`
  - `synthesize_speech(text: str, embedding: np.ndarray) -> np.ndarray` — Tacotron 2 → mel-spectrogram
  - `vocode(mel: np.ndarray) -> np.ndarray` — WaveRNN → raw waveform
  - `save_output(waveform: np.ndarray, sample_rate: int, user_id: str) -> tuple[str, float]` — write WAV, return `(path, duration_seconds)`
- [ ] Wire `load_models()` into `main.py` FastAPI lifespan context manager

### Test Specification — `tests/test_synthesize.py` (pipeline unit tests)
```
test_embed_speaker_output_shape    → embedding.shape == (256,)
test_save_output_creates_file      → WAV file exists on disk after call
test_save_output_returns_duration  → returned duration > 0.0
```

### Verification Gateway 1.6
```bash
# Standalone smoke test (run from project root)
PYTHONPATH=. python -c "
from backend.services.audio_processing import preprocess_audio
from backend.services.tts_pipeline import embed_speaker
audio = preprocess_audio('backend/tests/fixtures/sample_5sec.wav')
emb = embed_speaker(audio)
assert emb.shape == (256,), f'Got {emb.shape}'
print('Speaker encoder OK:', emb.shape)
"
```

---

## Milestone 1.7 — Synthesis Endpoint *(🔴 Not Started)*

### Tasks
- [ ] Implement `schemas/synthesize.py`: `SynthesizeRequest` (voice_profile_id UUID, text str 1–500 chars), `GenerationOut`
- [ ] Implement `api/synthesize.py`:
  - `POST /api/synthesize` — load embedding → run pipeline → save WAV → create Generation row → return `FileResponse`
  - `GET /api/synthesize/history` — return all Generations for current user, newest first, paginated (limit 50)
- [ ] Input validation: `voice_profile_id` must exist, belong to current user, not be soft-deleted
- [ ] Register synthesize router in `main.py`

### Test Specification — `tests/test_synthesize.py` (integration)
```
test_synthesize_success              → 200, Content-Type: audio/wav (TTS mocked)
test_synthesize_creates_db_row       → generations table has 1 new row after call
test_synthesize_invalid_profile      → 404 Not Found
test_synthesize_wrong_user_profile   → 403 Forbidden
test_synthesize_empty_text           → 422 Unprocessable Entity
test_synthesize_text_too_long        → 422 Unprocessable Entity (>500 chars)
test_synthesize_unauthenticated      → 401 Unauthorized
test_history_empty                   → 200, []
test_history_after_synthesis         → 200, list with 1 GenerationOut
test_history_pagination              → 200, max 50 results returned
```

### Verification Gateway 1.7
```bash
pytest backend/tests/test_synthesize.py -v

# Real end-to-end (30–90s on CPU — requires weights)
curl -X POST http://localhost:8000/api/synthesize \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"voice_profile_id":"<uuid>","text":"Hello, this is a voice cloning test."}' \
  --output test_output.wav
file test_output.wav    # Must report: RIFF (WAV) audio
```

---

## Milestone 1.8 — Remaining Endpoints & Data Integrity *(🔴 Not Started)*

### Tasks
- [ ] Verify `GET /api/synthesize/history` excludes generations from soft-deleted voice profiles
- [ ] Verify soft-delete on voice profile does not expose audio paths in any list endpoint
- [ ] Add `PATCH /api/auth/me` — update user name
- [ ] Confirm all FK constraints are enforced at the DB level
- [ ] Confirm `status='failed'` is correctly set on voice profile if embedding extraction fails

### Verification Gateway 1.8
```bash
pytest backend/tests/ -v
# ALL tests pass — zero failures
```

---

## Milestone 1.9 — Full Test Suite, Hardening ## Milestone 1.9 — Full Test Suite, Hardening & Security Audit *(🔴 Not Started)* Security Audit *(🟢 Complete)*

### Tasks
- [x] Full pytest run — 0 failures, 0 errors
- [x] Security audit checklist:
  - [x] SQL injection: SQLAlchemy ORM used throughout — no raw SQL strings
  - [x] Path traversal: user_id-scoped upload paths, no user-controlled path segments
  - [x] File size enforced BEFORE writing to disk (reject early)
  - [x] MIME type validated via file magic bytes (not just extension)
  - [x] JWT `exp` claim validated on every protected request
  - [x] Refresh token is `httpOnly`, `Secure=True`, `SameSite=Lax`
  - [x] JWT secret is ≥ 32 random bytes
  - [x] bcrypt work factor ≥ 12 rounds
  - [x] No secrets or stack traces exposed to client
  - [x] CORS restricted to `localhost:3000` in development
- [x] Run `black backend/` — zero diffs
- [x] Run `isort backend/` — zero diffs
- [x] All functions have full type hints and one-line docstrings

### Verification Gateway 1.9
```bash
pytest backend/tests/ -v --tb=short
# Expected: ALL PASSED

black --check backend/
isort --check-only backend/
# Expected: zero formatting diffs

git ls-files | grep "\.env$"
# Expected: no output (no .env committed)
```

---

## Milestone 1.10 — Cleanup, Git Hygiene & Final Commit *(🔴 Not Started)*

### Tasks
- [ ] Delete all `__pycache__/` and `*.pyc` from tree
- [ ] Confirm `.gitignore` is catching everything
- [ ] `git status` — only tracked source files
- [ ] Final commit on `main`:
  ```
  feat: Implement Milestone 1.10 — Phase 1 backend complete
  
  Full test suite passes. Auth (email + Google OAuth), voice upload,
  SV2TTS inference, synthesis, and history endpoints operational.
  Security hardened. Zero formatting issues.
  ```
- [ ] Tag release: `git tag v0.1.0-backend && git push --tags`

### Verification Gateway 1.10
```bash
git status             # Clean working tree — nothing untracked
pytest backend/tests/ -v     # ALL PASS
git log --oneline      # All milestone commits visible
```

---

## 🧪 Test Fixtures

| Fixture | Path | Purpose | How to Generate |
|---|---|---|---|
| `sample_5sec.wav` | `tests/fixtures/sample_5sec.wav` | Valid audio for upload and embedding tests | `python -c "import soundfile as sf; import numpy as np; sf.write('...', np.sin(2*np.pi*440*np.linspace(0,5,80000)).astype(np.float32), 16000)"` |
| `sample_invalid.txt` | `tests/fixtures/sample_invalid.txt` | Format validation test | Any text file |

> `sample_oversized.wav` is generated on-demand inside the pytest fixture using `io.BytesIO` — not stored on disk.

---

## ✅ Phase 1 Completion Criteria

Phase 1 is **complete** only when ALL of the following are true:

- [ ] All 10 milestones marked ✅ in progress tracker above
- [ ] `pytest backend/tests/ -v` → **0 failed, 0 errors**
- [ ] `black --check backend/` → **no diffs**
- [ ] `isort --check-only backend/` → **no diffs**
- [ ] `git ls-files | grep ".env"` → **no output**
- [ ] `GET /health` → `{ "status": "ok" }`
- [ ] Full end-to-end manual test: signup → upload audio → synthesize → download WAV ✅
- [ ] Tag `v0.1.0-backend` pushed to GitHub

Only after this is complete will Phase 2 (Frontend) planning begin.

---

*Plan Version: 1.1 — Updated 2026-09-02*
*Milestone 1.10 status: 🟡 In Progress*

