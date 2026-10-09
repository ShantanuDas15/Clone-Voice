# Frontend runbook

For whoever deploys, rolls back or debugs the web app. The API side is in
[`../RAILWAY_DEPLOYMENT.md`](../RAILWAY_DEPLOYMENT.md). Nothing here has been exercised on a real
host yet (FRONTEND_IMPLEMENTATION_PLAN.md, Phase 8); the smoke script has been run against a
local stack only.

## 1. Configuration

| Variable                   | When                | Notes                                                                                                  |
| -------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------ |
| `NEXT_PUBLIC_API_BASE_URL` | **build**           | `https://api.example.com/api/v1`, no trailing slash. The app fails to start without it.                |
| `NEXT_PUBLIC_APP_ORIGIN`   | build, optional     | The web origin.                                                                                        |
| `NEXT_PUBLIC_SENTRY_DSN`   | **build**, optional | Unset = no error reporting and the SDK is never downloaded. Also whitelists the DSN origin in the CSP. |
| `CSP_ENFORCE`              | runtime (server)    | Unset = `Content-Security-Policy-Report-Only`; `1` = enforcing.                                        |

`NEXT_PUBLIC_*` values are baked into the JavaScript at build time: changing one means a **rebuild**
and redeploy, not a restart. `CSP_ENFORCE` is read per request, so a restart is enough.

The web app and the API must be **same-site** (for example `app.example.com` and
`api.example.com`): the refresh cookie is `HttpOnly; Secure; SameSite=Lax`, so a browser will not
send it to an unrelated domain. API side: `ALLOWED_ORIGINS` (a JSON list holding the exact web
origin, no trailing slash), `FRONTEND_URL` (base of emailed links), `GOOGLE_REDIRECT_URI`.

## 2. Release procedure

1. Build with the production variables: `npm ci && npm run build`. CI (`.github/workflows/frontend.yml`)
   runs format, lint, typecheck, unit tests, build and the Lighthouse budget.
2. Deploy, then run the smoke script from any machine with Node 22.18+:

   ```bash
   cd frontend
   npm run smoke -- --web https://app.example.com --api https://api.example.com
   npm run smoke -- --web https://app.example.com --api https://api.example.com --with-account
   ```

   The first form is read-only. `--with-account` also signs up a throwaway user, checks the refresh
   cookie flags, refreshes, and deletes the account again (if the delete fails it names the address
   to remove by hand). Exit code 1 means a check failed; warnings do not fail the run. Expect these
   warnings until they are done on purpose: CSP still report-only, `/metrics` public.

3. Do the checks a script cannot (below), then flip `CSP_ENFORCE=1` once browsing every flow shows
   no CSP violations in the console.

### Manual release checks

- Sign up, open the **real** verification email, verify. Forgot password, open the reset email, set a
  new password; another signed-in browser must be signed out.
- Sign in with a real Google account (and an account whose email already exists with a password).
- Upload a real voice sample, synthesize, play, download, see it in history.
- Delete a voice profile, then delete the account.
- Measure real synthesis latency on the production CPU and confirm the host's request timeout is
  longer (open question Q3/Q4); a long text is the worst case.
- Safari and a screen-reader pass (not automated).

## 3. Rollback

The frontend is stateless and owns no database, so rolling back is redeploying the previous build.

- A bad **frontend** release: redeploy the previous build artifact. If the cause was a changed
  `NEXT_PUBLIC_*` value, revert the value _and_ rebuild.
- A bad **CSP**: set `CSP_ENFORCE` back to unset and restart; the policy becomes report-only
  immediately and nothing is blocked.
- Error reporting causing trouble: unset `NEXT_PUBLIC_SENTRY_DSN` and rebuild.
- Backend rollbacks and migrations are separate (see the backend docs); the frontend tolerates an
  older API as long as `frontend/contract/openapi.json` still matches what it calls. The backend test
  suite fails when that snapshot is stale.

## 4. Diagnosing problems

### Old links to `/dashboard` or `/profile`

The redesign renamed the signed-in routes to `/generate`, `/voices`, `/history` and `/account`.
The old `/dashboard` and `/profile` paths answer with a 308 to `/generate` and `/voices`, and a
`?next=` that still names them is mapped the same way after sign-in, so emailed links and
bookmarks keep working. If one of them returns 404, the redirects in `next.config.mjs` were lost.
The smoke script does not exercise them; check with `curl -sI $WEB/dashboard` (expect `308` and
`location: /generate`).

### "I keep getting signed out" / session lost on reload

The session lives in an `HttpOnly` refresh cookie. In the browser's network tab look at
`POST /auth/refresh`:

- **No `Cookie` header sent**: the browser dropped it. Check the web and API hosts share a
  registrable domain (the smoke script's same-site check), the page is on https (the cookie is
  `Secure`; Chromium also accepts it on `http://localhost`), and the browser is not blocking
  third-party cookies for an API on another site.
- **Cookie sent, 401**: expired or revoked token, or it was rotated by another tab and a stale one
  was replayed. A reset-password or account deletion revokes every session on purpose.
- **429**: the refresh route is rate limited per IP; check `Retry-After` and that the proxy count
  (`TRUSTED_PROXY_COUNT`) lets the API see real client addresses.

### Requests fail with "can't reach the server" (status 0) though the API is up

Almost always CORS. In the browser console look for a CORS error and inspect the `OPTIONS`
preflight. The response must carry `Access-Control-Allow-Origin` equal to the exact web origin and
`Access-Control-Allow-Credentials: true`. Fix `ALLOWED_ORIGINS` on the API (JSON list, scheme and
host exactly as the browser shows them, no trailing slash) and restart it. The smoke script reports
the same thing. A 413 for an oversized upload can also surface as a network error because the
server closes the connection.

### Pages are blank or styled wrongly after turning on `CSP_ENFORCE`

Open the console: every blocked resource is reported with the violated directive. `script-src` is
nonce-based, so a script injected by something outside the app (a browser extension is fine, a new
third-party tag is not) will be blocked. A new external host needs adding to `lib/csp.ts`. Set
`CSP_ENFORCE` back to unset to recover at once.

### Emailed links open the wrong place

They are built from the API's `FRONTEND_URL`. The token travels in the URL fragment
(`/verify-email#token=...`), which never reaches a server log; the page strips it immediately. If
the link host is wrong, fix `FRONTEND_URL` on the API.

### Google sign-in lands on `/login?error=...`

`google_failed`, `google_no_email`, `google_email_unverified` and `google_account_conflict` each have
their own message in the app. If the redirect itself fails, check `GOOGLE_REDIRECT_URI` is set to
`https://<api-domain>/api/v1/auth/google/callback` and registered in Google Cloud.

### The "experiencing problems" banner shows and uploading/generating is disabled

The web app polls `GET /health/ready` on the API origin. A 503 there (database down, or the
speech models not loaded) disables those two actions on purpose. Fix the API; the banner clears on
the next poll.

### Synthesis never finishes

It is one synchronous request. If a proxy or host idle timeout is shorter than synthesis on that
CPU the browser sees a dropped connection and reports it as an interrupted request without retrying
(a retry would run the model twice). Raise the timeout or shorten the maximum text.
