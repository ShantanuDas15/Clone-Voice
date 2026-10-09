# CloneVoice — Frontend Phase-Wise Implementation Plan

> **Status:** IN PROGRESS — Phase 0 (FE-P0, `63d2bd4`) Phase 1 (FE-P1, `36a424f`) Phase 2 (FE-P2, `a6c2913`) Phase 3 (FE-P3, `9b131dc`) and Phase 4 (FE-P4, `91efb3d`) implemented 2026-10-06 Phase 5 (FE-P5, `40a05a7`) Phase 6 (FE-P6, `67aac76`) the first slice of Phase 7 (FE-P7, `bc5210f`) its e2e/real-backend slice (FE-P7b, `e1a8561`) its browser-audit slice (FE-P7c, `13ca9b1`) its OpenAPI contract-test slice (FE-P7d, `856ef58`) its dialog-focus slice (FE-P7e, `7b69166`) its Lighthouse-budget slice (FE-P7f, `a5a1165`) its Firefox slice (FE-P7g, `0fbbdd8`) its observability slice (FE-P7h, `5b2e25c`) its documentation-reconciliation slice (FE-P7m, `dba0be3`) its CI-perf slice (FE-P7l, `e112ca0`) its soak-test slice (FE-P7k, `fe91eb6`) its narrow-header slice (FE-P7j, `3ace3f4`) and its banner-layout-shift slice (FE-P7i, `4186e42`) implemented 2026-10-07; its backend-alias fix (FE-P7n, `86ce187`) and Phase 8 preparation (FE-P8a, `d012995`: smoke script and runbook; FE-P8b, `a56d97f`: public-suffix same-site check) done, deployment itself not started. See the Task Status Log below.
> **Last reviewed:** 2026-10-09. UX-plan slices FE-UX0 (brand, tokens, fonts, theme toggle) FE-UX1 (Button, Alert, Badge primitives) FE-UX2 (Input, Select, Textarea), FE-UX3 (route split and rename) FE-UX4 (tab bar, inline verify alert, two-column layouts) FE-UX5 (first-run checklist, blocked-Generate reason, voice CTA) FE-UX6 (landing page, auth polish, copy pass) FE-UX7 (progress, result actions, file drop zone) FE-UX8 (Dialog primitive, session-ended message) FE-UX9 (offline handling, error recovery, empty-state actions) FE-UX10 (Take player with waveform) FE-UX11 (live level meter) and FE-UX12 (motion tokens, dialog fade, waveform draw-in) implemented the same day; FE-UX13 (radio keyboard model) FE-UX14 (prefers-contrast tokens, logo touch target) FE-UX15 (perf budget check) FE-UX16 (docs) and FE-UX17 (e2e run and fixes) followed on 2026-10-09.
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
| 6 — In-browser recording | 🟡 Partial | `67aac76` | Recorder, state machine, form integration and unit/integration tests done; e2e, real-browser recording and level meter not done. Details below. |
| 7 — Hardening | 🟡 Partial | `bc5210f`, `e1a8561`, `13ca9b1`, `856ef58`, `7b69166`, `a5a1165`, `0fbbdd8`, `5b2e25c`, `4186e42`, `3ace3f4`, `fe91eb6`, `e112ca0`, `86ce187` | CSP, axe (jsdom and real browser), guardrail tests, responsive and resilience audits, a 33-test Playwright suite against the real backend, and OpenAPI contract tests and modal-dialog focus management and a Lighthouse budget gate and a Firefox e2e project and PII-scrubbed error reporting with web vitals (and a header CLS fix) done; Safari, the screen-reader pass, a real Sentry project and sourcemaps not done. Details below. |
| 8 — Release | 🟡 Preparation only | `d012995`, `a56d97f` | Smoke script (`npm run smoke`) and `frontend/RUNBOOK.md` done and exercised against a local stack. Nothing deployed: needs hosting, a domain, real email and Google registration, and owner decisions Q3, Q4, Q8. Details below. |

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

### FE-P6 — Phase 6 (2026-10-07, branch `feat/FE-P6-recording`, commit `67aac76`)

| Task | Status | Evidence |
|---|---|---|
| Feature detection (R10) | ✅ | `lib/recording.ts` `detectRecordingSupport()`: insecure context, missing `getUserMedia`/`MediaRecorder`, no WEBM type (Safari/iOS, G-08) each give a distinct reason; the form then hides "Record now" and keeps file upload with the explanation. Prefers `audio/webm;codecs=opus`. |
| Recorder state machine | ✅ | `hooks/use-recorder.ts`: idle → requesting → recording → stopped \| error. Tracks always stopped (on stop, discard, error, unmount, and when a permission grant arrives after Cancel); auto-stop at 120 s; stop when the tab is hidden; mic unplugged mid-take → error and **no blob**; takes under 5 s yield an error, never a file. |
| Permission/device errors | ✅ | `NotAllowedError`/`SecurityError`, `NotFoundError`/`OverconstrainedError`, `NotReadableError`/`AbortError`, other → four distinct recoverable messages with "Try again". |
| `Recorder` UI | ✅ | `components/recorder.tsx`: timer, Stop disabled until 5 s, discard, preview player, "Discard and re-record"; result handed on as `recording.webm` with plain `audio/webm` type. |
| Reuse of the Phase 3 upload | ✅ | `UploadVoiceForm` gains an "Upload a file / Record now" radio group; same consent, validation, progress and error handling; one request per submit; recorder remounted after success. The recorder is lazy-loaded (`next/dynamic`, `ssr: false`). |

**Verification run (local, Node 24):** `npm test` → 17 files, **205 tests passed** (17 new: helpers, each mic error, min-length gating, preview + File type, discard, auto-stop at max, unplug, hidden tab, unmount, late-grant release, form integration, unsupported-browser fallback), zero failures/warnings, two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (`/profile` 184 kB first-load JS; recorder is a separate chunk). Backend untouched, suite not re-run. Exit criteria: every denial/failure path ends in a clear, recoverable state ✅; mic tracks stopped after stop/discard/unmount ✅ (asserted against a fake `MediaStream`).

**Deviations and open items from FE-P6**
1. **Never run in a real browser.** `MediaRecorder`/`getUserMedia` are fakes. Unverified: that real Chromium/Firefox WEBM output passes the server's magic-byte sniff (Unverified #6), the real permission prompt, and the planned Playwright run with `--use-fake-device-for-media-stream`. Safari/iOS is a manual check (recording is hidden there by design).
2. **Level meter not built** (plan mentions timer *and* level meter with reduced-motion fallback); a pulsing-free static recording dot and timer are shown instead.
3. A recording is capped at 120 s (plan: "well under 300 s"); minimum 5 s is the plan's own assumption.
4. A noisy or silent take is still rejected by the server only after a full upload (422, shown verbatim).
5. Carried over: Q8 (Next 14 advisories), CI never run on GitHub, Phase 0 viewport check, Phase 1-5 e2e.

### FE-P7 — Phase 7, first slice (2026-10-07, branch `feat/FE-P7-hardening`, commit `bc5210f`)

| Task | Status | Evidence |
|---|---|---|
| 1 Security headers + CSP | 🟡 | `middleware.ts` + `lib/csp.ts`: per-request nonce; `script-src 'self' 'nonce-…' 'strict-dynamic'` (no `unsafe-inline`/`unsafe-eval`, eval only in dev), `style-src` nonce, `connect-src 'self' <API origin>`, `media-src 'self' blob:`, `img-src` + Google avatar host, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri`/`form-action 'self'`. Root layout is `force-dynamic` so Next stamps the nonce. **Verified against a running `next start`:** header present, the nonce in the header matches the `nonce=` on the page's scripts and differs per request, `/verify-email` still sends `Referrer-Policy: no-referrer`, and `CSP_ENFORCE=1` switches the header to enforcing `Content-Security-Policy`. Ships **report-only** by default (the plan's soak step); enforcement is a server env flip. |
| 2 Accessibility audit | 🟡 | `tests/a11y.test.tsx`: axe-core on login, signup, forgot-password, upload (plain and with errors), recorder, profile list (and with delete dialog open), synthesis form, history, account (with delete dialog): zero serious/critical violations; a canary test proves the detector flags an unlabeled input. jsdom has no layout, so **colour-contrast, focus order, zoom and the NVDA/VoiceOver pass are not covered**. |
| 7/8 Guardrails (DoD 5, 7, 9) | 🟡 | `tests/hardening.test.ts` scans app source: no `dangerouslySetInnerHTML`, no `localStorage`/`sessionStorage`/`indexedDB`/`document.cookie`, only the two documented `NEXT_PUBLIC_*` variables, no `console.*`. |
| Reduced motion | ✅ | Already present (`globals.css` `prefers-reduced-motion`). |
| 3 Lighthouse budgets, 4 chaos tests, 5 multi-tab e2e, 6 Sentry/web-vitals, 7 OpenAPI contract tests | ⬜ | Not started (need Playwright, a real backend, or a Sentry project). |

**Verification run (local, Node 24):** `npm test` → 21 files, **228 tests passed** (23 new), zero failures/warnings, two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK (all routes now dynamic, `ƒ`; middleware 26.9 kB). `axe-core` added as an explicit devDependency (was already installed transitively). `npm audit --omit=dev` is unchanged: 1 critical + 1 high, both Next 14 / its bundled PostCSS (Q8). Backend untouched, suite not re-run.

**Open items from FE-P7**
1. **CSP never exercised in a real browser.** It is report-only for that reason. Next's inline bootstrap, `next/font`/style injection or the blob audio element could still produce violations; the soak (browse every flow, read console reports, then set `CSP_ENFORCE=1`) is outstanding, so **Definition of Done item 6 is not yet met**. There is no `report-uri`, so violations are visible only in the browser console.
2. Static prerendering is lost (every page is server-rendered on demand) as the price of nonces; fine for this client-gated app, worth a Lighthouse check.
3. Still open: Lighthouse CI, Playwright suites (Phases 1-6 e2e, multi-tab, chaos, cross-browser), Sentry with PII scrubber, OpenAPI contract tests, removing superseded workarounds, viewport check, Q8 (Next upgrade), CI never run on GitHub.

### FE-P7b — Phase 7, e2e against the real backend (2026-10-07, branch `feat/FE-P7b-e2e`, commit `e1a8561`)

First run of the frontend against the **real FastAPI backend with real SV2TTS weights** (SQLite, `EMAIL_BACKEND=console`, rate limits raised so a fast suite is not throttled) in real Chromium. Recipe in `frontend/e2e/README.md`; run with `npm run test:e2e`.

| Area | Status | Evidence |
|---|---|---|
| Phase 1 e2e | ✅ | `e2e/auth.spec.ts`: signup → reload keeps session → logout → login; **no JWT in local/session storage or readable cookies** (asserted); one generic wrong-password message; **two tabs reloading simultaneously 5 times never log each other out and logout propagates**; a forced 401 mid-session recovers silently. The `Secure` refresh cookie **does work on `http://localhost` in Chromium** (G-13, Chromium half). |
| Phase 2 e2e | ✅ | `e2e/email.spec.ts`: real emailed verification link (decoded from the console MIME message) clears the banner and is idempotent, fragment stripped; forgot → real reset link → password changed, **another browser's session dies**, old password refused, token reuse refused; Google error pages; fragment-less token page. |
| Phase 3 e2e | ✅ | `e2e/voice.spec.ts`: unverified upload refused with a verify message; **real upload of `sample_5sec.wav` creates a Ready profile** (real embedding), then delete; 0-byte file and fake `.wav` rejected; consent required (zero requests without it). |
| Phase 4 e2e | ✅ | `e2e/synthesis.spec.ts`: **real synthesis** → one request, decodable `blob:` WAV (duration > 0.3 s), download named `synthesized_<uuid>.wav` (generation id via CORS-exposed header), shows in history, replays through the authed endpoint; server-refused text shown on the field. ~7 s end to end on this CPU for a short sentence. |
| Phase 5 e2e | ✅ | `e2e/account.spec.ts`: rename persists across reload; delete with wrong password refused, then correct password deletes and login fails afterwards. |
| Phase 6 e2e | 🟡 | `e2e/recording.spec.ts` (Chromium fake microphone): Stop disabled until 5 s, preview shown, one upload sent. **Real Chromium WEBM passes the server's container check** (Unverified #6 resolved for Chromium; first bytes are a valid EBML/`webm` header), but this sandbox has **no ffmpeg**, so the server answered `422 "Could not process this audio file"` (`NoBackendError` from librosa). Decoding a real recording therefore remains unverified until run on a host with ffmpeg (the Docker image installs it). Firefox and Safari not run. |
| CSP soak | ✅ | `e2e/csp.spec.ts` browses every public page, the app, real playback and recording and fails on any `securitypolicyviolation` or console CSP report. **First run found two real violations** (below); after the fixes the whole suite passes both report-only **and with `CSP_ENFORCE=1`**. |

**Defects the real run found, now fixed with regression tests**
1. **Sign-out / account deletion landed on `/login?next=/profile`.** `AuthGate` redirected to sign-in as soon as the session cleared, beating the caller's `router.replace("/")`. Now `signedOutOnPurpose` makes the gate go home; an expired session still goes to sign-in with a return path (`tests/auth-gate.test.tsx`).
2. **A freshly uploaded voice did not appear in the list** until a window-focus refetch (success never invalidated the profiles query; only failures did). Unit tests had missed it because they mocked the list separately (`tests/voice-profiles.test.tsx` now renders form and list together; verified to fail without the fix).
3. **CSP: zod 4's `new Function` JIT probe** was reported as an `unsafe-eval` violation on every page. Fixed with `z.config({ jitless: true })` (`lib/zod-setup.ts`, imported before any schema).
4. **CSP: sonner injects an un-nonced `<style>`** (it has no nonce option). Allowed by two `sha256` hashes (the empty element and its stylesheet), not `unsafe-inline`; `tests/csp.test.ts` recomputes the hash from the installed sonner so an upgrade that changes its CSS fails a test.

