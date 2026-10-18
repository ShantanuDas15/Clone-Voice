# CloneVoice — Free-text History Search Plan

> **Status**: 🟡 H1 landed (`487bbf0`); H2 not started. **Last Reviewed**: 2026-10-18
> **Rule that orders this work**: backend first (CLAUDE.md §2). H1 (backend) merges before H2 (frontend).
> **Why**: History is paged 50 at a time and can only be filtered by voice. A user looking for "the birthday message" has to scroll and expand rows.

## 1. Options weighed

| Option | For | Against | Verdict |
|---|---|---|---|
| Client-side filter of loaded rows | No backend work | Only searches the pages already loaded; misleading "no results" | Rejected |
| Postgres full-text search (`tsvector` + GIN, migration) | Ranked, stemmed | Migration, English-only stemming, hard to mirror on the SQLite tests, overkill per user | Rejected for now |
| **Case-insensitive substring (`ILIKE`) on `input_text`, scoped to the user** | No migration, same behaviour on SQLite and Postgres, predictable ("what I typed is what matches") | Sequential scan within one user's rows (small); no ranking | **Chosen** |
| Also match voice name | One box for everything | The voice `Select` already covers it; mixed matches confuse | Rejected |

## 2. Decisions of record

| # | Decision | Why |
|---|---|---|
| 1 | `GET /synthesize/history?q=` — optional, whitespace-trimmed, `max_length=200` (422 beyond); blank means no filter. | Bounded input; a stray space must not hide everything. |
| 2 | Match is a case-insensitive **substring** of `Generation.input_text`. `%`, `_` and `\` in `q` are escaped and matched literally. | A user searching "50%" must not match everything; no wildcard injection. |
| 3 | Same scoping as today: own user, not deleted, non-deleted voice. Erased rows (text `[erased]`) are already excluded by `deleted_at`. | No new exposure; never searches scrubbed text. |
| 4 | `X-Total-Count`, `limit`/`offset` and `voice_profile_id` all compose with `q`. | The frontend's paging and "Showing n of N" keep working. |
| 5 | The search text is never logged: the app does not log it, and a filter on `uvicorn.access` (`core/log_redaction.py`) replaces the `q` value in the access line, which would otherwise carry the full query string. A reverse proxy or the host's edge logs (Railway) can still see URLs; that is outside this repo, so a search is a `GET` parameter, not a secret. | Typed speech is personal data (same rule as D1). Found while writing the test: the plan's first wording ("never logged") was false for uvicorn's access log. |
| 6 | No migration, no new setting, rate limit stays `API_RATE_LIMIT` (the frontend debounces). | Smallest change that works. |

## 3. Milestones

### H1 — Backend `q` parameter ✅

**Verified (2026-10-18):** full suite 1902 passed, 1 skipped, 11 warnings (26 new: 14 in `test_history_search.py`, 12 in `test_log_redaction.py`); live curl on a real server with seeded rows: `q=birthday` 2 rows/total 2, `q=50%25` only the literal `50%` row, `q=zebra` empty/0, blank = all 3, 201 chars 422, no token 401; the real uvicorn access log shows `?q=[redacted]` and the typed text appears nowhere in it. SQLite `LIKE` is case-insensitive for ASCII only (Postgres `ILIKE` handles all of Unicode); the Unicode test therefore matches same-case text. No real-Postgres run of the new query.

**Tests (CLAUDE.md §4.1)**: substring and case-insensitive match; no match gives `[]` and total 0; `%`/`_`/`\` literal; whitespace-only and empty `q` ignored; leading/trailing spaces trimmed; composes with `voice_profile_id`, `limit`/`offset` and total; never returns another user's, soft-deleted, erased or deleted-voice rows; 201-char `q` is 422; unicode text matches; no token 401. **Gateway**: `curl -H "Authorization: Bearer $T" "localhost:8000/api/v1/synthesize/history?q=birthday"` → 200 with only matching rows and a matching `X-Total-Count`.

### H2 — Frontend search box (after H1 merges)

Search field on History (debounced, keeps the previous list while fetching), "No generations match …" with Clear, polite live count, composes with the voice filter; vitest, real-backend e2e, a11y, visual baselines.

## 4. Milestone tracker

| Milestone | Status | Commit |
|---|---|---|
| H1 backend `q` | ✅ Done | `487bbf0` |
| H2 frontend search | ⬜ Not started | — |
