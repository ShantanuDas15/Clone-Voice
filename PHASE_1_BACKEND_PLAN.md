# CloneVoice — Phase 1: Backend Development Plan

> **Status**: 🔴 NOT STARTED
> **Scope**: Backend only. No frontend code until all milestones in this document are ✅ complete, tested, and committed.
> **Target**: A fully functional, tested, and hardened FastAPI backend with SV2TTS inference, JWT auth, Google OAuth, PostgreSQL persistence, and file I/O — ready to be consumed by any frontend client.

---

## 📋 Progress Tracker

| Milestone | Description | Status | Commit Hash |
|-----------|-------------|--------|-------------|
| 1.1 | Project scaffolding, virtual env, `.gitignore`, `requirements.txt` | 🔴 Not Started | — |
| 1.2 | Core config, database setup, SQLAlchemy models, Alembic migrations | 🔴 Not Started | — |
| 1.3 | Authentication — email/password signup & login (JWT) | 🔴 Not Started | — |
| 1.4 | Authentication — Google OAuth 2.0 backend flow | 🔴 Not Started | — |
| 1.5 | Audio upload endpoint + Librosa preprocessing service | 🔴 Not Started | — |
| 1.6 | SV2TTS inference pipeline integration (Encoder → Synthesizer → Vocoder) | 🔴 Not Started | — |
| 1.7 | Speech synthesis endpoint (`POST /api/synthesize`) | 🔴 Not Started | — |
| 1.8 | History endpoints + soft-delete voice profiles | 🔴 Not Started | — |
| 1.9 | Full test suite (unit + integration) + hardening pass | 🔴 Not Started | — |
| 1.10 | Git hygiene, `.gitignore` audit, final commit & push | 🔴 Not Started | — |

**Legend**: 🔴 Not Started · 🟡 In Progress · 🟢 Complete · ❌ Blocked

---

## 🧱 System Architecture Constraints (Free-Tier / Solo Dev)

| Constraint | Decision |
|---|---|
| No dedicated GPU in dev | SV2TTS inference runs on CPU. GPU toggled via `DEVICE=cuda` env var for production |
| No cloud object storage in v1.0 | Audio files stored on local filesystem under `uploads/` and `outputs/` |
| PostgreSQL locally via Docker | `docker-compose` runs Postgres 15 on `localhost:5432` |
| SQLite for tests | All automated tests use in-memory SQLite — never touch the dev DB |
| No Redis / task queue in v1.0 | Synthesis is synchronous per request. Async queue (Celery + Redis) is Phase 3 |
| Pre-trained weights only | No per-user fine-tuning. SV2TTS speaker encoder generates embeddings from uploaded clips without training |

---

## 📦 Complete Dependency Reference

### Python Version
```
Python 3.11+
```

### `requirements.txt` — Full Specification

```txt
# === Web Framework ===
fastapi==0.111.0
uvicorn[standard]==0.30.1
python-multipart==0.0.9        # File upload support

# === Data Validation ===
pydantic==2.7.1
pydantic-settings==2.3.0       # Settings from .env

# === Database ===
sqlalchemy==2.0.30
alembic==1.13.1
psycopg2-binary==2.9.9         # PostgreSQL adapter
aiosqlite==0.20.0              # Async SQLite for tests

# === Authentication & Security ===
python-jose[cryptography]==3.3.0   # JWT encode/decode
passlib[bcrypt]==1.7.4             # Password hashing
authlib==1.3.1                     # Google OAuth 2.0
httpx==0.27.0                      # HTTP client for OAuth token exchange

# === Audio & ML ===
torch==2.3.0                   # PyTorch (CPU build — no CUDA in dev)
torchaudio==2.3.0
librosa==0.10.2                # Audio loading, mel-spectrogram, feature extraction
numpy==1.26.4
scipy==1.13.1
soundfile==0.12.1              # WAV file I/O
resemblyzer==0.1.4             # Speaker encoder (GE2E) — part of SV2TTS

# === Dev & Testing ===
pytest==8.2.2
pytest-asyncio==0.23.7
httpx==0.27.0                  # AsyncClient for FastAPI TestClient
black==24.4.2                  # Code formatting
isort==5.13.2                  # Import ordering
python-dotenv==1.0.1           # Load .env in dev
```

