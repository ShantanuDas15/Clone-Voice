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
npx playwright install chromium
E2E_BACKEND_LOG=/tmp/backend.log npm run test:e2e
```

Set `CSP_ENFORCE=1` to run the whole suite under an **enforcing** Content-Security-Policy;
`csp.spec.ts` fails on any violation reported while browsing every flow.

## Notes

- `emailedToken()` reads the backend log and decodes the quoted-printable console email.
- Recording uses Chromium's fake microphone. The WEBM it produces passes the server's container
  check, but decoding needs `ffmpeg` on the API host (the Docker image has it; a bare dev
  machine may answer 422 "Could not process this audio file").
- The rate-limit overrides above only exist so a fast suite is not throttled; the real limits are
  covered by the backend tests and the MSW integration tests.
