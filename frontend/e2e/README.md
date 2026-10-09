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

- **WebKit needs HTTPS.** The API sets the refresh cookie with `Secure` (`backend/api/auth.py`);
  Chromium and Firefox accept it on `http://localhost`, WebKit stores nothing, so over plain HTTP
  every signed-in spec fails at sign-in (27 of 45, 2026-10-09). Run it behind local TLS instead:

  ```bash
  openssl req -x509 -newkey rsa:2048 -nodes -keyout /tmp/k.pem -out /tmp/c.pem -days 2 \
    -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost"
  node e2e/tools/https-proxy.mjs /tmp/k.pem /tmp/c.pem &     # 3443 -> web, 8443 -> API
  # API: as in the recipe above but ALLOWED_ORIGINS='["https://localhost:3443"]' and
  #      FRONTEND_URL=https://localhost:3443
  NEXT_PUBLIC_API_BASE_URL=https://localhost:8443/api/v1 npm run build
  NEXT_PUBLIC_API_BASE_URL=https://localhost:8443/api/v1 npx next start -p 3000 &
  E2E_BACKEND_LOG=/tmp/backend.log npx playwright test -c playwright.https.config.ts
  ```

  Result with this recipe: all applicable specs pass; the Chromium-only layout-shift specs and the
  real-microphone recording spec skip (Playwright's WebKit has no `getUserMedia`, and real Safari
  records a format the server does not accept, so the form offers upload instead, UR16).

- Two projects run the same specs: `chromium` and `firefox` (Firefox's fake microphone comes from
  `firefoxUserPrefs`; Playwright's `microphone` permission is Chromium-only). WebKit has its own HTTPS recipe (above).

- `emailedToken()` reads the backend log and decodes the quoted-printable console email.
- Recording uses Chromium's fake microphone. The WEBM it produces passes the server's container
  check, but decoding needs `ffmpeg` on the API host (the Docker image has it; a bare dev
  machine may answer 422 "Could not process this audio file").
- The rate-limit overrides above only exist so a fast suite is not throttled; the real limits are
  covered by the backend tests and the MSW integration tests.