> **Note on SV2TTS weights**: The Real-Time Voice Cloning repo (`CorentinJ/Real-Time-Voice-Cloning`) provides the Tacotron 2 synthesizer and WaveRNN vocoder. Weights are downloaded separately via the project's `download_weights.py` script and stored under `backend/weights/` (gitignored). `resemblyzer` provides the speaker encoder.

---

## 📁 Backend Directory Structure (Target)

```
backend/
├── main.py                        # FastAPI app entry point
├── api/
│   ├── __init__.py
│   ├── auth.py                    # /api/auth/* routes
│   ├── voice.py                   # /api/voice/* routes
│   └── synthesize.py              # /api/synthesize/* routes
├── core/
│   ├── __init__.py
│   ├── config.py                  # Pydantic Settings — reads .env
│   ├── security.py                # JWT creation/verification, bcrypt hashing
│   └── database.py                # SQLAlchemy engine, session factory, Base
├── models/
│   ├── __init__.py
│   ├── user.py                    # User ORM model
│   ├── voice_profile.py           # VoiceProfile ORM model
│   └── generation.py              # Generation ORM model
├── schemas/
│   ├── __init__.py
│   ├── auth.py                    # Pydantic schemas: SignupRequest, LoginRequest, TokenResponse
│   ├── voice.py                   # VoiceProfileCreate, VoiceProfileOut
│   └── synthesize.py              # SynthesizeRequest, GenerationOut
├── services/
│   ├── __init__.py
│   ├── audio_processing.py        # Librosa pipeline: load → resample → trim → normalize
│   └── tts_pipeline.py            # SV2TTS: embed_speaker(), synthesize_speech()
├── weights/                       # Model weights — GITIGNORED
│   ├── encoder.pt                 # GE2E speaker encoder weights (resemblyzer)
│   ├── synthesizer.pt             # Tacotron 2 weights
│   └── vocoder.pt                 # WaveRNN vocoder weights
├── uploads/                       # User audio uploads — GITIGNORED
├── outputs/                       # Generated speech — GITIGNORED
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Fixtures: test DB, mock JWT, mock TTS pipeline
│   ├── test_auth.py
│   ├── test_voice.py
│   └── test_synthesize.py
├── alembic/
│   ├── env.py
│   └── versions/                  # Migration scripts
├── alembic.ini
├── requirements.txt
├── .env.example                   # Safe to commit — no real secrets
└── .env                           # NEVER COMMITTED
```

---

## 🗄️ Database Schema — Full Specification

> Full DDL to be written in `DATABASE_DESIGN.md`. Summary below for Phase 1 reference.

### `users` table
```sql
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(255),
    avatar_url  TEXT,
    provider    VARCHAR(50) DEFAULT 'local',   -- 'local' | 'google'
    hashed_password TEXT,                       -- NULL for OAuth users
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ                     -- soft delete
);
```

### `voice_profiles` table
```sql
CREATE TABLE voice_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    audio_sample_path   TEXT NOT NULL,          -- path to uploaded WAV
    embedding_path      TEXT NOT NULL,          -- path to saved .npy embedding
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ             -- soft delete
);
```

### `generations` table
```sql
CREATE TABLE generations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    voice_profile_id    UUID NOT NULL REFERENCES voice_profiles(id),
    input_text          TEXT NOT NULL,
    output_audio_path   TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 🌐 API Endpoint Specification

### Health
| Method | Path | Auth | Request Body | Response |
|--------|------|------|---|---|
| `GET` | `/health` | ❌ | — | `{ "status": "ok", "version": "1.0.0" }` |

### Auth
| Method | Path | Auth | Request Body | Response |
|--------|------|------|---|---|
| `POST` | `/api/auth/signup` | ❌ | `{ email, password, name }` | `{ access_token, token_type }` |
| `POST` | `/api/auth/login` | ❌ | `{ email, password }` | `{ access_token, token_type }` |
| `POST` | `/api/auth/refresh` | ❌ (refresh cookie) | — | `{ access_token, token_type }` |
| `GET` | `/api/auth/me` | ✅ | — | `{ id, email, name, avatar_url, provider }` |
| `GET` | `/api/auth/google` | ❌ | — | Redirect to Google consent screen |
| `GET` | `/api/auth/google/callback` | ❌ | OAuth code in query params | `{ access_token, token_type }` |

### Voice Profiles
| Method | Path | Auth | Request Body | Response |
|--------|------|------|---|---|
| `POST` | `/api/voice/upload` | ✅ | `multipart/form-data: file, name` | `VoiceProfileOut` |
| `GET` | `/api/voice/profiles` | ✅ | — | `List[VoiceProfileOut]` |
| `DELETE` | `/api/voice/profiles/{id}` | ✅ | — | `{ "message": "deleted" }` |

### Synthesis
| Method | Path | Auth | Request Body | Response |
|--------|------|------|---|---|
| `POST` | `/api/synthesize` | ✅ | `{ voice_profile_id, text }` | Audio file (WAV) as `FileResponse` |
| `GET` | `/api/synthesize/history` | ✅ | — | `List[GenerationOut]` |

---

## Milestone 1.1 — Project Scaffolding

### Tasks
- [ ] Create `backend/` directory with all subdirectories as specified above
- [ ] Create Python virtual environment: `python3.11 -m venv .venv`
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Create `.gitignore` (see rules below)
- [ ] Create `.env.example` with all required keys (no values)
- [ ] Create `docker-compose.yml` with PostgreSQL 15 service
- [ ] Verify Docker Compose starts cleanly

### `.gitignore` — Required Entries
```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
*.egg-info/

