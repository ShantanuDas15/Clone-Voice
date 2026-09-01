# CloneVoice — Agent Rulebook & Permanent Memory

> This file is the single source of truth for every AI session working in this repository.
> All rules defined here are **mandatory and non-negotiable** and override any general default agent behaviour.

---

## 1. Project Context

**Project**: CloneVoice — AI-Powered Voice Cloning Web Application
**Domain**: Deep Generative Models · Speech Synthesis · Full-Stack Web Development
**Stack**: Next.js 14 + Tailwind CSS + NextAuth (Frontend) · FastAPI + PyTorch + Python 3.11 (Backend) · PostgreSQL · SQLAlchemy
**AI Models**: SV2TTS (Real-Time Voice Cloning) architecture (Speaker Encoder, Tacotron 2 Synthesizer, WaveRNN/HiFi-GAN Vocoder)

**Key Reference Documents** (read before planning any implementation):
- `project_description.md` — Full project description, features, and tech stack
- `DATABASE_DESIGN.md` (to be created) — Production-grade database schema, table definitions, ER diagram, index strategy

---

## 2. Development Order — MANDATORY

> **THE BACKEND MUST BE FULLY IMPLEMENTED, VALIDATED, TESTED, AND HARDENED BEFORE ANY FRONTEND WORK BEGINS.**

This is a hard rule. No Next.js component, no frontend route, no UI code is to be written until:
1. All backend API endpoints are implemented and passing tests.
2. The database schema is migrated and verified.
3. Authentication (JWT/OAuth handling on backend) is confirmed working.
4. The SV2TTS audio processing and inference pipeline is tested end-to-end.
5. All backend tests pass cleanly with zero errors.

If asked to implement a frontend feature before the backend is complete and validated — **decline and redirect** to the pending backend milestone.

---

## 3. Core Implementation Workflow

Whenever any feature, milestone, or sub-task from any phase plan is executed, YOU MUST follow this exact sequence without exception:

### Step 1 — Implement
- Write code strictly as specified in the milestone or phase plan documentation.
- Follow the project's established directory structure (`backend/api/`, `backend/services/`, `backend/models/`, etc.).
- Do not introduce new dependencies without updating `requirements.txt` or `package.json`.
- Never hardcode secrets, credentials, or file paths — use `.env`.

### Step 2 — Verify, Validate & Test
- Execute the **Verification Gateway** or test instructions specified in the phase plan for that milestone.
- If no test instructions exist in the plan, YOU MUST ask for permission before generating new test cases.
- Run all tests via the terminal. Do **not** assume tests pass — confirm with actual command output.
- Tests must cover: happy path, error cases, edge cases, and security boundary conditions (e.g. unauthenticated requests, oversized audio inputs, wrong formats).

### Step 3 — Clean & Isolate
Before any `git` operation, scrub the repository of:
- `__pycache__/` directories anywhere in the tree
- `.pytest_cache/` outside of `backend/`
- `*.pyc` compiled Python files
- `.DS_Store` files (macOS artefacts)
- Temporary test scripts, dummy audio files, or generated test WAVs
- Any `.env` file (must never be committed)

Verify `.gitignore` is correctly catching all of the above.

### Step 4 — Commit & Push
- **ONLY** commit if all tests pass and the directory is clean.
- Use the following commit message format:
  ```
  feat: Implement Milestone X.X — <short description>
  
  <Optional body: key decisions, what was tested, known limitations>
  ```
- Push to the GitHub remote after every successful milestone commit.

### Step 5 — Track Progress
- After a successful commit, update the relevant phase plan markdown file (e.g. `PHASE_1_BACKEND_PLAN.md`) by:
  - Checking off completed tasks (`[ ]` → `[x]`)
  - Appending the exact commit hash to the milestone's status log entry

---

## 4. Phase Plan Generation & Test Design Standards

When generating, drafting, or updating any Phase Development Plan or milestone specification, YOU MUST adhere to all of the following:

### 4.1 Structured & Professional Test Design
Every milestone MUST include explicitly defined test specifications covering:
- **Unit tests**: Individual functions and service methods in isolation (e.g., Librosa preprocessing).
- **Integration tests**: API endpoint behaviour with a real (in-memory) database.
- **Boundary condition checks**: Edge inputs (empty audio files, oversized WAV files, wrong format, expired JWT tokens).
- **API Verification Gateways**: `curl` or `pytest` commands that confirm the endpoint returns the exact expected status code and response shape.

### 4.2 Deployment Safety & Zero Error Guarantee
- Tests MUST NOT call live external services (e.g., real Google OAuth callbacks).
- Use **mocks and stubs** for: OAuth tokens, SV2TTS model inference on large clips, filesystem I/O.
- Tests must be deterministic — the same test run must always produce the same result.
- No test should leave residual state (DB rows, temp `.wav` files) that affects subsequent test runs.

