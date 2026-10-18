# CloneVoice — Account Data Export Plan

> **Status**: 🟡 E1 landed (`a5b166b`); E2 not started. **Last Reviewed**: 2026-10-18
> **Rule that orders this work**: backend first (CLAUDE.md §2). E1 (backend) is merged and verified before E2 (frontend).
> **Why**: erasure exists (`DELETE /auth/me`, voice and generation delete) but a user cannot take their data with them. For a product that stores voice recordings, a self-service export is the missing half of data-subject access/portability.

## 1. Options weighed

| Option | For | Against | Verdict |
|---|---|---|---|
| JSON only (metadata) | Tiny, trivial | Omits the recordings and clips, which is the data the user cares about most | Rejected |
| **ZIP: JSON + the user's own audio, built on request** | Complete, one file, no new infrastructure, no migration | Large for heavy users; CPU/disk while building | **Chosen** |
| Async job, emailed/expiring download link | Scales, no long request | Needs a job table, a storage lifecycle, email deliverability (Resend domain is still unverified) | Rejected for now; revisit if exports get slow |
| `GET` vs `POST` | `GET` is simpler for a plain link | Re-authentication needs a body; a link would put the password in a URL | **`POST`** (mirrors `DELETE /auth/me`) |

## 2. Decisions of record

| # | Decision | Why |
|---|---|---|
| 1 | `POST /api/v1/auth/me/export`, body `{password?}`, answers `200 application/zip` with `Content-Disposition: attachment`. | Same re-auth model as account erasure: a stolen access token alone must not yield someone's voice recordings. |
| 2 | Accounts with a password must repeat it (403 otherwise, counted by the login throttle under the same identity as erasure); Google-only accounts rely on the signed-in session. | Reuses `ensure_not_throttled` / `record_failure`. |
| 3 | `get_current_user`, not the verified-user dependency. | An unverified user may always take or erase their own data. |
| 4 | Contents: `account.json`, `voice_profiles.json`, `generations.json`, `README.txt`, `voice_samples/<profile_id>/<position>.<ext>`, `generations/<generation_id>.wav`. | Everything the service holds that is the user's. |
| 5 | **Excluded**: password hash, refresh tokens, speaker embeddings (`.npy`, derived and model-specific), soft-deleted rows (already scrubbed by erasure). The README says so. | Credentials are never exported; embeddings are meaningless outside the model. |
| 6 | Files are read only if `_within_storage` accepts the path; a missing file (retention-pruned output) is listed with `audio_file: null`, never an error. | Same safety rule as `remove_files`; no path traversal through a bad DB row. |
| 7 | The archive is built in a temp file on disk (WAV stored, JSON deflated) and streamed with `FileResponse`; a background task removes it. A bounded semaphore (2) answers `429` + `Retry-After` when busy. | Memory stays flat for large audio; CPU/disk burst is capped. |
| 8 | Rate limit `AUTH_LOGIN_RATE_LIMIT`. No new setting, so no `.env.example` change. | Same cost class as erasure. |
| 9 | Logs record user id and counts, never text or file names. | Same rule as the rest of the API. |

## 3. Milestones

### E1 — Backend export endpoint ✅

**Verified (2026-10-18):** full suite 1876 passed, 1 skipped, 11 warnings (17 new tests in `test_account_export.py`); live curl against a real server: no token 401, wrong password 403, missing body 403, correct password 200 `application/zip` with `Cache-Control: no-store` and a valid archive, temp file removed. The live run had no voice data (the real-weights upload path was not exercised); clips and audio are covered by the tests.

**Work**
1. `services/account_export.py`: `build_export(db, user) -> str` (path of the temp zip).
2. `ExportAccountRequest` schema; route `POST /auth/me/export` in `api/auth.py` (before the Google routes is irrelevant; path is unique).
3. Refresh `frontend/contract/openapi.json` (`python -m backend.export_openapi`); add the row to the CLAUDE.md §7 table.

**Tests (CLAUDE.md §4.1)**
- *Unit*: JSON never contains `hashed_password`/token/embedding paths; deleted rows excluded; missing file gives `audio_file: null`; a path outside storage is never read; legacy profile with no clips falls back to `audio_sample_path`.
- *Integration* (in-memory SQLite, temp dirs, no residue): 200 + zip with the expected members and bytes; another user's data absent; wrong password 403 and counted; no password for a password account 403; Google-only account exports with no body; throttled identity 429; no token 401; unverified user allowed; busy semaphore 429; temp file removed after the response.
- *Boundary*: user with no data (valid zip, empty lists); 10-clip profile; password at max length.
- *Gateway*: `curl -sS -X POST -H "Authorization: Bearer $T" -H 'content-type: application/json' -d '{"password":"…"}' localhost:8000/api/v1/auth/me/export -o export.zip && unzip -l export.zip` → 200, `application/zip`; wrong password → 403.

### E2 — Frontend: "Download my data" on Account (after E1 merges)

Button in the Account data section beside erase, password field when `has_password`, blob download via the existing authed fetch, busy and error states (403, 429), vitest + e2e + visual baselines per the FE-UX gotchas.

## 4. Milestone tracker

| Milestone | Status | Commit |
|---|---|---|
| E1 backend export | ✅ Done | `a5b166b` |
| E2 frontend button | ⬜ Not started | — |