**Verification run (local, Node 24, Chromium headless shell 153):** `npm test` → 22 files, **233 tests passed** (5 new), zero failures/warnings, two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npx playwright test` → **18 passed**, in both report-only and `CSP_ENFORCE=1` modes. Backend source untouched (its suite not re-run); the backend ran with a scratch SQLite DB outside the repo.

**Open items from FE-P7b**
1. **CSP Definition-of-Done item 6 is now met in Chromium** but the default stays report-only: flip `CSP_ENFORCE=1` in the deployed environment once Firefox/Safari have been browsed (not done) and a `report-uri` is chosen.
2. e2e is **not in CI** (needs the backend, its weights and a console-mail log); CI still runs only the MSW suite. SQLite was used instead of Postgres.
3. Recording decode on a real host (ffmpeg), Firefox/Safari runs, the rest of Phase 7 (Lighthouse, chaos/offline, Sentry, OpenAPI contract tests, axe in a real browser for colour contrast and focus order), the Phase 0 viewport check, Q8 and CI-never-run-on-GitHub.
4. Unmeasured: real-CPU synthesis latency for long (500-char) texts and behind a proxy (Q3/Q4).

### FE-P7c — Phase 7, browser audits (2026-10-07, branch `feat/FE-P7c-browser-audits`, commit `13ca9b1`)

| Area | Status | Evidence |
|---|---|---|
| Accessibility in a real browser | ✅ (Chromium) | `e2e/a11y.spec.ts` runs axe-core (WCAG 2.0/2.1/2.2 A+AA tags, real layout) in **light and dark**: every public page, `/login?error=…`, the signed-in dashboard and profile, the recorder, both delete dialogs. **Zero serious/critical violations, including colour contrast** (which jsdom could not check). A canary test proves the audit does flag low contrast and an unlabeled input. |
| Responsive (Phase 0 viewport check) | ✅ | `e2e/responsive.spec.ts`: no horizontal scroll and every button/input ≥ 44 px at **320, 768 and 1280 px**, public and signed-in pages, plus a 320 px-wide reflow check (≈400 % zoom). The first run **failed at 320 px**: see defect 1. |
| Resilience / chaos | ✅ | `e2e/resilience.spec.ts`: degraded health pauses generate/upload then recovers; a 503 with `Retry-After` exhausts the two automatic GET retries, shows the error and **Try again** recovers; slow network shows skeletons; a connection reset during synthesis is not called a failure and is **attempted exactly once** (R5); an aborted upload says "interrupted", leaves the list consistent, one attempt; going offline gives "can't reach the server" and works again once online. |

**Defects/gaps found and fixed**
1. **Signed-in header overflowed horizontally at 320 px (53 px) and "Sign out" was 36 px tall.** Nav and menu now wrap, the name truncates, controls are 44 px.
2. **R17 was only half built:** the banner showed but Generate/Create voice stayed enabled while `/health/ready` was 503. A shared `useDegraded()` hook now disables both and says why (`tests/degraded-forms.test.tsx`, including "stays enabled if the probe itself fails").

**Verification run (local, Node 24, Chromium):** `npm test` → 23 files, **236 tests passed** (3 new), two consecutive runs, zero failures/warnings; `typecheck`, `lint` (incl. `e2e/`), `format:check` clean. `npx playwright test` → **32 passed under `CSP_ENFORCE=1`** (the canary was added and run after, 33 tests total) against the real backend with real weights. Backend source untouched, suite not re-run.

**Open items from FE-P7c**
1. Not done in Phase 7: Lighthouse CI budgets, Sentry + PII scrubber, OpenAPI contract tests, Firefox/Safari runs, a **manual NVDA/VoiceOver pass and keyboard-only walkthrough** (axe cannot judge focus order or announcements), dialogs still lack a focus trap, e2e not in CI, SQLite not Postgres.
2. Recording decode still needs a host with ffmpeg (see FE-P7b).
3. Carried over: Q8 (Next 14 advisories), CI never run on GitHub, Q3/Q4 latency unknowns.

### FE-P7d — Phase 7, OpenAPI contract tests (2026-10-07, branch `feat/FE-P7d-contract-tests`, commit `856ef58`)

Phase 7 task 7 and Definition-of-Done item 10 ("contract tests match the backend OpenAPI").

| Area | Status | Evidence |
|---|---|---|
| Snapshot + drift guard | ✅ | `python -m backend.export_openapi` writes `frontend/contract/openapi.json` (OpenAPI 3.1, sorted, deterministic) from the real FastAPI app; `--check` exits 1 if stale. `backend/tests/test_openapi_snapshot.py` fails the backend suite when a schema change lands without refreshing the snapshot, so the frontend can never validate against an outdated contract. |
| Fixtures vs schemas | ✅ | `tests/contract.test.ts` validates the `user`, `profile`, `generation`, `token` and `terms` fixtures against `UserOut`, `VoiceProfileOut`, `GenerationOut`, `TokenResponse`, `TermsOut` (Ajv 2020-12 + formats), and asserts a fixture invents no field the backend lacks. Canaries prove a missing required field or wrong type is rejected. |
| Every default MSW handler | ✅ | Each handler is hit for real: its path and method must exist in the spec, its status must be declared, and a JSON body must match the declared response schema. A guard test lists the endpoints the app calls that must stay mocked. |
| Outgoing requests | ✅ | The real API functions are run against capture handlers and their bodies validated against the request schemas: signup, login, verify-email, forgot-password, reset-password (snake_case `new_password`), `PATCH /auth/me`, `DELETE /auth/me` with and without a password, `POST /synthesize`. Upload's multipart field names are checked against the form schema (all required present, none unknown) and history's `limit`/`offset` against the declared parameters and bounds. A canary proves a payload the backend would 422 is rejected. |

**Drift the contract tests found, now fixed:** four mocks returned bodies the backend never sends. `verify-email`, `resend-verification`, `forgot-password` and `reset-password` all answer `{"detail": "<message>"}` (`MessageResponse`), but the mocks returned `{status:"verified"}`, `{}`, `{}` and `{status:"ok"}`. The client ignores these bodies so nothing was broken, but the mocks now carry the real shape and wording.

**Verification run (local, Node 24):** `npm test` → 24 files, **280 tests passed** (44 new), two consecutive runs, zero failures/warnings; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. Backend: `pytest backend -q` → **898 passed, 1 skipped, 11 warnings** (the known third-party baseline; 4 new tests). Playwright was not re-run: only unit-test mocks changed, no app code. `ajv@8` and `ajv-formats@2` added as devDependencies (v2 because `@hookform/resolvers` declares an optional peer on `ajv-formats@^2`).

**Open items from FE-P7d**
1. The contract covers the JSON and multipart shapes the app uses. It cannot catch what OpenAPI does not describe: error bodies for 4xx other than 422 (G-04), response headers (`X-Total-Count`, `Content-Disposition`, `Retry-After`), cookies, and the untyped `DELETE /voice/profiles/{id}` body (G-12).
2. The frontend `interface`s in `lib/api/*.ts` are still hand-written; they are checked indirectly through the fixtures, not generated from the spec (Phase 0's type generation remains undone).
3. Remaining in Phase 7: Lighthouse CI budgets, Sentry + PII scrubber, Firefox/Safari runs, manual NVDA/VoiceOver and keyboard-only pass, dialog focus trap, e2e in CI, SQLite vs Postgres. Carried over: ffmpeg recording decode, Q8 (Next 14 advisories), CI never run on GitHub, Q3/Q4 latency.

### FE-P7e — Phase 7, modal dialog focus management (2026-10-07, branch `feat/FE-P7e-dialog-focus`, commit `7b69166`)

Closes the gap recorded in FE-P7c ("dialogs still lack a focus trap"). Both confirmation dialogs declared `aria-modal="true"` but behaved like plain boxes: Tab walked into the page behind, Escape did nothing and focus was lost on close.

| Area | Status | Evidence |
|---|---|---|
| Shared `useDialog` hook | ✅ | `hooks/use-dialog.ts`: focus moves in on open (first focusable, else the container); Tab/Shift+Tab cycle inside and pull stray focus back; Escape closes unless `closeDisabled`; focus returns to the opener on close if it is still in the DOM. The opener is captured during the first render because children's `autoFocus` runs before any effect. |
| Delete-voice dialog | ✅ | Extracted to `DeleteDialog`; confirm button keeps initial focus; Escape cancels back to that row's Delete button. |
| Delete-account dialog | ✅ | Wrapped in `ModalPanel`; the first field is focused; **Escape is ignored while the deletion request is in flight** (as Cancel already was). The "Delete my account…" trigger now stays mounted while the dialog is open (it used to unmount, which would have made focus-restore impossible). |
| Tests | ✅ | `tests/dialog.test.tsx` (9): cycling, disabled controls skipped, stray focus recovered, Escape, Escape blocked, empty dialog, and both real dialogs. **Verified to fail without the hook** (6 of 9 fail with its listener and focus-restore removed; the other 3 assert absences). `e2e/dialog-keyboard.spec.ts` drives both dialogs by keyboard in real Chromium: 6-8 Tab presses never leave, Shift+Tab, Escape restores the opener. |

**Verification run (local, Node 24, Chromium):** `npm test` → 25 files, **289 tests passed** (9 new), two consecutive runs, zero failures; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npx playwright test` against the real backend with real weights under `CSP_ENFORCE=1` → **34 passed** (the real-browser axe audits of both dialogs still report zero serious/critical issues with the changed markup). Backend source untouched. The axe `_isIconLigature` stderr lines in `a11y.test.tsx` are jsdom noise present before this change.

**Open items from FE-P7e**
1. Background content is not `inert`; the trap relies on key handling, so a screen reader's virtual cursor can still browse behind the dialog (`aria-modal` covers most readers). The manual NVDA/VoiceOver pass is still outstanding.
2. Remaining in Phase 7: Lighthouse CI budgets, Sentry + PII scrubber, Firefox/Safari runs, the manual screen-reader and keyboard-only walkthrough of the remaining flows, e2e in CI, SQLite vs Postgres. Carried over: ffmpeg recording decode, Q8 (Next 14 advisories), CI never run on GitHub, Q3/Q4 latency.

### FE-P7f — Phase 7, Lighthouse performance budgets (2026-10-07, branch `feat/FE-P7f-lighthouse`, commit `a5a1165`)

Phase 7 task 3 and Definition-of-Done item 13 (performance budgets). Also answers the FE-P7 open item "static prerendering is lost to nonces, worth a Lighthouse check".

| Area | Status | Evidence |
|---|---|---|
| Budget gate | ✅ | `npm run perf` (`perf/run.mjs`) drives Lighthouse 13 through Playwright's Chromium against a production `next start`, on `/`, `/login`, `/signup`, `/forgot-password`, with Lighthouse's default mobile profile (slow 4G, 4x CPU), median of 3 runs. Exits 1 on any breach of `perf/budget.mts`: **LCP 2500 ms and JS 200 KB gzipped** (the plan's two proposals) plus CLS 0.1 and TBT 300 ms (Core Web Vitals "good", added). |
| Pure budget logic | ✅ | `tests/perf-budget.test.ts` (9): metric extraction (bytes→KB), missing/NaN audit throws instead of passing silently, median (outlier, even count, single run), at-the-limit passes, per-metric violation messages. |
| Measured result | ✅ | `/` LCP 1861 ms · JS 171 KB; `/login` 2384 ms · 187 KB; `/signup` 1959 ms · 186 KB; `/forgot-password` 2035 ms · 189 KB; **CLS 0 and TBT ≤ 32 ms everywhere**. All inside the budget. Confirmed the JS figure is real gzip transfer (the server compresses 691 KB of chunks to 218 KB). |
| Gate can fail | ✅ | A negative control with an impossible budget (LCP 1000 ms, JS 100 KB) failed all four routes with named reasons and **exit code 1**; the real budget was then restored. |
| Dynamic rendering cost | ✅ | Per-request CSP nonces make every page server-rendered, yet LCP stays under budget on slow 4G, so the trade-off is acceptable. |

**Headroom is thin:** `/login` JS is 187 of 200 KB (about 7 %) and its LCP reached 2384 of 2500 ms in one run (2336 in another). Any new dependency on the public routes (for example a Sentry browser SDK) will likely break the JS budget, so add it lazily. The simulated-throttling numbers vary by a few percent between runs, hence the median.

**Verification run (local, Node 24):** `npm test` → 26 files, **298 tests passed** (9 new), two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npm run perf` passed twice (the second run after the final code). Backend untouched. `lighthouse@13` and `chrome-launcher` are devDependencies; Lighthouse needs Node 22+, so `engines` (≥ 18.17) and the CI job (Node 20) apply to the app, not to `perf`. `npm audit --omit=dev` is unchanged (the same Next 14 advisories, Q8). `tsconfig.json` gained `allowImportingTsExtensions` (valid with `noEmit`) so tests can import `perf/budget.mts`, which Node runs natively.

**Open items from FE-P7f**
1. **`perf` is not in CI** (needs a built server and Chromium; CI has never run on GitHub), so the budget is enforced only when someone runs it. A CI job on Node 22 would need `npx playwright install chromium`.
2. Only public routes are budgeted; signed-in pages (`/dashboard` 157 kB, `/profile` 185 kB first-load) need a login flow in the runner. The plan also asks for a 50-generation soak for object-URL/stream leaks (DoD 13), not done.
3. Lab numbers on simulated throttling, from this CPU; no real-device or field (web-vitals) data until Sentry/web-vitals reporting exists.
4. Remaining in Phase 7: Sentry + PII scrubber and web-vitals, Firefox/Safari runs, the manual screen-reader and keyboard-only pass, e2e in CI, SQLite vs Postgres. Carried over: ffmpeg recording decode, Q8, CI never run on GitHub, Q3/Q4 latency.

### FE-P7g — Phase 7, Firefox e2e (2026-10-07, branch `feat/FE-P7g-firefox`, commit `0fbbdd8`)

Definition-of-Done item 12 (Firefox smoke) and the Phase 7 "e2e full regression on Chromium + Firefox". `playwright.config.ts` now has a `chromium` and a `firefox` project running the same 35 tests against the real backend with real weights; Firefox's fake microphone comes from `firefoxUserPrefs` (Playwright's `microphone` permission is Chromium-only). Firefox 155 (Playwright build 1543).

The first Firefox run **failed 11 of 34**. Nine were one product bug (every test that uploads a WAV), one was a second product bug, and one a test race.

| Finding | Status | Evidence |
|---|---|---|
| **Firefox users could not upload a `.wav` at all** | ✅ fixed | Firefox on Linux reports a WAV as `audio/vnd.wave` (the IANA name, RFC 2361). Neither the client allowlist nor the server accepts it, so the form said "Use a WAV, MP3 or WEBM audio file" before any request. 9 e2e tests that upload a WAV timed out or failed (seven after 2 minutes each). Fix is client-side, leaving the hardened server allowlist alone: `canonicalMediaType`/`canonicalAudioFile` fold the alias into `audio/wav` for validation and for the upload (same bytes, name and date; any other type is sent untouched, the same `File` object). Tests: 4 in `tests/audio-validation.test.ts`, 1 in `tests/voice-profiles.test.tsx` that uploads an `audio/vnd.wave` file and asserts the form sends `audio/wav`. |
| **Long email overflowed the account page** | ✅ fixed | The email `<dd>` was a flex item holding one unbreakable string, so a long address widened the page (Firefox showed 9 px at 320 px on the existing test; Chromium passed only because its test email wraps at hyphens). Now `min-w-0` + `overflow-wrap:anywhere`. A new e2e test (`responsive.spec.ts`, an address with a 40-char unbroken segment at 320 px) **fails without the fix in both browsers (59 px Chromium, 276 px Firefox) and passes with it**. |
| `NS_BINDING_ABORTED` after sign-out | ✅ test race | `auth.spec.ts` called `goto` straight after clicking Sign out, colliding with the app's own navigation home; Firefox reports the abort as an error (50 % failure rate in a 12x repeat, 0 of 40 after the fix). A shared `signOut()` helper now waits for the URL to settle. Not an app defect. |

**Verification run (local, Node 24; Chromium and Firefox):** `npm test` → 26 files, **303 tests passed** (5 new), two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npx playwright test` with `CSP_ENFORCE=1` against the real backend → **70 passed (35 per browser)** in 3.2 min, run on the final code. Backend untouched.

**Open items from FE-P7g**
1. The backend still rejects `audio/vnd.wave` from any other client (curl, scripts, a native app); only this web client folds it. If non-browser clients matter, add the alias to `audio_processing.py`'s allowlist (the real container is sniffed anyway).
2. Recording in Firefox reaches the server (the WEBM passes the container check) but, as in Chromium, decoding needs ffmpeg on the API host, so a successful recording upload is still unverified end to end.
3. **Safari/WebKit not run** (manual check, and the iOS MP4 recording gap G-08 / Q5). e2e is still not in CI, and CI has never run on GitHub; the e2e suite now takes both browsers (`npx playwright install chromium firefox`).
4. Remaining in Phase 7: Sentry + PII scrubber and web-vitals, the manual NVDA/VoiceOver and keyboard-only pass of the remaining flows, SQLite vs Postgres. Carried over: Q8, Q3/Q4 latency.

### FE-P7h — Phase 7, observability and a layout-shift fix (2026-10-07, branch `feat/FE-P7h-observability`, commit `5b2e25c`)

Phase 7 task 6 and Definition-of-Done item 7 ("no input text, audio, email or token reaches error reports, tested scrubber").

| Area | Status | Evidence |
|---|---|---|
| PII scrubber | ✅ | `lib/observability/scrub.ts` is an **allow-list**: an event keeps only id, level, release, environment, SDK, a scrubbed message, exception type/value/frame file+line (frame `vars` dropped), allow-listed tags (`route`, `status`, `kind`, `request_id`, `metric`, `rating`) and the route. User, request (URL, query, cookies, headers, body), breadcrumbs, extra and contexts are discarded; emails, JWTs and 32+ char opaque strings are redacted in what remains; URLs collapse to a route with ids as `:id`. `tests/observability.test.ts` feeds a deliberately dirty event (email, IP, bearer token, cookie, password, synthesis text, reset-token fragment) and asserts none of it appears anywhere in the serialized result. |
| Reporter | ✅ | `lib/observability/report.ts`: off unless `NEXT_PUBLIC_SENTRY_DSN` is set; `@sentry/browser` 8 loaded by dynamic `import()` only; **no default integrations, no breadcrumbs, `sendDefaultPii:false`**, `beforeSend` = scrubber; an `ApiError` is reduced to status, kind and request id (its message is server text that can echo input). Failures are swallowed. Wired to `app/error.tsx`, `app/global-error.tsx` and the Query/Mutation caches (5xx only; 4xx and network conditions are user states, not faults). Web vitals via `next/web-vitals`, reporting only non-"good" ratings. |
| Bundle impact | ✅ | `lib/observability/lazy.ts` is the only reporter code the initial bundle contains (it checks the DSN, then imports lazily); a guard test fails if any statically imported module imports `report.ts` or the SDK. `npm run build`: `/login` 158 to 159 kB first-load. |
| CSP | ✅ | The DSN's origin is added to `connect-src` by `middleware.ts`/`buildCsp` and only then (unit-tested both ways). |
| Real-browser check | ✅ (manual) | Built with a DSN pointing at a local capture server, under **`CSP_ENFORCE=1`**, on a page whose URL carried a token fragment: an uncaught `Error("boom for jane.doe@example.com token eyJ…")` arrived as one envelope, message `boom for [email] token [token]`, **no URL, request, user or fragment**, zero CSP violations. Not an automated test (the e2e web server is built without a DSN). |

**Defects found and fixed along the way**
1. **Header layout shift (CLS 0.265).** Lighthouse failed the CLS budget once the reporter code changed hydration timing: the header's right side was 24 px while the session loaded and 32 px (signed out) or 44 px (signed in) afterwards, shoving the whole page down. This was latent, not caused by reporting. Every state is now at least 44 px (`components/user-menu.tsx`); CLS is **0.001**. On screens under 640 px the signed-in menu also hides the display name (it wrapped to a second row and shifted the page; the name is still on `/profile`) and uses tighter gaps. `e2e/layout-shift.spec.ts` (Chromium, session refresh delayed 1.2 s, 412 px) asserts CLS < 0.05 signed out and signed in; **both fail without the fix (0.17 and 0.31) and pass with it**.
2. Uncaught errors would never have been reported: the SDK was initialised lazily on the first explicit report, so its global handlers did not exist yet. Found by the real-browser check; the lazily loaded `WebVitals` component now starts it on mount.

**Verification run (local, Node 24; Chromium and Firefox; real backend with real weights, SQLite):** `npm test` → 27 files, **315 tests passed** (12 new), two consecutive runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npx playwright test` with `CSP_ENFORCE=1` → **72 passed, 2 skipped** (35 shared tests per browser plus the two new Chromium-only CLS tests, skipped in Firefox) in 3.3 min. `npm run perf` → all four routes within budget (LCP 1.8-2.0 s; JS 177/193/193/192 KB; CLS 0.001; TBT <= 2 ms). Backend untouched. `npm audit --omit=dev` unchanged (the Next 14 advisories only; `@sentry/browser` adds none).

**Open items from FE-P7h**
1. **No real Sentry project:** the DSN is empty everywhere, so nothing is reported in any deployed environment until one is created and `NEXT_PUBLIC_SENTRY_DSN` is set at build time. **Release tagging and sourcemap upload are not done** (need a project and an auth token), so reported stack frames are minified. The Definition-of-Done "tested live" part of item 17 is open.
2. **`/login` JS is 193 of 200 KB (3 % headroom).** FE-P7f recorded 187 KB; this slice added about 1 KB, the rest is run-to-run drift on this machine. Do not add anything else to public routes without measuring.
3. **The "verify your email" banner still shifts the page when it appears** after the session resolves (about 0.16 CLS for an unverified user on reload). The new CLS test deliberately uses a verified user. Fix by reserving its space or moving it below the header.
4. A narrow-screen signed-in menu with only 3 items still wraps below about 360 px (the responsive test passes because it only checks overflow and target size, not shift).
5. Remaining in Phase 7: the manual NVDA/VoiceOver and keyboard-only pass of the remaining flows, Safari/WebKit, e2e and `perf` in CI (CI has never run on GitHub), SQLite vs Postgres. Carried over: ffmpeg recording decode, Q8, Q3/Q4 latency.

### FE-P7i — Phase 7, verify-email notice layout shift (2026-10-07, branch `feat/FE-P7i-banner-cls`, commit `4186e42`)

Closes FE-P7h open item 3. The "verify your email" notice rendered above the header once the session resolved, so every reload by an unverified user pushed the whole page down (CLS about 0.17).

| Area | Status | Evidence |
|---|---|---|
| Fix | ✅ | `VerificationBanner` now renders after the footer and is `sticky bottom-0`: it still stays in view while scrolling, but appearing late only extends the page and moves nothing already painted. (The degraded-service banner stays on top: it needs prominence and is not tied to session timing.) |
| Test | ✅ | `e2e/layout-shift.spec.ts` gains an unverified-user case (session refresh delayed 1.2 s, 412 px, CLS < 0.05). **Fails without the fix (0.173), passes with it.** |

**Verification run (local, Node 24; Chromium and Firefox; real backend with real weights):** `npm test` → 27 files, **315 passed**, two runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npx playwright test` with `CSP_ENFORCE=1` → **73 passed, 3 skipped** (the three Chromium-only CLS tests in Firefox), including the real-browser axe audits of the signed-in pages. `npm run perf` → within budget, CLS 0.001. Backend untouched.

**Open items from FE-P7i**
1. The notice is now last in DOM and tab order, so keyboard and screen-reader users reach it after the page content. It is a `sticky` block, not a live region; the manual NVDA/VoiceOver pass should judge whether that is discoverable enough (a `role="status"` was not added because it would announce on every reload).
2. On a narrow signed-in menu below about 360 px the items still wrap (FE-P7h item 4). Everything else from FE-P7h item 5 is unchanged: screen-reader and keyboard pass, Safari, e2e and `perf` in CI, SQLite vs Postgres, ffmpeg recording decode, Q8, Q3/Q4, and no real Sentry project.

### FE-P7j — Phase 7, header stability on narrow screens (2026-10-07, branch `feat/FE-P7j-narrow-header`, commit `3ace3f4`)

Closes FE-P7h/FE-P7i open item "the signed-in menu still wraps below about 360 px". Measured first: with the session refresh delayed, a verified signed-in user shifted the page by **0.22 at 320 px and 0.27 at 360 px** (the menu wrapped to a second row only after the session loaded); signed out and 412 px were fine.

| Area | Status | Evidence |
|---|---|---|
| Fix | ✅ | Below `sm` (640 px) the header is two fixed rows in every state: brand, then the account menu (44 px min height) on its own row (`components/app-shell.tsx`); from `sm` up it is the previous single wrapping row. The loading skeleton, signed-out links and signed-in menu all occupy the same row, so the header height no longer depends on the session. Cost: signed-out visitors on phones get a 44 px taller header. |
| Test | ✅ | `e2e/layout-shift.spec.ts` now runs signed out, signed in (verified) and signed in (unverified) at **320, 360 and 412 px**: 9 cases, CLS < 0.05. 4 failed before the fix (0.22 to 0.27), all 9 pass after. |

**Verification run (local, Node 24; Chromium and Firefox; real backend with real weights):** `npm test` → 27 files, **315 passed**, two runs; `typecheck`, `lint`, `format:check` clean; `npm run build` OK. `npx playwright test` with `CSP_ENFORCE=1` → **79 passed, 9 skipped** (the nine Chromium-only CLS cases in Firefox), including the responsive (no overflow, 44 px targets at 320/768/1280) and real-browser axe audits. `npm run perf` → within budget, CLS 0.000. Backend untouched.

**Safari/WebKit attempt (not done):** Playwright's WebKit build downloads but cannot launch here: the host lacks system libraries and installing them needs `sudo npx playwright install-deps`, which was not run. Running it, then adding a `webkit` project beside the other two, is the quickest way to automate part of the Safari check; the real-Safari manual pass remains outstanding either way.

**Open items from FE-P7j**
1. Safari/WebKit as above, and the manual NVDA/VoiceOver and keyboard-only pass. The sticky verify-email notice's discoverability (FE-P7i) belongs in that pass.
2. e2e and `perf` are still not in CI (CI has never run on GitHub); no real Sentry project, release tagging or sourcemaps. Carried over: SQLite vs Postgres, ffmpeg recording decode, Q8, Q3/Q4 latency.

### FE-P7k — Phase 7, 50-generation soak (2026-10-07, branch `feat/FE-P7k-soak`, commit `fe91eb6`)

Closes the second half of Definition-of-Done item 13 ("object URLs/streams released, no leak in a 50-generation soak"), an open item since FE-P7f.

| Area | Status | Evidence |
|---|---|---|
| Soak test | ✅ | `e2e/soak.spec.ts` (both browsers): a real signed-in, verified user with a real voice profile runs **50 generations** on `/dashboard`. `URL.createObjectURL`/`revokeObjectURL` are wrapped to track live blob URLs; after every run there is at most **1 live URL and exactly 1 `<audio>`**, 50 or more were created in total, and navigating away leaves **0**. Synthesis is stubbed (a valid 0.2 s WAV with the real `Content-Disposition` and CORS headers) so the soak takes seconds, not 6 minutes; the profile, session and everything else are real. |
| Can fail | ✅ | With the revoke removed from `hooks/use-object-url.ts` the test fails at run 2 (`live blob URLs after run 2`, expected <= 1, received 2). The hook was restored. |

**Verification run (local, Node 24; Chromium and Firefox; real backend with real weights):** `npm test` → 27 files, **315 passed**, two runs; `typecheck`, `lint`, `format:check` clean. `npx playwright test` with `CSP_ENFORCE=1` → **81 passed, 9 skipped** (Chromium-only CLS cases in Firefox). No app code changed. Backend untouched.

**Open items from FE-P7k**
1. The soak covers blob URLs and audio elements, the leak sources in this code. It does not measure JS heap or a `MediaStream` over many recordings (the recorder's track release is asserted once in the unit tests); real synthesis was not repeated 50 times (about 6 minutes on this CPU).
2. Everything else from FE-P7j stands: Safari/WebKit (needs `sudo npx playwright install-deps`), the manual NVDA/VoiceOver and keyboard pass, e2e and `perf` in CI, no real Sentry project, SQLite vs Postgres, ffmpeg recording decode, Q8, Q3/Q4 latency.

### FE-P7l — Phase 7, Lighthouse budget in CI (2026-10-07, branch `feat/FE-P7l-ci-perf`, commit `e112ca0`)

Closes FE-P7f open item 1 ("`perf` is not in CI") for the performance budget. e2e is deliberately not added (below).

| Area | Status | Evidence |
|---|---|---|
| `perf` job | 🟡 | `.github/workflows/frontend.yml` gains a `perf` job beside `check`: Node 22 (Lighthouse 13 needs it; `check` stays on 20), `npm ci`, `npm run build`, `npx playwright install --with-deps chromium`, a start-and-wait step for `next start`, then `npm run perf`, which exits 1 on any budget breach. The public routes need no backend. **Run end to end locally with the same commands, from a clean `.next`, with the backend off as on a runner:** all four routes within budget (LCP 1.8 to 2.0 s, JS 177/193/193/192 KB, CLS 0.000). YAML parses. **It has never run on GitHub**, like the rest of the workflow, so runner CPU variance against the 2500 ms LCP and the thin `/login` JS margin (193 of 200 KB) is unproven; if it flaps, raise `PERF_RUNS` or relax LCP rather than disabling it. |
| e2e in CI | ⬜ | Not added: the suite needs the real backend with its model weights (multi-GB, not in the repo), a console-mail log and two browsers. A weights-free subset (auth, email, a11y, responsive, layout shift, dialogs) is possible once the backend can start without TTS weights, which is a backend change. |

**Verification run (local, Node 24):** the perf commands above. No application or test code changed, so the unit and e2e suites were not re-run for this slice beyond the post-merge unit run. Backend untouched.

**Open items from FE-P7l**
1. The first GitHub run of `perf` and `check` is the real test; watch it. Safari/WebKit (needs `sudo npx playwright install-deps` locally), the manual NVDA/VoiceOver and keyboard pass, e2e in CI, no real Sentry project, SQLite vs Postgres, ffmpeg recording decode, Q8, Q3/Q4 latency.
2. With these, Phase 7 has only items that need a person, a browser this host cannot run, or infrastructure. Phase 8 (deploy on one registrable domain, real email, Google redirect, runbook, smoke script) needs the owner's hosting decisions (Q4) and cannot be started from this machine.

### FE-P7m — documentation reconciliation (2026-10-07, branch `docs/FE-P7m-doc-reconciliation`, commit `dba0be3`)

Definition-of-Done item 18 and gap G-15 ("stale endpoint docs"). Documentation only; no code, tests or backend behaviour changed.

| Area | Status | Evidence |
|---|---|---|
| `CLAUDE.md` §5 and §7 | ✅ | The architecture sketch and the endpoint table named `/api/auth/login`, `/api/voice/upload` and five routes. §7 now lists every route under `/api/v1` (signup, login, refresh, logout, `me` GET/PATCH/DELETE, email verification, password reset, Google, `terms`, voice upload/list/delete, synthesize, history, past-audio download) plus `/health*`, and points to `frontend/contract/openapi.json` as the authority. **Cross-checked: every one of the 20 paths in the OpenAPI snapshot appears in the doc.** Only the reference tables were edited, none of the rules. |
| `project_description.md` | ✅ | Already carried the full `/api/v1` list (done in an earlier milestone); verified, not changed. |
| `README.md` | ✅ | The frontend stack no longer claims NextAuth and shadcn (neither is used); the "not yet implemented" note is replaced with how to run it and a pointer to `frontend/README.md`, plus the same-site requirement for the refresh cookie. |

**Open items from FE-P7m**
1. The README now states NextAuth is not used, but Q1 (drop NextAuth or wrap the backend with it) is formally still the owner's decision; the code already follows "drop". Confirm Q1 so the docs, `project_description.md` and the plan agree.
2. Docs changed, so the graph's semantic layer needs `/graphify --update`. Everything else from FE-P7l stands.

### FE-P8a — Phase 8 preparation: smoke script and runbook (2026-10-07, branch `feat/FE-P8a-smoke-runbook`, commit `d012995`)

The two Phase 8 deliverables that need no hosting: "runbook (rollback, cookie/CORS troubleshooting); smoke script" (Definition of Done 17, the runbook and script parts). The deployment, domain, real email, Google redirect and error-tracking project remain.

| Area | Status | Evidence |
|---|---|---|
| Smoke script | ✅ (local only) | `npm run smoke -- --web <url> --api <origin> [--with-account]` (`smoke/run.mts`, logic in `smoke/lib.mts`). Read-only checks: web `/login` 200 and security headers (CSP present and free of `unsafe-inline`/`unsafe-eval`, nosniff, framing protection), `Referrer-Policy: no-referrer` on `/verify-email`, API `/health/live` and `/health/ready`, `GET /terms`, **CORS preflight and exposed `Content-Disposition` for the web origin**, `/metrics` not public, and **web and API same-site** (G-13). `--with-account` also signs up a throwaway user, checks the refresh cookie is `HttpOnly`/`SameSite=Lax` (`Secure` on https), refreshes with it, and deletes the account. Exit 1 on any failure; warnings do not fail. |
| Verified | ✅ | Run against the real local stack (backend with real weights + production web build, `--with-account`): **21 checks, 0 failed**, 3 warnings that are true of a dev setup (CSP report-only, `/metrics` public, http so `Secure` unchecked). Negative controls: calling the web via `127.0.0.1` fails the CORS and same-site checks with the fix named (exit 1); an unreachable web fails its checks (exit 1); missing arguments exit 2. |
| Unit tests | ✅ | `tests/smoke.test.ts` (16): same-site logic, security-header, referrer, CORS, cookie-flag and exit-code rules, each with failing inputs. |
| Runbook | ✅ (unproven on a host) | `frontend/RUNBOOK.md`: build-time vs runtime variables, release procedure, manual release checks, rollback (frontend, CSP, Sentry), and diagnosis for lost sessions (cookie), status-0 errors (CORS), CSP breakage, wrong email links, Google errors, the degraded banner and synthesis timeouts. `frontend/README.md` links it. |

**Verification run (local, Node 24):** `npm test` → 28 files, **331 passed** (16 new), two runs; `typecheck`, `lint`, `format:check` clean. The smoke script run as above. No application code changed, so the e2e and perf suites were not re-run. Backend untouched.

**Open items from FE-P8a**
1. The registrable-domain check takes the last two labels; it does not use the public-suffix list, so two sites under a multi-label suffix (`a.co.uk`, `b.co.uk`) would wrongly pass. Documented in the code.
2. The script and runbook have never met a real deployment, so provider-specific behaviour (proxy timeouts, `X-Forwarded-*`, idle limits: Unverified #1, Q4) is untested.
3. Phase 8 proper still needs the owner: hosting and a same-site domain, a verified email domain and working email (`HARDENING_PLAN.md` §4 item 2), the Google redirect registered, a Sentry project, Q1/Q4 answered. Carried over from Phase 7: Safari, the manual screen-reader and keyboard pass, e2e in CI, SQLite vs Postgres, ffmpeg recording decode, Q8.

### FE-P7n — backend accepts the `audio/vnd.wave` alias (2026-10-07, branch `fix/accept-audio-vnd-wave`, commit `86ce187`)

Closes FE-P7g open item 1. Chosen over the other candidates (WebKit needs `sudo`; Phase 8 needs the owner's hosting decisions; running the API without model weights would loosen hardening finding C2) because it was small, self-contained, testable and a real defect.

| Area | Status | Evidence |
|---|---|---|
| Fix | ✅ | `backend/services/audio_processing.py`: `audio/vnd.wave` (the IANA name, RFC 2361, which Firefox on Linux uses for WAVs) joins the accepted names for `.wav`. Nothing else is loosened: the declared type must still match the **sniffed container**, so an MP3 or WebM called `audio/vnd.wave` is refused, and the error text and size limits are unchanged. Before, only this web client could upload such a file (it folded the alias into `audio/wav`); curl, scripts and native clients got a 422. |
| Tests | ✅ | `backend/tests/test_upload_hardening.py`: a WAV declared `audio/vnd.wave`, and with a mixed-case name and parameters, is accepted; an MP3 and a WebM declared `audio/vnd.wave` are refused. **Without the fix the two accept cases fail** (2 failed, 33 passed); with it all pass. |
| Frontend | ✅ | The client still folds the alias into `audio/wav`, now documented as protection for older deployed APIs. |

**Verification run (local):** `pytest backend -q` → **902 passed, 1 skipped, 11 warnings** (898 before plus 4 new; the 11 warnings are the known third-party baseline). Frontend: `npm test` → 28 files, **331 passed**; `typecheck`, `lint`, `format:check` clean (a comment changed only). `black` and `isort` clean. The OpenAPI snapshot is unchanged (the allowlist is not in the schema).

**Open items from FE-P7n**
1. The error message still says "Allowed: WAV, MP3, WEBM." (accurate: the alias is a name for WAV, not a new format). Other WAV aliases a client might send (for example `audio/vnd.wave` with unusual parameters is handled; `audio/x-pn-wav` is not) are untouched.
2. Everything else is unchanged: Safari/WebKit (needs `sudo npx playwright install-deps`), the manual NVDA/VoiceOver and keyboard pass, e2e in CI, Phase 8 (owner decisions: hosting, domain, email, Google, Sentry, Q1/Q3/Q4/Q8), SQLite vs Postgres, ffmpeg recording decode.

### FE-P8b — smoke same-site check uses the public-suffix list (2026-10-08, branch `fix/FE-P8b-public-suffix-samesite`, commit `a56d97f`)

Closes FE-P8a open item 1. Chosen as the next step because every other remaining item needs a person, hosting, or a browser this host cannot run, while this one was small, testable and made the Phase 8 smoke check trustworthy (a false "same-site" pass would hide the exact cookie failure G-13 describes).

| Area | Status | Evidence |
|---|---|---|
| `registrableDomain` | ✅ | `frontend/smoke/lib.mts` now calls `tldts.getDomain(host, { allowPrivateDomains: true })` instead of taking the last two labels. Private suffixes count (as browsers treat them for SameSite), so two tenants of `*.up.railway.app` are different sites; `a.co.uk` vs `b.co.uk` now fails; `localhost`, IPs and IPv6 are returned whole. `tldts` added as a devDependency (it was already in the tree via jsdom and msw). |
| Tests | ✅ | `tests/smoke.test.ts` 16 → 18 tests: multi-label suffix, private suffix, IPv6, and the pass/fail pairs for `checkSameSite`. The new fail cases would pass wrongly under the old two-label logic. |

**Verification run (local, Node 24):** `npm test` → 28 files, **333 passed** (2 new); `typecheck`, `lint`, `format:check` clean; `node smoke/run.mts` with no args still loads and exits 2. Smoke script not re-run against a live stack (only the pure check changed). Backend untouched. `npm audit --omit=dev` still reports the known Next 14 advisories (Q8).

**Open items from FE-P8b**
1. The public-suffix data is whatever the installed `tldts` ships; refresh it with `npm update tldts` before a release.
2. Everything else from FE-P8a item 2-3 stands: Phase 8 proper needs the owner (hosting, same-site domain, real email, Google redirect, Sentry, Q1/Q3/Q4/Q8); Safari, the manual screen-reader pass, e2e in CI, SQLite vs Postgres, ffmpeg recording decode.

### FE-UX0 — UX plan, first slice: brand, tokens, fonts, theme toggle (2026-10-08, branch `feat/UX-U0-brand-theme`, commit `6b7281d`)

The first implementation slice of `FRONTEND_UX_IMPROVEMENT_PLAN.md` (phase U0). The plan itself and the owner's six decisions are in that file (§11); this entry records what was built.

| Area | Status | Evidence |
|---|---|---|
| Brand mark and favicon | ✅ | `components/logo.tsx` (waveform of five bars that fade out), `app/icon.svg`, used in the header. |
| Palette tokens, both themes | ✅ | `app/globals.css`, `tailwind.config.ts`: new `surface`, `line`, `danger`, `success` tokens; existing names kept; every `text-red-600 dark:text-red-400` and `bg-red-600` replaced by `text-danger`/`bg-danger`; control outlines moved to `line` (3:1). `tests/theme.test.ts` recomputes WCAG contrast from the shipped HSL values (text and accent ≥ 4.5:1, outlines ≥ 3:1, both themes) and forbids `dark:` variants and raw palette colours in components. |
| Theme toggle | ✅ | System → Light → Dark button (`components/theme-toggle.tsx`), `lib/theme.ts`, server-rendered `data-theme` from the `cv-theme` cookie in `app/layout.tsx` (no flash, no inline script, CSP-safe), 200 ms cross-fade only on switch, instant under reduced motion, `<meta name="theme-color">` kept in step. `tests/theme-toggle.test.tsx` (3), `tests/theme.test.ts`. |
| Guardrail change | ✅ | `tests/hardening.test.ts`: `document.cookie` stays forbidden everywhere except `lib/theme.ts`, which must write exactly one cookie, never touch storage, and never mention tokens, passwords or emails. The access token remains memory-only. |
| Fonts | ✅ | IBM Plex Sans 400/500/600 and Plex Mono 400, self-hosted (`app/fonts/`, OFL licence included) with `next/font/local`; mono used for the character counter and recording clock. |

**Verification run (local, Node 24):** `npm test` → 30 files, **351 passed** (28 → 30 files, 331 → 351 tests); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build with the API mocked: OS-dark follows the OS; cycle light → dark → system sets and clears the cookie; an explicit choice survives a reload; with JavaScript disabled the cookie still renders dark; no console errors; no horizontal overflow at 320/375/1280 px; header height unchanged by toggling; reduced motion adds no transition class. `npm run perf` (median of 5, public routes): LCP 2.1-2.3 s, JS 178-194 KB, CLS 0.000, all within budget (LCP was 1.8-2.0 s before the fonts). Backend untouched. The e2e suite was **not** re-run (it needs the real backend with model weights); the changes it could notice are class and colour changes, and the header gained one 44 px button.

**Open items from FE-UX0**
1. The rest of U0-U7 is not started: the Button/Field/Alert primitives, the route split and rename (decision §11.2), the first-run flow, the take component.
2. `frontend/e2e/*` has not been run against the new header; run `layout-shift`, `responsive` and `a11y` against the real stack before relying on them. The LCP margin is now about 0.3 s: watch the first GitHub `perf` run.
3. No Safari/WebKit check and no manual screen-reader pass of the toggle. `app/global-error.tsx` renders its own `<html>` and follows the OS only.
4. New backend dependency UBD-4 (expose `output_retention_days`) and a stale hard-coded "30 days" string in `components/history-list.tsx:49`; see the UX plan §11.3. No trademark search was done for the name "CloneVoice".

### FE-UX1 — UX plan, U0.4/U0.5 part 1: Button, Alert, Badge primitives (2026-10-08, branch `feat/UX-U0-primitives`, commit `7dc993d`)

| Area | Status | Evidence |
|---|---|---|
| `Button` primitive | ✅ | `components/ui/button.tsx` (cva): primary, secondary, quiet, danger × md/sm; defaults to `type="button"`; `loading` sets `aria-busy`; hover, active and disabled states; 44 px minimum height. All 30 inline button recipes in 13 components now use it, plus `buttonVariants` for the landing, header and Google links. |
| `Alert` and `Badge` | ✅ | `components/ui/alert.tsx` (danger → `role="alert"`, others → `status`), `components/ui/badge.tsx`. Every `<p role="alert" class="text-danger">` migrated; `StatusChip` is now `Badge`. |
| Destructive confirms | ✅ | Delete voice and Delete account confirm buttons use the `danger` variant (UX-15, colour part only; the overlay dialog is still U3.1). |
| Tokens | ✅ | New `--danger-foreground` (contrast asserted in both themes); Tailwind colours use `<alpha-value>` so `/90` hover shades work. |
| Guardrail | ✅ | `tests/theme.test.ts` fails on any ad-hoc button or error recipe outside `components/ui/`. `tests/ui-primitives.test.tsx` (11 tests). |

**Verification run (local, Node 24):** `npm test` -> 31 files, **362 passed** (351 -> 362); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. `npm run perf` (median of 5, quiet machine, public routes): LCP 1.85-2.26 s, JS 180.8-197.6 KB, CLS 0.000, all within budget. A first attempt with `tailwind-merge` inside the primitives pushed `/login`, `/signup` and `/forgot-password` to 204-206 KB (over the 200 KB budget), so the primitives use cva's own `className` merge and no `cn()`; JS headroom on the form routes is now about 2.4 KB, so the next primitive (`Field`, `Dialog`) must watch it. Perf runs under load (graph rebuild running) gave LCP 2.6 s on `/` and `/login`; they passed when repeated on an idle machine. Backend untouched. e2e not re-run (needs the real backend and model weights).

**Open items from FE-UX1**
1. U0.4 part 2: `Field` (input, select, textarea) and `Card` primitives; the input and select recipes in `form-fields.tsx` and `voice-profile-select.tsx` and the mode toggle in `upload-voice-form.tsx` are the only remaining ad-hoc controls.
2. Remaining U0: U0.6 accent documentation and a visual-regression baseline. Not started: U1-U7.
3. `npm run perf` needs `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_APP_ORIGIN` at build and start time and a server on port 3000; without them it fails with a misleading "no script row" error.
4. The UX plan's markdown changed; run `/graphify --update` to refresh its semantic nodes (the code graph was refreshed with `graphify update .`).

### FE-UX2 — UX plan, U0.4 part 2: Input, Select, Textarea field primitives (2026-10-08, branch `feat/UX-U0-field`, commit `b82eab6`)

| Area | Status | Evidence |
|---|---|---|
| Field controls | ✅ | `components/ui/field.tsx`: `Input`, `Select`, `Textarea` share one recipe (3:1 `line` outline, hover, disabled, `aria-invalid` turns the outline `danger`, 44 px minimum on single-line controls). `TextField`, the voice picker and the generate textarea use them. |
| Guardrail | ✅ | `tests/theme.test.ts` now also fails on the raw control recipe (`border-line bg-surface`) outside `components/ui/`. `tests/ui-primitives.test.tsx` +3 tests. |
| Left as is, on purpose | n/a | The native file input (U2.7 replaces it), the consent checkbox, and the Upload/Record mode toggle (U6.1 rebuilds it as an arrow-key radio group). `Card` is not built: the plan limits cards to the take and dialogs (§4.9), so it waits for U3/U4. |

**Verification run (local, Node 24):** `npm test` -> 31 files, **365 passed** (362 -> 365); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. The jsdom "HTMLCanvasElement.getContext not implemented" lines printed by axe are pre-existing (same count on `main` before this change). `npm run perf` (median of 5): LCP 2.11-2.26 s, JS 180.8-197.7 KB, CLS 0.000, TBT <= 4 ms, all within budget. One earlier run read `/` at 2.64 s with identical JS (the landing page uses no field code), and it passed at 2.11 s when repeated with a warm server: treat the first route after a cold `next start` as noisy. Backend untouched; e2e not re-run (needs the real backend and weights).

**Open items from FE-UX2**
1. U0 is complete apart from U0.6 (document the `signal` swap point) and the visual-regression baseline; JS headroom on the form routes is about 2.3 KB, so `Dialog` (U3.1) should reuse existing code.
2. Next phase is U1 (route split to Generate · Voices · History · Account, `NavLink`, mobile tab bar), which touches routes, e2e, smoke and RUNBOOK; it needs its own branch and a grep checklist.
3. Run `/graphify --update` to refresh semantic nodes for the changed plan docs.

### FE-UX3 — UX plan, U1.1/U1.2/U1.6: route split, rename, NavLink (2026-10-08, branch `feat/UX-U1-routes`, commit `78ff7b6`)

Implements owner decision §11.2 (option C): `/profile` is split by job and the generator is renamed **Generate** (not "Studio").

| Area | Status | Evidence |
|---|---|---|
| New routes | ✅ | `/generate` (was `/dashboard`), `/voices` (create form + list), `/history`, `/account`; each has exactly one `h1` and a matching title. Nav labels: Generate · Voices · History · Account. |
| Old URLs | ✅ | `next.config.mjs` `redirects()`: `/dashboard` → `/generate`, `/profile` → `/voices`, permanent (308), query kept. Checked against the production server with curl (`/profile?tab=history` → `/voices?tab=history`). |
| `next=` handling | ✅ | `lib/auth/next-path.ts`: default is `/generate`; the old paths in a `next=` are mapped; look-alikes such as `/profile-x` are not. Signup, Google callback, verify-email and the empty-voice link now point at the new routes. |
| `NavLink` (UX-19) | ✅ | `components/nav-link.tsx`: `aria-current="page"` plus a bold underline (not colour alone). The "Create one" link in the voice picker is now a client-side `Link` instead of a full reload (part of UX-06). |
| Tests | ✅ | `tests/navigation.test.tsx` (new), `tests/next-path.test.ts`, `tests/auth-ui.test.tsx`, `tests/auth-gate.test.tsx`, `tests/email-flows.test.tsx` updated. 13 e2e specs and `e2e/helpers.ts` updated by hand to the new routes (history check on `/history`, display-name checks on `/account`); `responsive.spec.ts` now covers all four routes. |

**Verification run (local, Node 24):** `npm test` -> 32 files, **378 passed** (365 -> 378); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Production server with the API mocked, real Chromium, at 375 and 1280 px: each of the four routes renders one `h1`, marks exactly its own nav link `aria-current="page"`, and has zero horizontal overflow; `/dashboard` lands on `/generate`. `npm run perf` (median of 5) JS 180.9-197.8 KB, CLS 0, TBT <= 5 ms. **LCP flapped:** three runs each had one or two routes between 2.56 and 2.64 s (a different route each time, and the same routes passed at 1.96-2.26 s in the other runs). The public routes' JS changed by about 0.1 KB, so I read this as host noise, not a regression, but the LCP margin to 2.5 s is thin and the first CI `perf` run should be watched (already flagged in FE-UX0). Backend untouched. **The e2e suite was edited but NOT run** (needs the real backend and model weights), so the e2e route updates are unverified.

**Open items from FE-UX3**
1. Not done from U1: U1.3 mobile bottom tab bar (the header now has four nav links plus the menu, so on a phone it wraps to more rows; no overflow, but taller), U1.4 inline verification `Alert` replacing the sticky banner, U1.5 desktop two-column layouts.
2. Run the e2e suite against the real stack before relying on the route edits; a missed reference would show up as a timeout, not a type error. `RUNBOOK.md`, `README.md` and `smoke/` had no references to the old routes (grep).
3. Old routes work only through the redirect; nothing else links to them. Remove the redirects in a later release if no traffic uses them.
4. `/graphify --update` is still needed for the changed plan docs.

### FE-UX4 — UX plan, U1.3/U1.4/U1.5: mobile tab bar, inline verify alert, two-column layouts (2026-10-08, branch `feat/UX-U1-shell`, commit `be38858`)

Completes phase U1 of `FRONTEND_UX_IMPROVEMENT_PLAN.md`.

| Area | Status | Evidence |
|---|---|---|
| Mobile tab bar (UX-25) | ✅ | `components/mobile-tabs.tsx`: below `sm`, signed-in users get a fixed bottom bar (Generate · Voices · History · Account, 56 px tall, `aria-current`), and the header keeps only the name and Sign out. `APP_LINKS` in `user-menu.tsx` is the single list used by both. The spacer after the footer keeps the last line reachable. |
| One verification notice (UX-07) | ✅ | `components/verify-email-alert.tsx` (replaces the sticky `VerificationBanner`) is rendered once, inline, on Generate and Voices. The duplicate notices inside the generate and upload forms are gone. The server still enforces the gate; making the buttons disabled-with-a-reason is U2.3. |
| Desktop two columns (UX-20) | ✅ | Generate: form beside the result (`lg`); Voices: create form beside the list (`lg`); one column on phones. |
| Header polish | ✅ | Desktop nav links are 44 px targets; the loading skeleton reserves the signed-in menu width at `sm`+. |
| Tests | ✅ | `tests/shell.test.tsx` (new: tabs, current marker, hidden while loading/signed out), `tests/navigation.test.tsx` (+1: alert only on the pages that need it, no sticky banner), form tests changed to assert there is no duplicate notice. |

**Verification run (local, Node 24):** `npm test` -> 33 files, **382 passed** (378 -> 382); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build with the API mocked (a 400 ms delayed `/auth/me`), at 320, 375 and 1280 px, unverified and verified users, all four routes: the tab bar is visible below `sm` and hidden above it; the header shows the four links only at desktop; exactly one verify alert on Generate and Voices and none elsewhere; zero horizontal overflow; two columns at 1280 px and one at phone width. `npm run perf` (median of 5): LCP 1.96-2.41 s, JS 180.6-197.5 KB, CLS 0.000, TBT <= 7 ms, all within budget. Layout shift measured with the same mock on `main` and on this branch: on phones it fell from 0.13-0.58 (the header re-wrapped when the session resolved) to 0.00-0.09; on desktop it ranged 0.005-0.048 before and 0.00-0.09 after, run to run. The shifts seen after the change came from the footer moving as the voice list loads and from the header menu growing when the session resolves; the second now has a reserved width. These are mocked-network numbers, not the repo's `layout-shift` e2e. Backend untouched. **e2e not run**; the `layout-shift` spec (budget 0.05) and the `responsive` spec (44 px targets, four routes) are the ones most likely to be affected and need the real stack.

**Open items from FE-UX4**
1. Run `e2e/layout-shift.spec.ts` and `e2e/responsive.spec.ts` against the real backend. If the desktop unverified case exceeds 0.05, the cause to chase is the footer shift while the voice list loads (give the list a reserved height).
2. Phase U1 is complete. Next is U2: landing page, auth form polish, the Generate first-run checklist, "Generate speech with this voice" after creating one, honest progress and result actions, copy pass, and the file-drop styling.
3. The plan's wireframe also showed a footer notice on every page; the footer text is unchanged.
4. `/graphify --update` for the plan docs is still pending (see the earlier note about not shrinking the graph).

### FE-UX5 — UX plan, U2.3/U2.4: first-run checklist, blocked-Generate reason, voice CTA (2026-10-08, branch `feat/UX-U2-first-run`, commit `44e49df`)

The first slice of phase U2: removes the first-minute dead end (UX-06) and the late-failing Generate button (UX-07).

| Area | Status | Evidence |
|---|---|---|
| First-run checklist | ✅ | `components/first-run-checklist.tsx` + `components/step-list.tsx` on Generate: "Verify your email -> Create a voice -> Generate speech", numbered (a real sequence), each step labelled Done / Next / To do in words, the next step has `aria-current="step"` and a primary "Create a voice" link. It holds the resend control, so Generate no longer shows a separate verify alert. It disappears once the email is verified and a ready voice exists, and waits for the voice list before deciding, so a returning user never sees a flash. A failed-only voice says the last upload could not be processed. |
| Generate is blocked with a stated reason (UR4) | ✅ | `lib/first-run.ts` derives the state from two facts. The Generate button is disabled for an unverified user ("Verify your email first.") or when no voice is ready ("Create a voice first."), and the reason is shown beside the button and linked with `aria-describedby`. While the list loads it does not block; the server still enforces both rules. |
| Next step after creating a voice | ✅ | The upload form shows a success message and a primary link "Generate speech with “<name>”" to `/generate?voice=<id>`; Generate preselects that voice. A preselected or remembered voice that is gone or not ready is cleared once the list loads (the plan's deleted-voice edge case). |
| Tests | ✅ | `tests/first-run.test.tsx` (13: the four state combinations, step list semantics, checklist for each state, blocked/enabled/preselect/stale preselect); updated `voice-profiles`, `synthesis`, `navigation` tests. |

**Verification run (local, Node 24):** `npm test` -> 34 files, **395 passed** (382 -> 395); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build with the API mocked, at 375 and 1280 px, for unverified / verified-no-voice / failed-only / ready-voice users: the right step is current, Generate is disabled with the matching reason in the first three and enabled in the last, `?voice=` preselects only a real ready voice, no horizontal overflow. `npm run perf` (median of 5): JS 180.6-197.5 KB, CLS 0.000, TBT <= 3 ms; LCP 1.82-2.17 s on three routes and 2.75 s on `/signup` in this run. This change does not touch the public pages (their JS is unchanged to 0.1 KB), and the failing route differs from run to run, so I read it as host noise as in FE-UX3/UX4; the thin LCP margin still needs watching on the first CI `perf` run. Backend untouched. **e2e not run** (needs the real backend and weights). Specs that sign up and then generate or upload must now expect the disabled button for an unverified user; `e2e/email.spec.ts` and `e2e/voice.spec.ts` (unverified upload) are the ones to check first.

**Open items from FE-UX5**
1. Rest of U2 not done: U2.1 landing page (copy must follow the owner decision in §11.3: no retention figure), U2.2 auth form polish and the single "Create account" label, U2.5 honest progress and result actions ("Edit text", "Generate again"), U2.6 copy pass (incl. the consent sentence and "Working…"), U2.7 styled file drop zone.
2. The upload form's own submit stays enabled for an unverified user (the server answers 403 with the existing message); only Generate follows UR4 so far. Do the same for Create voice with U2.6.
3. Run the e2e suite against the real stack; `/graphify --update` for the plan docs is still pending.

### FE-UX6 — UX plan, U2.1/U2.2/U2.6: landing page, auth form polish, copy pass (2026-10-08, branch `feat/UX-U2-public-copy`, commit `efd5f70`)

| Area | Status | Evidence |
|---|---|---|
| Landing page (UX-04) | ✅ | `app/page.tsx`: one `h1`, a concrete value sentence (10 to 30 seconds of a voice you have the right to use), "Create account" (primary) and "Sign in" (secondary), and three plain statements that are true by construction (consent is required to clone, deleting a voice erases everything made with it, speech is labelled AI-generated in the app). **No retention figure is published** (owner decision, UX plan §11.3); no demo audio (§11.4). Server component, no added JS. |
| Auth forms (UX-14) | ✅ | `components/form-fields.tsx`: `TextField` gets an always-visible `hint` linked by `aria-describedby`; new `PasswordField` with a "Show password" checkbox. Signup and reset-password show "8 to 128 characters" before typing; login, signup and reset use the show switch (the confirm field has none). `components/or-divider.tsx` separates Google from the email fields. |
| One action name (UX-13) | ✅ | "Create account" everywhere (header, landing, signup button). |
| Copy pass (UX-13) | ✅ | "Working…" -> "Creating voice…"; "Loading…" -> "Loading voices…", "Loading audio…", "Loading more…"; the consent line no longer exposes internal state: the terms version shows only with a real terms URL, otherwise "Terms are being finalised." |
| Create voice blocked with a reason (UR4) | ✅ | An unverified user gets a disabled Create voice button with "Verify your email first." linked by `aria-describedby` (matches Generate). |
| Guardrail | ✅ | `tests/public-copy.test.tsx` fails on "Working…", "Get started", "Sign up" as an action, a bare "Loading…" label, or "not published yet" anywhere in `app/` or `components/`. |

**Not done from this slice:** the Google provider mark (the official mark is a four-colour logo and the colour test forbids raw hex in components; add it as an SVG asset with the brand's own guidance if wanted).

**Verification run (local, Node 24):** `npm test` -> 35 files, **404 passed** (395 -> 404); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build (API stubbed to 401), light and dark at 320, 375 and 1280 px on `/`, `/signup`, `/login`, `/reset-password`: one `h1` each, no horizontal overflow, no console errors. `npm run perf`: JS 180.6-197.8 KB (login/signup about 2.2 KB under the 200 KB budget), CLS 0.001, TBT <= 6 ms. LCP was 1.9-2.3 s on most routes but one route read 2.56-2.61 s in two of three runs (`/` once, `/login` once; both passed in the other runs). The same intermittent single-route overrun has appeared in every recent run, including changes that did not touch that route, so I treat it as host noise; the margin is thin, so check the first CI `perf` run. Backend untouched. **e2e not run**: `e2e/voice.spec.ts` (unverified user now sees a disabled button) and `e2e/layout-shift.spec.ts` ("Create account" link) were edited by hand.

**Open items from FE-UX6**
1. Rest of U2: U2.5 honest progress and result actions ("Edit text", "Generate again") and U2.7 styled file drop zone.
2. JS headroom on `/login` and `/signup` is about 2.2 KB; new shared form code needs a budget check.
3. Backend asks UBD-2 (terms URL) and UBD-4 (expose retention) still pending; the in-app "kept for 30 days" text in `components/history-list.tsx` is still hard-coded.
4. `/graphify --update` for the plan docs is still pending.

### FE-UX7 — UX plan, U2.5/U2.7: Generate progress and result actions, file drop zone (2026-10-08, branch `feat/UX-U2-progress-drop`, commit `025d9b5`)

Completes phase U2 of `FRONTEND_UX_IMPROVEMENT_PLAN.md`.

| Area | Status | Evidence |
|---|---|---|
| Honest progress (UX-08) | ✅ | `components/text-to-speech-form.tsx`: while generating, a mono elapsed clock plus an indeterminate bar and the existing Cancel. The clock is `aria-hidden` so a screen reader hears "Generating…" once instead of every second. The bar moves only while a request is in flight (state, not decoration, UX plan §4.10); under reduced motion it is a static full bar (`motion-reduce:`), and the global reduced-motion rule now also sets `animation-iteration-count: 1`. |
| Result actions (UX-08) | ✅ | "Edit text" focuses and selects the text box; "Generate again" re-runs the original text with the same voice (even if the box was edited since) and follows the same blocking rules as the main button. |
| Styled file picker (UX-18) | ✅ | `components/audio-uploader.tsx`: a visible "Choose file" / "Choose a different file" button (a `label` for the real input), the real `<input type="file">` is visually hidden but remains the single tab stop with a visible focus ring on the button; drag-and-drop and validation unchanged; the chosen file name and size are shown in the mono face. |
| Tests | ✅ | `tests/synthesis.test.tsx` (+3: Edit text/Generate again, original-text rule, quiet progress), `tests/voice-profiles.test.tsx` (+1: picker label and selected file). |

**Verification run (local, Node 24):** `npm test` -> 35 files, **408 passed** (404 -> 408); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build, API mocked, 375 and 1280 px and reduced-motion: the bar animates for 1.4 s per cycle normally and does not under reduced motion, the clock ticks, "Edit text" lands focus in the text box, no horizontal overflow; the file button is 44 px tall in light and dark, shows the chosen file, and shows a 2 px focus outline when the hidden input has keyboard focus. (A first run of this check showed that the reduced-motion rule alone leaves the bar parked off-screen at its end position; that is why the static `motion-reduce` classes exist.) `npm run perf`: JS unchanged at 180.6-197.8 KB, CLS 0.001, TBT <= 7 ms. **LCP is flaky:** across the last three runs one or two of the four public routes read 2.56-2.76 s, a different pair each time (`/`, `/login`, `/signup`, `/forgot-password`), and `/` and `/forgot-password` do not use any code changed here. The host has a browser running alongside; I treat this as noise, but it is now the thing most likely to fail the first CI `perf` run (LCP budget 2.5 s). If CI confirms it, the options already listed in FE-UX0 apply first (drop the 500 weight of Plex Sans, then raise `PERF_RUNS`). Backend untouched. **e2e not run**; the file input is still found by `input[type=file]`, so the existing upload specs should be unaffected.

**Open items from FE-UX7**
1. Phase U2 is complete except the Google provider mark (see FE-UX6). Next is U3: `Dialog` primitive (focus trap, scrim, destructive variant) for delete voice and delete account, session-expiry message and return path, offline handling, error-fallback routes, empty states as buttons, skeletons.
2. JS headroom on `/login` and `/signup` is about 2.2 KB; `Dialog` should reuse `hooks/use-dialog.ts` and load only on the pages that open it.
3. `/graphify --update` for the plan docs is still pending.

### FE-UX8 — UX plan, U3.1/U3.2: Dialog primitive and session-ended message (2026-10-08, branch `feat/UX-U3-dialog`, commit `d628dea`)

| Area | Status | Evidence |
|---|---|---|
| `Dialog` primitive (UX-15) | ✅ | `components/ui/dialog.tsx`: a real overlay (scrim, centred panel, `alertdialog` named by its heading), focus trap and focus return from the existing `hooks/use-dialog.ts`, Escape and a scrim click both cancel, both ignored while a request is in flight (`closeDisabled`), page scroll locked while open. A press that starts inside the panel and ends on the scrim (selecting text) does not dismiss. Delete voice and Delete account now use it (the inline pseudo-dialogs and `ModalPanel` are gone); their confirm buttons use the red `danger` variant. |
| Session ended message (UX-16) | ✅ | `components/auth-gate.tsx`: if a signed-in session ends while the page is open (expiry, or sign-out in another tab) the redirect is `/login?reason=expired&next=…` and the sign-in page says "Your session ended. Sign in to continue."; after sign-in the user returns to the same page. A first visit without a session, and a deliberate sign-out, are unchanged (no message). |
| Tests | ✅ | `tests/dialog-primitive.test.tsx` (new, 4), `tests/auth-gate.test.tsx` (+1), `tests/auth-ui.test.tsx` (+2); existing delete-dialog and keyboard tests unchanged and green. |

**Verification run (local, Node 24):** `npm test` -> 36 files, **415 passed** (408 -> 415); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build with the API mocked, light and dark, at 320 and 1280 px: the delete-voice dialog sits fully inside the viewport, focus starts on the red confirm button, the page is scroll-locked while open and unlocked after, a scrim click closes it and focus returns to the row's Delete button. (The first run of this check showed focus did *not* return after a mouse click on the scrim, because closing on `mousedown` let the browser move focus afterwards; the scrim now closes on `click` and the check passes.) The account dialog at 320 x 420 has no horizontal overflow. Session expiry: with the session expired mid-use, opening History redirected to `/login?reason=expired&next=%2Fhistory` and the message was shown. `npm run perf` (median of 5): LCP 2.1-2.4 s, JS 180.6-197.9 KB, CLS 0.001, TBT <= 8 ms, all within budget this run. Backend untouched. **e2e not run**; `e2e/dialog-keyboard.spec.ts` asserts the same roles and focus rules and should still pass, but a scrim now covers the page, so any e2e step that clicked behind an open dialog would now be blocked.

**Not done from U3.2, on purpose:** keeping the voice name, consent and generate text across the sign-in redirect. `AuthProvider.endSession` clears the in-memory draft on every session end (R16, no data survives sign-out) and the plan itself warns that restoring state must not leak between accounts; doing this safely needs a design decision (restore only when the same user signs back in) and its own test.

**Open items from FE-UX8**
1. Rest of U3: U3.3 offline handling (`useOnline`, alert, disabled network actions, refetch on reconnect), U3.4 error fallback with "Go to Generate" and a branded global error, U3.5 empty states as buttons and skeletons matching the final layout, U3.6 (the single verification alert is already done via FE-UX4/FE-UX5; mark complete after the checklist review).
2. The draft-restore decision above.
3. `/graphify --update` for the plan docs is still pending.

### FE-UX9 — UX plan, U3.3/U3.4/U3.5: offline handling, error recovery, empty-state actions (2026-10-08, branch `feat/UX-U3-resilience`, commit `aba1849`)

Completes phase U3 of `FRONTEND_UX_IMPROVEMENT_PLAN.md` apart from the draft-restore decision (see FE-UX8).

| Area | Status | Evidence |
|---|---|---|
| Offline (UX-22, UR5) | ✅ | `hooks/use-online.ts` (`useSyncExternalStore` over `online`/`offline`), `components/offline-banner.tsx` in the app shell ("You're offline. Uploading and generating are paused until your connection is back."), and Generate and Create voice are disabled with "You're offline." beside the button, linked by `aria-describedby`. `lib/query.ts` now sets `refetchOnReconnect: "always"`: the default only refetches stale queries, and the app's 30 s `staleTime` meant fresh-looking data was not re-read after a connection loss. |
| Error screens (UX-23, UR15) | ✅ | `components/error-fallback.tsx` offers "Try again" and "Go to Generate" (a plain link: after a crash router state cannot be trusted and the global fallback has no router). `app/global-error.tsx` now brings the wordmark, main landmark and footer, so it is never a blank page; raw error text is never shown. |
| Empty states (UR2) | ✅ | Voices: "You haven't created a voice yet." with a "Create a voice" button that focuses the name field. History: "Nothing generated yet." with a "Generate speech" link button; the stale mention of a "dashboard" is gone. |
| Tests | ✅ | `tests/resilience-ui.test.tsx` (new, 11): `useOnline`, banner, both forms disabled/enabled with the reason, refetch on reconnect through the real `createQueryClient`, both error fallbacks, both empty states. |

**Verification run (local, Node 24):** `npm test` -> 37 files, **425 passed** (415 -> 425; the refetch test first failed, which is how the stale-data gap above was found); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build with the API mocked, using `setOffline` at 375 and 1280 px: the banner appears, Generate becomes disabled with the reason, there is no horizontal overflow, and on reconnect the banner clears, Generate is enabled again and the voice list is refetched. `npm run perf` (median of 5): LCP 1.96-2.26 s, JS 181.2-198.5 KB, CLS 0.001, TBT <= 5 ms, all within budget this run. **JS headroom on `/login` is now about 1.5 KB** (it was 2.2 KB): the offline banner and hook ship in the shell on every page. **Not exercised in a browser:** the route and global error screens (they are covered by unit tests; there is no safe way to force a crash in the production build without adding a test-only route). Backend untouched. **e2e not run**; `e2e/resilience.spec.ts` already uses `context.setOffline` and should be extended to assert the banner (not done).

**Open items from FE-UX9**
1. Draft restore across the sign-in redirect (U3.2) still needs the same-user design decision.
2. Add e2e assertions for the offline banner and the disabled buttons; add per-route error-boundary tests (UR15) if the owner wants them as a release gate.
3. Phase U4 (the `Take` component: waveform, level meter, playback) is next and is the largest remaining visual piece. It must stay lazy: JS headroom on the form routes is about 1.5 KB.
4. `/graphify --update` for the plan docs is still pending.

### FE-UX10 — UX plan, U4.1/U4.3/U4.4: the Take player with waveform (2026-10-08, branch `feat/UX-U4-take`, commit `9ed6ea5`)

The first slice of phase U4 (UX-12: make the audio visible).

| Area | Status | Evidence |
|---|---|---|
| `Take` component | ✅ | `components/take.tsx` replaces `AudioPlayer` (deleted). A native `<audio>` element (no browser controls) under our own: a Play/Pause button, a monospaced timecode ("0:03 / 0:07"), a waveform with a playhead, and a seek slider laid over the waveform (`aria-valuetext` carries the timecode; arrow keys jump 2 s because takes are short; Home/End work natively; a focus ring surrounds the whole strip). The waveform is `aria-hidden`: the button and slider are the accessible controls. Download link retained. If the audio errors it says so and keeps the download; if the shape cannot be computed the controls still work (no bars, a plain line). |
| Waveform data | ✅ | `lib/audio-peaks.ts`: `bucketPeaks` (loudest sample per slice, scaled to the loudest bar) and `computePeaks` (Web Audio `decodeAudioData` on the blob already in memory, no fetch of a `blob:` URL so the CSP `connect-src` is untouched; size cap 8 MB; returns null on any failure, never throws). Loaded with a dynamic `import()` so the decoder is in no page's first-load JavaScript. |
| Where it is used | ✅ | Generate result, History playback (still loads audio only on Play, as before) and the recording preview (no download link there). |
| Tests | ✅ | `tests/take.test.tsx` (new, 14): peak maths, every `computePeaks` failure path, play/pause, timecode, seeking by slider and arrows, ended, error with download kept, waveform present and absent. |

**Verification run (local, Node 24):** `npm test` -> 38 files, **438 passed** (425 -> 438); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build with a real 2 s WAV (synthesised in the check script) returned from the mocked API, at 375 px light and 1280 px dark: 64 bars are drawn and their heights vary with the audio, Play flips to Pause and the playhead clip advances, Home then ArrowRight lands on 0 then 2 s, the focus ring shows, no horizontal overflow. `npm run perf`: the public routes' JS is unchanged by this change (181.3 / 198.5 / 198.1 / 196.9 KB, Take is not on them); LCP read 2.76 s on `/` and 2.56 s on `/login` in this run and 2.1 s on the others, the same intermittent pattern as the last several runs on routes this change does not touch (host noise, but the margin is thin). Backend untouched. **e2e not run.** The recorder preview was not exercised in a browser (needs the fake-media flags the e2e recording spec already uses). `e2e/synthesis.spec.ts` and `e2e/recording.spec.ts` look for the audio by its label or the "Download WAV" link; the label on the `<audio>` element is unchanged, but the visible controls are now ours, so any step that clicked the native player needs updating.

**Open items from FE-UX10**
1. U4.2: the live level meter while recording (`AnalyserNode`, lazy with the recorder) and the recording dot driven by level, not a timer. Not started.
2. Playhead is driven by `timeupdate` (about 4 updates a second), which is adequate for short takes; smoother motion is U5.
3. Add a recording e2e assertion for the preview `Take`, and update e2e steps that used the native controls.
4. `/graphify --update` for the plan docs is still pending.

### FE-UX11 — UX plan, U4.2: live microphone level meter (2026-10-08, branch `feat/UX-U4-level-meter`, commit `b26cd6a`)

Completes phase U4 of `FRONTEND_UX_IMPROVEMENT_PLAN.md`.

| Area | Status | Evidence |
|---|---|---|
| Level meter (UX-12) | ✅ | `hooks/use-input-level.ts` reads an `AnalyserNode` on the live recording stream once per animation frame (every 250 ms under `prefers-reduced-motion`), smooths with a short decay, and quantises to 20 steps to limit renders. `components/recorder.tsx` shows a `role="meter"` bar ("Microphone level", 0-100) and the recording dot now swells with the input level instead of sitting static, so it shows the microphone is live. |
| Silent-microphone warning | ✅ | If nothing is heard for 3 s: "We can't hear anything. Check that the right microphone is selected and not muted." (polite status). It clears as soon as sound returns. |
| Stream plumbing | ✅ | `hooks/use-recorder.ts` now exposes `stream` (set when recording starts, cleared whenever the microphone is released), so the meter's audio graph is torn down with it. Without Web Audio the level stays 0 and recording works exactly as before. The recorder is already loaded on demand, so none of this is in any page's first-load JavaScript. |
| Tests | ✅ | `tests/input-level.test.tsx` (new, 8: RMS maths, follow and decay, silence timing and recovery, reduced-motion sampling, graph teardown, no-Web-Audio); `tests/recording.test.tsx` (+1: labelled meter, no false silent warning). |

**Verification run (local, Node 24):** `npm test` -> 39 files, **446 passed** (438 -> 446); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium with its fake microphone (`--use-fake-device-for-media-stream`) against the production build: with the built-in test tone the meter's value moved between 0 and 100 while recording (375 px light, 1280 px dark) and no silent warning appeared; with a silent WAV as the microphone input the meter stayed at 0 and the warning appeared; no horizontal overflow. `npm run perf` (median of 5): all four public routes within budget this run (LCP 2.11-2.47 s, JS 181.3-198.5 KB, CLS 0.001); JS is unchanged by this change. Backend untouched. **e2e not run**; `e2e/recording.spec.ts` uses the same fake-media flags and should be unaffected, but it should be extended to assert the meter.

**Open items from FE-UX11**
1. Phase U4 is complete. Next is U5 (motion: the `fast`/`base` tokens on press and disclosure, the one-time waveform draw-in when a result finishes, and a reduced-motion audit including the playhead and this meter), then U6 (accessibility and performance: arrow keys for the Upload/Record radio group, forced-colors and `prefers-contrast` pass, the manual NVDA/VoiceOver pass that needs a person) and U7 (release hardening).
2. The 3-second silence threshold and the meter scaling were checked only against Chromium's synthetic microphone; real microphones and laptops differ, so a manual check on real hardware is worthwhile.
3. `/graphify --update` for the plan docs is still pending.

### FE-UX12 — UX plan, U5: motion tokens, dialog fade, waveform draw-in (2026-10-08, branch `feat/UX-U5-motion`, commit `c5447fd`)

| Area | Status | Evidence |
|---|---|---|
| Motion tokens (U5.1) | ✅ | `tailwind.config.ts`: `duration-fast` (120 ms) and `duration-base` (200 ms). Buttons use `duration-fast` (colour feedback only, no transform, so no layout shift). A guardrail test fails on any other numeric `duration-*` in `app/` or `components/`. |
| Dialog appearance (U5.1) | ✅ | The dialog scrim fades in over 200 ms (`animate-fade-in`). |
| One deliberate moment (U5.2) | ✅ | `Take` takes `animateIn`; only the Generate result sets it, so the waveform draws in once over 350 ms when a generation finishes. History replays and the recording preview do not animate. |
| Reduced motion (U5.3) | ✅ | Audited with the browser's own animation list (`document.getAnimations()`), see below. The earlier fix (`animation-iteration-count: 1` in the global rule, static `motion-reduce` classes on the progress bar) is what makes this hold; the level meter already sampled at 250 ms, and the playhead is driven by `timeupdate`, not animation. U5.4 (no illustrations) needs no work. |
| Bug found while here | ✅ | Every waveform used the SVG clip id `take-played`; ids are document-global, so on a page with several takes (History) all would have been clipped by the first one's playhead. Each take now has its own id (`useId`); covered by a test. |
| Tests | ✅ | `tests/take.test.tsx` (+1: animate only when asked, unique clip ids), `tests/theme.test.ts` (+1: duration tokens), small additions to the dialog and button tests. |

**Verification run (local, Node 24):** `npm test` -> 39 files, **449 passed** (446 -> 449); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Real Chromium against the production build, the running-animation list at each step. Normal motion: idle none; while generating only the 120 ms button colour change and the 1.4 s indeterminate bar; on completion a single 350 ms `draw-in`, none 600 ms later and the waveform at its final state; opening the delete dialog a single 200 ms `fade-in`, none 400 ms later. Reduced motion: idle none; while generating only 0.01 ms transitions (which finish at once); on completion nothing runs and the waveform is at its final state; the dialog's fade is 0.01 ms. `npm run perf` (median of 5): JS unchanged (181.3 / 198.5 / 198.1 / 196.9 KB), CLS 0.001, TBT <= 7 ms; LCP 2.1-2.4 s on three routes and 2.62 s on `/` in this run (the same one-route intermittent overrun as in the last several runs on code this change does not touch). Backend untouched. **e2e not run.**

**Open items from FE-UX12**
1. Not done from U5.1: toast and disclosure motion. There are no disclosures in the app, and the toast library (`sonner`) brings its own animation; whether it honours the global reduced-motion rule was not checked.
2. Skeleton loaders still pulse (`animate-pulse`); they are a loading state, not decoration, and stop under reduced motion, but the plan could be read as banning looping motion, so say if you want them static.
3. Next: U6 (accessibility and performance: arrow keys on the Upload/Record choice, forced-colors and `prefers-contrast` pass, 200-400% zoom reflow at 320 px, the manual NVDA/VoiceOver pass that needs a person) then U7 (cross-browser, visual baselines, docs, release gate).
4. `/graphify --update` for the plan docs is still pending.

### FE-UX13 — UX plan, U6.1: radio keyboard model for the sample source choice (2026-10-09, branch `feat/UX-U6-a11y-radio`, commit `d552fe9`)

| Area | Status | Evidence |
|---|---|---|
| Arrow-key handling (U6.1, UX-17) | ✅ | `components/upload-voice-form.tsx`: the "Upload a file / Record now" `role="radio"` group now has roving `tabIndex` (one tab stop), Arrow keys move and select with wrap-around, Home/End jump, and focus follows selection. |
| Forced colours (U6.2, part) | ✅ | The selected choice gets a 2 px `Highlight` border under `forced-colors`, so the state does not rely on background colour. Not checked in a real forced-colors browser. |
| Tests | ✅ | `tests/recording.test.tsx` (+1: tab stops, arrows, wrap, Home/End). |

**Verification run (local, Node 24):** `npm test` -> 39 files, **450 passed** (449 -> 450); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. Backend untouched. **e2e, `npm run perf` and axe-in-browser not run.**

**Open items from FE-UX13**
1. Rest of U6: U6.2 contrast/`prefers-contrast` re-verify and a real forced-colors pass, U6.3 manual NVDA/VoiceOver (needs a person), U6.4 perf budget confirmation, U6.5 44 px targets and 320 px reflow at 200-400% zoom. Then U7.

### FE-UX14 — UX plan, U6.2/U6.5: prefers-contrast tokens, logo touch target (2026-10-09, branch `feat/UX-U6-contrast-targets`, commit `a5d4bd3`)

| Area | Status | Evidence |
|---|---|---|
| `prefers-contrast: more` (U6.2) | ✅ | `app/globals.css`: darker `--line`, `--border` and `--muted-foreground` for light, explicit dark and OS dark (three entry points). `tests/theme.test.ts` (+1) asserts secondary text >= 7:1 on background, surface and muted, outlines >= 4.5:1, and that the two dark blocks match. Computed `--line` confirmed in Chromium for contrast more/no-preference, light/dark. |
| Forced colours (U6.2) | ✅ (partial) | Pages render without overflow under emulated `forced-colors: active`; the radio's `Highlight` border from FE-UX13 is not visually inspected. |
| Touch targets (U6.5) | ✅ | A real-Chromium sweep of every link, button, input and radio on 7 routes at 320, 375 (light, dark, forced-colors, contrast more) and 1280 px found one miss: the header logo link, 34 px high. It is now `min-h-11`. The visually hidden file input is excluded (its label button is 44 px). Zero horizontal overflow on every route and size. |
| e2e guard | ✅ (unrun) | `e2e/responsive.spec.ts` now also measures links (inline links in text and `.sr-only` are exempt), so a short nav link fails the spec. |

**Verification run (local, Node 24):** `npm test` -> 39 files, **451 passed** (450 -> 451); `typecheck`, `lint`, `format:check` clean; `npm run build` ok. The browser sweep used the production build with the API mocked. Backend untouched. **e2e, `npm run perf` and axe not run.**

**Open items from FE-UX14**
1. Rest of U6: U6.3 manual NVDA/VoiceOver (needs a person) and U6.4 the `npm run perf` confirmation. The header is about 10 px taller now, so run perf once. Then U7.

### FE-UX15 — UX plan, U6.4: performance budget confirmation (2026-10-09, branch `chore/UX-U6-perf-check`; verification only, no code change)

`npm run perf` (Lighthouse mobile profile, median of 5) on the production build of `main` at `aaefba9`, after the FE-UX14 header change:

| Route | LCP | JS | CLS | TBT |
|---|---|---|---|---|
| `/` | 2421 ms | 181.3 KB | 0.001 | 2 ms |
| `/login` | 2411 ms | 198.5 KB | 0.001 | 0 ms |
| `/signup` | 2263 ms | 198.1 KB | 0.001 | 4 ms |
| `/forgot-password` | 2419 ms | 196.9 KB | 0.001 | 2 ms |

All four pass the gate (LCP <= 2500 ms, JS <= 200 KB, TBT <= 300 ms). **Margins are thin:** LCP is 80-240 ms under the limit and `/login` is 1.5 KB under the JS limit, so a small addition to the public routes will break the budget. **The enforced CLS budget in `perf/budget.mts` is 0.1, looser than the 0.02 this plan asks for (U6.4, U0 exit criteria);** measured CLS is 0.001, so tightening the constant to 0.02 is safe and not done here (it changes the gate, so it is your call). This run is one host and one session; the first CI `perf` run is still the authority.

**Open items from FE-UX15**
1. Phase U6 now waits only on U6.3 (manual NVDA/VoiceOver, needs a person). U7 (cross-browser e2e, visual baselines, docs, release gate) can start; the e2e suites need the real backend and weights.

### FE-UX16 — UX plan, U7.3: README and RUNBOOK update (2026-10-09, branch `chore/UX-U7-docs`, commit `72c532a`; docs only)

`frontend/README.md` gains a route table, the legacy `/dashboard` and `/profile` redirects, and a design-system and accessibility section (token guardrails, 44 px targets, reduced motion, the manual screen-reader pass still owed); the perf section notes the CLS gap (budget 0.1, plan 0.02). `frontend/RUNBOOK.md` gains a troubleshooting entry for old links (`curl -sI $WEB/dashboard` should give 308 to `/generate`; the redirects are in `next.config.mjs`). Prettier clean; no code or test changes, so the test suite was not re-run. The smoke script was **not** changed: it checks `/login`, `/verify-email` and the API only, and does not exercise the redirects.

**Open items from FE-UX16**
1. U7.3 is done except that nothing automates the redirect check. U7.1 (full e2e on Chromium and Firefox, needs the real backend and weights; recipe in `frontend/e2e/README.md`), U7.2 (visual baselines) and U7.4 (rollout note) remain, then the manual U6.3.

### FE-UX17 — UX plan, U7.1: first full e2e run since the redesign, and the fixes (2026-10-09, branch `fix/e2e-redesign-specs`, commit `0d91969`)

The e2e suite (real FastAPI backend, real weights, SQLite, console email; recipe in `frontend/e2e/README.md`) had **never been run** against the FE-UX0..16 UI. First Chromium run: **35 of 45 failed**. Almost all were stale selectors, but two were real defects.

| Finding | Kind | Fix |
|---|---|---|
| `getByLabel("Password")` matched the field and the "Show password" checkbox (strict-mode violation); 35 specs died at sign-up | spec | `{ exact: true }` in all e2e files |
| "Sign in" matched the nav link and the landing page CTA | spec | scoped to the Primary navigation (`helpers.ts`, `auth.spec.ts`) |
| `getByLabel("Generated speech" / "Recording preview")` matched the `<audio>`, the Play button and the seek slider; the `<audio>` has no UI so is never "visible" | spec | `audio[aria-label=...]` + `toBeAttached()` (`synthesis`, `soak`, `recording`, `csp`); history replay uses the `Generated audio from` prefix and an exact `Play` button |
| Dialog spec looked for "Delete my account" on `/voices`; it moved to `/account` | spec | `page.goto("/account")` (`dialog-keyboard`, `a11y`) |
| axe read colours mid-way through the 200 ms dialog fade (FE-UX12) and reported contrast on the dialog | spec | the audit waits for running animations to finish |
| **Success `Badge` text (`--success` on `--muted`) was 4.37:1 in light mode, under WCAG AA 4.5:1** (axe: `color-contrast` on `/voices`). The palette test only checked `success` on surface/background | **product** | `--success` light 30% -> 28% lightness (4.87:1); `tests/theme.test.ts` now asserts `success` on `muted` |
| First-run checklist arrives after the voice list and pushes the form down about 290 px (CLS 0.23 at 320 px for a brand-new user) | **product, not fixed** | A localStorage "seen it" hint plus a placeholder fixed it but breaks the memory-only-storage guardrail (`tests/hardening.test.ts`), so it was reverted. Without a hint a placeholder just moves the shift to returning users, who are the majority. The "signed in, after a reload" CLS spec now uses a returning user (a voice created first), and passes at 320/360/412 px. |

**Result:** Chromium **44 passed, 1 failed**; Firefox **36 passed, 9 skipped** (the skips are the Chromium-only layout-shift specs). Unit: `npm test` 39 files, 451 passed; `typecheck`, `lint`, `format:check` clean. **Not run: WebKit, `npm run perf` after the `--success` change (a colour only).**

**Still failing (Chromium):** `layout-shift` > 320px > "signed in but unverified" measures **0.056** against the spec's 0.05. The shifting element is the footer, which sits at about 693 px while the session skeleton shows (`main` is `min-h-[70vh]`) and leaves the viewport once the page content arrives; the header does not move. It is within Google's 0.1 "good" threshold; either raise the spec bound to 0.1 or make `main` taller on phones. I did not loosen the spec.

**Open items from FE-UX17**
1. Decide the 320 px unverified CLS bound (above) and whether a first-run user's checklist shift is acceptable or the checklist should move (for example into the page grid beside the form) so it cannot push the form.
2. U7.2 visual baselines, U7.4 rollout note, WebKit, and the manual U6.3 remain.

### FE-UX18 — UX plan, U7.2: visual-regression baselines (2026-10-09, branch `feat/FE-UX18-visual-baselines`, commit `8824d4d`)

New `frontend/playwright.visual.config.ts` and `frontend/visual/public.spec.ts`, run with `npm run test:visual`. The API is mocked at the network layer (signed out, health ok), so **no backend is needed**. Public routes (`/`, `/login`, `/signup`, `/forgot-password`) x 375/768/1280 px x light/dark (theme set through the `cv-theme` cookie) = **24 full-page baselines** in `frontend/visual/__screenshots__/` (760 KB, committed; no platform suffix, so regenerate them on the CI OS). Reduced motion on, animations disabled, `maxDiffPixelRatio` 0.002. Two baselines (`home-1280-dark`, `signup-375-light`) were reviewed by eye; the other 22 were not. A second run passed 24/24 (deterministic on this host). `npm test` 451 passed; `typecheck`, `lint` clean.

**Not done:** signed-in routes (`/generate`, `/voices`, `/history`, `/account`) have no baselines yet; they need mocked session, voices and history responses. The baselines are not wired into CI.

**Open items from FE-UX18**
1. Add signed-in baselines with mocked responses, and run `test:visual` in CI on the same OS that generated them.
2. U7.4 rollout note, the FE-UX17 CLS decisions, WebKit and the manual U6.3 remain.

### FE-UX19 — UX plan, U7.2: signed-in visual baselines (2026-10-09, branch `feat/FE-UX19-signed-in-baselines`, commit `2f144d1`)

`frontend/visual/signed-in.spec.ts` adds **30 baselines**: `/generate`, `/voices`, `/history`, `/account` (plus the `/generate` first-run state: unverified, no voices) x 375/768/1280 px x light/dark. The API is mocked with CORS headers (verified user, one ready and one failed voice, one history row); the config now pins `en-US` and `UTC` so dates do not drift. Total **54 baselines, 54/54 on a second run**; `npm test` 451 passed, typecheck and lint clean. Viewed by eye: `voices-1280-light`, `generate-first-run-375-dark` (the tab bar appears mid-image: a full-page capture artefact of the fixed bar, not a defect). The other 28 were not opened.

**Not done:** no baselines for open dialogs, error or offline states, or a finished `Take`; not wired into CI.

**Open items from FE-UX19**
1. U7.4 rollout note, the FE-UX17 CLS decisions, CI wiring for `test:visual`, WebKit, and the manual U6.3.

### FE-UX20 — UX plan, U7.4: staged rollout note (2026-10-09, branch `docs/FE-UX20-rollout-note`, commit `32b1acc`; docs only)

`frontend/RUNBOOK.md` gains "Staged rollout of the UX redesign": six stages (tokens and primitives, routes and shell, core flows, states, voice take and motion, accessibility), each with its real commit hashes, the user-visible change and the signal to revert on; stage 2 (URL changes) is flagged as the riskiest. No code or test change, so the suite was not re-run.

**Open items from FE-UX20**
1. Nothing in U0-U7 is left to build. Remaining: the FE-UX17 CLS decisions (owner), CI wiring for `test:visual`, WebKit, and the manual screen-reader pass (U6.3, needs a person).

### FE-UX21 — UX plan close-out: U0.6 and U3.6 (2026-10-09, branch `docs/FE-UX21-plan-closeout`, commit `7ccb801`; docs only)

Checked against the code before marking: U0.6 (`--primary` is the single teal swap point in `app/globals.css`, documented in plan §11.1 and guarded by the token lint) and U3.6 (`VerifyEmailAlert` renders once on `/voices`; `/generate` shows the same notice only inside the first-run checklist, so no page shows it twice). Both were done earlier but never marked. No code change. I also correct my FE-UX20 summary: its commit is `32b1acc`, as recorded above.

**Left in the UX plan:** the Google provider mark (U2.2) and the draft restore (U3.2, needs an owner decision), the FE-UX17 CLS decisions (owner), CI wiring for `test:visual`, WebKit, and the manual U6.3.

### FE-UX22 — UX plan, U2.2: Google provider mark (2026-10-09, branch `feat/FE-UX22-google-mark`, commit `e58f693`)

New `components/google-mark.tsx` (inline SVG "G", decorative, `aria-hidden`) shown in `GoogleButton` with `gap-2`. Its four fills are Google's mandated brand colours, so the raw-colour guardrail in `tests/theme.test.ts` now skips that one file (the exemption is stated in the test and the file header). The 12 `/login` and `/signup` visual baselines were regenerated (`login-375-dark` viewed: mark renders, button label unchanged). `npm test` 451 passed, typecheck and lint clean. Not run: `npm run perf` (a ~1 KB inline SVG, no new request), WebKit.

**Open items from FE-UX22**
1. Remaining in the UX plan: draft restore (U3.2) and the FE-UX17 CLS decisions (owner), CI wiring for `test:visual`, WebKit, manual U6.3.

### FE-UX23 — Owner decision on the 320 px unverified CLS bound (2026-10-09, branch `fix/cls-bound-320`, commit `0743840`)

Decision (owner): raise the bound for "signed in but unverified" in `e2e/layout-shift.spec.ts` from 0.05 to 0.1 (Google's "good" threshold; FE-UX17 measured 0.056, from the footer moving). Only that one spec changed; the other layout-shift specs keep 0.05. **Not re-run:** the e2e needs the real backend and weights, so the spec is edited but unexecuted; the bound is above the measured value, so it should pass. The first-run checklist shift (an unrelated, larger shift for brand-new users) is still open.

**Open items from FE-UX23**
1. Run `e2e/layout-shift.spec.ts` on the next e2e pass to confirm. Remaining in the UX plan: draft restore (U3.2), the checklist shift, CI wiring for `test:visual`, WebKit, manual U6.3.

### FE-UX24 — UX plan, U3.2: draft restore across an expired session (2026-10-09, branch `feat/FE-UX24-draft-restore`, commit `3e19798`)

Design (the one FE-UX8 proposed): `lib/draft.ts` is now keyed by user id (`getDraft(userId)`, `saveDraft(userId, …)`). It holds the generate voice and text and the new voice name, in memory only. `AuthProvider.endSession` no longer clears it, so an expired session (redirect to `/login?reason=expired`) keeps it; `logout` and `discardSession` (deliberate sign-out, account deletion) call `clearDraft()` explicitly. A different user sees an empty draft, and their first save discards the old one. Both forms restore once the session is known, then start saving (so the empty initial state never overwrites it). **Consent is deliberately not restored** (it must be confirmed again), and the file is never kept.

Tests: `tests/draft.test.ts` (6: owner-only, other user, replacement, no user, sign-out, no consent field) and an integration test in `tests/synthesis.test.tsx` (no restore after sign-out, nor for another owner). **Negative control:** removing `clearDraft()` from `logout` fails the integration test. `npm test` 458 passed; typecheck, lint, prettier clean.

**Limits:** a sign-out in another tab arrives as the same `cleared` event as an expiry, so that draft is kept in memory for the same user only; it never survives a reload. Not covered by an e2e test; the upload form's name restore has no dedicated test (it shares the generate form's pattern).

**Open items from FE-UX24**
1. Remaining: the first-run checklist shift, CI wiring for `test:visual`, WebKit, manual U6.3.

### FE-UX25 — UX plan, U7.2: visual tests in CI (2026-10-09, branch `chore/FE-UX25-visual-ci`, commit `4664f07`; CI config only)

`.github/workflows/frontend.yml` gains a `visual` job (Node 20, Playwright Chromium, `npm run test:visual`, diff images uploaded as an artifact on failure). It is **advisory** (`continue-on-error: true`): the baselines were generated on a local Ubuntu host, and **this job has never run on GitHub's runner**, so whether they match is unknown. The YAML parses; nothing else was run. After the first CI run: if green, delete `continue-on-error`; if it fails on font or anti-aliasing noise, download the artifact and either regenerate the baselines from that run or raise `maxDiffPixelRatio`.

**Open items from FE-UX25**
1. Read the first CI result for the `visual` job. Remaining: the first-run checklist shift (owner), WebKit, manual U6.3.

### FE-UX26 — Owner decision: reserve space for the first-run checklist (2026-10-09, branch `fix/FE-UX26-checklist-shift`, commit `e1dcd60`)

Decision (owner): reserve space. `FirstRunChecklist` now renders an `aria-hidden` placeholder (`min-h` 16.625rem below 360 px, 15.375rem above) while a **verified** user's voice list loads, instead of nothing, so the form below does not jump down when the checklist arrives. (An unverified user's checklist renders with the page, so it never shifted; the shifting case was verified-with-no-voice.) Heights were measured in Chromium (266 px at 320, 246 px from 360 up).

**Measured (Chromium, API mocked, voice list delayed 600 ms, verified user with no voice, one page per width):** CLS **0.23 / 0.23 / 0.23 / 0.23 / 0.24 / 0.28 / 0.14** before at 320/360/375/400/600/768/1280 px; **0.048 / 0.042 / 0.040 / 0.040 / 0.032 / 0.038 / 0.019** after. The remainder is the session skeleton giving way to the page (footer), unrelated to the checklist and unchanged. Only 320-768 px are below the 0.05 spec bound by a small margin; 0.1 is the e2e bound for the unverified case (FE-UX23).

**Cost, as chosen:** a returning verified user who has a voice sees a blank gap of that height until the list loads, then the form moves up (a shift in the other direction; not measured separately). A checklist taller than the placeholder (very long email addresses wrapping) still shifts by the difference.

Tests: a new case in `tests/first-run.test.tsx` (placeholder present while loading, gone once the checklist shows); **negative control:** returning `null` instead fails it. `npm test` 459 passed; typecheck, lint, prettier clean; all 54 visual baselines still pass unchanged. Not run: the real-backend e2e `layout-shift` spec.

**Open items from FE-UX26**
1. Re-run `e2e/layout-shift.spec.ts` and read the CI `visual` job (FE-UX23, FE-UX25). Remaining: WebKit, manual U6.3.

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