# Environment
.env

# Audio data (user sensitive)
backend/uploads/
backend/outputs/

# ML model weights (large binary files)
backend/weights/

# Database files
*.db
clonevoice_test.db

# macOS
.DS_Store

# IDE
.vscode/
.idea/
```

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

volumes:
  postgres_data:
```

### `.env.example`
```env
# Database
DATABASE_URL=postgresql://clonevoice:clonevoice_dev@localhost:5432/clonevoice

# JWT
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# App
APP_ENV=development
DEVICE=cpu
MAX_AUDIO_SIZE_MB=25
UPLOAD_DIR=uploads
OUTPUT_DIR=outputs
```

### Verification Gateway 1.1
```bash
# Verify Docker Compose
docker-compose up -d db
docker-compose ps   # db service must show "Up"

# Verify Python env
source backend/.venv/bin/activate
python --version    # Must be 3.11.x
pip list | grep fastapi   # Must show fastapi 0.111.x

# Verify gitignore
git status          # .env and uploads/ must NOT appear as untracked
```

---

## Milestone 1.2 — Core Config, Database & ORM Models

### Tasks
- [ ] Implement `core/config.py` — Pydantic `Settings` class loading all `.env` variables
- [ ] Implement `core/database.py` — SQLAlchemy async engine, `SessionLocal`, `Base`, `get_db` dependency
- [ ] Implement `models/user.py` — `User` ORM model matching schema above
- [ ] Implement `models/voice_profile.py` — `VoiceProfile` ORM model
- [ ] Implement `models/generation.py` — `Generation` ORM model
- [ ] Initialize Alembic: `alembic init alembic`
- [ ] Configure `alembic/env.py` to use `DATABASE_URL` from settings and import all models
- [ ] Generate and run first migration: `alembic revision --autogenerate -m "initial schema"`
- [ ] Apply migration: `alembic upgrade head`
- [ ] Verify all three tables exist in PostgreSQL

### Verification Gateway 1.2
```bash
# Run migration
alembic upgrade head

# Verify tables
docker exec -it <db_container> psql -U clonevoice -d clonevoice -c "\dt"
# Expected: users, voice_profiles, generations

# Column check
docker exec -it <db_container> psql -U clonevoice -d clonevoice -c "\d users"
```

---

## Milestone 1.3 — Authentication: Email/Password + JWT

### Tasks
- [ ] Implement `core/security.py`:
  - `hash_password(plain: str) -> str`
  - `verify_password(plain: str, hashed: str) -> bool`
  - `create_access_token(data: dict, expires_delta: timedelta) -> str`
  - `create_refresh_token(data: dict) -> str`
  - `decode_token(token: str) -> dict`
  - `get_current_user(token: str, db: Session) -> User` (FastAPI dependency)
- [ ] Implement `schemas/auth.py`: `SignupRequest`, `LoginRequest`, `TokenResponse`, `UserOut`
- [ ] Implement `api/auth.py`:
  - `POST /api/auth/signup` — create user, return access token
  - `POST /api/auth/login` — verify credentials, return access token + set refresh cookie
  - `POST /api/auth/refresh` — read refresh cookie, return new access token
  - `GET /api/auth/me` — return current user profile
- [ ] Register auth router in `main.py`
- [ ] Implement `GET /health` in `main.py`

