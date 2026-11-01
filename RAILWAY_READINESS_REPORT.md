# CloneVoice — Railway Readiness & Security Report

> **Audit date:** 2026-11-01 · **Method:** read-only static audit plus dependency-audit tooling · **Author:** automated audit (Claude Code)
> **State audited:** `main` at `7f9a572` (PRs #143-#161 merged). Re-verified on 2026-11-01: runtime `npm audit` 0 vulnerabilities; `pip-audit` on the hash lock clean apart from the 3 accepted advisories; only the three `.env.example` files are tracked (no `.env`, key or certificate files); no private keys or token-pattern secrets in the tree or in history; all three Dockerfiles digest-pinned and non-root. The Findings Register keeps its original wording, with a status table added after it.

> **Update 2026-11-01 (second pass, PRs #148, #149, #157, #158 also merged: F-04, F-10, F-12 resolved):** F-13 (React 19 and `proxy.ts`) was resolved in PR #160; no code items remain. Everything still open is Railway dashboard or staging work.

> **Update 2026-11-01 (after PRs #143-#145 merged to `main`):** F-01 (Next 16, runtime audit 0), F-02 (web service: `frontend/Dockerfile`, `frontend/railway.toml`, runbook section, `frontend-docker-build` CI), F-03 (JS budget raised to 240 KB) and F-05 (HSTS) are resolved. Current verdict: **READY WITH CONDITIONS**. Remaining conditions: F-06 (set `TRUSTED_PROXY_COUNT=1`, add Redis), F-07 (verified email domain), custom domains on one parent domain, and a staging deploy to check the *Unverified* items.

---

## 1. Executive Summary

CloneVoice is a voice-cloning web application: a FastAPI/PyTorch API with PostgreSQL, an optional separate Chatterbox inference worker, and a Next.js web app. The **backend and worker are unusually well prepared for Railway** (Railway-specific entrypoint, config-as-code, pre-deploy migrations, readiness health check, hash-locked dependencies, non-root runtime, and a documented runbook). The original blockers were on the **frontend**: a Next.js version with advisories up to unauthenticated RCE, and no Railway deployment path for the web app. **Both are now fixed on `main`.**

### Overall verdict: **READY WITH CONDITIONS** (was NOT READY at the time of the audit)

The conditions are operational, not code: Railway dashboard setup (domains, variables), a verified email domain, shared rate-limit state, and a staging deploy to check the *Unverified* items. See §9.

| Severity | Found | Resolved on `main` | Open |
|---|:---:|:---:|:---:|
| Critical | 1 | 1 (F-01) | 0 |
| High | 2 | 2 (F-02 in the repo, F-03) | 0 |
| Medium | 5 | 2 (F-04, F-05) | 3 (F-06, F-07, F-08) |
| Low | 8 | 4 (F-09 accepted risk, F-10, F-12, F-13) | 4 (F-11, F-14, F-15, F-16) |
| **Total** | **16** | **9** | **7** |

**Original blockers:** 3 (F-01, F-02, F-03). **All resolved.** The register was first reported as 15 findings; the correct count is 16 (five Medium, not four).

---

## 2. Scope and Method

**Reviewed:** the whole repository: `backend/` (API, services, models, Alembic migrations, tests), `tts_worker/`, `frontend/`, `Dockerfile`s, `railway.toml` files, `.github/workflows/`, `.env.example` files, `.gitignore`/`.dockerignore`, and the existing `RAILWAY_DEPLOYMENT.md` and `CHATTERBOX_RUNBOOK.md`.

**Tooling run:** `pip-audit` (requirements and hash lock), `npm audit` (with and without dev dependencies), a secret-pattern scan of the working tree and of all 952 commits, file-tracking checks for `.env`/key files, and the backend test suite (2151 passed, 1 skipped on `main` at `7f9a572`).

**Could not be verified (marked *Unverified* below):**
- Current Railway platform behavior against docs.railway.com (no live documentation check was made; platform statements here come from the repository's own runbook and should be re-checked before go-live).
- Anything that needs a running Railway project: proxy hop count (`TRUSTED_PROXY_COUNT`), outbound SMTP/Resend behavior, volume ownership, real cold-start timing.
- Contents of git history beyond pattern matches. No token-shaped strings or key/`.env` files were found, but a pattern scan is not proof of absence.
- Line-by-line injection review of every endpoint. Evidence below is from targeted greps and the project's own hardening log (`HARDENING_PLAN.md`), not an independent penetration test.
- Docker image builds locally (no Docker daemon); CI's `backend-docker-build` passes on `main`.

**Assumptions:** deploy target is three Railway services (API, web app, optional worker) plus the Postgres plugin and one volume; custom domains on a shared registrable domain.

---

## 3. Project Profile

| Item | Finding |
|---|---|
| Purpose | Upload a voice sample, derive a speaker embedding, synthesize speech from text |
| Backend | Python 3.11, FastAPI, SQLAlchemy, Alembic, PyTorch (CPU), SV2TTS (encoder, Tacotron 2, WaveRNN) |
| Frontend | Next.js 16.4.3, React 19.3, Tailwind, TanStack Query, zod, axios |
| Worker | Separate FastAPI service in `tts_worker/` (own image, Chatterbox models, bearer-token auth) |
| Start command | `python -m backend.serve` → `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1` (`backend/serve.py`) |
| Data stores | PostgreSQL (psycopg2); volume at `/data` for uploads, outputs, weights; optional Redis for rate limits |
| External services | Google OAuth, Resend/SMTP email, Hugging Face (weights), Sentry (optional) |
| Background work | In-process token/storage pruning; inference behind a semaphore; no WebSockets |
| Migrations | Alembic as Railway `preDeployCommand`; schema-drift guard and readiness check |
| CI/CD | Six GitHub Actions workflows (lint/test/build/visual/perf, schema, dependency audit, Docker builds) |
| Existing platform config | `railway.toml` (API), `tts_worker/railway.toml`, `RAILWAY_DEPLOYMENT.md`, `CHATTERBOX_RUNBOOK.md` |
| Web app platform config | `frontend/Dockerfile`, `frontend/railway.toml`, web app section of `RAILWAY_DEPLOYMENT.md`, `frontend-docker-build` workflow (added in PR #145) |

---

## 4. Readiness Scorecard

| Area | Status | Notes |
|---|:---:|---|
| Build and start | **Pass** | Hash-locked multi-stage build, import smoke test at build time, single CMD (`backend/Dockerfile:20-110`). |
| Platform fit (host/port) | **Pass** | `0.0.0.0` and `$PORT` handled in `backend/serve.py`. |
| Platform fit (filesystem, scaling) | **Warning** | Needs a volume; one instance only (`--workers 1`, process-local limiter). Redeploys incur short downtime. Documented. |
| Configuration | **Pass** | Pydantic Settings; `.env.example` complete; production defaults. Weak/default JWT secret rejected (`core/config.py:527`). |
| Health and observability | **Pass** | `/health/ready` as Railway check (`railway.toml`), JSON logs to stdout, Sentry optional, protected `/metrics`. |
| Database | **Pass** | Alembic pre-deploy, pooling with `pool_pre_ping` (`core/database.py:25`), no create-all/drop-all in app code. TLS to DB **Unverified** (private network). |
| Dependencies (backend) | **Pass** | Both `pip-audit` runs clean apart from accepted `setuptools` advisories (F-09). |
| Dependencies (frontend) | **Pass** | Runtime `npm audit` reports 0 vulnerabilities and is blocking in CI (F-01 fixed). Dev-only advisories remain (F-04). |
| Frontend deployment | **Pass (repo) / Pending (dashboard)** | Dockerfile, `railway.toml`, runbook and CI image build exist (F-02). The Railway service and domains still have to be created. |
| Secrets | **Pass** | `.env`, `frontend/.env.local` ignored and untracked; no secret patterns in tree or history. |
| Auth and authorization | **Pass** | bcrypt (`core/security.py:33`), short-lived access JWT with `jti`, rotating refresh tokens, algorithm pinned (`core/security.py:117`), email verification, soft-delete checks. |
| Input and injection | **Pass (partial)** | ORM queries; magic-byte and type validation, UUID-named uploads (`services/audio_processing.py:92,107`); no `shell=True`/`pickle` in app code; weights checksum-verified before `torch.load`. Deep review **Unverified**. |
| SSRF | **Pass** | Worker URL must be https or a Railway private host (`core/config.py:455-470`). |
| Web hardening: CORS | **Pass** | Exact origins enforced by validator (`core/config.py:507`). |
| Web hardening: cookies | **Pass** | `HttpOnly`, `Secure`, `SameSite=Lax` (`api/auth.py:66-72`). |
| Web hardening: CSRF | **Pass** | No CSRF token; defence in depth: `SameSite=Lax`, JSON bodies, exact-origin CORS, and `X-Requested-With` required on `/auth/refresh` (F-10 fixed, PR #157). |
| Web hardening: headers | **Pass (CSP report-only)** | nosniff/frame/referrer and HSTS on the web app; HSTS and nosniff on the API (F-05 fixed). CSP is report-only until enforced (F-11). |
| Web hardening: rate limiting | **Warning** | Present on auth and synthesis; defaults to in-memory (`core/config.py:115`) and `TRUSTED_PROXY_COUNT=0` (`:119`) unless set (F-06). |
| Exposure | **Pass** | Docs/OpenAPI disabled in production (`main.py:165`); `/metrics` needs token. |
| Data protection | **Pass** | Search-text redaction in access logs (`core/log_redaction.py`); account export/erasure exist. Provider-side email and Sentry data handling **Unverified**. |
| Container | **Pass** | Non-root runtime (uid 1000 / 10001); initial root only to chown the volume, then dropped (`backend/serve.py`). Base images pinned by digest and kept current by Dependabot (F-12 fixed, PRs #149, #158). |

---

## 5. Findings Register

| ID | Severity | Category | Description | Evidence | Recommended fix | Effort |
|---|:---:|---|---|---|---|:---:|
| **F-01** | **Critical** | Supply chain | `next` 14.2.x on `main` has many advisories, including unauthenticated RCE (Image Optimization API, up to 15.5.27), Server Action DoS/SSRF and middleware cache poisoning. No 14.x/15.x release fixes them. | `frontend/package.json:31`; `npm audit --omit=dev` | Merge PR #144 (Next 16.4.3). Runtime audit then reports 0 vulnerabilities. | M (done in PR) |
| **F-02** | **High** | Deployment | Nothing deploys the web app: no Dockerfile/`railway.toml`/runbook. The refresh cookie is `SameSite=Lax`, so web app and API must share a registrable domain. | `frontend/` (no deploy config); `RAILWAY_DEPLOYMENT.md` covers API/worker only; `api/auth.py:66-72` | Add a frontend service (Dockerfile or Railpack), `NEXT_PUBLIC_*` build variables, two custom domains under one parent, and document it. | M |
| **F-03** | **High** | Delivery | PR #144 fails the `perf` budget: public-route JS is 211-227 KB gz against 200 KB because Next 16 is ~30 KB larger. The required check blocks the merge, so F-01 cannot reach `main`. | CI run on PR #144; `frontend/perf/run.mjs` | Decide: raise the JS budget (recommended 240 KB, recorded in the plan) or undertake a client refactor (replace axios with XHR code, move zod to `zod/mini`). | S (budget) / L (refactor) |
| F-04 | Medium | Supply chain | Frontend dev dependencies carry advisories (`vitest`/`tinypool` critical, `vite` high, ESLint plugins). Dev-only: not in the runtime bundle. 33 before, 22 after PR #144. | `npm audit` (full) | Upgrade `vitest` to a patched major in a separate PR; CI audits runtime only. | M |
| F-05 | Medium | Web hardening | No HSTS header on `main`, in the API or the web app. Railway's edge terminates TLS but does not add HSTS. | `frontend/next.config.mjs`, `backend/main.py` (no header) | PR #144 adds `Strict-Transport-Security` to both (`backend/core/security_headers.py`). Consider `includeSubDomains` once all subdomains are HTTPS. | S (done in PR) |
| F-06 | Medium | Platform fit | Rate limiter is in-memory and resets each deploy; `TRUSTED_PROXY_COUNT` defaults to 0, so behind Railway every client could share the edge IP (throttling everyone) or, if mis-set, be spoofable. Proxy hop count is **Unverified**. | `backend/core/config.py:115,119`; `core/rate_limit.py:40` | Set `TRUSTED_PROXY_COUNT=1`, add Redis (`RATE_LIMIT_STORAGE_URI`), and confirm the client IP in staging logs. | S |
| F-07 | Medium | Operations | Email verification is required (default); without a verified sending domain and `RESEND_API_KEY`, no local user can verify, upload or synthesize. | `backend/.env.example` (`REQUIRE_EMAIL_VERIFICATION`, `EMAIL_BACKEND=disabled`) | Verify a sending domain (SPF/DKIM) and set the three email variables before launch. | S |
| F-08 | Medium | Platform fit | Single instance with a volume: redeploys cause brief downtime, and a volume rules out replicas. Weights (~424 MB) download on first boot (up to 10 min health window). | `railway.toml:15-24`; `RAILWAY_DEPLOYMENT.md` | Accept for MVP; plan object storage if scale or zero-downtime is needed. | L |
| F-09 | Low | Supply chain | `setuptools` 79.0.1 carries `PYSEC-2026-3447` and `GHSA-xmj3-9gf7-h52w`, accepted because every patched release lacks `pkg_resources`, which `webrtcvad` imports. No runtime attack surface identified. | `backend/requirements.constraints.txt`; `.github/workflows/backend-audit.yml` | Revisit if `webrtcvad` drops `pkg_resources`. | M |
| F-10 | Low | Web hardening | No CSRF token. Mitigated: `SameSite=Lax` cookie, JSON-only bodies, exact-origin credentialed CORS. | `api/auth.py:66-72`, `main.py:249` | Optionally require a custom header (e.g. `X-Requested-With`) on cookie-authenticated POSTs (`/auth/refresh`). | S |
| F-11 | Low | Web hardening | CSP is report-only until `CSP_ENFORCE=1`. | `frontend/proxy.ts` (was `middleware.ts` before F-13) | Soak in staging, then set `CSP_ENFORCE=1`. | S |
| F-12 | Low | Container | Base images pinned by tag (`python:3.11-slim`), not by digest; builds can drift. | `backend/Dockerfile:20,56`; `tts_worker/Dockerfile:10` | Pin by digest and let Dependabot/Renovate bump it. | S |
| F-13 | Low | Frontend | Next 16 warns React 18 is deprecated (removed in Next 17) and that `middleware.ts` is renamed `proxy.ts`. | `npm run build` output on PR #144 | Plan a React 19 and `proxy.ts` migration. | M |
| F-14 | Low | Container | The container starts as root on Railway (`RAILWAY_RUN_UID=0`) to chown the volume, then drops to uid 1000 before serving. Safe as implemented, but a failure to drop is fatal by design. | `backend/serve.py` (`drop_privileges`) | None; keep the test coverage (`backend/tests/test_serve.py`). | — |
| F-15 | Low | Data protection | Database TLS and provider-side retention (Resend, Sentry, Hugging Face) are **Unverified**. Postgres is reached over Railway's private network. | `DATABASE_URL` reference variable | Confirm private-network URL is used; review provider data-processing terms. | S |
| F-16 | Low | Worker | Worker traffic is plain http on the private network (explicitly allowed for `*.railway.internal` only) with a 32-char bearer token. | `core/config.py:455-470`; `tts_worker/app.py:102` | Keep the worker without a public domain. | — |

### Status of each finding (2026-11-01)

| ID | Status | Notes |
|---|---|---|
| F-01 | **Resolved** | PR #144 |
| F-02 | **Resolved (repo); dashboard pending** | PR #145 |
| F-03 | **Resolved** | Budget 240 KB |
| F-04 | **Resolved** | PR #148: vitest 5, vite 7. Critical/high dev advisories cleared; 16 moderate remain (one accepted `minimatch` ReDoS in the ESLint plugins, FE-SEC2) |
| F-05 | **Resolved** | HSTS on web app and API (PR #144); `includeSubDomains` intentionally not set |
| F-06 | Open | Set `TRUSTED_PROXY_COUNT=1` and add Redis in Railway; defaults are still `0` and `memory://` |
| F-07 | Open | Verified email domain and keys |
| F-08 | Accepted | MVP trade-off |
| F-09 | Accepted | Documented exceptions in `backend-audit.yml` |
| F-10 | **Resolved** | PR #157: `/auth/refresh` answers 403 without `X-Requested-With: XMLHttpRequest` |
| F-11 | Open | Enforce CSP after a staging soak |
| F-12 | **Resolved** | PRs #149, #158: all three Dockerfiles pin base images by digest; Dependabot refreshes digests and patches, and ignores Python minor and Node major bumps |
| F-13 | **Resolved** | React 19.3 and `proxy.ts` (FE-SEC3); no Next 16 deprecation warnings left |
| F-14 | No action | Safe as implemented |
| F-15 | Unverified | Needs a staging deploy and provider review |
| F-16 | No action | Keep the worker private |

---

## 6. Required Fixes (Blockers) — all resolved

### F-01 + F-03 — Ship the Next.js security upgrade: **Done** (PR #144)

- JS budget raised to 240 KB (`frontend/perf/budget.mts:41`) and recorded as FE-SEC1 in `FRONTEND_IMPLEMENTATION_PLAN.md`.
- PR #144 merged with `check`, `perf` and `visual` green; `npm audit --omit=dev` reports 0 vulnerabilities on `main`.

### F-02 — Add a frontend Railway service: **Done in the repo** (PR #145); dashboard steps remain

Implemented as a Dockerfile built from the repo root (matching the API and worker), not Railpack:

```toml
# frontend/railway.toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "frontend/Dockerfile"
watchPatterns = ["frontend/**"]

[deploy]
healthcheckPath = "/login"
healthcheckTimeout = 120
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
drainingSeconds = 15
```

`frontend/Dockerfile` takes `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_APP_ORIGIN` and `NEXT_PUBLIC_SENTRY_DSN` as build arguments, runs as the unprivileged `node` user and starts with `npm run start` on `$PORT`. The `frontend-docker-build` workflow builds and runs it on real Docker (non-root, `/login` on `$PORT`, HSTS/nosniff/CSP headers). The runbook section is "The web app" in `RAILWAY_DEPLOYMENT.md`.

**Still to do in the Railway dashboard (not code):**

1. Create the web service from this repo and set its **Config file path** to `/frontend/railway.toml` (no root directory needed).
2. Set the build-time variables before the first deploy:

   ```bash
   NEXT_PUBLIC_API_BASE_URL=https://api.<YOUR_DOMAIN>/api/v1
   NEXT_PUBLIC_APP_ORIGIN=https://app.<YOUR_DOMAIN>
   ```

3. Attach `app.<YOUR_DOMAIN>` and `api.<YOUR_DOMAIN>` (same registrable domain, required by the `SameSite=Lax` refresh cookie), then set on the API: `ALLOWED_ORIGINS=["https://app.<YOUR_DOMAIN>"]`, `FRONTEND_URL=https://app.<YOUR_DOMAIN>`, `GOOGLE_REDIRECT_URI=https://api.<YOUR_DOMAIN>/api/v1/auth/google/callback`.

---

## 7. Recommended Improvements

Ordered by impact:

1. **F-06** — Redis for rate limiting and `TRUSTED_PROXY_COUNT=1`, verified in staging.
2. **F-07** — Verified email domain and provider key before inviting users.
3. **F-05** — HSTS is merged; add `includeSubDomains` once every subdomain is served over HTTPS.
4. **F-11** — Enforce the CSP after a staging soak.
5. ~~**F-10** — Custom-header check on `/auth/refresh`.~~ Done.
6. ~~**F-04** — Upgrade `vitest` to clear dev-only advisories.~~ Done.
7. ~~**F-12** — Digest-pin base images.~~ Done.
8. ~~**F-13** — React 19 and `proxy.ts` migration.~~ Done.
9. **F-08** — Evaluate object storage and replicas.

---

## 8. Items Needed for Railway

**Files (all added):** `frontend/Dockerfile`, `frontend/railway.toml`, `.github/workflows/frontend-docker-build.yml`, the web app section of `RAILWAY_DEPLOYMENT.md`, and the budget change in `frontend/perf/budget.mts`.

**API service variables (existing runbook, plus the changes below):**

| Variable | Required | Purpose | Placeholder |
|---|:---:|---|---|
| `DATABASE_URL` | Yes | Postgres (reference variable) | `${{Postgres.DATABASE_URL}}` |
| `JWT_SECRET_KEY` | Yes | Access/refresh signing, 32+ chars | `<OPENSSL_RAND_HEX_32>` |
| `SESSION_SECRET_KEY` | Yes | OAuth session cookie, different from JWT key | `<OPENSSL_RAND_HEX_32>` |
| `DATA_DIR` | Yes | Volume root | `/data` |
| `FETCH_WEIGHTS_ON_START` | Yes | Download checkpoints on first boot | `true` |
| `RAILWAY_RUN_UID` | Yes | Let the entrypoint chown the volume | `0` |
| `TRUSTED_PROXY_COUNT` | Yes | Real client IP behind Railway's proxy | `1` |
| `ALLOWED_ORIGINS` | Yes | Exact web origin(s), JSON list | `["https://app.<YOUR_DOMAIN>"]` |
| `FRONTEND_URL` | Yes | Base for emailed links | `https://app.<YOUR_DOMAIN>` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | If Google sign-in | OAuth | `<FROM_GOOGLE_CLOUD>` |
| `EMAIL_BACKEND`, `EMAIL_FROM`, `RESEND_API_KEY` | Yes (verification on) | Transactional email | `resend`, `CloneVoice <no-reply@<YOUR_DOMAIN>>`, `<RESEND_KEY>` |
| `METRICS_AUTH_TOKEN` | Yes | `/metrics` is otherwise 401 | `<OPENSSL_RAND_HEX_32>` |
| `RATE_LIMIT_STORAGE_URI` | Recommended | Shared limiter state | `${{Redis.REDIS_URL}}` |
| `SENTRY_DSN` | Optional | Error tracking | `<SENTRY_DSN>` |
| `TTS_WORKER_URL`, `TTS_WORKER_ALLOW_PRIVATE_HTTP`, `TTS_WORKER_TOKEN` | Only with worker | Chatterbox service | `http://tts-worker.railway.internal:8100`, `true`, `${{tts-worker.TTS_WORKER_TOKEN}}` |

Leave `PORT` unset (injected by Railway), `APP_ENV` at `production`, `DEVICE` at `cpu`.

**Web service variables:** `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_APP_ORIGIN` (build time, required), `CSP_ENFORCE=1` (after soak), `NEXT_PUBLIC_SENTRY_DSN` (optional, build time).

---

## 9. Remediation Roadmap

### Must fix before deploy
- [x] Decide the JS budget and get PR #144 green (**F-03**)
- [x] Merge PR #144: Next 16, ESLint 9, HSTS, blocking runtime audit (**F-01**, F-05)
- [x] Add the frontend Railway service config and docs (**F-02**, repo side)
- [ ] Create the web service in Railway and attach both custom domains (**F-02**, dashboard side)
- [ ] Verify an email sending domain and set the email variables (F-07)
- [ ] Set `TRUSTED_PROXY_COUNT=1` and confirm client IPs in staging logs (F-06)

### Should fix soon
- [ ] Add Redis for rate-limit state (F-06)
- [ ] Enforce the CSP after a soak (F-11)
- [ ] Re-check Railway behavior against docs.railway.com (volume ownership, proxy headers, SMTP policy) in a staging deploy
- [ ] Measure `TORCH_NUM_THREADS` and inference timeouts on the real CPU (R3 in `RAILWAY_DEPLOYMENT.md`)
- [x] Upgrade `vitest` (F-04)

### Nice to have
- [x] Digest-pin base images (F-12)
- [x] React 19 and `proxy.ts` migration (F-13)
- [x] Custom-header check on `/auth/refresh` (F-10)
- [ ] Object storage instead of a volume (F-08)

---

## 10. Passed Checks

- Reproducible, hash-locked, multi-stage image; CPU-only torch; import smoke test during build
- `$PORT`/`0.0.0.0` binding; uvicorn is PID 1 and handles SIGTERM with a 70 s drain
- Config-as-code for API and worker; pre-deploy Alembic migration; readiness health check
- Production-safe defaults: `APP_ENV=production`, weak JWT secret refused, OpenAPI/docs disabled, `/metrics` token-protected
- No secrets in the tree or history (pattern scan); `.env` files ignored; `uploads/`, `outputs/`, `weights/` ignored
- bcrypt hashing; pinned JWT algorithm; access/refresh separation with `jti` and refresh rotation; per-account failed-login throttling
- Upload validation by type and magic bytes; random file names; request body size limit
- Exact-origin credentialed CORS; `HttpOnly`/`Secure`/`SameSite` cookies
- Weights verified by checksum before loading; worker URL restricted to https or Railway private hosts
- Non-root runtime in all three images (API, worker, web app); backend dependencies free of unaccepted advisories (PR #143); frontend runtime dependencies at 0 advisories (PR #144)
- 2151 backend tests and 730 frontend tests pass (React 19); CI includes schema drift, Docker builds for all three images, Lighthouse and visual gates

---

## 11. Conclusion

**Verdict: READY WITH CONDITIONS.** The three original blockers (Next.js advisories, the JS budget gate, and the missing web app deployment path) are fixed and merged. What remains is operational: dashboard setup, email and rate-limit configuration, and a staging deploy to verify the items this audit could not.

**Single most important next step:** do a staging deploy of all three services on custom domains under one parent domain, with `TRUSTED_PROXY_COUNT=1`, Redis and a verified email domain, then work through the *Unverified* items (client IP, volume ownership, email delivery, cold start).
