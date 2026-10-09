# End-to-end tests (Playwright, real backend)

These run Chromium against the **real FastAPI backend with real model weights**, and a production
build of the web app. They are not part of `npm test` (which uses MSW and never touches a
service). Every test signs up its own throwaway user.

## Recipe (from the repo root)

```bash
# 1. Backend: SQLite is enough; console email so the tests can read verification/reset links.
export DATABASE_URL=sqlite:////tmp/e2e.db APP_ENV=development EMAIL_BACKEND=console \
  REQUIRE_EMAIL_VERIFICATION=true ALLOWED_ORIGINS='["http://localhost:3000"]' \
  FRONTEND_URL=http://localhost:3000 \
  JWT_SECRET_KEY=<32+ chars> SESSION_SECRET_KEY=<32+ chars> \
  AUTH_SIGNUP_RATE_LIMIT=1000/minute AUTH_LOGIN_RATE_LIMIT=1000/minute \
  AUTH_EMAIL_RATE_LIMIT=1000/hour AUTH_TOKEN_RATE_LIMIT=1000/minute \
  AUTH_REFRESH_RATE_LIMIT=1000/minute API_RATE_LIMIT=1000/minute
rm -f /tmp/e2e.db
backend/.venv/bin/python -c "from backend.core.database import Base, engine; import backend.models; Base.metadata.create_all(engine)"
backend/.venv/bin/alembic -c backend/alembic.ini stamp head
backend/.venv/bin/uvicorn backend.main:app --port 8000 > /tmp/backend.log 2>&1 &

# 2. Browser (once) and tests. Playwright builds and starts the web app itself.
cd frontend
npx playwright install chromium firefox
E2E_BACKEND_LOG=/tmp/backend.log npm run test:e2e   # both browsers
# one browser: npm run test:e2e -- --project=firefox
```

Set `CSP_ENFORCE=1` to run the whole suite under an **enforcing** Content-Security-Policy;
`csp.spec.ts` fails on any violation reported while browsing every flow.

## Notes

- **WebKit cannot run this suite over plain HTTP.** The API sets the refresh cookie with `Secure`
  (`backend/api/auth.py`), Chromium and Firefox accept it on `http://localhost`, WebKit does not
  store it (probed: Chromium keeps `refresh_token`, WebKit has no cookies), so every signed-in spec
  loses its session on the first full navigation. Tried on 2026-10-09 with a `webkit` project:
  9 passed, 27 failed, 9 skipped, all of the failures at sign-in. Running it needs the web app and API
  behind local HTTPS (for example a TLS-terminating proxy with a trusted certificate); the mocked
  smoke (`npm run test:cross-browser`) covers WebKit structurally in the meantime.

- Two projects run the same specs: `chromium` and `firefox` (Firefox's fake microphone comes from
  `firefoxUserPrefs`; Playwright's `microphone` permission is Chromium-only). Safari/WebKit is a
  manual check.

- `emailedToken()` reads the backend log and decodes the quoted-printable console email.
- Recording uses Chromium's fake microphone. The WEBM it produces passes the server's container
  check, but decoding needs `ffmpeg` on the API host (the Docker image has it; a bare dev
  machine may answer 422 "Could not process this audio file").
- The rate-limit overrides above only exist so a fast suite is not throttled; the real limits are
  covered by the backend tests and the MSW integration tests.