### Unit Tests — `tests/test_auth.py`
```python
# test_signup_success            → 201, returns access_token
# test_signup_duplicate_email    → 409 Conflict
# test_signup_invalid_email      → 422 Unprocessable Entity
# test_signup_short_password     → 422 Unprocessable Entity
# test_login_success             → 200, returns access_token
# test_login_wrong_password      → 401 Unauthorized
# test_login_nonexistent_email   → 401 Unauthorized
# test_me_authenticated          → 200, returns user profile
# test_me_unauthenticated        → 401 Unauthorized
# test_me_expired_token          → 401 Unauthorized
# test_refresh_valid_cookie      → 200, returns new access_token
# test_refresh_no_cookie         → 401 Unauthorized
```

### Verification Gateway 1.3
```bash
# Run auth tests
pytest backend/tests/test_auth.py -v

# Manual curl verification
curl -X POST http://localhost:8000/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Password123!","name":"Test User"}'
# Expected: {"access_token": "...", "token_type": "bearer"}

curl -X GET http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <token_from_above>"
# Expected: {"id":"...","email":"test@example.com","name":"Test User","provider":"local"}

curl -X GET http://localhost:8000/health
# Expected: {"status":"ok","version":"1.0.0"}
```

---

## Milestone 1.4 — Authentication: Google OAuth 2.0

### Tasks
- [ ] Register OAuth app in Google Cloud Console, obtain `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`
- [ ] Implement in `api/auth.py`:
  - `GET /api/auth/google` — redirect to Google consent screen using `authlib`
  - `GET /api/auth/google/callback` — exchange code for token, fetch user profile, upsert user in DB, return JWT
- [ ] Upsert logic: if email already exists as `provider=local`, link OAuth (set `provider=google`, store `avatar_url`)
- [ ] Store Google `avatar_url` and `name` on the user record

### Unit Tests — additions to `tests/test_auth.py`
```python
# test_google_callback_new_user       → 200, creates user with provider=google
# test_google_callback_existing_user  → 200, links OAuth to existing account
# test_google_callback_invalid_code   → 400 Bad Request (mocked OAuth failure)
```
> All OAuth tests mock the `authlib` token exchange — no real Google calls.

### Verification Gateway 1.4
```bash
pytest backend/tests/test_auth.py -v -k "google"
# All Google OAuth tests must pass with mocked responses
```

---

## Milestone 1.5 — Audio Upload & Librosa Preprocessing

### Tasks
- [ ] Implement `services/audio_processing.py`:
  - `preprocess_audio(file_path: str) -> np.ndarray` — load WAV/MP3 with librosa, resample to 16kHz, trim silence, peak-normalize
  - `validate_audio_file(file: UploadFile) -> None` — check MIME type (audio/wav, audio/mpeg, audio/ogg), check file size ≤ `MAX_AUDIO_SIZE_MB`
  - `save_upload(file: UploadFile, user_id: str) -> str` — save to `uploads/<user_id>/<uuid>.wav`
- [ ] Implement `schemas/voice.py`: `VoiceProfileOut`
- [ ] Implement `api/voice.py`:
  - `POST /api/voice/upload` — validate, save, preprocess, store VoiceProfile row, return `VoiceProfileOut`
  - `GET /api/voice/profiles` — return all non-deleted profiles for current user
  - `DELETE /api/voice/profiles/{id}` — soft-delete (set `deleted_at`)
- [ ] Register voice router in `main.py`

### Unit Tests — `tests/test_voice.py`
```python
# test_upload_valid_wav               → 201, returns VoiceProfileOut
# test_upload_valid_mp3               → 201, returns VoiceProfileOut
# test_upload_invalid_format_txt      → 422 Unprocessable Entity
# test_upload_oversized_file          → 413 Payload Too Large
# test_upload_empty_file              → 422 Unprocessable Entity
# test_upload_unauthenticated         → 401 Unauthorized
# test_list_profiles_empty            → 200, returns []
# test_list_profiles_after_upload     → 200, returns list with 1 item
# test_delete_profile_success         → 200, sets deleted_at
# test_delete_profile_not_found       → 404 Not Found
# test_delete_profile_wrong_user      → 403 Forbidden
# test_librosa_preprocess_unit        → unit test on preprocess_audio() with a synthetic WAV
```

