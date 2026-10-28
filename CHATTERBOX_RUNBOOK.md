# Chatterbox worker runbook (Railway)

> Milestone R0.4 of `CHATTERBOX_ROLLOUT_PLAN.md`. Written from the repo, **not yet run on Railway**:
> every step marked *(verify)* is something R1 must confirm on the real project.

The worker (`tts_worker/`) is a second Railway service that runs one Chatterbox model (Nano, on CPU)
for the API. The API stays the owner of users, consent and quotas; it calls the worker over Railway's
private network, and serves the request itself with SV2TTS whenever the worker cannot.

```
browser ──https──> API service (backend/, SV2TTS in-process, volume /data, Postgres)
                      │  http://tts-worker.railway.internal:8100   (private network, bearer token)
                      └──────────────> tts-worker service (tts_worker/, Chatterbox Nano, CPU, no volume)
```

## 1. Create the worker service

1. In the same Railway project and environment as the API, add a service from this GitHub repo and
   **name it `tts-worker`** (the name is its private hostname, `tts-worker.railway.internal`).
2. Settings, **Config file path**: `/tts_worker/railway.toml`. It sets the Dockerfile
   (`tts_worker/Dockerfile`, built from the repo root), the `/health` check, a 600 s start allowance and
   35 s draining; do not override them in the dashboard.
3. **No public domain.** Do not generate one: the worker is reachable only from the project's private network.
4. **No volume** for the first deploy (see "Weights and cold start"). One replica only: the worker runs one
   synthesis at a time by design.
5. Set the variables below, then deploy.

## 2. Worker variables

| Variable | Value | Notes |
|---|---|---|
| `TORCH_BACKEND` | `cpu` | A **build** argument (Railway passes service variables to `ARG`s): the CPU image is about 2 GB against 6.4 GB for the CUDA one. Changing it needs a rebuild. |
| `TTS_WORKER_TOKEN` | 32+ random characters | Required (`openssl rand -hex 24` makes 48). Checked before the request body is read. The API must hold the same value. |
| `TTS_WORKER_MODEL` | `nano` | The image default. Only Nano is acceptable on a CPU (RTF 0.76 at 8 threads; the original model is 6.5). |
| `TTS_WORKER_DEVICE` | `cpu` | Railway has no GPU. |
| `OMP_NUM_THREADS` | the vCPUs this service really gets | More threads than real cores were slower in the S4.2b measurements. Check the plan's per-service limit in Railway's docs; do not guess. |
| `PORT` | `8100` | The image listens on 8100; setting `PORT` tells Railway's health check and networking the same. |

Memory: Nano used 4.3 GiB on CPU at 8 threads. Make sure the plan's per-service memory limit leaves
headroom (R1 gate: at most 80% of the limit).

## 3. API variables

On the **API** service (see also `RAILWAY_DEPLOYMENT.md`):

| Variable | Value |
|---|---|
| `TTS_WORKER_URL` | `http://tts-worker.railway.internal:8100` |
| `TTS_WORKER_ALLOW_PRIVATE_HTTP` | `true` (accepts plain http for `<service>.railway.internal` hosts only; any other http host still fails startup) |
| `TTS_WORKER_TOKEN` | `${{tts-worker.TTS_WORKER_TOKEN}}` (a reference variable, so the two never drift) |
| `TTS_ENGINE` | `sv2tts` in production, **`chatterbox_nano` in staging** |
| `TTS_CANARY_ENGINE` / `TTS_CANARY_PERCENT` | `chatterbox_nano` / `0` in production; raise the percent only after the go/no-go (plan section 6) |
| `TTS_FALLBACK_ENGINE` | `sv2tts` (the default; `none` turns a worker outage into a 503) |

`TTS_WORKER_TIMEOUT_SECONDS` (25) must stay below `INFERENCE_CALL_TIMEOUT_SECONDS` (30); the API refuses to
start otherwise. The API refuses to start too when a worker engine is selected without a URL, a 32+ character
token, or an https/private URL.

## 4. Weights and cold start

The worker downloads Nano's weights from Hugging Face on its first start and keeps them in
`HF_HOME` (`/home/worker/.cache/huggingface`). Without a volume that happens **on every deploy and every
restart**, so a restart means a cold start of tens of seconds to minutes; the health check allows 600 s and the
API falls back to SV2TTS meanwhile. A volume would remove that, but a fresh Railway volume is root-owned and
this image runs as uid 10001, so it needs an entrypoint like `backend/serve.py` (chown, then drop
privileges) or `RAILWAY_RUN_UID=0` (running the worker as root, not recommended). Decide after R1 measures the
cold start.

## 5. Check it

1. The worker deployment turns green (health check `/health`).
2. From the API service's shell (private network only): `curl http://tts-worker.railway.internal:8100/health`
   returns `{"ready": true, "model": "nano", "device": "cpu", ...}`.
3. `curl https://<api-domain>/health/ready` names the engine and the worker, and stays 200 if the worker is down.
4. A synthesis in staging returns `X-Voice-Engine: chatterbox_nano`; with the worker stopped it returns audio
   with `X-Voice-Engine-Fallback` set.

*(verify)* **IPv6.** Railway's private network is IPv6, and older environments are IPv6-only. The image binds
`0.0.0.0`. If step 2 cannot connect from the API, set the worker's start command to
`uvicorn tts_worker.main:app --host :: --port 8100` and redeploy.

## 6. Roll back

| Situation | Action |
|---|---|
| Worker misbehaving, users unaffected | Nothing: requests already fall back to SV2TTS (`clonevoice_engine_fallback_total`), and after 3 outages in a row the API skips the worker for 30 s. |
| Stop sending traffic to it | On the API set `TTS_CANARY_PERCENT=0` (and `TTS_ENGINE=sv2tts` if it was changed), then redeploy. The worker may keep running. |
| Remove it entirely | The above, then delete the `tts-worker` service. Nothing on the API depends on it. |
| Bad worker deploy | Redeploy the previous deployment from Railway's deployment list; the API needs no change. |

## 7. What to watch

| Signal | Meaning |
|---|---|
| `clonevoice_engine_fallback_total{reason}` | By `reason`: `unavailable` (worker down, timing out or refusing the token), `busy` (queue full), `circuit_open` (the 3-outage breaker is skipping the worker), `reference` (a voice's clip is too short for Nano, which needs more than 5 s). |
| `clonevoice_engine_synthesis_total`, `clonevoice_engine_rtf` | Engine mix and speed. Nano on the real host must finish maximum-length text inside 25 s with at least 30% headroom (R1 gate). |
| `/health/ready` | Names the engine and the worker; never fails because of the worker. |
| Worker logs | Must contain no request text, audio or token; failures log a class name only. |

## 8. Before real users

Not done by this runbook: the consent text and `TERMS_VERSION` bump (R0.3, decision D4) and the owner's
decision on the model's undisclosed training data (D1). Recordings reach the worker as a new data flow, so
neither may be skipped before `TTS_CANARY_PERCENT` goes above 0 in production.
