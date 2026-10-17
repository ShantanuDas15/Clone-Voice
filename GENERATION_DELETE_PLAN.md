# CloneVoice — Delete a Single Generation (Privacy) Plan

> **Status**: 🟡 D1 (backend) landed 2026-10-17 (`f6eafbf`); D2 (frontend) and D3 (optional filter) not started
> **Last Reviewed**: 2026-10-17 (D1 landed)
> **Rule that orders this work**: backend first (CLAUDE.md §2). D1 (backend) must be merged and verified before D2 (frontend). D3 is optional and independent.
> **Why now**: today the only ways to remove a generated clip are deleting the whole voice (which erases every clip made with it) or waiting for retention to prune the file (default 30 days, `OUTPUT_RETENTION_DAYS`). For a voice-cloning product a user must be able to remove one output, and the text they typed, on request.

## 1. What exists today (verified in this session)

| Fact | Where |
|---|---|
| `generations` already has `deleted_at`; no route sets it for a single row | `backend/models/generation.py` (comment: "No route deletes a Generation today") |
| Voice deletion soft-deletes the profile **and** its generations, then removes the files **after** the commit | `backend/services/erasure.py::erase_voice_profile`, `remove_files` |
| Account erasure scrubs `input_text` to `"[erased]"`, clears `output_audio_path`, sets `deleted_at` | `erasure.py::erase_account` |
| `remove_files` deletes only paths inside `UPLOAD_DIR`/`OUTPUT_DIR` (realpath check), tolerates a missing file, never raises | `erasure.py::_within_storage`, `remove_files` |
| The audio route already excludes `deleted_at` rows and answers 404 for unknown, foreign, deleted or failed ids alike (no probing), 410 for a pruned file | `backend/api/synthesize.py::get_generation_audio` |
| **The history route does NOT filter `Generation.deleted_at`**; it relies on the join to a non-deleted profile. So a single deleted row would still be listed and counted | `backend/api/synthesize.py::get_history` (`visible` query) |
| Retention pruning protects only non-deleted rows younger than the window, so a deleted row's file is already unprotected | `backend/services/storage_cleanup.py::get_protected_paths` |
| `tts_metadata` is never written (default `{}`), so only `input_text` and the audio file hold user content | grep of `tts_metadata`: model only |

## 2. Decisions of record

| # | Decision | Why |
|---|---|---|
| 1 | **Soft delete, then scrub**: set `deleted_at`, set `input_text = "[erased]"` (the existing `ERASED_TEXT`), set `output_audio_path = NULL`, remove the file after the commit. The row stays. | CLAUDE.md §6 forbids hard-deleting user data; account erasure already treats the typed text as personal data, so a user-requested delete must too. |
| 2 | `DELETE /api/v1/synthesize/{generation_id}` → **204**, auth required (`get_current_user`, not the verified-user dependency: an unverified user may still remove their own data), `API_RATE_LIMIT`. | Matches the audio route's ownership model; deletion must never be blocked by email state. |
| 3 | **404** for unknown, foreign or already-deleted ids; invalid UUID is the framework's 422. Failed rows (no audio) are deletable. | No id probing (same rule as the audio route); the typed text of a failed attempt is also user data. |
| 4 | Order of effects: update the row, **commit**, then `remove_files([path])`. A failed commit deletes nothing. | The pattern S2.1d and `erase_voice_profile` already use. |
| 5 | **`get_history` gains `Generation.deleted_at.is_(None)`** in the shared `visible` query, so both the rows and `X-Total-Count` drop the deleted one. | Without it the feature does nothing visible. Highest-risk line of D1: it needs its own test. |
| 6 | No migration (the column exists). Check the history query plan on real Postgres only if the added predicate shows in `EXPLAIN` as a regression (the table is small per user). | Avoid an Alembic change for no schema change. |
| 7 | Logs record the generation id and user id, never the text. | Same rule as the rest of the API. |

## 3. Milestones

### D1 — Backend: `DELETE /synthesize/{id}` (not started)

**Work**
1. `erasure.erase_generation(db, generation) -> list[str]`: scrub and soft-delete one row, return the file paths to remove; the caller commits, then calls `remove_files`.
2. Route in `api/synthesize.py` (placed so `/history` and `/capabilities` still win over `/{generation_id}`; check route order).
3. History filter (decision 5).
4. Refresh `frontend/contract/openapi.json` (`python -m backend.export_openapi`; a backend test fails when stale); add the row to the CLAUDE.md §7 table.

**Tests (CLAUDE.md §4.1)**
- *Unit* (`erase_generation`): returns the output path and clears it on the row; sets `deleted_at`; scrubs `input_text`; a row with `output_audio_path = NULL` returns `[]`; calling it on an already-deleted row changes nothing.
- *Integration* (in-memory SQLite, mock auth, temp `OUTPUT_DIR`, no residue):
  - 204 and the file is gone from disk; the row is soft-deleted with text `[erased]` and `output_audio_path` NULL;
  - `GET /history` no longer lists it and `X-Total-Count` drops by one; other generations of the same voice are untouched;
  - `GET /{id}/audio` afterwards is 404;
  - second DELETE is 404; unknown id 404; another user's id 404 **and their file is still on disk**; malformed id 422; no token 401;
  - a failed generation (no audio) is deletable;
  - the file already missing on disk still gives 204;
  - **commit failure** (stub the session commit to raise): the file is still on disk and the row unchanged (the S2.1d technique);
  - the voice can be deleted afterwards without error, and deleting the voice does not resurrect or double-remove the row;
  - rate limit is the `API_RATE_LIMIT` one.