### Verification Gateway 1.5
```bash
pytest backend/tests/test_voice.py -v

# Manual curl
curl -X POST http://localhost:8000/api/voice/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@sample_audio.wav" \
  -F "name=My Voice"
# Expected: {"id":"...","name":"My Voice","created_at":"..."}
```

---

## Milestone 1.6 — SV2TTS Inference Pipeline

### Tasks
- [ ] Download pre-trained weights:
  - Speaker encoder: `resemblyzer` provides this automatically via `VoiceEncoder()`
  - Synthesizer: `synthesizer.pt` from Real-Time Voice Cloning repo
  - Vocoder: `vocoder.pt` from Real-Time Voice Cloning repo
- [ ] Create `backend/download_weights.py` — a one-time script to download and place weights in `backend/weights/`
- [ ] Implement `services/tts_pipeline.py`:
  - Model singletons loaded at FastAPI lifespan startup (not per-request)
  - `embed_speaker(audio: np.ndarray) -> np.ndarray` — returns 256-dim embedding using `resemblyzer.VoiceEncoder`
  - `synthesize_speech(text: str, embedding: np.ndarray) -> np.ndarray` — Tacotron 2 forward pass → mel-spectrogram
  - `vocode(mel: np.ndarray) -> np.ndarray` — WaveRNN/vocoder forward pass → raw waveform
  - `save_output(waveform: np.ndarray, user_id: str) -> str` — write WAV to `outputs/<user_id>/<uuid>.wav`
- [ ] Wire lifespan model loading into `main.py`

### Unit Tests — `tests/test_synthesize.py` (partial — TTS mocked)
```python
# test_embed_speaker_shape    → embedding.shape == (256,)  [uses a real 3-sec synthetic WAV]
# test_save_output_creates_file → output WAV file exists on disk after save_output()
```
> Full inference is mocked in integration tests — only the embedding shape and file I/O are tested with real calls.

### Verification Gateway 1.6
```bash
# Standalone pipeline smoke test
python -c "
from backend.services.audio_processing import preprocess_audio
from backend.services.tts_pipeline import embed_speaker
import numpy as np
audio = preprocess_audio('tests/fixtures/sample_5sec.wav')
emb = embed_speaker(audio)
assert emb.shape == (256,), f'Expected (256,), got {emb.shape}'
print('Speaker encoder OK:', emb.shape)
"
```

---

## Milestone 1.7 — Synthesis Endpoint

### Tasks
- [ ] Implement `schemas/synthesize.py`: `SynthesizeRequest`, `GenerationOut`
- [ ] Implement `api/synthesize.py`:
  - `POST /api/synthesize` — load embedding from `voice_profile.embedding_path`, run full TTS pipeline, save WAV, create `Generation` row, return `FileResponse`
  - `GET /api/synthesize/history` — return all `Generation` rows for current user (newest first)
- [ ] Add input validation: `text` must be 1–500 characters, `voice_profile_id` must exist and belong to current user
- [ ] Register synthesize router in `main.py`

### Integration Tests — `tests/test_synthesize.py`
```python
# test_synthesize_success              → 200, returns audio/wav Content-Type (TTS mocked)
# test_synthesize_saves_generation_row → DB has 1 row in generations after call
# test_synthesize_invalid_profile_id   → 404 Not Found
# test_synthesize_wrong_user_profile   → 403 Forbidden
# test_synthesize_empty_text           → 422 Unprocessable Entity
# test_synthesize_text_too_long        → 422 Unprocessable Entity (>500 chars)
# test_synthesize_unauthenticated      → 401 Unauthorized
# test_history_empty                   → 200, returns []
# test_history_after_synthesis         → 200, returns list with 1 GenerationOut
```

### Verification Gateway 1.7
```bash
pytest backend/tests/test_synthesize.py -v

# End-to-end manual test (real inference — takes 10–60s on CPU)
curl -X POST http://localhost:8000/api/synthesize \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"voice_profile_id":"<profile_uuid>","text":"Hello, this is a voice cloning test."}' \
  --output test_output.wav
file test_output.wav   # Must report: RIFF (WAV) audio data
```

---

## Milestone 1.8 — History, Soft-Delete & Remaining Endpoints

### Tasks
- [ ] Confirm all soft-delete logic is working correctly across voice profiles
- [ ] Confirm `GET /api/synthesize/history` correctly excludes generations for soft-deleted profiles
- [ ] Confirm `GET /api/auth/me` returns the correct updated user profile after OAuth link
- [ ] Add `PATCH /api/auth/me` endpoint to allow name update