### 4.3 Fixture Scrubbing & Environment Isolation
- All test fixtures (temp DB, temp uploaded audio, mock generated WAV files) must be torn down automatically in `teardown` / `pytest` fixtures.
- Use a **separate SQLite test database** (e.g. `clonevoice_test.db` or in-memory `sqlite://`) — never run tests against the development or production database.

---

## 5. Backend Architecture Reference

```
backend/
├── main.py                    # FastAPI app, lifespan, CORS, router registration
├── api/
│   ├── auth.py                # POST /api/auth/login, /api/auth/signup
│   ├── voice.py               # POST /api/voice/upload, GET /api/voice/profiles
│   └── synthesize.py          # POST /api/synthesize, GET /api/synthesize/history
├── services/
│   ├── tts_pipeline.py        # SV2TTS inference (Encoder, Synthesizer, Vocoder)
│   └── audio_processing.py    # Librosa preprocessing (resample, trim, normalize)
├── models/
│   └── database.py            # SQLAlchemy ORM models (User, VoiceProfile, Generation)
├── core/
│   ├── security.py            # JWT and password hashing
│   └── config.py              # Environment variable management
├── weights/                   # Pre-trained model weights (gitignored if >100MB)
│   ├── encoder.pt
│   ├── synthesizer.pt
│   └── vocoder.pt
├── uploads/                   # Audio sample inputs stored by user_id (gitignored)
├── outputs/                   # Generated SR output audio stored by user_id (gitignored)
├── tests/
│   ├── conftest.py            # Shared fixtures: test DB, mock auth, mock TTS
│   ├── test_auth.py
│   ├── test_voice.py
│   └── test_synthesize.py
├── requirements.txt
└── .env                       # Never committed — contains JWT Secret, DB URL, OAuth keys
```

---

## 6. Database Schema Reference

Three core tables for v1.0. Full specification to be detailed in `DATABASE_DESIGN.md`.

| Table | Purpose |
|-------|---------|
| `users` | Local projection of user account (Email/Password or OAuth). |
| `voice_profiles` | One row per extracted speaker embedding. Links to the uploaded source audio. |
| `generations` | Audit trail and history of all generated text-to-speech outputs. |

**Critical schema rules**:
- All PKs are `UUID` strings — never serial integers.
- All tables use `created_at` + `updated_at` audit timestamps.
- Use `deleted_at` for soft deletes — never hard-delete user data or voice profiles.

---

## 7. API Endpoint Contracts

| Method | Path | Auth Required | Description |
|--------|------|:---:|-------------|
| `POST` | `/api/auth/login` | ❌ | Email/password login → returns JWT |
| `POST` | `/api/voice/upload` | ✅ | Upload audio sample(s) → returns new voice profile |
| `GET` | `/api/voice/profiles` | ✅ | List user's voice profiles |
| `POST` | `/api/synthesize` | ✅ | Text + Voice Profile ID → generates and returns audio output |
| `GET` | `/api/synthesize/history`| ✅ | List user's generated audio history |
| `GET` | `/health` | ❌ | Liveness check — returns `{ "status": "ok" }` |

All protected endpoints must validate the JWT token via dependency injection.

---

## 8. Environment & Security Rules

- **Never commit `.env`** — it must be in `.gitignore` before the first commit.
- Secrets stored in `.env`: `JWT_SECRET_KEY`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
- The `uploads/` and `outputs/` directories must be gitignored — they contain sensitive user audio data.
- The `weights/` directory must not be committed to Git if files exceed 100MB (use Git LFS or external download scripts).

---

## 9. Coding Standards

- **Python style**: PEP 8. Use `black` for formatting, `isort` for import ordering.
- **Type hints**: All function signatures must use Python type hints.
- **Docstrings**: All service methods and router handlers must have a one-line docstring.
- **Error handling**: Never let unhandled exceptions propagate to the client. Use FastAPI `HTTPException` with appropriate status codes.
- **Logging**: Use Python's `logging` module (not `print`). Log at `INFO` for normal flow, `ERROR` for exceptions.
- **No global mutable state** except the TTS model singletons (loaded once at lifespan startup).

---

## 10. Git & Repository Hygiene

- **Branch strategy**: `main` is the stable branch. Feature work on `feat/<milestone-name>` branches. Merge only after tests pass.
- **`.gitignore` must include**: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.DS_Store`, `.env`, `uploads/`, `outputs/`, `*.db`, `clonevoice_test.db`, `weights/`.
- **Commit atomically**: One commit per completed milestone — not per file save.
- **Never force-push** to `main`.
