# CloneVoice — Frontend Phase-Wise Implementation Plan

> **Status:** IN PROGRESS — Phase 0 (FE-P0, `63d2bd4`) Phase 1 (FE-P1, `36a424f`) Phase 2 (FE-P2, `a6c2913`) Phase 3 (FE-P3, `9b131dc`) and Phase 4 (FE-P4, `91efb3d`) implemented 2026-10-06 and Phase 5 (FE-P5, `40a05a7`) 2026-10-07; Phases 6-8 not started. See the Task Status Log below.
> **Last reviewed:** 2026-10-07.
> **Backend dependencies done:** BD-1, BD-2 (milestone FE-1, `155049e`) and BD-4, BD-5, BD-6 (milestone FE-2, `9fc3bac`), 2026-10-05. G-01, G-02, G-06, G-07 are resolved and G-09 is mostly resolved (F20 unblocked). Only BD-3 (stable error codes, Retry-After on busy responses) remains open.
> **Produced:** 2026-10-05 by following `frontend-plan-prompt.md`.
> **Citation convention:** `path:line` = code/markdown line read this session; `file > heading` = markdown section.
> Anything not found in the repo is labelled **Assumption:** or **Proposal:**.
> Severity scale for gaps: **Blocker** (a spec'd feature cannot work), **High** (feature works badly or unsafely),
> **Medium** (workaround needed), **Low** (cosmetic / doc).

---

## 1. Coverage note

**Status: COMPLETE for the user-facing API surface; PARTIAL for infrastructure and ML internals** (not needed for a UI plan).

### Opened and read in full
| Area | Files |
|---|---|
| Specs | `project_description.md`, `DATABASE_DESIGN.md`, `README.md`, `RAILWAY_DEPLOYMENT.md`, `backend-review.md` (a backend-audit prompt, irrelevant to the UI), `frontend-plan-prompt.md` |
| Entrypoint & routers | `backend/main.py`, `backend/api/auth.py`, `backend/api/voice.py`, `backend/api/synthesize.py`, `backend/api/terms.py` |
| Schemas | `backend/schemas/auth.py`, `voice.py`, `synthesize.py`, `terms.py` |
| Auth / middleware / errors | `backend/core/security.py`, `config.py`, `rate_limit.py`, `body_limit.py`, `db_errors.py`, `login_throttle.py`, `validators.py`, `backend/services/refresh_tokens.py` |
| Upload / outputs / email | `backend/services/audio_processing.py`, `email_service.py`, `erasure.py`, `storage_cleanup.py` |
| Models | `backend/models/generation.py`, `user.py`, `voice_profile.py` |

### Opened partially
- `CLAUDE.md` (project rules; read in session context).
- `HARDENING_PLAN.md` (240 KB): header, task-log rows that mention the frontend/clients, and §4 "Unverified / Needs Human Input" (lines 189-199). **Not read end-to-end.**
- `backend/services/tts_pipeline.py`: only the `run_inference_pipeline` signature/docstring (lines 743-768) and the provenance constants (702-720).
- Installed libraries, inspected only to confirm behaviour: `slowapi` (`_rate_limit_exceeded_handler`, `Limiter.headers_enabled` default) and `asgi_correlation_id.middleware`.

### Not reviewed (nothing is claimed about them)
`backend/models/refresh_token.py`, `user_identity.py`; `backend/core/database.py`, `metrics.py`, `migrations.py`, `sentry.py`, `cpu_limits.py`;
`backend/services/text_chunking.py`, `backend/services/sv2tts/**`; `backend/tests/**` (about 60 files); Alembic revisions;
`backend/Dockerfile`, `docker-compose.yml`, `railway.toml`, `.github/workflows/**`; `PHASE_1_BACKEND_PLAN.md`, `PHASE_2_BACKEND_HARDENING_PLAN.md`, `PREPROCESSING_STUDY.md`;
`graphify-out/` (used only to orient). No `frontend/` directory exists to review.

### Method limits
- No endpoint was exercised live; every behaviour below is read from code. Items that depend on runtime or hosting behaviour are marked **Inferred** or listed in §10.
- Re-verification (Step 5): all cited code files were re-opened in this session; the two library-level claims (slowapi 429 body/headers, no CORS exposure by the correlation-ID middleware) were confirmed by inspecting the installed packages.

---

## 2. Context summary

### Product
CloneVoice lets a signed-in user (1) upload or record a speech sample of a speaker, (2) have the backend extract a voice embedding (SV2TTS), (3) type text and receive synthesized speech in that voice, (4) review history. (`project_description.md` > Core Use Case, lines 15-23.)

### Stack
- **Specified for the frontend (Doc):** Next.js 14 App Router, Tailwind CSS, shadcn/ui, NextAuth.js v5, TanStack Query, Axios (`project_description.md:54-66`).
- **Backend:** FastAPI, PostgreSQL, JWT auth with its own refresh-token registry, Google OAuth done server-side (`project_description.md:70-95`; `backend/api/auth.py`).
- **Conflict:** the Doc stack lists NextAuth v5, but the backend already owns sessions and Google sign-in; see §4 G-14 and §10 Q1.

### Backend contract highlights (all prefixed `/api/v1`, `backend/main.py:252-259`)
| Topic | Fact | Source |
|---|---|---|
| Access token | JWT, 15 min, returned in JSON body `{access_token, token_type}`; sent as `Authorization: Bearer` | `config.py:25`; `schemas/auth.py:41-43`; `security.py:26,199` |
| Refresh token | 7 days, `httpOnly; Secure; SameSite=Lax` cookie named `refresh_token`, **single-use rotation**, set by `/login`, `/refresh` and the Google callback (**not** by `/signup`) | `config.py:26`; `auth.py:59-68,165,201,567-568,122-123` |
| Cookie scope | No `Domain` attribute, so the cookie belongs to the API host only; `SameSite=Lax` means it is sent only when web app and API are same-site | `auth.py:61-68`; `RAILWAY_DEPLOYMENT.md` > Contract with the web app |
| CORS | exact origins only (default `http://localhost:3000`), `allow_credentials=True`, any method/header, **no `expose_headers`** | `config.py:79,292-310`; `main.py:238-244` |
| Email verification | `REQUIRE_EMAIL_VERIFICATION` defaults on: unverified users get **403 "Email address not verified"** on upload and synthesize | `config.py:118`; `security.py:220-231` |
| Upload limits | one `file`; WAV/MP3/WEBM only (declared MIME **and** magic bytes must agree); ≤ 25 MB (+256 KB body overhead); ≥ 2 s of speech after silence trim; ≤ 300 s raw | `audio_processing.py:34-42,65-98,134-188`; `config.py:51,55,60-61` |
| Synthesis limits | `text` 1-500 chars, restricted character set (422 otherwise) | `schemas/synthesize.py:48-66` |
| Rate limits (per client IP) | upload 10/min, synthesize 5/min (hard-coded); login 10/min, signup 5/min, refresh 60/min, email-sending 5/hour, token endpoints 20/min, other authed 120/min; plus per-account failed-password throttle 10 per 15 min | `voice.py:102`; `synthesize.py:93`; `config.py:95-111`; `rate_limit.py:35-55` |
| Long-running work | **Synchronous.** `POST /synthesize` holds the request open and returns the WAV bytes. No job id, polling, SSE or WebSocket exists | `synthesize.py:92-244`; grep for websocket/streaming/StaticFiles in non-test backend code returned nothing |
| Pagination | only `GET /synthesize/history` (`limit` ≤ 50 default 50, `offset`); no total count | `synthesize.py:247-258` |
| Terms | `GET /terms` returns `{version, url|null}`; upload may send `terms_version`, mismatch → 409 | `terms.py:10-14`; `voice.py:129-138` |
| Email links | `FRONTEND_URL/verify-email#token=…` and `FRONTEND_URL/reset-password#token=…` | `email_service.py:26-34,93,124` |
| Google | browser navigates to `GET /auth/google`; callback redirects to `FRONTEND_URL/auth/callback` (cookie set) or `FRONTEND_URL/login?error=<code>` | `auth.py:55-56,497-514,522-569` |

### Key constraints
1. Access token is memory-only by spec (`project_description.md:180-183`), so **every full page load needs a `POST /auth/refresh` bootstrap**.
2. The refresh cookie is invisible to the Next.js server (API-host cookie), so **auth cannot be decided server-side**; protected pages are client-gated (Proposal; derived from `auth.py:61-68`).
3. `CLAUDE.md` §2 forbids frontend code until the backend is "fully implemented, validated, tested, and hardened". §4 lists backend changes the frontend needs; whether they gate Phase 0 is Open Question Q2.

---

## 3. Feature inventory

Backend support: **Full** = endpoint + data sufficient; **Partial** = works with a workaround or a documented limitation; **Missing** = no endpoint.

| # | Feature (user goal) | Endpoints (cited) | Entities | Backend support |
|---|---|---|---|---|
| F1 | Landing page, CTA to sign up | none (`project_description.md:268`) | — | Full (no API needed) |
| F2 | Sign up (email + password + name) | `POST /auth/signup` `auth.py:81-123` | User | **Partial** — returns only an access token, no refresh cookie (G-06) |
| F3 | Log in | `POST /auth/login` `auth.py:126-166` | User, RefreshToken | Full |
| F4 | Stay signed in across reloads / silent renewal | `POST /auth/refresh` `auth.py:169-203` | RefreshToken | Full (cookie-dependent; multi-tab race, G-22) |
| F5 | Log out | `POST /auth/logout` `auth.py:206-221` | RefreshToken | Full (idempotent 204) |
| F6 | See my account | `GET /auth/me` `auth.py:224-228` | User | **Partial** — no `has_password` / linked-provider info (G-07) |
| F7 | Verify email from emailed link | `POST /auth/verify-email` `auth.py:242-259` | User | Full |
| F8 | Resend verification email | `POST /auth/resend-verification` `auth.py:262-283` | User | Full (5/hour) |
| F9 | Request password reset / set password for Google account | `POST /auth/forgot-password` `auth.py:286-325` | User | Full |
| F10 | Choose new password from emailed link | `POST /auth/reset-password` `auth.py:328-351` | User | Full |
| F11 | Sign in with Google | `GET /auth/google`, callback redirect, then `POST /auth/refresh` `auth.py:497-569` | User, UserIdentity | Full |
| F12 | Read acceptable-use terms version/link | `GET /terms` `terms.py:10-14` | — | Full |
| F13 | Upload a voice sample and create a profile | `POST /voice/upload` `voice.py:99-238` | VoiceProfile | **Partial** — one file only; docs say 1-3 clips (G-08) |
| F14 | Record a sample in the browser | same as F13 | VoiceProfile | **Partial** — WEBM only; Safari/iOS recorders emit MP4 (G-08) |
| F15 | List my voice profiles | `GET /voice/profiles` `voice.py:241-258` | VoiceProfile | **Partial** — unordered, unpaginated, includes `failed` rows (G-09, G-11) |
| F16 | Delete a voice profile | `DELETE /voice/profiles/{id}` `voice.py:261-293` | VoiceProfile, Generation | Full (also erases its generations, `erasure.py:52-76`) |
| F17 | Generate speech from text + profile | `POST /synthesize` `synthesize.py:92-244` | Generation | **Partial** — synchronous, no progress/cancel; result id only in a CORS-hidden header (G-02, G-03) |
| F18 | Play / download the just-generated audio | same response body (`audio/wav`) `synthesize.py:242-244` | Generation | Full via `Blob` |
| F19 | Browse generation history | `GET /synthesize/history` `synthesize.py:247-290` | Generation | **Partial** — no total, no profile name, no status, failed rows appear (G-09) |
| F20 | Play / download a past generation | `GET /synthesize/{generation_id}/audio` (added in FE-1, `backend/api/synthesize.py`); `audio_available` on history items | Generation | **Full** (410 once the file expires, G-10) |
| F21 | Edit display name | `PATCH /auth/me` `auth.py:572-586` | User | Full |
| F22 | Delete my account | `DELETE /auth/me` (JSON body) `auth.py:589-619` | all user data | **Partial** — UI cannot tell if a password is required (G-07) |
| F23 | Service-down / degraded banner | `GET /health/ready` `main.py:316-351` | — | Full (optional) |

**Backend features that do not exist (not planned, not invented):** delete a history item; rename a voice profile; change password or email while signed in; unlink Google; list/revoke sessions; multi-clip profiles; shareable links; streaming/WebSocket synthesis (`project_description.md:299-301` lists the last two as Phase 3 ideas).

---

## 4. Backend gaps & conflicts

### 4.1 Blockers / high

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| **G-01** | ✅ **Resolved by FE-1** (`155049e`): `GET /synthesize/{id}/audio` + `audio_available`. Was: Blocker for F20 | **No endpoint returns the audio of a past generation.** History items carry only `output_filename` (a basename), and the only route that returns audio is the one-shot `POST /synthesize`. No static mount or download route exists. A history list can show text and duration but cannot replay or download. | `synthesize.py:276-288,242-244`; `schemas/synthesize.py:69-77`; `main.py:252-259` (only 4 routers); grep for `StaticFiles` found nothing |
| **G-02** | ✅ **Resolved by FE-1** (`155049e`): `expose_headers` set. Was: High | **The new generation's id is unreadable from the browser.** The id appears only in `Content-Disposition: …filename="synthesized_<id>.wav"`, and CORS has no `expose_headers`, so a cross-origin `fetch`/Axios cannot read that header (Content-Disposition is not CORS-safelisted — browser platform rule). `X-Request-ID` is likewise not exposed (middleware source has no Access-Control logic). Result: the UI cannot link the fresh result to its history row, nor quote a request id in error reports. | `synthesize.py:242-244`; `main.py:238-244,250`; library inspection |
| **G-03** | High | **Synthesis is one long synchronous request** with no job id, progress, or server-side cancel. Worst case is two stages × 30 s (+ up to 10 s waiting for the inference slot), and on CPU hosts a maximum-length request can exceed the per-stage 30 s. Hosting-proxy/idle timeouts are not in the repo. The roadmap item "progress indicator during synthesis" is unbuilt. | `config.py:143-158`; `synthesize.py:151-207`; `README.md` > Resource Requirements; `RAILWAY_DEPLOYMENT.md` > Not covered here; `project_description.md:292` |
| **G-04** | Medium→High | **Error bodies have four shapes and no machine-readable codes.** (a) `HTTPException` → `{"detail": "<string>"}`; (b) FastAPI validation 422 → `{"detail": [ {loc,msg,type}, … ]}` (no custom handler is registered; only `RateLimitExceeded` and `SQLAlchemyError`); (c) slowapi 429 → `{"error": "Rate limit exceeded: …"}`; (d) any other unhandled exception → Starlette's plain-text 500 (**Inferred**). Distinct conditions share one status and are told apart only by English text: e.g. 409 "terms changed" vs 409 "profile not ready"; 403 "Email address not verified" vs 403 "Incorrect password" vs 403 "Not authorized to use this voice profile". | `main.py:168-171`; `slowapi._rate_limit_exceeded_handler` (inspected); `voice.py:133-138`; `synthesize.py:117-127`; `security.py:227-230`; `auth.py:611` |
| **G-05** | Medium | **Retry hints are mostly absent.** Only the DB-outage 503 and the per-account login/erase throttle send `Retry-After`. The "service busy" 429 and "overloaded" 503 from inference (and from upload) do not. slowapi's own 429 sends no rate-limit headers because `Limiter` is built without `headers_enabled` (library default `False`). | `db_errors.py:38-44`; `login_throttle.py:45-55`; `synthesize.py:162-179`; `voice.py:190-200`; `rate_limit.py:49-55` |
| **G-06** | ✅ **Resolved by FE-2** (`9fc3bac`): `/signup` sets the cookie. Was: Medium | **Signup does not set the refresh cookie.** Login, refresh and Google do. A freshly signed-up user holds a 15-minute in-memory token that can never be renewed and is lost on reload. | `auth.py:122-123` vs `165`; `project_description.md:180-183` |
| **G-07** | ✅ **Resolved by FE-2** (`9fc3bac`): `has_password` on `/me`. Was: Medium | **`UserOut` lacks `has_password` and linked providers.** Account linking sets `provider="google"` while keeping the password of a verified local account, so `provider` cannot tell the UI whether a password exists. The spec wants "linked OAuth provider" on the profile screen, and `DELETE /me` needs the password only if one exists. | `schemas/auth.py:46-55`; `auth.py:376-388,606-611`; `project_description.md:178` |

### 4.2 Medium / low

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| **G-08** | Medium | **Upload scope differs from the docs.** Docs: "1–3 short clips (10–30 s each)", later M4A/OGG. Code: exactly one `file`; WAV/MP3/WEBM; min 2 s of speech, max 300 s; declared Content-Type must match the sniffed container. Browser `MediaRecorder` on Safari/iOS produces MP4/AAC, which is rejected (**Inferred** from the allow-list). | `project_description.md:18,290`; `voice.py:108`; `audio_processing.py:34-42,60-98` |
| **G-09** | ✅ **Mostly resolved by FE-2** (`9fc3bac`): history has `voice_profile_name`, `status`, `X-Total-Count`; profiles newest first. Still open: no profile pagination; failed generations are still returned (filter on `status`). Was: Medium | **List shapes are thin.** Profiles: no ordering, no pagination. History: no total count, no voice-profile name (client must join with the profiles list), no `status` field, and **failed generations are returned** (filter is by owner and non-deleted profile only) with `output_filename=""` and `duration_seconds=null`. | `voice.py:248-254`; `synthesize.py:260-288`; `schemas/synthesize.py:69-77` |
| **G-10** | Medium | **Output audio expires but the row stays.** WAV files are protected for `OUTPUT_RETENTION_DAYS` (30), then pruned; history rows remain forever with no "audio expired" flag. | `config.py:185-191`; `storage_cleanup.py:83-95` |
| **G-11** | Low | **Failed uploads leave visible `failed` profiles** (embedding failure, queue-full 429, timeout 503, 500 all persist a `status="failed"` row) and `GET /profiles` returns them. The UI must show and allow deleting them; `synthesize` returns 409 for them. | `voice.py:64-96,185-209,248-254`; `synthesize.py:122-127` |
| **G-12** | Low | `DELETE /auth/me` requires a JSON **body** (some HTTP clients drop bodies on DELETE); `DELETE /voice/profiles/{id}` returns an untyped `{"status":"deleted"}` with 200. | `auth.py:589-595`; `voice.py:261-293` |
| **G-13** | Low (config) | Refresh cookie is always `Secure` and `SameSite=Lax`. Local `http://localhost` works only where the browser treats localhost as secure for cookies (**Assumption:** Chromium/Firefox yes, Safari no — verify). Production needs web app and API on one registrable domain, or a same-origin proxy. | `auth.py:61-68`; `RAILWAY_DEPLOYMENT.md:91-94` |
| **G-14** | Medium (decision) | **Doc-vs-code conflict on auth stack.** Docs: "NextAuth.js on frontend + Authlib on backend" and NextAuth v5 in the stack. Code: the backend alone issues access/refresh tokens, runs the Google flow, and redirects the browser to `FRONTEND_URL/auth/callback`, which then calls `/refresh`. NextAuth would add a second session layer the backend cannot consume. | `project_description.md:63,176`; `auth.py:55,567`; `RAILWAY_DEPLOYMENT.md:78-84` |
| **G-15** | Low (docs) | **Stale endpoint docs.** `CLAUDE.md` §7 lists `/api/auth/login`, `/api/voice/upload` (no `/v1`) and 5 routes; code mounts everything under `/api/v1` and has more (`/logout`, `PATCH`/`DELETE /me`, `GET /terms`, email/password routes). `project_description.md:233-260` omits `/logout`, `PATCH`/`DELETE /me`, `GET /terms`. **Code wins:** this plan uses the code. | `main.py:252-259`; `auth.py:206,572,589`; `terms.py:10` |
| **G-16** | Low (docs) | `DATABASE_DESIGN.md` says `generations` has no `updated_at`/`deleted_at` and is immutable; the model has both and erasure soft-deletes rows. Not UI-relevant beyond "history hides deleted-profile generations". | `DATABASE_DESIGN.md` > `generations` Table (line 128); `models/generation.py`; `erasure.py:52-76` |
| **G-17** | Low (docs) | The UI-screen table omits pages the backend requires: `/verify-email`, `/reset-password`, `/auth/callback`, and `/login?error=<code>` handling. | `project_description.md:264-272`; `auth.py:55-56`; `RAILWAY_DEPLOYMENT.md:85-90` |
| **G-18** | Low | `terms.url` may be `null` ("blank until the page exists"); the consent UI needs fallback text. | `config.py:196-199`; `schemas/terms.py:6-8` |
| **G-19** | Low (UX) | A Google-only account that tries email login gets the generic 401 "Incorrect email or password" (by design, to avoid revealing accounts). UI copy must hint at Google/forgot-password **without** confirming an account exists. | `auth.py:145-158,298-302` |
| **G-20** | Low | Rate limits are **per client IP** (shared NAT users share budgets); the per-account throttle can lock a victim's password login for 15 min (accepted trade-off). | `rate_limit.py:35-46`; `login_throttle.py:8-14` |
| **G-21** | Low | `/docs` and `/openapi.json` are served only when `APP_ENV=development` or `API_DOCS_ENABLED`, so typed-client generation must run against a dev instance. | `main.py:148-163` |
| **G-22** | **High (frontend-critical)** | **Refresh-token rotation punishes concurrent refreshes.** A token is single-use. A second use within 10 s (`REFRESH_REUSE_GRACE_SECONDS`) is refused with 401 but harmless; a replay after the grace window **revokes all of the user's sessions**. Two tabs (or React dev double-effects) refreshing at once will see one 401. The client must serialize refreshes across tabs. | `refresh_tokens.py:55-92`; `config.py:27-30`; `auth.py:169-203` |

### 4.3 Backend dependencies the plan needs (proposed backend milestones, **not** frontend work)
| ID | Closes | Ask | Priority |
|---|---|---|---|
| BD-1 ✅ `155049e` | G-01, G-10 | Authenticated `GET /api/v1/synthesize/{id}/audio` (owner-checked, returns WAV or 404/410 when expired); optionally add `audio_available` to `GenerationOut`. | **Required for F20** |
| BD-2 ✅ `155049e` | G-02 | CORS `expose_headers=["Content-Disposition","X-Request-ID","Retry-After"]`; or add `generation_id` to a response header. | Required for F17↔F19 linking |
| BD-3 | G-04, G-05 | Stable machine `code` in error bodies; consistent `{detail, code}` for 422/429; `Retry-After` on busy/overloaded; `headers_enabled=True`. | Strongly recommended |
| BD-4 ✅ `9fc3bac` | G-06 | Set the refresh cookie in `/signup`. | Recommended (client workaround exists) |
| BD-5 ✅ `9fc3bac` | G-07 | Add `has_password` (and `providers`) to `UserOut`. | Recommended (workaround exists) |
| BD-6 ✅ `9fc3bac` | G-09 | `status` and `voice_profile_name` on history items; `total` or `has_more`. | Optional |

Until BD-1/BD-2 land, the plan ships F20 as "not available" and uses a client-side workaround for F17↔F19 linking (§7 Phase 4).

---

## 5. Frontend architecture

Tags: **Doc** = specified in the repo docs; **Proposal** = my choice (justified); **Code** = dictated by backend code.

### 5.1 Stack & structure
| Decision | Tag | Detail / justification |
|---|---|---|
| Next.js 14 App Router, TypeScript strict, Tailwind CSS, shadcn/ui | **Doc** (`project_description.md:59-61`) | TypeScript is a **Proposal** (the doc names `.tsx` files at lines 123-132, so TS is implied). |
| TanStack Query for server state, Axios for HTTP | **Doc** (`project_description.md:63-64`) | Axios gives interceptors (refresh/retry) and upload progress events, both needed here. |
| **No NextAuth** | **Proposal**, conflicts with Doc (G-14) | The backend owns tokens and Google sign-in (`auth.py:497-569`). A thin custom auth module replaces NextAuth. If the owner insists on NextAuth, it can only wrap the same backend (Credentials provider calling `/login`), which adds a second session with nothing to renew it; see Q1. |
| `react-hook-form` + `zod` for forms | **Proposal** | shadcn/ui's form primitives are built on it; zod schemas mirror backend limits (§6 R6). |
| Directory layout | **Proposal**, extends the `project_description.md:118-135` sketch | See below. |
| Unit/integration tests: Vitest + React Testing Library + MSW; e2e: Playwright | **Proposal** | MSW mocks every endpoint so tests never call live services (mirrors `CLAUDE.md` §4.2). Playwright runs against a real backend booted with mock-friendly settings (§7 Phase 7). |
| Package manager / Node | **Assumption:** Node 18+ (`README.md` > Prerequisites) and npm or pnpm. |

```
frontend/
├── app/
│   ├── (public)/            # landing, login, signup, forgot-password, reset-password, verify-email
│   ├── auth/callback/       # Google return page (calls /refresh)       [auth.py:55]
│   ├── (app)/               # client-gated: dashboard, profile (voices + history + account)
│   └── layout.tsx           # providers, toaster, a11y skip-link
├── components/              # AudioUploader, Recorder, TextToSpeechForm, AudioPlayer, ProfileCard, …
├── lib/
│   ├── api/                 # typed client: http.ts (Axios), auth.ts, voice.ts, synth.ts, terms.ts
│   ├── auth/                # session store, refresh single-flight, tab sync
│   ├── errors.ts            # ApiError normalizer (§5.5)
│   └── validation/          # zod schemas mirroring backend limits
├── tests/ e2e/ mocks/       # Vitest, Playwright, MSW handlers
└── next.config.mjs          # security headers, rewrites (optional)
```

### 5.2 Typed API client layer (Proposal)
- One Axios instance, `baseURL = NEXT_PUBLIC_API_BASE_URL` (ends with `/api/v1`), `withCredentials: true` (needed so the refresh cookie travels; CORS already allows credentials, `main.py:238-244`).
- Request types: hand-written TS mirroring `schemas/*.py` first; **generated from `openapi.json`** of a dev backend in CI once Phase 0 is done (G-21: docs are off in production).
- Every call returns parsed data or throws `ApiError` (§5.5). No component touches Axios directly.
- Blob endpoints (`POST /synthesize`) use `responseType: "blob"`; error bodies arrive as Blobs and must be re-parsed as JSON (a classic Axios pitfall) inside the normalizer.
- Timeouts: default 15 s; `/synthesize` and `/voice/upload` use a long timeout (Proposal: 120 s; justified by G-03 worst case ≈ 70 s plus cold start). Final values depend on Q4.

### 5.3 Auth/session handling (Code-driven)
- **Access token lives in a module-level variable / in-memory store only** (`project_description.md:180-183`); never `localStorage`/`sessionStorage`/readable cookie.
- **Bootstrap:** on app mount call `POST /auth/refresh` once; success → store token, fetch `GET /auth/me`; 401 → "signed out". The UI shows a skeleton until bootstrap settles (no flash of login page).
- **Single-flight refresh** (G-22): one in-process promise shared by all callers, plus a cross-tab lock via the Web Locks API (fallback: `BroadcastChannel` leader election). A tab that loses the race waits for the winner's broadcast token rather than treating its own 401 as a logout. React Strict Mode double effects must be guarded by the same promise.
- **401 handling:** an authenticated call that gets 401 triggers exactly one refresh then one retry of the original request; a second 401 or a failed refresh → clear session, redirect to `/login?next=…`.
- **Route gating is client-side** (the Next.js server cannot see the API-host cookie, `auth.py:61-68`): an `<AuthGate>` wraps `(app)/`; middleware is used only for security headers.
- **Logout:** `POST /auth/logout` (204, idempotent, `auth.py:206-221`), then clear memory, query cache and broadcast a `logout` event to other tabs.
- **Google:** a plain `<a href="{API}/auth/google">` full-page navigation (never XHR). `/auth/callback` calls `/refresh` and routes to `/dashboard`; `/login` reads `?error=` (§7 Phase 2).
- **Proactive refresh:** none. Lazy refresh on 401 is sufficient and keeps rotation traffic low (limit 60/min/IP, `config.py:103`).

### 5.4 Routing (Proposal; routes mandated by backend marked)
| Route | Purpose | Gate |
|---|---|---|
| `/` | Landing | public |
| `/login`, `/signup` | forms (+ Google button) | public; redirect if signed in. `/login?error=` is **Code-mandated** (`auth.py:56,519`) |
| `/forgot-password` | request reset | public |
| `/reset-password` | **Code-mandated** (`email_service.py:124`), token in `#fragment` | public |
| `/verify-email` | **Code-mandated** (`email_service.py:93`), token in `#fragment` | public |
| `/auth/callback` | **Code-mandated** (`auth.py:55`) | public, bootstrap-only |
| `/dashboard` | choose/create voice, type text, generate | signed in |
| `/profile` | account, voice profiles, history | signed in |

### 5.5 Error and notification strategy (Proposal, needed because of G-04/G-05)
- `ApiError { status, kind, message, fieldErrors?, retryAfterSec?, requestId? }`, built by one normalizer that understands: `{detail:string}`, `{detail:[…]}` (map `loc` → field), `{error:string}` (slowapi 429), Blob bodies, empty/plain-text bodies, and network/timeout (`status=0`).
- `kind` is derived from **status first**, then from a small table of exact backend strings (e.g. `"Email address not verified"` → `EMAIL_UNVERIFIED`; `"Incorrect password"` → `BAD_PASSWORD`). The table lives in one file and is covered by contract tests; it disappears once BD-3 adds real codes.
- **Surface rules:** field errors inline; action-level failures as a toast with a retry affordance when safe; page-level failures in an error boundary with a retry button; auth failures redirect. Messages are user-readable and never echo raw server text for 5xx.
- Error boundaries: root, per route group, and around the audio player.
- Toasts via shadcn `sonner`; the live region is announced to screen readers.

### 5.6 Forms
`react-hook-form` + zod. Zod schemas replicate backend rules **only where deterministic** (lengths, required fields, file type/size, 8-128 password); everything else is deferred to the server's 422 and shown inline (§6 R6).

### 5.7 Environment config
| Variable | Tag | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Proposal | e.g. `https://api.example.com/api/v1` |
| `NEXT_PUBLIC_APP_ORIGIN` | Proposal | for absolute links/CSP |
| `NEXT_PUBLIC_SENTRY_DSN` | Proposal | optional (backend already supports Sentry: `config.py:213`) |
Backend settings the frontend must be coordinated with: `ALLOWED_ORIGINS` (exact origin, no trailing slash), `FRONTEND_URL`, `GOOGLE_REDIRECT_URI` (`config.py:79,124,36`; `RAILWAY_DEPLOYMENT.md:54-58`).

### 5.8 Observability (Proposal)
Sentry (browser) with PII scrubbing (no text/audio/emails in breadcrumbs); capture `ApiError.status`, route, and `X-Request-ID` once BD-2 exposes it; web-vitals reporting; a `/health/ready` poll (low frequency) for the degraded banner (F23).

### 5.9 Security
| Topic | Decision |
|---|---|
| Token storage | memory only (**Doc**); refresh is `httpOnly` (**Code**). |
| XSS | React escaping; **never** `dangerouslySetInnerHTML`; `input_text` and names rendered as text. Strict CSP: `default-src 'self'`; `connect-src 'self' <API origin>`; `media-src 'self' blob:`; `script-src` with nonces; `frame-ancestors 'none'`; `object-src 'none'`. |
| Fragment tokens | `/verify-email` and `/reset-password` read `location.hash`, call `history.replaceState` immediately, and are served with `Referrer-Policy: no-referrer` (**Doc**: `RAILWAY_DEPLOYMENT.md:85-90`). Site-wide default `Referrer-Policy: strict-origin-when-cross-origin`. |
| CSRF | Cookie is `SameSite=Lax` and only `/refresh`, `/logout` use it; both are POST, so cross-site posts do not carry it. Do not add other cookie-authenticated endpoints. |
| Blob URLs | revoke with `URL.revokeObjectURL` on unmount/replace (memory) — see §6 R15. |
| Clickjacking / sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`. |
| Dependencies | lockfile + `npm audit`/Dependabot in CI (mirrors backend `pip-audit`, `HARDENING_PLAN.md` §4 item 3). |
| Same-site deploy | web app and API on one registrable domain (**Code**-forced, G-13). |

### 5.10 Performance
Route-level code splitting; the recorder and waveform code lazy-loaded; no audio decoded client-side beyond an `<audio>` element and (optional) a `decodeAudioData` duration check; list virtualization is **not** needed (history page ≤ 50 rows, `synthesize.py:257-258`); Lighthouse budgets set in Phase 7.

### 5.11 Accessibility
WCAG 2.2 AA target (**Proposal**): semantic landmarks, labelled inputs, focus management after route/modals, visible focus, `aria-live` for toasts/progress, a custom audio player operable by keyboard with accessible names, recorder state announced, reduced-motion respected, 44 px touch targets, colour contrast ≥ 4.5:1 in both themes.

---

## 6. Cross-cutting resilience standards

Every feature must satisfy the rules below (or state "N/A because …" in its phase). IDs are referenced in §7 and §8.

| ID | Rule |
|---|---|
| **R1 States** | Every data view has loading (skeleton), empty (with next-step CTA), error (retry), and partial/stale states; no blank screens. |
| **R2 Auth expiry mid-flow** | 401 → one refresh + one retry (§5.3). Form state (text, chosen profile) survives the redirect to `/login?next=` via in-memory/URL state; **an in-flight file is not re-uploaded silently**. |
| **R3 Status handling** | **400** (invalid id/token) → inline message; **401** → R2; **403** → disambiguate by `kind` (unverified-email → verification banner with resend; wrong password → field error; foreign profile → refresh list); **404** → refresh the list and tell the user the item is gone; **409** → by `kind` (terms changed → refetch `/terms`, re-show consent; profile not ready → refresh list); **413** → file-too-large message; **422** → field errors from `detail[]` or the string; **429** → countdown from `Retry-After` when present, else a default backoff, controls disabled; **5xx** → generic "try again" + Retry-After if sent; **0** (network) → offline message. |
| **R4 Double submit** | Submit controls disabled while a mutation is in flight; a per-form in-flight guard prevents Enter-key repeats. The backend has **no idempotency keys**, so duplicates create duplicate rows (profile / generation) and burn the 5-10/min budgets. |
| **R5 Retries** | Automatic retry (exponential backoff with jitter, max 2) **only** for idempotent GETs and only on network error/502/503/504. **Never** auto-retry `POST /synthesize`, `POST /voice/upload`, `/signup`, `/refresh` (rotation) or `DELETE /auth/me`. After an ambiguous failure (timeout/network) of a non-idempotent POST, re-fetch the relevant list and let the user decide. |
| **R6 Validation parity** | Mirror deterministic backend rules client-side: email format; password 8-128 on signup/reset (`schemas/auth.py:18-20,25-27,88-90`); login password ≤ 4096; name 1-255, non-blank, trimmed (`validators.py`); `text` 1-500 (`schemas/synthesize.py:50`); file ≤ 25 MB, type in {WAV, MP3, WEBM}, non-empty (`audio_processing.py:34-42,77-84`). **Do not** re-implement the SV2TTS character check (it depends on `unidecode` behaviour, `schemas/synthesize.py:18-45`); allow a light pre-warning for obviously unsupported characters (emoji) and render the server's 422 message verbatim. Emails are lower-cased by the server (`schemas/auth.py:16`), so compare case-insensitively in the UI. |
| **R7 Cancellation & races** | Use `AbortController` for navigations away from list queries; stale responses ignored (TanStack Query keys). A **cancel button for synthesis only aborts the browser request**; the server may still finish and record a generation (**Inferred**: no cancellation code in `synthesize.py`), so after a cancel invalidate history. |
| **R8 Large / invalid uploads** | Pre-check size and type; show progress via Axios `onUploadProgress`; a `413` from the body-limit middleware may arrive as a **network error** because it replies with `Connection: close` while the browser is still sending (`body_limit.py:86-93`; **Inferred**), so client-side size pre-check is mandatory and a network error during upload suggests "file may be too large". The browser-declared Content-Type must match the container (`audio_processing.py:93-97`): send the `File`'s own type, never override it. |
| **R9 Interrupted long jobs** | Synthesis timeout/tab close: no job id exists to resume. On the next load, history shows the result if it completed. UI copy: "If you left this page, check History." Warn on `beforeunload` while a synthesis/upload is running. |
| **R10 Permissions & browser support** | Microphone: handle `NotAllowedError`, `NotFoundError`, `NotReadableError`, insecure context, and missing `MediaRecorder`; feature-detect `audio/webm` support via `MediaRecorder.isTypeSupported` (Safari/iOS do not produce WEBM; fall back to file upload only). |
| **R11 Stale data / multiple tabs** | Query cache invalidated after mutations; `BroadcastChannel` events (`logout`, `token`, `profiles-changed`) sync tabs; refetch on window focus for lists; a 404/409 on a stale profile triggers a list refresh. |
| **R12 Pagination / large lists** | History uses `limit`/`offset` with "Load more" (server clamps to 50, `synthesize.py:257-258`); because there is no total, "has more" = `page.length === limit`; handle the final empty page. Profiles are unpaginated: render all, with an upper-bound UI note (**Assumption:** a user has few). |
| **R13 Rate limits** | UI reflects 429 with a cooldown and disables the control; do not stack retries; show remaining-time text only when `Retry-After` exists (G-05). Per-IP limits are shared across users behind one NAT (G-20). |
| **R14 Responsive & a11y** | Mobile-first layouts; all flows operable by keyboard and screen reader; tested at 320 px, 768 px, 1280 px; dark/light parity. |
| **R15 Media lifecycle** | Blob URLs revoked on replace/unmount; never keep more than one synthesized blob per player in memory; downloads use `<a download>` with a safe filename. |
| **R16 Privacy** | Never log or send to analytics: input text, audio, emails, tokens. Clear the query cache on logout. |
| **R17 Degraded service** | If `/health/ready` is 503 (`main.py:316-351`) show a non-blocking banner; disable generate/upload while degraded. |
| **R18 Time** | Show timestamps in the user's locale from the ISO strings the API returns (`datetime` fields, `schemas/*.py`). |

---

## 7. Phase-wise plan

Order: foundation → auth → email/Google → voice profiles → synthesis → history/account → advanced → hardening → release.
Every phase ends only when its exit criteria are verified by tests, per the repo's zero-failure rule (`CLAUDE.md` §3.3, applied to the frontend by **Proposal**).

**Gate (CLAUDE.md §2):** frontend work starts only after the owner confirms the backend gate is met (Q2). Backend dependencies BD-1…BD-6 (§4.3) are separate backend milestones; each phase below states which it needs.

### Phase 0 — Foundation & contracts
- **Goal:** a runnable, tested shell with the API client, error model and CI, before any feature.
- **Features:** F23 (health banner); infrastructure for all others.
- **Endpoints:** `GET /health/ready` (`main.py:316-351`); `GET /terms` smoke-wired.
- **Edge cases:** R1, R3 (normalizer), R5, R7, R13, R17, R18; CORS/cookie same-site setup (G-13); `/openapi.json` availability (G-21).
- **Tasks**
  1. Scaffold Next.js 14 + TS strict + Tailwind + shadcn/ui; ESLint, Prettier, `tsc --noEmit`.
  2. `lib/api/http.ts`: Axios instance, `withCredentials`, timeouts, `X-Request-ID` capture (if exposed), long-timeout variant.
  3. `ApiError` normalizer for all four error shapes + Blob error bodies + network/timeout (§5.5) with a string→`kind` table.
  4. TanStack Query provider with retry policy per R5; Sonner toaster; root error boundary; theme tokens (light/dark).
  5. MSW handlers for every endpoint in §3 using realistic bodies copied from the schemas; Vitest + RTL setup.
  6. Env validation (zod) for `NEXT_PUBLIC_*`.
  7. Local dev recipe: web on `localhost:3000`, API on `localhost:8000` (same-site; `ALLOWED_ORIGINS` default already allows it, `config.py:79`); document `EMAIL_BACKEND=console` or `REQUIRE_EMAIL_VERIFICATION=false` for dev (`README.md` > Environment Setup).
  8. CI: lint, typecheck, unit tests, `npm audit`; OpenAPI-type generation job against a dev backend.
  9. App shell: header, nav, footer, skip-link, degraded-service banner.
- **Tests:** *Unit:* normalizer (each shape: `{detail:str}`, `{detail:[…]}`, `{error:str}`, Blob JSON, Blob non-JSON, empty, network, timeout); env validation. *Integration:* provider + MSW 503/network scenarios. *E2E:* app boots, health banner shows on 503.
- **Deliverables:** `frontend/` scaffold, CI workflow, `frontend/README.md`, ADR for "no NextAuth" (pending Q1).
- **Exit criteria:** CI green; normalizer unit tests cover all shapes; app renders in light/dark at 320/768/1280 px.
- **Dependencies:** Q1, Q2. **Risks:** Doc-mandated NextAuth (mitigated by Q1); cookie/same-site misconfiguration discovered late (mitigated by item 7 on day one).

### Phase 1 — Public shell, signup, login, session core
- **Goal:** a user can create an account, sign in, stay signed in, and sign out, safely across tabs.
- **Features:** F1, F2, F3, F4, F5, F6.
- **Endpoints:** `POST /auth/signup`, `/login`, `/refresh`, `/logout`; `GET /auth/me` (`auth.py:81-228`).
- **Edge cases:**
  - *Signup:* 409 "Email already registered" (`auth.py:100`) → inline field error with link to login; 422 field mapping; password 8-128; name non-blank; 429 (5/min); double submit (R4); **ambiguous failure** (timeout then 409 on retry) → send to login. No refresh cookie after signup (G-06): **No workaround needed after FE-2:** `/signup` now sets the refresh cookie, so the client treats the signup response like a login response.
  - *Login:* 401 generic message (G-19); 429 with `Retry-After` from the per-account throttle (`login_throttle.py:45-55`) and per-IP limit (no header, G-05); soft-deleted account looks like a bad password; password up to 4096 chars accepted (`schemas/auth.py:20,38`).
  - *Session:* bootstrap `/refresh` once; single-flight + cross-tab lock (G-22, R11); 401 on refresh → signed-out state silently (not an error toast); refresh rate 60/min; Strict-Mode double effect guard; token never persisted (§5.3).
  - *Logout:* idempotent; also when offline (clear local state even if the call fails); cross-tab logout broadcast.
  - *Unverified user:* `/me.email_verified_at == null` → persistent verification banner (feeds Phase 2).
  - *Redirects:* `next=` parameter must be validated as a same-origin relative path (open-redirect prevention, **Proposal**).
- **Tasks:** auth store + `AuthGate`; `refresh` single-flight with Web Locks/BroadcastChannel; Axios 401 interceptor (one refresh, one retry, queue concurrent callers); signup/login forms with zod; landing page (F1); header user menu; skeletons during bootstrap; sign-out.
- **Tests:** *Unit:* single-flight returns one network call for N concurrent callers; interceptor retries once then fails; `next` sanitizer; zod schemas vs backend bounds. *Integration (MSW):* login 401/429/422; signup 409; refresh 401 → signed out; two simulated tabs with one 401 within grace → loser adopts winner's token (no logout); refresh replay after grace → forced logout and message. *E2E (Playwright vs real backend):* signup→login→reload stays signed in→logout; two-tab session; expired access token mid-action recovers.
- **Deliverables:** `/`, `/login`, `/signup`, `AuthGate`, session module, e2e suite v1.
- **Exit criteria:** reload keeps the session; two tabs never log each other out in a 100-iteration concurrent-refresh test; no token appears in storage (asserted in e2e); all listed status codes have a tested UI.
- **Dependencies:** Phase 0. BD-4 optional (removes the post-signup re-login workaround). **Risks:** Safari cookie behaviour on `http://localhost` (G-13); rotation races (G-22) — the highest-risk item of this phase.

### Phase 2 — Email lifecycle and Google sign-in
- **Goal:** all non-password-typing identity flows work end to end.
- **Features:** F7, F8, F9, F10, F11.
- **Endpoints:** `POST /auth/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`; `GET /auth/google`; `/auth/callback` consumer of `POST /auth/refresh` (`auth.py:242-351,497-569`).
- **Edge cases:**
  - *Token pages* (`/verify-email`, `/reset-password`): read token from `location.hash`, then `history.replaceState` immediately; `Referrer-Policy: no-referrer`; missing/malformed fragment → friendly "link incomplete" state; **400 "Invalid or expired token"** (`auth.py:253,341`) for expired (24 h verification, 30 min reset, `config.py:119-120`), already-used, wrong-purpose, or email-changed tokens → offer "resend"/"request a new link". Verification is idempotent (`auth.py:247,255-259`); opening the link twice must show success.
  - *Verify when signed out / in another browser:* works (token-only); after success refetch `/me` if a session exists, else route to login. Banner hides on `email_verified_at` change (poll `/me` on window focus, R11).
  - *Resend:* 202; "already verified" is a 200 with a different message (`auth.py:274-275`) → treat both as success; 5/hour → 429 cooldown UI (G-05: no Retry-After → show fixed "try again later"); not signed in → 401 → route to login.
  - *Forgot password:* always shows the same neutral confirmation (`auth.py:323-325`); never reveal account existence; 5/hour 429; Google-only accounts receive a "set password" email (copy must say so without confirming the account).
  - *Reset:* new password 8-128; success revokes all sessions (`auth.py:348-351`) → clear local session, send to login; token reuse → 400 (fingerprint check, `auth.py:338-341`); double submit (R4). Also marks the email verified (`auth.py:344-346`).
  - *Google:* the start link is a full navigation; 429 on `/google` (120/min) returns JSON to a navigation → the browser would show raw JSON (**Inferred**); acceptable but note in risks. Return pages: `/auth/callback` (bootstrap, then `/dashboard`; if `/refresh` 401 → login with a generic error) and `/login?error=` with the four stable codes `google_failed`, `google_no_email`, `google_email_unverified`, `google_account_conflict` (`auth.py:531-533`; unknown code → generic text). The OAuth state cookie lasts 10 min (`main.py:205`); an expired state surfaces as `google_failed`.
  - *Cookie blocked / third-party cookie policies:* after Google redirect, if `/refresh` returns 401 despite success → show "browser is blocking cookies" help (same-site requirement, G-13).
- **Tasks:** the three token pages + callback page; error-code map with copy; verification banner & resend action; forgot/reset forms; Google button; e2e with `EMAIL_BACKEND=console` log scraping or MSW (never live providers, `CLAUDE.md` §4.2).
- **Tests:** *Unit:* fragment parser, `replaceState` called once, error-code map exhaustiveness. *Integration (MSW):* 400 / 202 / 429 for each endpoint; neutral forgot-password copy identical for both outcomes. *E2E:* signup → grab verification link from backend console log → verify → banner gone; forgot → reset → old sessions dead; Google flow against a mocked OAuth server if available, else contract test for `/login?error=` pages only (**Assumption**: a real Google round trip is a manual release check, Phase 8).
- **Deliverables:** pages `/verify-email`, `/reset-password`, `/forgot-password`, `/auth/callback`, error handling on `/login`.
- **Exit criteria:** all 4 Google error codes render distinct copy; fragment never appears in the URL after load (asserted); reset invalidates the other tab's session (asserted).
- **Dependencies:** Phase 1; backend `FRONTEND_URL` and `GOOGLE_REDIRECT_URI` configured (`RAILWAY_DEPLOYMENT.md:54-58`). **Risks:** emails need a verified sending domain in production (`HARDENING_PLAN.md` §4 item 2, "still open"); Safari ITP/cookie behaviour on the callback hop.

### Phase 3 — Voice profiles (upload, list, delete)
- **Goal:** a verified user can create, view, and delete voice profiles with explicit consent.
- **Features:** F12, F13, F15, F16 (F14 recording is Phase 6).
- **Endpoints:** `GET /terms`; `POST /voice/upload`; `GET /voice/profiles`; `DELETE /voice/profiles/{id}` (`terms.py`, `voice.py:99-293`).
- **Edge cases:**
  - *Gating:* unverified → 403 "Email address not verified" (`security.py:229`); pre-empt using `/me`, disable the form, show banner + resend (R3).
  - *Consent:* checkbox required (`consent_confirmed=true`, else 422, `voice.py:124-128`); display the terms version from `GET /terms` and send `terms_version`; **409 "terms have changed"** → refetch `/terms`, reset the checkbox, explain; `terms.url == null` → inline fallback text (G-18).
  - *Fields:* `name` 1-255 non-blank (`voice.py:105,115-118`); `file` required; multipart built by the browser (no manual `Content-Type` header).
  - *File validation (client):* size ≤ 25 MB (R8), non-empty, extension and `File.type` in WAV/MP3/WEBM; allow `audio/webm;codecs=opus` style params (server strips them, `audio_processing.py:44-46`); mismatch between extension and real content is only detected server-side → 422 "File content does not match its declared audio type." shown verbatim.
  - *Server rejections:* 422 empty / invalid signature / too short after trimming / too long (> 300 s) / undecodable / "Could not extract a voice" (`audio_processing.py:65-188`, `voice.py:174-178`); 413 (**may appear as network error**, R8); 429 "service busy" (`voice.py:185-193`) and 503 "overloaded" (`voice.py:194-200`) → retry button, **no auto-retry** (R5); 500 → generic. Failed embedding paths persist a `failed` profile (G-11): after any 429/503/500 on upload, refetch profiles and surface the failed row with "Delete".
  - *Rate limit:* 10/min/IP (`voice.py:102`) → cooldown.
  - *Progress:* upload progress bar (bytes), then an indeterminate "analyzing voice" state; embedding runs after the upload completes, so the request stays open (G-03 applies).
  - *Double submit / tab close:* R4, R9 (warn before unload; on reload refetch profiles).
  - *List:* unordered (G-09) → sort client-side by `created_at` desc; `status` chips (`ready`, `failed`, `processing` is documented in `DATABASE_DESIGN.md` > `voice_profiles` but never set by the code reviewed); empty state with CTA; no pagination (R12).
  - *Delete:* confirm dialog (it also erases the profile's generations and files, `erasure.py:52-76`); 404 → treat as already gone and refresh; 400 invalid id; double click; optimistic removal with rollback on error; invalidate history cache afterward.
  - *Concurrent tabs:* R11.
- **Tasks:** `AudioUploader` with drag-drop and keyboard support; consent block; profile list/cards; delete dialog; verification gating; failed-profile UX.
- **Tests:** *Unit:* file pre-validation (0 B, 25 MB + 1 B, wrong type, param-suffixed MIME); terms-version mismatch handler. *Integration (MSW):* each status above (201, 403, 409, 413 as network error, 422 variants, 429, 503, 500) → expected UI; delete 404/400. *E2E:* upload `backend/tests/fixtures/sample_5sec.wav` (exists in repo) → profile appears; upload a 0-byte file and a text file renamed `.wav` → proper 422 messages; delete flow.
- **Deliverables:** `/profile` voices section, reusable `VoiceProfileSelect` for Phase 4.
- **Exit criteria:** every upload failure leaves the UI consistent with the server (verified by refetch); no auto-retry of POST (asserted); consent can never be bypassed (asserted).
- **Dependencies:** Phases 1-2. **Risks:** CPU-bound embedding latency; 413-as-network-error ambiguity; docs promising multi-clip profiles (G-08, Q5).

### Phase 4 — Synthesis (generate, play, download)
- **Goal:** pick a ready voice, enter text, get playable/downloadable audio with robust handling of slow or failed jobs.
- **Features:** F17, F18.
- **Endpoints:** `POST /synthesize` (`synthesize.py:92-244`); `GET /voice/profiles` for the selector.
- **Edge cases:**
  - *Gating:* unverified → 403; no ready profiles → empty state linking to upload; `failed` profiles excluded from the selector (server returns 409 for them, `synthesize.py:122-127`).
  - *Text:* 1-500 chars with live counter; trim; reject whitespace-only; pre-warn on emoji/unsupported symbols (R6) while trusting the server's 422 string "Text contains characters unsupported by the SV2TTS symbol set: …" (`schemas/synthesize.py:60-65`); the message arrives as `detail[]` (validator error) → map to the text field. Allowed set: Latin text, digits (read as words), basic punctuation ( !'"(),-.:;? ).
  - *Server errors:* 404 profile deleted elsewhere → refresh selector; 403 not owner (stale cache / tampering); 409 not ready; 429 "busy" (queue full, no Retry-After, G-05) → backoff UI; **429 per-IP 5/min** (`synthesize.py:93`) → different body shape `{error}` handled by the normalizer; 503 overloaded / DB (with Retry-After when DB); 500 generic. No automatic retry (R5).
  - *Long-running:* an indeterminate progress UI with elapsed timer and honest copy ("can take up to a minute or more on slow servers"), cancel button (R7: aborts the browser request only), `beforeunload` warning (R9), long Axios timeout. On timeout/network error: do **not** assume failure; refetch history to see whether a row was recorded (R5), then let the user retry.
  - *Result:* response is `audio/wav` → `Blob` → object URL → player; filename from `Content-Disposition` only if exposed (BD-2); else generate a client filename. **Workaround for G-02 until BD-2:** treat the result as ephemeral ("Download now; later playback depends on History"), and match to history by `(voice_profile_id, input_text, created_at ≈ now)` — heuristic, flagged **Proposal**, and dropped once BD-2 lands.
  - *Player:* load errors (`error` event, unsupported codec — WAV PCM16 mono is universally supported), play/pause, seek, download, replace-on-regenerate (R15), keyboard + screen reader labels.
  - *Regenerate with different text* keeps the selected voice (per `project_description.md:23`); double-click guard (R4).
  - *Provenance:* generated files carry a "synthetic speech" metadata tag (`tts_pipeline.py:702-720`); the UI should label results "AI-generated voice" (**Proposal**, aligns with the responsible-use intent of `HARDENING_PLAN.md` §4 item 8).
- **Tasks:** `TextToSpeechForm`, `VoiceProfileSelect`, `AudioPlayer`, long-request UX, result card, error mapping, history invalidation on success/ambiguous failure.
- **Tests:** *Unit:* counter/trim, filename fallback, Blob-error parser (JSON inside Blob), object-URL revoke on replace. *Integration (MSW):* 200 `audio/wav` with delay + abort; 422 list-detail; 404/403/409/429 (both shapes)/503/500; network drop after request sent → ambiguous-state flow. *E2E:* real backend with the repo's test model setup (**Assumption**: a mocked-weights mode is available to e2e; if not, a manual real-weights run is a release gate): generate → play → download → regenerate; 6th synth in a minute shows 429 UX.
- **Deliverables:** `/dashboard` generate flow.
- **Exit criteria:** one request per submit (asserted via MSW call count); cancel leaves UI idle and history consistent; object URLs revoked (asserted); every status code in §R3 has a tested message.
- **Dependencies:** Phase 3. BD-2 (strongly), BD-3 (nice). **Risks:** G-03 timeouts behind a proxy/CDN (hosting idle timeout unknown, Q4); CPU latency >60 s making the UX poor — may justify a backend async-job redesign (out of scope here, flagged in Q3).

### Phase 5 — History and account management
- **Goal:** users can review past generations, manage their name, and erase their account.
- **Features:** F19, F20 (blocked on BD-1), F21, F22, F6 (profile display).
- **Endpoints:** `GET /synthesize/history`; `PATCH /auth/me`; `DELETE /auth/me`; `GET /auth/me` (`synthesize.py:247-290`; `auth.py:572-619`).
- **Edge cases:**
  - *History:* `limit`/`offset` ("Load more", R12); API clamps `limit` to 50 and rejects `limit < 1`/`offset < 0` with 422 (`synthesize.py:249-258`); no total → `has_more` by page fullness; empty state; join profile name from the cached profiles list (profile deleted → its generations are hidden by the server filter, `synthesize.py:263`); **failed rows** (`output_filename == ""`, `duration == null`) rendered as "Failed — no audio" or hidden (decision Q6); long `input_text` truncated with expand; locale timestamps (R18); stale list after new synthesis → invalidate; concurrent tabs (R11).
  - *Audio (F20):* **until BD-1: show text, duration and date only, with a disabled/absent play button and explanatory copy**; **after BD-1:** lazy-fetch the blob on play (Authorization header, so not a plain `<audio src>`), handle 404/410 "expired after 30 days" (G-10, `config.py:191`) and per-IP 120/min on bursts.
  - *Name edit:* 1-255, non-blank (`schemas/auth.py:58-64`); blank → server 422; optimistic update with rollback; `PATCH` with `null` is a no-op server-side (`auth.py:581`) so never send it.
  - *Account display:* provider shown from `provider` (G-07: may read "google" while a password also exists); avatar `avatar_url` may be null or an external URL → image domain allow-list in CSP `img-src` (**Proposal**), fallback initials.
  - *Delete account:* irreversible; typed confirmation; password field shown with copy "leave blank if you only use Google" (G-07 workaround; BD-5 removes ambiguity); server returns **403 "Incorrect password"** and is counted per user against the same 10-per-15-min failure limit as login (separate counter keyed `user:<id>`, `auth.py:604-612`; `login_throttle.py:34-36`), and the route also has the per-IP `AUTH_LOGIN_RATE_LIMIT` (`auth.py:590`) → 429 with `Retry-After` (per-account case) handled; Axios must send a JSON body on DELETE (`data:`) (G-12); success 204 → clear all client state, cross-tab logout, goodbye page; network failure mid-delete → refetch `/me`: a 401 means it succeeded.
  - *Auth expiry mid-flow:* R2.
- **Tasks:** history list with load-more; history item component; profile/account page; name form; delete-account dialog; wire BD-1 behind a feature flag.
- **Tests:** *Unit:* `has_more` logic, failed-row classifier, delete-request builder includes body. *Integration (MSW):* pagination edge (0, exactly 50, 51 rows), 422 on bad params, 403/429 on delete, 204 flow. *E2E:* generate → appears in history; rename; delete account → signed out and login fails afterwards.
- **Deliverables:** `/profile` complete.
- **Exit criteria:** history never shows duplicates across pages (key by `id`); account deletion leaves no cached data (asserted); F20 flag-off state is clearly communicated.
- **Dependencies:** Phase 4. BD-1 for F20, BD-5/BD-6 optional. **Risks:** F20 slipping; history without profile names if profiles list is large.

### Phase 6 — Advanced input: in-browser recording
- **Goal:** record a sample directly (the "AudioUploader" experience in `project_description.md:129`) without leaving the app.
- **Features:** F14.
- **Endpoints:** `POST /voice/upload` (same as Phase 3).
- **Edge cases (R10):** feature-detect `navigator.mediaDevices.getUserMedia` and `MediaRecorder`; **insecure context** (needs HTTPS or localhost); permission `NotAllowedError` (denied/dismissed → instructions for the browser), `NotFoundError` (no mic), `NotReadableError` (in use), device unplugged mid-recording; choose a MIME type via `isTypeSupported("audio/webm;codecs=opus")`; if unsupported (Safari/iOS, G-08) hide recording and say why, keeping file upload; recorded blob must satisfy the server rules — length ≥ 2 s of *speech* (trim happens server-side, `audio_processing.py:163-175`) so enforce a UI minimum (e.g. 5 s, **Assumption**; docs recommend 10-30 s, `project_description.md:18`) and a maximum well under 300 s and 25 MB; chunk collection; stop on tab hide/visibility change; recording timer and level meter with reduced-motion fallback; re-record/discard; preview before upload; release the stream tracks on stop/unmount; auto-stop at the max duration; do not upload partial blobs after an error; **sniff check:** the WEBM container's first 64 bytes must contain `webm` (`audio_processing.py:60`), which Chromium/Firefox output satisfies (**Assumption**, verify with a real recording in e2e).
- **Tasks:** `Recorder` component; permission-flow UX; preview player; reuse Phase 3 upload mutation.
- **Tests:** *Unit:* state machine (idle→requesting→recording→stopped→uploaded/error), duration limits. *Integration:* mocked `MediaRecorder`/`getUserMedia` for each failure mode; `isTypeSupported` false path. *E2E:* Chromium with `--use-fake-device-for-media-stream` records and uploads; Firefox smoke; Safari recorded as manual check.
- **Deliverables:** recorder in the "New voice" dialog.
- **Exit criteria:** every denial/failure path ends in a clear, recoverable state; mic indicator off after stop (tracks stopped, asserted).
- **Dependencies:** Phase 3. **Risks:** Safari/iOS format gap (needs backend MP4/M4A support — Q5); noisy recordings rejected server-side with 422 only after a full upload.

### Phase 7 — Hardening
- **Goal:** make the shipped features safe, accessible, fast and observable.
- **Features:** all.
- **Edge cases:** the full R1-R18 audit; cross-browser; offline/slow network; `prefers-reduced-motion`; high-zoom (400 %).
- **Tasks**
  1. Security headers and CSP (§5.9) with report-only soak, then enforce; `Referrer-Policy` per route; dependency audit; check no secret/`NEXT_PUBLIC_` leaks.
  2. Accessibility audit (axe in CI + manual NVDA/VoiceOver pass) for every flow, including the player and recorder.
  3. Performance: Lighthouse CI budgets (**Proposal:** LCP < 2.5 s on 4G for `/` and `/login`, JS < 200 KB gz on public routes); lazy-load recorder.
  4. Resilience chaos tests: throttle/offline in Playwright for upload and synthesis; kill the backend mid-request; DB-down 503 with Retry-After (`db_errors.py:24-44`).
  5. Multi-tab suite: logout, refresh storms, profile changes (R11).
  6. Observability: Sentry release/sourcemaps, PII scrubbing test, web vitals.
  7. Contract tests: each MSW fixture validated against the backend's OpenAPI to prevent drift (G-15 shows docs drift easily).
  8. Remove G-02/G-06/G-07 workarounds if the matching BD items shipped.
- **Tests:** a11y (axe, zero serious/critical); e2e full regression on Chromium + Firefox; visual smoke on 3 viewports; security header assertions.
- **Deliverables:** passing hardening checklist, CSP in enforce mode, perf report.
- **Exit criteria:** §9 items 1-12 satisfied. **Dependencies:** Phases 1-6. **Risks:** CSP breaking Next.js inline scripts (nonce setup), Safari quirks.

### Phase 8 — Release
- **Goal:** deploy and verify against the production-like environment.
- **Tasks:** deploy web on a domain **same-site** with the API (e.g. `app.example.com` + `api.example.com`; `RAILWAY_DEPLOYMENT.md:91-94`); set backend `ALLOWED_ORIGINS`, `FRONTEND_URL`, `GOOGLE_REDIRECT_URI`, a verified email domain; register Google redirect; Referrer-Policy and CSP on the host; error-tracking project; runbook (rollback, cookie/CORS troubleshooting); smoke script.
- **Release checks (manual + scripted):** sign up → real verification email → verify; Google sign-in with a real account; upload a real sample; synthesize on the production CPU (measure latency, feed back to Q3/Q4); history; delete profile; delete account; `/metrics` unaffected.
- **Exit criteria:** §9 fully ticked; owner sign-off. **Dependencies:** Phase 7; backend deployed with working email (open per `HARDENING_PLAN.md` §4 item 2). **Risks:** hosting idle timeout shorter than synthesis time (Q4); cookie not sent cross-site (G-13).

---

## 8. Traceability matrix

Test types: **U** unit, **I** integration (MSW), **E** e2e (Playwright), **M** manual release check.
"Edge cases" lists the §6 rule IDs plus feature-specific items from §7.

| Feature | Phase | Edge cases covered | Tests |
|---|---|---|---|
| F1 Landing | 1 | R1, R14 | I, E, a11y |
| F2 Signup | 1 | R3 (409/422/429), R4, R5, R6, G-06 workaround, ambiguous retry | U, I, E |
| F3 Login | 1 | R3 (401/429), R4, G-19 copy, throttle `Retry-After`, `next` sanitizing | U, I, E |
| F4 Session/refresh | 1 | R2, R5 (never retry), R11, G-22 single-flight + tab lock, Strict-Mode guard | U, I, E |
| F5 Logout | 1 | idempotent, offline logout, cross-tab (R11), R16 cache clear | I, E |
| F6 Current user | 1, 5 | R1, unverified banner, G-07 | I, E |
| F7 Verify email | 2 | fragment handling, 400 expired/used, idempotent, R3 | U, I, E |
| F8 Resend verification | 2 | 202 vs 200 "already verified", 429 5/hour, 401, R4 | I, E |
| F9 Forgot password | 2 | neutral copy, Google-only mail, 429, R4 | I, E |
| F10 Reset password | 2 | fragment, 400 reuse/expiry, session revocation, R6 | U, I, E |
| F11 Google sign-in | 2 | 4 error codes, callback bootstrap, cookie-blocked help, 429-as-JSON | U, I, E, M |
| F12 Terms | 3 | 409 version change, `url == null` (G-18) | I |
| F13 Upload sample | 3 | R3 (403/409/413/422/429/503/500), R4, R5, R6, R8, R9, G-11 failed rows, consent | U, I, E |
| F14 Recording | 6 | R10 (all mic errors, unsupported browsers), duration/size limits, track release | U, I, E, M (Safari) |
| F15 List profiles | 3 | R1, R11, R12, sort, failed rows | I, E |
| F16 Delete profile | 3 | 400/404, confirm, optimistic rollback, history invalidation | I, E |
| F17 Synthesize | 4 | R3 (all), R4, R5, R6, R7 cancel, R9, R13, G-02/G-03 workarounds | U, I, E, M |
| F18 Play/download result | 4 | R15 blob lifecycle, player errors, a11y | U, I, E |
| F19 History list | 5 | R12 pagination, failed rows, stale (R11), R18 | U, I, E |
| F20 Past-audio playback | 5 (blocked on BD-1) | 404/410 expiry (G-10), auth header fetch | I, E (after BD-1) |
| F21 Edit name | 5 | R6, null no-op, optimistic rollback | U, I, E |
| F22 Delete account | 5 | 403 password, 429 throttle, DELETE-with-body, ambiguous failure, cache clear | U, I, E |
| F23 Health banner | 0 | R17 | I, E |

Reverse check (every phase item maps to a feature): Phase 0 → F23 + infrastructure; Phase 1 → F1-F6; Phase 2 → F7-F11; Phase 3 → F12, F13, F15, F16; Phase 4 → F17, F18; Phase 5 → F6, F19-F22; Phase 6 → F14; Phases 7-8 → cross-cutting verification of all features. Every feature F1-F23 appears in at least one phase.

---

## Task Status Log

Legend: ✅ Done and verified · 🟡 Partial (works, named gap remains) · ⬜ Not started.

| Phase | Status | Commit | Notes |
|---|---|---|---|
| 0 — Foundation & contracts | 🟡 Partial | `63d2bd4` | Tasks 1-7 and 9 done; task 8 (CI) partly; Playwright e2e and OpenAPI type generation not done. Details below. |
| 1 — Signup, login, session core | 🟡 Partial | `36a424f` | All app code and unit/integration tests done; Playwright e2e and real-backend run not done. Details below. |
| 2 — Email lifecycle, Google | 🟡 Partial | `a6c2913` | All app code and unit/integration tests done; real-email and real-Google e2e not done. Details below. |
| 3 — Voice profiles | 🟡 Partial | `9b131dc` | All app code and unit/integration tests done; e2e and real-backend upload not done. Details below. |
| 4 — Synthesis | 🟡 Partial | `91efb3d` | All app code and unit/integration tests done; e2e and real-weights run not done. Details below. |
| 5 — History & account | 🟡 Partial | `40a05a7` | All app code (F19-F22) and unit/integration tests done; e2e and real-backend run not done. Details below. |
| 6 — In-browser recording | ⬜ | | Next step. |
| 7 — Hardening | ⬜ | | |
| 8 — Release | ⬜ | | |

### FE-P0 — Phase 0 (2026-10-06, branch `feat/FE-P0-foundation`)

| Task | Status | Evidence |
|---|---|---|
| 1 Scaffold Next 14 + TS strict + Tailwind, ESLint, Prettier, `tsc` | ✅ | `npm run typecheck`, `lint`, `format:check` clean; `npm run build` succeeds (87.5 kB first-load JS on `/`). shadcn/ui **not** added: no component needs it yet (`cn` helper in `lib/utils.ts`; add primitives per phase). |
| 2 Axios client | ✅ | `lib/api/http.ts`: `withCredentials`, 15 s default / 120 s long timeout, every failure becomes `ApiError`. `X-Request-ID` captured when exposed (BD-2 shipped). |
| 3 `ApiError` normalizer | ✅ | `lib/errors.ts`; `tests/errors.test.ts` covers `{detail:str}`, `{detail:[…]}`, `{error:str}`, Blob JSON, Blob text, empty, network, timeout, cancel, 5xx text suppression, 403/409 string→kind table, `Retry-After`. |
| 4 Query provider (R5), Sonner, error boundaries, theme tokens | ✅ | `lib/query.ts` (retry only network/502/503/504, max 2, mutations never); `app/error.tsx`, `global-error.tsx`; light/dark CSS tokens. |
| 5 MSW handlers + Vitest/RTL | ✅ | `mocks/handlers.ts` covers every endpoint in §3; `onUnhandledRequest: "error"` so tests cannot reach live services. |
| 6 Env validation | ✅ | `lib/env.ts` + `tests/env.test.ts`; the app and build fail fast without `NEXT_PUBLIC_API_BASE_URL`. |
| 7 Local dev recipe | ✅ | `frontend/README.md`, `frontend/.env.example`. |
| 8 CI | 🟡 | `.github/workflows/frontend.yml` (format, lint, typecheck, test, build) **not yet run on GitHub**. OpenAPI type-generation job not written. |
| 9 App shell | ✅ | skip-link, header, footer, `DegradedBanner` (F23/R17) with tests for 503, healthy and probe-failure. |

**Verification run (local, Node 24):** `npm test` → 5 files, 36 tests passed, zero failures; `typecheck`, `lint`, `format:check` clean; `npm run build` OK with `NEXT_PUBLIC_API_BASE_URL` set. Backend untouched, so the backend suite was not re-run.

**Open items from FE-P0**
1. **Security audit — Next 14.x.** `npm audit --omit=dev` reports 1 critical/1 high (Next 14.2.35 and its bundled postcss); fixes exist only in Next 15/16. The plan mandates Next 14 (Doc), so the upgrade is an **owner decision (new Q8)**; the CI audit step is `continue-on-error` until decided. Dev-only advisories (vitest → tinypool/vite) do not ship. This blocks Definition of Done item 8.
2. **Q1/Q2 assumed, not confirmed.** Work followed the plan's own assumption ("drop NextAuth"; backend gate treated as met since FE-1/FE-2 landed). BD-3 (stable error codes) is still open, so the string→`kind` table remains in `lib/errors.ts`.
3. **Not done from Phase 0:** Playwright e2e ("app boots, banner on 503"), ADR for "no NextAuth", Lighthouse/viewport checks at 320/768/1280 px (layout is responsive by construction but not measured), OpenAPI-generation CI job.
4. Phase 0 exit criteria are therefore **not fully met** (CI not yet green on GitHub; viewport check pending).

### FE-P1 — Phase 1 (2026-10-06, branch `feat/FE-P1-auth-session`, commit `36a424f`)

| Task | Status | Evidence |
|---|---|---|
| Session core, single-flight refresh + cross-tab Web Lock/BroadcastChannel (G-22) | ✅ | `lib/auth/session.ts`. Token is module memory only. A tab that waited on the lock adopts a token broadcast meanwhile instead of refreshing. |
| Axios 401 interceptor: one refresh, one retry, concurrent callers share it | ✅ | `lib/api/http.ts`; auth endpoints excluded; a request whose token was already replaced retries without refreshing; failed refresh ends the session. |
| `AuthProvider` bootstrap (`/refresh` then `/me`), Strict-Mode guard | ✅ | `components/auth-provider.tsx`; signed-out is silent (no toast); unreachable API falls back to signed-out UI. |
| `AuthGate` (client-side), skeleton during bootstrap, `?next=` redirect | ✅ | `components/auth-gate.tsx`, `app/(app)/layout.tsx`, placeholder `/dashboard`. |
| `next` sanitizer (open-redirect) | ✅ | `lib/auth/next-path.ts`; rejects absolute, `//`, backslash, control chars. |
| Signup / login forms (react-hook-form + zod mirroring backend bounds) | ✅ | 409 → email error + sign-in link; 422 → fields; 429 → `Retry-After` copy; 401 → one generic message (G-19); one request per submit. Signup uses the FE-2 cookie, so no re-login workaround. |
| Landing CTA (F1), header user menu, logout (offline-safe, cache cleared, cross-tab) | ✅ | `app/page.tsx`, `components/user-menu.tsx`. |

**Verification run (local, Node 24):** `npm test` → 10 files, **84 tests passed**, zero failures and zero warnings; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (`/login` 156 kB first-load JS). Backend untouched, suite not re-run. Exit-criteria status: reload keeps session (bootstrap test) ✅; 100-iteration concurrent-refresh test never nulls a session ✅ (unit level against MSW); no token in storage ✅ (asserted in jsdom).

**Open items from FE-P1**
1. **No Playwright e2e and no run against the real backend.** The e2e set (signup → reload → logout, two-tab session, expired-token recovery) and the real-cookie behaviour (`Secure` on `http://localhost`, G-13) are **unverified**; the cross-tab lock is only tested with a fake `navigator.locks`. Next to build when the e2e harness is added (Phase 7 or sooner).
2. Phase 1 edge cases not built: unverified-email banner (belongs to Phase 2), ambiguous-timeout signup guidance beyond the 409 link, "refresh replay after grace → forced logout message".
3. Carried over: Q8 (Next 14 advisories), Phase 0 gaps (CI unrun, viewport check).

### FE-P2 — Phase 2 (2026-10-06, branch `feat/FE-P2-email-google`, commit `a6c2913`)

| Task | Status | Evidence |
|---|---|---|
| Fragment-token handling | ✅ | `lib/auth/fragment.ts`: reads `#token=`, strips it with one `history.replaceState`, caches per component so Strict Mode's second effect still gets the token. |
| `/verify-email` | ✅ | Success, "link incomplete" (no API call), 400 invalid/expired (resend if signed in, else sign-in link), idempotent, one POST under Strict Mode; refreshes `/me` on success. |
| `/forgot-password` | ✅ | Identical neutral confirmation (copy also covers Google-only "set a password"); 429 shows a cooldown and does **not** claim the email was sent. |
| `/reset-password` | ✅ | Token from fragment; 8-128 + confirm; success clears the local session (which also logs out other tabs via broadcast, since the server revokes all sessions); 400 → "request a new link"; single-submit guard. |
| Verification banner + resend | ✅ | `components/verification-banner.tsx` in the shell; 202 and 200 both read as success; 429 copy; re-reads `/me` on window focus so verifying elsewhere hides it (R11). |
| Google sign-in | ✅ | Plain `<a>` link on login/signup; `/auth/callback` routes on the bootstrap result; `/login?error=` maps all four backend codes plus client-side `session_unavailable` (cookie-blocked help); unknown code → generic text. |
| `Referrer-Policy: no-referrer` on token pages | ✅ | Verified against a running `next start`: `/verify-email` and `/reset-password` send `no-referrer`; `/login` sends `strict-origin-when-cross-origin`. |

**Verification run (local, Node 24):** `npm test` → 12 files, **113 tests passed**, zero failures/warnings; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (9 routes). Backend untouched, suite not re-run. Exit criteria: all 4 Google error codes render distinct copy ✅ (unit-tested for distinctness); fragment never remains in the URL after load ✅ (asserted); reset clears the session and broadcasts logout to other tabs ✅ (cross-tab delivery itself is unit-level only, see below).

**Open items from FE-P2**
1. **No Playwright e2e and nothing run against the real backend or a real mail/Google round trip.** Unverified: that the real emailed link format `FRONTEND_URL/verify-email#token=…` lands correctly, that Safari/ITP keeps the cookie across the Google redirect (G-13), and the "reset invalidates the other tab" case across two real tabs. The planned e2e (signup → console-log link → verify; forgot → reset; Google error pages) remains to build; a real Google round trip stays a Phase 8 manual check.
2. The Google start link returns raw JSON on a 429 (plan §7 Phase 2 risk); not mitigated.
3. Real email delivery still depends on the backend's verified sending domain (`HARDENING_PLAN.md` §4 item 2).
4. Carried over: Q8 (Next 14 advisories), CI never run on GitHub, Phase 0 viewport check, Phase 1 e2e.

### FE-P3 — Phase 3 (2026-10-06, branch `feat/FE-P3-voice-profiles`, commit `9b131dc`)

| Task | Status | Evidence |
|---|---|---|
| Typed voice API client | ✅ | `lib/api/voice.ts`: list (sorted newest first client-side, G-09), upload (multipart built by the browser, File's own MIME untouched, 120 s timeout, `onUploadProgress`), delete. |
| Client-side file pre-check (R6/R8) | ✅ | `lib/validation/audio.ts`: 0 B, 25 MB + 1 B, type/extension mismatch, parameterised MIME (`audio/webm;codecs=opus`). Content sniffing stays server-side. |
| `AudioUploader` (drag-drop, keyboard, announced errors) | ✅ | `components/audio-uploader.tsx`. |
| Consent + terms version | ✅ | Required checkbox (no request without it); shows the version from `GET /terms`; link or fallback text when `url` is null (G-18); 409 → consent reset, terms refetched, message. |
| Upload form + failure handling | ✅ | Progress bar then "Analysing…"; mapped messages for 403/422 (field and string)/429 busy and rate-limit/503/500/timeout; a network drop reads as "may be too large" (R8); one request per submit; **no auto-retry** (asserted); `beforeunload` warning only while running (R9); list is resynced after every failure so `failed` rows appear (G-11). |
| Profile list | ✅ | Skeleton, empty, error + retry, status chips, failed-row hint, locale timestamps; confirmed delete (warns generations are erased), optimistic removal with rollback, 404 counted as gone, history cache invalidated. |
| `VoiceProfileSelect` for Phase 4 | ✅ | Ready profiles only; empty-state link to `/profile`. |
| `/profile` page + nav link | ✅ | `app/(app)/profile/page.tsx` holds the Voices section; account and history join in Phase 5. |

**Verification run (local, Node 24):** `npm test` → 14 files, **141 tests passed**, zero failures/warnings; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (`/profile` 166 kB first-load JS). Backend untouched, suite not re-run. Exit criteria: every upload failure resyncs the list ✅; no auto-retry of POST ✅ (asserted); consent cannot be bypassed ✅ (asserted).

**Deviations and open items from FE-P3**
1. **Unverified users are not hard-blocked.** The plan says to disable the form; the form instead shows a notice with a resend link and lets the server answer 403 (mapped to a clear message). Reason: `REQUIRE_EMAIL_VERIFICATION=false` is a supported dev setting and the client cannot read it, so disabling would lock out those environments. Revisit if the owner prefers the strict behaviour.
2. **Multipart body not asserted at the wire.** jsdom's XHR gives MSW an unreadable `FormData`, so the field names/values are asserted at the Axios call instead (`name`, `consent_confirmed`, `terms_version`, `file`, File type, timeout). A real upload against the backend is **unverified**; no Playwright e2e exists (the plan's `sample_5sec.wav` upload, 0-byte and renamed-text-file cases remain to build).
3. Real **413** behaviour (may surface as a network error) is only simulated; progress-bar rendering at real speeds is untested.
4. No cross-tab `profiles-changed` broadcast; tabs resync on window-focus refetch instead.
5. Carried over: Q8 (Next 14 advisories), CI never run on GitHub, Phase 0 viewport check, Phase 1-2 e2e.

### FE-P4 — Phase 4 (2026-10-06, branch `feat/FE-P4-synthesis`, commit `91efb3d`)

| Task | Status | Evidence |
|---|---|---|
| Synthesis client | ✅ | `lib/api/synthesize.ts`: JSON body, `responseType: "blob"`, 120 s timeout, abortable. Filename and **generation id** come from `Content-Disposition` (exposed by FE-1), so the G-02 heuristic match against history is not needed and was not built. |
| Text rules (R6) | ✅ | `lib/validation/text.ts`: trimmed 1-500; live counter; emoji pre-warning only; the server's 422 text is shown verbatim on the text field. |
| `TextToSpeechForm` on `/dashboard` | ✅ | Voice select (ready profiles only), textarea, elapsed-time progress with honest "a minute or more" copy, **Cancel**, `beforeunload` warning only while running, one request per submit (asserted), never auto-retried. |
| Error handling (R3/R13) | ✅ | 404/403/409 → message and profile list refetched; 403 unverified; 422 list-detail → text field; 429 (both `{error}` and `{detail}` shapes) and "service busy" → countdown that disables the button (`Retry-After` if sent, else 60 s / 15 s); 503, 500; JSON error bodies inside Blobs are decoded. |
| Ambiguous failures (R7/R9) | ✅ | Timeout/network drop does not claim failure ("may still have been generated, check History") and invalidates history; Cancel aborts only the browser request, says so, and invalidates history. |
| Player + download (R15) | ✅ | `components/audio-player.tsx` (native controls, labelled, decode-error state that keeps Download), labelled "AI-generated voice"; object URL revoked on replace and on unmount (asserted); client filename fallback. |
| Form state survives re-login (R2) | ✅ | In-memory draft (`lib/draft.ts`, never persisted; cleared on sign-out). |
| Success invalidates history | ✅ | Asserted. |

**Verification run (local, Node 24):** `npm test` → 15 files, **167 tests passed**, zero failures/warnings, stable over three consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (`/dashboard` 156 kB first-load JS). A test fix en route: the `AuthProvider` was missing its `clearDraft` import, caught by the existing logout/reset tests. Backend untouched, suite not re-run. Exit criteria: one request per submit ✅ (asserted); cancel leaves the UI idle and history refreshed ✅; object URLs revoked ✅; every R3 status has a tested message ✅ (404, 403, 409, 422, 429 x2, 503, 500, network).

**Open items from FE-P4**
1. **Never run against real weights or the real backend.** Actual latency, the browser's real behaviour with a long-held request behind a proxy (Q3/Q4), and real WAV playback are **unverified**; no Playwright e2e (generate → play → download → regenerate; 6th request in a minute).
2. jsdom cannot play audio, so playback is only tested by the player's error state and link wiring.
3. The cooldown uses fixed defaults because the "service busy" 429 sends no `Retry-After` (G-05, BD-3 still open).
4. As in Phase 3, unverified users get a notice rather than a disabled form (server answers 403 with a mapped message).
5. Carried over: Q8 (Next 14 advisories), CI never run on GitHub, Phase 0 viewport check, Phase 1-3 e2e.

### FE-P5 — Phase 5 (2026-10-07, branch `feat/FE-P5-history-account`, commit `40a05a7`)

| Task | Status | Evidence |
|---|---|---|
| History client | ✅ | `lib/api/history.ts`: `limit`/`offset`, total from `X-Total-Count` (exposed since FE-1), `has_more` from the total (page fullness if the header is unreadable; an empty page always stops), audio blob fetch with the bearer header. |
| History list (F19) | ✅ | `components/history-list.tsx` + `hooks/use-history.ts` (`useInfiniteQuery` on `HISTORY_KEY`, so synthesis/profile deletion already invalidate it): skeleton, empty, error + retry, "Load more", rows de-duplicated by `id`, long text truncated with an expander, voice name from the API (BD-6), locale timestamps, failed rows shown as "Failed — no audio" (Q6 decided: show, labelled). |
| Past-audio playback (F20) | ✅ | Lazy fetch on **Play** (auth header), autoplay in the shared `AudioPlayer`, object URL revoked on unmount (asserted); 404/410 or `audio_available=false` → "expired after 30 days" copy; other errors → alert + retry. |
| Name edit (F21) | ✅ | `components/account-section.tsx`: zod 1-255 trimmed (blank never sent), optimistic update with rollback, server 422 shown on the field; only `{name}` is ever sent. |
| Account display (F6) | ✅ | Email, sign-in method (uses `has_password`, G-07), member-since. |
| Delete account (F22) | ✅ | Typed `DELETE` confirmation; password field only when `has_password` (omitted body field for Google-only); JSON body on DELETE (G-12, asserted); 403 → "incorrect password", 429 → `Retry-After` countdown; success clears session, query cache and other tabs, then routes home; network/timeout failure → re-reads `/me` (401 = it succeeded). |
| `/profile` page | ✅ | Now sections: create voice, voices, history, account; nav link renamed "Account". |

**Verification run (local, Node 24):** `npm test` → 16 files, **188 tests passed** (21 new), zero failures/warnings, two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (`/profile` 183 kB first-load JS). Backend untouched, suite not re-run. Exit criteria: no duplicate rows across pages ✅ (asserted); account deletion leaves no cached data ✅ (asserted); F20 works (BD-1 shipped) with expiry clearly communicated ✅.

**Deviations and open items from FE-P5**
1. **No Playwright e2e, nothing run against the real backend** (generate → appears in history → play; rename; delete account → login fails). Real WAV playback is untestable in jsdom.
2. No dedicated "goodbye" page: after deletion the user gets a toast and lands on `/`.
3. The in-dialog account-deletion UI is a plain inline `alertdialog` (no focus trap), consistent with the Phase 3 delete confirmation; revisit in the Phase 7 a11y audit.
4. History is not bounded by a virtualised list (not needed at ≤ 50 rows per page, but "Load more" accumulates).
5. Carried over: Q8 (Next 14 advisories), CI never run on GitHub, Phase 0 viewport check, Phase 1-4 e2e.

---

## 9. Definition of Done (release checklist)

**Functional**
1. All features F1-F19 and F21-F23 work end to end against the real backend; F20 either works (BD-1 shipped) or is explicitly hidden with copy.
2. Every status code in R3 has a tested, user-readable outcome for every feature that can produce it.
3. No non-idempotent POST is auto-retried; double-submit produces exactly one request (asserted).
4. Session survives reload and multi-tab use; a 100-iteration concurrent-refresh test never logs a user out (G-22).

**Security & privacy**
5. Access token never persisted to any browser storage; refresh handling relies only on the httpOnly cookie.
6. CSP enforced with no `unsafe-inline`/`unsafe-eval`; security headers present (§5.9); fragment-token pages set `Referrer-Policy: no-referrer` and strip the fragment.
7. No input text, audio, email or token reaches logs, analytics or error reports (tested scrubber).
8. `npm audit` (or equivalent) clean at release; lockfile committed.
9. `next=` redirects validated; no `dangerouslySetInnerHTML`.

**Quality**
10. Unit, integration and e2e suites pass with zero failures/warnings on CI; contract tests match the backend OpenAPI.
11. axe: zero serious/critical issues; keyboard-only and screen-reader pass on login, upload, synthesize, history, account.
12. Works at 320 px - 1920 px, light and dark; Chromium, Firefox and Safari smoke-tested (recording degrades gracefully where unsupported).
13. Performance budgets met (Phase 7); object URLs/streams released (no leak in a 50-generation soak).

**Operations**
14. Web app and API deployed on one registrable domain; `ALLOWED_ORIGINS`, `FRONTEND_URL`, `GOOGLE_REDIRECT_URI` set and verified; Google redirect registered.
15. Real email delivery verified (verified sending domain, inbox arrival confirmed by a person).
16. Hosting idle/request timeouts verified to exceed worst-case synthesis time, or the long-request UX has been validated against the shorter limit (Q4).
17. Error tracking live and tested; runbook (rollback, cookie/CORS diagnostics) written; smoke script green.
18. Documentation reconciled: `CLAUDE.md` §7 and `project_description.md` endpoint tables updated to `/api/v1` and the full route list (G-15), frontend section added to `README.md`.

---

## 10. Open questions / unverified

### Decisions needed from the owner
| # | Question | Why it changes the plan |
|---|---|---|
| **Q1** | NextAuth v5 is in the documented stack but the backend already does auth (G-14). Drop NextAuth (recommended) or wrap the backend with it? | Changes Phase 0-2 scope and the session model. This plan assumes "drop". |
| **Q2** | `CLAUDE.md` §2 requires a fully hardened backend before frontend work. Does the owner treat BD-1…BD-6 (§4.3) as part of that gate, or accept the F20 gap and workarounds for a first release? | Determines whether Phase 0 starts now and whether F20 ships in v1. |
| **Q3** | Is a long synchronous synthesis request acceptable, or should the backend move to a job pattern (`pending` rows already exist in `DATABASE_DESIGN.md` > Scalability, "Asynchronous Processing")? | A job API would replace the Phase 4 long-request UX with polling and enable resume/cancel. |
| **Q4** | What are the production host/proxy idle timeouts, and what CPU will the API run on? | Not in the repo. Real latency may exceed the 30 s-per-stage timeout (`README.md` > Resource Requirements; `RAILWAY_DEPLOYMENT.md` > Not covered here). Sets frontend timeouts and may force Q3. |
| **Q5** | Should multi-clip profiles (docs: 1-3 clips) and M4A/OGG/MP4 input (Safari recording) be added to the backend? | Today single-file WAV/MP3/WEBM only (G-08); affects Phase 3 and 6 scope. |
| **Q6** | In history, show or hide failed generations (G-09)? | UI/list behaviour; or fix server-side via BD-6. |
| **Q7** | Is a "processing" voice-profile status ever going to exist? | Docs list it (`DATABASE_DESIGN.md` > `voice_profiles`); the reviewed upload code never sets it. Determines whether polling a profile is needed. |
| **Q8** | Next 14.x has unfixed advisories (fixes only in Next 15/16). Upgrade, or accept the risk for now? | The Doc mandates Next 14; blocks Definition of Done item 8. |

### Unverified (could not be confirmed from the repo)
1. **Hosting behaviour:** Railway/edge proxy request timeouts and body-size limits; whether `X-Forwarded-*` is set as `TRUSTED_PROXY_COUNT=1` assumes (`RAILWAY_DEPLOYMENT.md:53`, "confirm in staging").
2. **Browser cookie behaviour:** `Secure` cookie on `http://localhost` in Safari; third-party-cookie/ITP effects on the Google redirect hop (G-13).
3. **Plain-text 500s:** that non-DB unhandled exceptions return Starlette's plain-text body (G-04 d) — inferred, not exercised.
4. **Client abort vs server work:** that cancelling a synthesis request does not stop inference (R7) — inferred from the absence of cancellation code.
5. **413 delivery:** that the body-limit 413 may surface as a network error in browsers (R8) — inferred from `Connection: close`.
6. **MediaRecorder output** passes the server's magic-byte sniff in current Chromium/Firefox (Phase 6) — to be verified with a real recording.
7. **Whether the `processing` profile status** and the DB's `tts_metadata`/`preferences` JSON columns are exposed anywhere — they are not in any reviewed schema.
8. **Files not reviewed** (§1): `refresh_token.py` and `user_identity.py` models, `tts_pipeline.py` beyond the pipeline signature, tests, Alembic, Dockerfile/compose/railway/CI. None are expected to change the UI contract, but nothing is claimed about them.
9. **Real email delivery and verified sending domain** are still open on the backend side (`HARDENING_PLAN.md` §4 item 2) and gate Phases 2 and 8.
10. **`HARDENING_PLAN.md` was read selectively**; there may be client-relevant notes in log rows not opened.