### Verification Gateway 1.8
```bash
pytest backend/tests/ -v
# All tests must pass — zero failures
```

---

## Milestone 1.9 — Full Test Suite, Hardening & Security Audit

### Tasks
- [ ] Run complete test suite — all tests must pass
- [ ] Verify no `.env`, no audio files, no weights leak into `git status`
- [ ] Confirm CORS is correctly configured in `main.py` (only `localhost:3000` allowed in dev)
- [ ] Confirm all endpoints return correct HTTP status codes for all edge cases
- [ ] Confirm bcrypt work factor is ≥ 12 rounds
- [ ] Confirm JWT `exp` claim is validated on every protected request
- [ ] Confirm refresh token is `httpOnly`, `Secure`, `SameSite=Lax`
- [ ] Confirm audio file MIME type validation cannot be bypassed (check file magic bytes, not just extension)
- [ ] Run `black backend/` and `isort backend/` — zero diffs
- [ ] Check all functions have type hints and docstrings

### Hardening Checklist
```
[ ] SQL injection: SQLAlchemy ORM used throughout — no raw SQL strings
[ ] Path traversal: user_id-scoped paths, no user-controlled path components
[ ] File size limit enforced before writing to disk
[ ] JWT secret is ≥ 32 random bytes
[ ] No secrets in logs
[ ] No stack traces exposed to client (FastAPI exception handlers configured)
```

### Verification Gateway 1.9
```bash
# Full test run
pytest backend/tests/ -v --tb=short

# Formatting check
black --check backend/
isort --check-only backend/

# Security: no .env committed
git ls-files | grep "\.env$"   # Must return nothing
```

---

## Milestone 1.10 — Cleanup, Git Hygiene & Final Commit

### Tasks
- [ ] Delete all `__pycache__/`, `*.pyc`, `.pytest_cache/` from tree
- [ ] Delete any temporary test WAV files from `tests/` (keep `tests/fixtures/` synthetics)
- [ ] Confirm `.gitignore` catches everything
- [ ] Run `git status` — only tracked source files should appear
- [ ] Final commit on `feat/phase-1-backend` branch:
  ```
  feat: Implement Milestone 1.10 — Phase 1 backend complete
  
  All endpoints implemented and tested. Full pytest suite passes.
  Auth (email + Google OAuth), voice upload, SV2TTS inference, synthesis,
  and history endpoints operational. Zero hardening issues.
  ```
- [ ] Open PR → merge to `main`
- [ ] Tag release: `git tag v0.1.0-backend`

### Verification Gateway 1.10
```bash
git status          # Clean working tree
git log --oneline   # All milestone commits visible
pytest backend/tests/ -v   # ALL PASS — zero failures, zero errors
```

---

## 🧪 Test Fixtures Required

Place in `backend/tests/fixtures/`:

| Fixture File | Description | How to Generate |
|---|---|---|
| `sample_5sec.wav` | 5-second synthetic sine-wave WAV at 16kHz | `python -c "import soundfile as sf; import numpy as np; sf.write('sample_5sec.wav', np.sin(2*np.pi*440*np.linspace(0,5,80000)), 16000)"` |
| `sample_oversized.wav` | 30MB+ WAV file to test size limit | `dd if=/dev/zero bs=1M count=30 > sample_oversized.wav` |
| `sample_invalid.txt` | Text file with `.txt` extension to test format validation | Any text file |

> All fixtures are committed to `tests/fixtures/` except `sample_oversized.wav` (generate on demand in test setup).

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

## 📌 Phase 1 Completion Criteria

Phase 1 is **complete** only when ALL of the following are true:

- [ ] All 10 milestones are marked ✅ in the progress tracker above
- [ ] `pytest backend/tests/ -v` shows **0 failed, 0 errors**
- [ ] `black --check backend/` and `isort --check-only backend/` show **no diffs**
- [ ] `git ls-files | grep ".env"` returns **nothing**
- [ ] `GET /health` returns `{ "status": "ok" }`
- [ ] Full end-to-end curl test: signup → upload audio → synthesize → download WAV ✅
- [ ] Final commit tagged `v0.1.0-backend` and pushed to GitHub

Only after this checklist is complete will Phase 2 (Frontend) planning begin.

---

*Plan Version: 1.0 — September 2026*
*Last Updated: Milestone 1.1 — Not Started*