- *Boundary*: `output_audio_path` pointing outside the storage directories is never removed (reuses the `remove_files` guard; assert with a path in a second temp dir); an empty-string path.
- *Regression*: the existing history, audio, erasure and cleanup suites unchanged (baseline **1833 passed, 1 skipped, 11 warnings**; new tests add to it, no new warning).

**Verification gateway**
```bash
TOKEN=<access token of a verified user with one generation>
ID=<generation id from GET /api/v1/synthesize/history>
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/synthesize/$ID   # 204
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/synthesize/$ID   # 404
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/synthesize/$ID/audio       # 404
curl -si -H "Authorization: Bearer $TOKEN" "localhost:8000/api/v1/synthesize/history?limit=1" | grep -i x-total-count      # one less
ls backend/outputs/<user_id>/                                                                                               # the file is gone
```

**Rollback**: revert one commit; no schema or data change to undo (rows already scrubbed stay scrubbed, which is the intent).

### D2 — Frontend: Delete on a History row (after D1 merges)

- A **Delete** button per row (secondary), accessible name `Delete: <snippet>` (same `snippet` as Play/Download), opening the existing confirm `Dialog`: "Delete this audio? This permanently deletes the audio and the text you typed. It can't be undone."
- Optimistic removal with rollback, a 404 counts as already gone, history and its total refetched (the pattern of `useDeleteProfile`).
- Focus after a delete moves to the next row's Play (or the heading when the list is empty); a polite announcement "Deleted." and the "Showing n of N" line updates.
- Tests: the dialog flow (cancel does nothing), request path, optimistic remove and rollback on failure, 404 as success, focus target, count line, empty state after the last delete. e2e on the real backend: generate, open History, delete, row gone, `/audio` 404, file removed. Visual: refresh the 8 `history-*` baselines only if the row changes.
- Rollback: revert one commit; D1 stays valid.

### D3 — Backend then frontend: filter History by voice (optional, independent)

- `GET /synthesize/history?voice_profile_id=<uuid>` (optional). Another user's or unknown profile → an empty list, not 404 (no probing). `X-Total-Count` respects the filter. Bad uuid → 422. Tests: filter, count, foreign id returns empty and leaks nothing, combined with `limit`/`offset`, no param unchanged.
- Frontend: an "All voices" select above the list (only when the user has 2+ voices), the query key includes the filter, "Showing n of N" respects it, empty-result copy "No generations with this voice yet."
- Not planned: free-text search (needs an index on user text, which is also personal data; decide separately).

## 4. Risks and open questions
1. **Hidden history coupling** (decision 5): any other reader of `generations` that assumed "no route deletes a row" must be re-checked; grep showed only the audio route and `get_protected_paths` filter on `deleted_at`.
2. **Scrubbed text in an audit trail**: the row keeps its id, owner, voice, engine and timestamps but not the text. Confirm with the owner that this is the wanted audit trail (it matches account erasure).
3. **Retention number**: unchanged; the History "Expires in" hint (FE-UX44) keeps using the server's `output_retention_days`.
4. **Backups and logs are out of scope**: deleting a row does not purge database backups or request logs; say so in the terms copy if the owner wants a stronger promise.

## 5. Status log

| Milestone | Status | Commit | Date | What was verified | What is still open |
|---|:---:|:---:|:---:|---|---|
| D1 | 🟡 Partial | `f6eafbf` | 2026-10-17 | `DELETE /api/v1/synthesize/{id}` (204; 404 unknown / foreign / already deleted; 422 malformed; 401 without a token; open to unverified users): `erasure.erase_generation` soft-deletes, scrubs `input_text` to `[erased]`, clears the path; the file is removed **after** the commit; a failed commit answers 503 (transient, with `Retry-After`) or 500 and removes nothing. `get_history` now also filters `Generation.deleted_at`, so the rows and `X-Total-Count` drop a deleted one. 20 new tests (3 unit, 17 integration/boundary/failure: file gone and row scrubbed, history and total, audio 404, double delete, foreign id with the file kept, failed and file-already-missing rows, path outside storage never removed, empty path, sibling generations untouched, voice deleted afterwards, unverified user, both commit-failure paths). Backend suite **1853 passed, 1 skipped, 11 warnings** (was 1833; no new warning). OpenAPI snapshot refreshed (frontend contract tests 46 pass), CLAUDE.md §7 row added. **Live gateway** (real models, real SQLite, uvicorn, curl): DELETE 204 then 404, audio 404, `X-Total-Count` 1 to 0, the WAV removed from disk, the row `[erased]`, no path, `deleted_at` set; no token 401; bad id 422. | (1) The plan's rate-limit test was **dropped**: the only version I could write asserted a config value, not behaviour; the route carries the same `API_RATE_LIMIT` decorator as history and audio, unverified by a test. (2) Not run against real Postgres: no schema change, the one new predicate is a plain `IS NULL`. (3) `tts_metadata` is never written, so nothing else holds the text; backups and request logs are not purged (open question 4). (4) Two generations created in the same second tie on `created_at` (SQLite resolution), which made a test helper return the wrong id; fixed in the test, but any client that assumes "newest = first" has the same ambiguity (pre-existing). (5) Frontend not changed (D2) |
| D2 | 🔴 Not started (blocked on D1) | — | — | — | all of §3 D2 |
| D3 | 🔴 Not started (optional) | — | — | — | all of §3 D3 |
