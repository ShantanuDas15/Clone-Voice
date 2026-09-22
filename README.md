# 🎙️ CloneVoice

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-green.svg)
![Next.js](https://img.shields.io/badge/Next.js-14-black.svg)

> **CloneVoice** is an AI-powered full-stack web application that allows users to clone a person's voice from a short audio sample and synthesize new speech mimicking the original speaker's tone, pitch, and style.

## ✨ Features

- **🗣️ Rapid Voice Cloning:** Extract a speaker embedding from just 10–30 seconds of audio.
- **📝 Text-to-Speech:** Synthesize natural-sounding speech in the cloned voice.
- **🔐 Secure Authentication:** Email/Password and Google OAuth integrations.
- **🗂️ Profile Management:** Manage multiple voice profiles and review your synthesis history.
- **⚡ AI Pipeline:** Powered by SV2TTS (Real-Time Voice Cloning) using a pre-trained Speaker Encoder, Tacotron 2 Synthesizer, and WaveRNN/HiFi-GAN Vocoder.

## 🛠️ Tech Stack

### Frontend
- **Framework:** Next.js 14 (App Router)
- **Styling:** Tailwind CSS + shadcn/ui
- **Auth:** NextAuth.js v5

### Backend
- **Framework:** FastAPI (Python 3.11+)
- **AI/ML:** PyTorch, Librosa, SV2TTS Core (Resemblyzer)
- **Database:** PostgreSQL (via SQLAlchemy & Alembic)

### Infrastructure
- **Containerization:** Docker & Docker Compose
- **Storage:** Local Filesystem (v1.0) / AWS S3 (v1.1+)

## 🚀 Getting Started (Local Development)

### 1. Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Node.js 18+

### 2. Clone the Repository
```bash
git clone https://github.com/yourusername/clonevoice.git
cd clonevoice
```

### 3. Environment Setup
Copy the example environment files and fill in the required keys (e.g., Google OAuth credentials, JWT secrets).
```bash
cp backend/.env.example backend/.env
```
Optionally, also copy the root `.env.example` to override the Postgres
credentials `docker-compose.yml` uses (`POSTGRES_USER`/`POSTGRES_PASSWORD`/
`POSTGRES_DB`/`POSTGRES_PORT`) — it works with no `.env` here at all, since
each has a dev-only default, but set at least `POSTGRES_PASSWORD` for
anything beyond local dev (`HARDENING_PLAN.md` finding L12).
```bash
cp .env.example .env
```

### 4. Start Services
The project uses Docker Compose to spin up the database and the backend API
(`docker-compose.yml` — `db` and `backend` services; see `backend/Dockerfile`
and `HARDENING_PLAN.md` finding H7).
```bash
docker-compose up --build
```

- **Frontend:** http://localhost:3000 (not yet implemented — CLAUDE.md §2 requires the
  backend to be fully hardened first)
- **Backend API:** http://localhost:8000
- **API Documentation:** http://localhost:8000/docs
- **Database:** localhost:5432 (bound to `127.0.0.1` only — not reachable from outside
  the host; see `HARDENING_PLAN.md` finding L12)

The `backend` container runs a single `uvicorn` worker on purpose — see "Resource
Requirements" below and the comment on `CMD` in `backend/Dockerfile`. It will report
`503`/`"degraded"` at `/health/ready` (alias: `/health`) until real model checkpoints are provisioned (next section);
`docker-compose up` alone does not fetch them.

### 5. Model Weights

The backend refuses to start without real, checksum-verified SV2TTS checkpoints — it does not
fall back to mock, placeholder, or unverified weights (see `HARDENING_PLAN.md`, finding C2).

- **Speaker encoder:** downloads automatically on first use via the `resemblyzer` package. Run
  `python -m backend.download_weights` to pre-warm this cache and confirm it succeeds.
