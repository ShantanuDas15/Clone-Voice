# CloneVoice — Agent Rulebook & Permanent Memory

> This file is the single source of truth for every AI session working in this repository.
> All rules defined here are **mandatory and non-negotiable** and override any general default agent behaviour.

---

## 0. Attribution — MANDATORY

- Do **not** add any Claude/Claude Code attribution to git commits or pull requests —
  no `Co-Authored-By: Claude ...` trailer, no `Claude-Session:` line, and no
  "🤖 Generated with Claude Code" footer in PR descriptions.
- Commit and push using the repository's configured git user only. Claude must never
  appear as a contributor/author/co-author on any commit or PR in this repository.

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
- Do NOT add any Claude/Claude Code attribution trailer or footer (see Section 0).
- Push to the remote repository: `git push -u origin <branch-name>` (or `main` if directly integrating).

### Phase 3.6 — Plan Synchronization
- Open the relevant Phase Plan markdown file.
- Mark the completed tasks with `[x]`.
- Append the exact commit hash (via `git rev-parse --short HEAD`) to the milestone's tracker table.
- Update the document's top-level Status and Last Reviewed date.
- Commit the plan update separately: `git commit -am "docs: Update phase plan for Milestone X.X" && git push`.

### Phase 3.7 — Merge to Main — MANDATORY
- `main` is protected (**Include administrators** is on): the required checks `check`, `perf` and `visual` must pass and a direct `git push origin main` is rejected. Everything reaches `main` through a pull request. Never bypass the protection, switch it off, or force-push to get around it.
- **After an implementation is complete and verified** (Phase 3.3 tests pass with zero errors, and the plan-sync commit from Phase 3.6 is pushed to the feature branch), open and merge the pull request in the same session — do not leave the branch unmerged, waiting on a separate step.
- Open it with `gh pr create --base main --head <feature-branch>` (title in the Conventional Commits format; **no Claude/AI attribution** in the title or body, see Section 0). Wait for the checks (`gh pr checks <n> --watch`).
- A red check is a finding, not an obstacle: read its log (`gh run view <id> --log-failed`), fix the cause on the branch, push, and wait again. Do not re-run until green without understanding why it failed; do not weaken a check to make it pass.
- Merge with `gh pr merge <n> --merge --delete-branch` (a merge commit, as before). If other work merged first and there are conflicts (e.g. in `HARDENING_PLAN.md`/`PHASE_X_PLAN.md` when milestones touched adjacent rows), resolve them on the branch, preserving every merged branch's resolved findings — never silently drop one side's fix.
- Afterwards `git checkout main && git pull --ff-only origin main`, re-run the full test suite on `main` (zero-error tolerance still applies), and confirm the `main` workflow run is green. Delete any leftover local branch (`git branch -d <feature-branch>`).
- A change that touches only the backend or only docs still gets the frontend checks (the workflow has no path filter, by design).
- This applies to every implementation going forward — not just when the user explicitly asks for a merge.

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
│   ├── auth.py                # /api/v1/auth/* (signup, login, refresh, logout, me, email, Google)
│   ├── voice.py               # /api/v1/voice/* (upload, profiles)
│   └── synthesize.py          # /api/v1/synthesize (+ history, past-audio download)
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
| `POST` | `/api/v1/auth/signup` | ❌ | Register with email + password |
| `POST` | `/api/v1/auth/login` | ❌ | Email/password login → access JWT + httpOnly refresh cookie |
| `POST` | `/api/v1/auth/refresh` | ❌ (cookie) | Rotate the refresh cookie, return a new access token |
| `POST` | `/api/v1/auth/logout` | ❌ (cookie) | Revoke the refresh token |
| `GET` / `PATCH` / `DELETE` | `/api/v1/auth/me` | ✅ | Current user / rename / delete account (password in body) |
| `POST` | `/api/v1/auth/verify-email`, `/resend-verification` | ❌ / ✅ | Email verification |
| `POST` | `/api/v1/auth/forgot-password`, `/reset-password` | ❌ | Password reset by emailed single-use token |
| `GET` | `/api/v1/auth/google`, `/google/callback` | ❌ | Google OAuth |
| `GET` | `/api/v1/terms` | ❌ | Current voice-consent terms (version, text) |
| `POST` | `/api/v1/voice/upload` | ✅ | Upload an audio sample (+ `consent_confirmed=true`) → new voice profile |
| `GET` | `/api/v1/voice/profiles` | ✅ | List user's voice profiles |
| `DELETE` | `/api/v1/voice/profiles/{profile_id}` | ✅ | Soft-delete a voice profile |
| `POST` | `/api/v1/synthesize` | ✅ | Text + Voice Profile ID → generates and returns audio output |
| `GET` | `/api/v1/synthesize/history` | ✅ | List user's generated audio history (`limit`/`offset`, `X-Total-Count`) |
| `GET` | `/api/v1/synthesize/{generation_id}/audio` | ✅ | Download a past generation's WAV (404 / 410 expired) |
| `GET` | `/health`, `/health/live`, `/health/ready` | ❌ | Liveness / readiness (outside `/api/v1`) |

The authoritative list is the generated OpenAPI snapshot, `frontend/contract/openapi.json`
(refresh with `python -m backend.export_openapi`; a backend test fails when it is stale).

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
- **No AI Attribution**: Never add Claude/AI co-author trailers, session links, or "Generated with" footers to commits or PRs (see Section 0).

---

## 11. Knowledge Graph (Graphify) — Planning & Impact Analysis

- `graphify-out/` (gitignored, derived) holds a map of the code **and** these docs.
  Read `graphify-out/GRAPH_REPORT.md` and run `graphify query "<question>"` /
  `graphify path "A" "B"` / `graphify explain "X"` **before planning any feature**, to
  list every module, test, doc and hardening finding the change touches.
- The graph shows structure, not proof: it never replaces the test suite (§3.3), and
  `HARDENING_PLAN.md` remains the source of truth for what is fixed vs. unverified.
- Keep it fresh: the git post-commit hook re-extracts changed **code**. After changing
  `*.md` docs (plans, this file), run `/graphify --update` to refresh the semantic part.
- **Blind spots — open these directly, the graph does not parse their contents:**
  `backend/Dockerfile`, `docker-compose.yml`, `.env.example`, `backend/.env.example`,
  `backend/alembic.ini`, `backend/requirements*.txt`, `backend/weights_manifest.json`,
  `.gitignore`/`.dockerignore`, and individual `Settings` attributes in `core/config.py`.
  Any change touching config, deploy or dependencies must check these by hand.
- `.graphifyignore` excludes `.venv/`, `weights/`, `uploads/`, `outputs/`. Never remove
  those entries; they keep user audio and multi-GB dependencies out of the graph.
