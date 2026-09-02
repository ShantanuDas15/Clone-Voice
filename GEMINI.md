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
- `DATABASE_DESIGN.md` — Production-grade database schema, table definitions, ER diagram
- `PHASE_X_PLAN.md` — Active development phase tracking

---

## 2. Development Order — MANDATORY

> **THE BACKEND MUST BE FULLY IMPLEMENTED, VALIDATED, TESTED, AND HARDENED BEFORE ANY FRONTEND WORK BEGINS.**

This is a hard rule. No Next.js component, no frontend route, no UI code is to be written until:
1. All backend API endpoints are implemented and passing tests.
2. The database schema is migrated and verified.
3. Authentication (JWT/OAuth handling on backend) is confirmed working.
4. The SV2TTS audio processing and inference pipeline is tested end-to-end.
5. All backend tests pass cleanly with zero errors.

---

## 3. Industry-Grade Implementation Workflow (SOP)

Whenever executing a milestone or sub-task, YOU MUST strictly follow this standard operating procedure:

### Phase 3.1 — Initialization & Branching
- Review the active `PHASE_X_PLAN.md` to understand the exact scope and constraints.
- Ensure the working tree is clean.
- Create and checkout a feature branch for the milestone (e.g., `git checkout -b feat/1.2-database-setup`).

### Phase 3.2 — Implementation & Linting
- Implement code adhering strictly to `PEP 8`.
- Format code immediately after writing: run `black backend/` and `isort backend/`.
- Ensure all functions include Python type hints and one-line docstrings.
- No hardcoded secrets. Rely solely on Pydantic Settings and `.env`.

### Phase 3.3 — Verification & Testing (Zero-Error Tolerance)
- Run the relevant `pytest` suite.
- **CRITICAL**: Do NOT proceed to commit if a single test fails, warns, or errors out. Fix it immediately.
- Run the manual Verification Gateway (e.g., `curl` commands) specified in the Phase Plan.

### Phase 3.4 — Environment Scrubbing
- Before staging, ensure no `.env` files, `.DS_Store`, `__pycache__`, or `*.pyc` files exist in the git index.
- Ensure large binary models (`weights/`) and local `uploads/` or `outputs/` are appropriately gitignored.

### Phase 3.5 — Conventional Commits & Pushing
- Stage verified files: `git add .`
- Commit using the **Conventional Commits** format:
  `feat|fix|chore(scope): [Milestone X.X] <Subject>`
  *Example:* `feat(db): [Milestone 1.2] Implement SQLAlchemy ORM models and Alembic`
- Push to the remote repository: `git push -u origin <branch-name>` (or `main` if directly integrating).

### Phase 3.6 — Plan Synchronization
- Open the relevant Phase Plan markdown file.
- Mark the completed tasks with `[x]`.
- Append the exact commit hash (via `git rev-parse --short HEAD`) to the milestone's tracker table.
- Update the document's top-level Status and Last Reviewed date.
- Commit the plan update separately: `git commit -am "docs: Update phase plan for Milestone X.X" && git push`.

---

## 4. Phase Plan Generation & Test Design Standards

When generating, drafting, or updating any Phase Development Plan, YOU MUST adhere to all of the following:

### 4.1 Structured & Professional Test Design
Every milestone MUST include explicitly defined test specifications covering:
- **Unit tests**: Individual functions and service methods in isolation.
- **Integration tests**: API endpoint behaviour with an in-memory SQLite database.
- **Boundary condition checks**: Edge inputs (empty audio files, oversized WAV files, expired JWTs).
- **API Verification Gateways**: Explicit bash/curl commands to confirm status codes and shapes.

### 4.2 Deployment Safety & Environment Isolation
- Tests MUST NOT call live external services (e.g., real Google OAuth callbacks). Use mocks.
- Tests must be deterministic and leave zero residual state (DB rows, temp `.wav` files).
- Fixtures must be automatically torn down via `pytest` dependencies.

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
├── uploads/                   # Audio sample inputs stored by user_id (gitignored)
├── outputs/                   # Generated SR output audio stored by user_id (gitignored)
└── tests/
    ├── conftest.py            # Shared fixtures: test DB, mock auth, mock TTS
    ├── test_auth.py
    └── test_synthesize.py
```

---

## 6. Database Schema Reference (PostgreSQL)

| Table | Purpose | Keys |
|-------|---------|------|
| `users` | Auth identity | PK: `UUID` |
| `voice_profiles` | Extracted speaker embedding | PK: `UUID`, FK: `user_id` |
| `generations` | Audit trail of synthesized outputs | PK: `UUID`, FKs: `user_id`, `voice_profile_id` |

**Critical schema rules**:
- All PKs are `UUID` strings — never serial integers.
- All tables use `created_at` + `updated_at` audit timestamps.
- Use `deleted_at` for soft deletes — never hard-delete user data.

---

## 7. API Endpoint Contracts

| Method | Path | Auth Required | Description |
|--------|------|:---:|-------------|
| `POST` | `/api/auth/login` | ❌ | Email/password login → returns JWT |
| `POST` | `/api/voice/upload` | ✅ | Upload audio sample(s) → returns new voice profile |
| `GET` | `/api/voice/profiles` | ✅ | List user's voice profiles |
| `POST` | `/api/synthesize` | ✅ | Text + Voice Profile ID → generates and returns audio output |
| `GET` | `/api/synthesize/history`| ✅ | List user's generated audio history |

---

## 8. Environment & Security Rules

- **Never commit `.env`** — it must be in `.gitignore` natively.
- Secrets stored in `.env`: `JWT_SECRET_KEY`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
- Directories containing user PII or massive binaries (`uploads/`, `outputs/`, `weights/`) MUST be gitignored.

---

## 9. Coding Standards

- **Python style**: `PEP 8`, enforced via `black` and `isort`.
- **Type hints**: Mandatory for all function signatures (e.g., `def fn(a: str) -> bool:`).
- **Error handling**: Never let unhandled exceptions propagate. Use FastAPI `HTTPException`.
- **Logging**: Use Python's `logging` module. No `print()` statements in production code.

---

## 10. Git & Repository Hygiene (Strict)

- **Branch Naming**: Use `feat/M.M-<name>`, `fix/<name>`, or `chore/<name>` (e.g., `feat/1.2-orm-models`).
- **Commit Format**: Must adhere to Conventional Commits: `type(scope): Subject`. Max 72 chars for subject.
- **Atomic Commits**: One commit per logical milestone or sub-task. Do not bundle unrelated changes.
- **No Force Pushing**: Never run `git push -f` against `main`.
- **Main Protection**: The `main` branch must always remain deployable. Code only enters `main` when tests pass 100%.