- **Synthesizer & vocoder:** real Tacotron2/WaveRNN checkpoints, loaded via the architecture
  vendored at `backend/services/sv2tts/` (MIT licensed; see
  `backend/services/sv2tts/THIRD_PARTY_NOTICE.md` for provenance and the exact upstream commit
  pinned), sourced from
  [huggingface.co/CorentinJ/SV2TTS](https://huggingface.co/CorentinJ/SV2TTS) (~424 MB for
  `synthesizer.pt` + `vocoder.pt` combined — **not** `encoder.pt`, that's unused, the encoder
  above already covers it). Two ways to provision them:
  ```bash
  # Downloads whichever of synthesizer.pt/vocoder.pt are missing or fail
  # checksum verification into WEIGHTS_DIR, via huggingface_hub (resumable,
  # retried, and idempotent — a file already present and verified is never
  # re-downloaded). The only command in this repo that makes a network call
  # for these two files; never triggered automatically by the running app.
  python -m backend.download_weights --fetch

  # Or place them yourself at <WEIGHTS_DIR>/synthesizer.pt and
  # <WEIGHTS_DIR>/vocoder.pt, then verify without downloading:
  python -m backend.download_weights
  ```
  `WEIGHTS_DIR` defaults to `backend/weights/` and can be overridden via `.env`
  (`core/config.py`). Either way, each file's SHA256 is checked against the pinned manifest at
  `backend/weights_manifest.json` before it is ever loaded — a corrupted download or a tampered
  file is rejected with a clear error, not silently loaded, and re-running `--fetch` self-heals a
  corrupted local copy by re-downloading it. `load_models()` (called at server startup) performs
  this same verification independently and refuses to start without it either way.
- **Post-deploy smoke test:** presence/checksum checks prove a checkpoint *file* is intact, not
  that it actually produces working audio through the real model code. `--verify-inference` loads
  the real models and runs one short end-to-end synthesis, catching a shape/interface/checkpoint
  incompatibility once, deliberately, rather than on a real user's first request:
  ```bash
  python -m backend.download_weights --fetch --verify-inference
  ```
  `/health/ready` also reports a `checksum_verified` field per model (`true` for a real, verified
  checkpoint; `false` for the test suite's mock models; `null` where it doesn't apply, e.g. the
  encoder) — diagnostic only, so it never flips a healthy mock-backed test deployment to
  `"degraded"`.
- **Under Docker Compose:** the `backend` service stores `WEIGHTS_DIR` in the
  `backend_weights` named volume, not the image, so it survives `docker-compose down` /
  rebuilds. Run the same provisioning commands inside the running container instead of on
  the host:
  ```bash
  docker-compose exec backend python -m backend.download_weights --fetch --verify-inference
  ```

### 6. Resource Requirements

Sizing for the `backend` container (`backend/Dockerfile`), from the two real checkpoints
being ~424 MB combined on disk (§5) plus the fixed cost of one held inference at a time —
**not** per-concurrent-request, since the inference semaphore (`HARDENING_PLAN.md` finding
H6) allows only one synthesizer+vocoder forward pass in the whole process at once, however
many requests are queued behind it:

- **CPU-only (`DEVICE=cpu`, the default):** 2+ cores, 4 GB RAM minimum. Works, but WaveRNN's
  autoregressive sample-by-sample generation is slow on CPU — expect synthesis to take much
  longer than real-time (`C2.3`'s smoke test measured ~8.6s for a 1.4s clip on GPU; CPU is
  markedly slower still).
- **GPU (`DEVICE=cuda`):** an NVIDIA GPU with **4 GB+ VRAM** is a reasonable baseline —
  ~424 MB of fp32 parameters once loaded onto the device, plus a few hundred MB of fixed CUDA
  context overhead, plus mel/waveform activation buffers for one in-flight request (the
  semaphore keeps this from multiplying with request volume). This is an **estimate from
  checkpoint size, not a benchmarked figure** — this session had no provisioned checkpoints to
  load and measure against (`weights/` was empty), so treat it as a starting point and confirm
  the real figure with `nvidia-smi` while `--verify-inference` (§5) is running. Also requires
  `nvidia-container-toolkit` on the Docker host and a `deploy.resources.reservations.devices`
  GPU block added to the `backend` service in `docker-compose.yml` — not included by default,
  since a GPU is not guaranteed to be present on every host this compose file runs on.
- **Disk:** ~424 MB for the two checkpoints, plus resemblyzer's own pretrained encoder cache
  (~17 MB, downloaded automatically into the container user's home directory on first use —
  persist `~appuser` if you don't want to re-download it on every container recreation).

## 🗺️ Roadmap

- **Phase 1:** Core Backend Architecture & AI Inference Pipeline (In Progress)
- **Phase 2:** Next.js Frontend Integration & Dashboard UI
- **Phase 3:** Advanced Features (GPU Acceleration, Cloud Storage, WebSockets)

## 📄 License

This project is licensed under the MIT License.

