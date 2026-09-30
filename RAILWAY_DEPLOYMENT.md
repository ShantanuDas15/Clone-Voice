# Deploying the backend to Railway

Runbook for HARDENING_PLAN.md milestone R1. The repo side is done: `railway.toml`
(build, migrations, health check, draining), `backend/serve.py` (the image's
entrypoint) and the settings below. What follows is the one-time setup you do in
the Railway dashboard. Staging measurements (R3) are separate and listed at the end.

## What runs where

| Piece | Railway resource |
|---|---|
| API (this repo, `backend/Dockerfile`) | one service, built from the repo root |
| PostgreSQL | the Postgres plugin |
| Uploads, outputs, model weights | one **volume** on the API service, mounted at `/data` |
| Rate-limit state (optional) | the Redis plugin; without it limits reset on each deploy |

Constraints that come from Railway, not from this repo (per Railway's volume docs):

- A volume rules out replicas: **one instance only**. That matches `--workers 1`,
  which the code requires anyway (the inference semaphore and rate limiter are
  process-local).
- Redeploying a service with a volume has a **short downtime**, even with a health
  check. Acceptable for an MVP; the deployment only goes live once `/health/ready`
  passes, so a bad build never replaces a working one.
- Volume size is 5 GB on Hobby and 50 GB on Pro. The weights take about 0.4 GB;
  uploads and outputs are pruned by the retention settings (`STORAGE_MAX_AGE_HOURS`,
  `OUTPUT_RETENTION_DAYS`).

## One-time setup

1. Create a project and add the **Postgres** plugin (and optionally **Redis**).
2. Add a service from this GitHub repo. `railway.toml` at the repo root already sets
   the Dockerfile, the pre-deploy migration, the health check and draining; do not
   override them in the dashboard (the file wins).
3. On the service, add a **volume** mounted at `/data`.
4. Set the variables below. Generate each secret yourself, for example
   `openssl rand -hex 32`, and paste it straight into the dashboard.
5. Deploy. The first boot downloads the checkpoints into the volume (about 424 MB),
   which can take a few minutes; the health check allows 10.

## Variables

Set these on the API service. `PORT` is injected by Railway; do not set it.

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Reference variable; uses the private network. |
| `JWT_SECRET_KEY` | 32+ random characters | Required; the app refuses to start without it. |
| `SESSION_SECRET_KEY` | 32+ random characters, different from the JWT key | Signs the OAuth session cookie. |
| `DATA_DIR` | `/data` | Puts `uploads/`, `outputs/` and `weights/` on the volume. |
| `FETCH_WEIGHTS_ON_START` | `true` | Downloads missing or corrupt checkpoints (checksum-verified) on boot. |
| `RAILWAY_RUN_UID` | `0` | See "Why root" below. The app still runs as uid 1000. |
| `TRUSTED_PROXY_COUNT` | `1` | Railway's edge proxy sets `X-Forwarded-For`. Confirm in staging (R3). |
| `ALLOWED_ORIGINS` | `["https://app.example.com"]` | JSON list of the web app's origin(s). |
| `FRONTEND_URL` | `https://app.example.com` | Base of the emailed verification and reset links. |
| `GOOGLE_CLIENT_ID` | from Google Cloud | |
| `GOOGLE_CLIENT_SECRET` | from Google Cloud | |
| `GOOGLE_REDIRECT_URI` | `https://<api-domain>/api/v1/auth/google/callback` | Must be set explicitly (the proxy hides the public scheme) and registered in Google Cloud. |
| `EMAIL_BACKEND` | `resend` | HTTPS API; use it if outbound SMTP is blocked on your plan. |
| `EMAIL_FROM` | `CloneVoice <no-reply@your-domain>` | The domain must be verified with the provider (SPF and DKIM). |
| `RESEND_API_KEY` | from Resend | |
| `METRICS_AUTH_TOKEN` | 32+ random characters | `/metrics` is public on Railway; require a bearer token. |
| `RATE_LIMIT_STORAGE_URI` | `${{Redis.REDIS_URL}}` | Optional; only with the Redis plugin. |

Leave `APP_ENV` at its default (`production`) and `DEVICE` at `cpu`; Railway has no GPU.

## Why root

A freshly mounted volume is owned by root, while the image runs as an unprivileged
user (uid 1000), so the app could not write to it. Railway's documented fix is
`RAILWAY_RUN_UID=0`. The entrypoint (`backend/serve.py`) makes that safe: started as
root, it chowns `/data` to uid 1000 and immediately drops to that user before it
downloads weights or starts uvicorn, so the API process is never root. If the
variable is missing, the container stops with an error that names it.

## Contract with the web app

- **Google sign-in:** the browser goes to `GET /api/v1/auth/google`; the callback
  then redirects to `FRONTEND_URL/auth/callback` with the refresh cookie set, or to
  `FRONTEND_URL/login?error=<code>` (`google_failed`, `google_no_email`,
  `google_email_unverified`). The page at `/auth/callback` calls
  `POST /api/v1/auth/refresh` (with credentials) to obtain its access token; no token
  is ever placed in a URL.
- **Same site:** the refresh cookie is `SameSite=Lax`, so it is only sent when the web
  app and the API share a registrable domain (for example `app.example.com` and
  `api.example.com`) or when the web app proxies API calls. Use custom domains; a
  `*.up.railway.app` API with a differently hosted web app will not receive the cookie.

## Checks after the first deploy

- The deployment turns green (the health check is `/health/ready`).
- `curl https://<api-domain>/health/ready` returns 200.
- Sign up, open the emailed link, upload a sample and synthesize (this needs
  `EMAIL_BACKEND` working and a verified domain).
- `curl https://<api-domain>/metrics` returns 401 without the token.

## Not covered here (R3, staging measurements)

`TORCH_NUM_THREADS`, `INFERENCE_CALL_TIMEOUT_SECONDS` and the maximum text length
depend on the CPU the service actually gets. On a small host, maximum-length text
can exceed the 30 s per-stage timeout (HARDENING_PLAN.md P2-L3). Measure on
the staging service, then set them; if you raise a timeout, raise `drainingSeconds`
in `railway.toml` with it (it must exceed uvicorn's 30 s wait plus the inference
drain).
