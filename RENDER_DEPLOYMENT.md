# Deploying to Render

The Blueprint is `render.yaml` at the repo root. It defines the API, the web app, a
Key Value (Redis-compatible) instance for rate limits, and Postgres. The Railway files
stay as they are; both targets build the same Dockerfiles. Platform statements below
come from docs.render.com (checked 2026-11-01); anything that needs a real deploy is
marked **Unverified**.

Not included: the optional Chatterbox worker. `TTS_WORKER_URL` only accepts https or a
`*.railway.internal` host (`backend/core/config.py`), which rules out Render's private
hostnames until the validator is extended. Run the default `sv2tts` engine on Render.

## Steps

1. Render dashboard → **New → Blueprint**, pick this repo. A paid account is needed:
   the API has a persistent disk and a 4 GB instance.
2. Fill the prompted variables (the ones marked `sync: false`). Generate no secrets
   by hand: `JWT_SECRET_KEY`, `SESSION_SECRET_KEY` and `METRICS_AUTH_TOKEN` are created
   by Render.
3. Attach two custom domains on **one parent domain**: `api.<your-domain>` to
   `clonevoice-api` and `app.<your-domain>` to `clonevoice-web`. The refresh cookie is
   `SameSite=Lax`, and `onrender.com` is a public suffix, so two `*.onrender.com`
   hostnames are different sites and the cookie would not be sent.
4. Set the web service's `NEXT_PUBLIC_API_BASE_URL=https://api.<your-domain>/api/v1`
   and `NEXT_PUBLIC_APP_ORIGIN=https://app.<your-domain>`, then redeploy it (they are
   build-time values).
5. Set on the API: `ALLOWED_ORIGINS=["https://app.<your-domain>"]`,
   `FRONTEND_URL=https://app.<your-domain>`,
   `GOOGLE_REDIRECT_URI=https://api.<your-domain>/api/v1/auth/google/callback`,
   `EMAIL_FROM` and `RESEND_API_KEY` (verified sending domain), and
   `TRUSTED_PROXY_COUNT` (see "Client IP").
6. The first boot downloads about 424 MB of weights onto the disk. Render cancels a
   deploy that is not healthy within 15 minutes.

## Known differences from Railway

| Topic | Render | What it means here |
|---|---|---|
| Disk ownership | The docs do not say who owns a mounted disk, and there is no `RAILWAY_RUN_UID`. The image runs as `appuser` (uid 1000). **Unverified** | If the disk is root-owned the container stops with "Storage directory ... is not writable". Fix: make the Dockerfile's `USER` an `ARG` defaulting to `appuser` and set it to `root` on Render, so `backend/serve.py` chowns the disk and drops to uid 1000. Not done yet because it changes the image's non-root guard tests. |
| Shutdown delay | Default 30 s, and it **cannot be changed** on a service with a disk | The API needs about 70 s (30 s uvicorn drain plus 30 s inference drain). A deploy can cut an in-flight synthesis short. |
| Deploys | A disk disables zero-downtime deploys: the old instance stops first | A few seconds of downtime per deploy. One instance only. |
| Health check | 5 s response limit; 15 s of failures stops traffic, 60 s restarts; `Host` is the `onrender.com` name until a custom domain is verified | `/health/ready` must answer in under 5 s. The API has no host allow-list, so the `Host` is accepted. |
| Migrations | `preDeployCommand` runs without the disk | `alembic upgrade head` needs only the database. |
| Build variables | Service variables are passed to the Docker build as build arguments | The web app's `NEXT_PUBLIC_*` values reach `frontend/Dockerfile`. |
| Port | `PORT` defaults to 10000 and the app must bind `0.0.0.0` | `backend/serve.py` reads `$PORT`. |

## Client IP

The rate limiter (`backend/core/rate_limit.py`) reads `X-Forwarded-For` only. Render's
docs do not say which proxy headers it adds. **Unverified.** On the first deploy, log
the request headers on a staging call, then set `TRUSTED_PROXY_COUNT` to the number of
proxies you see appending to `X-Forwarded-For`. If the header is absent, leave it `0`
and the limiter falls back to the socket peer, which is the proxy: everyone would share
one bucket until `get_client_ip` is taught the header Render does set.

## Still to verify on a real deploy

- Disk ownership and the `USER` change above.
- Cold start and weights download time; memory use against the 4 GB plan.
- The client-IP header, CSP report-only output (then `CSP_ENFORCE=1` on the web service),
  and email delivery from the verified domain.
