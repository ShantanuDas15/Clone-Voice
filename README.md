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

### 4. Start Services
The project uses Docker Compose to easily spin up the database and services.
```bash
docker-compose up --build
```

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API Documentation:** http://localhost:8000/docs
- **Database:** localhost:5432

### 5. Model Weights

The backend refuses to start without real, checksum-verified SV2TTS checkpoints — it does not
fall back to mock, placeholder, or unverified weights (see `HARDENING_PLAN.md`, finding C2).

- **Speaker encoder:** downloads automatically on first use via the `resemblyzer` package. Run
  `python -m backend.download_weights` to pre-warm this cache and confirm it succeeds.
- **Synthesizer & vocoder:** real Tacotron2/WaveRNN checkpoints, loaded via the architecture
  vendored at `backend/services/sv2tts/` (MIT licensed; see
  `backend/services/sv2tts/THIRD_PARTY_NOTICE.md` for provenance and the exact upstream commit
  pinned). Download `synthesizer.pt` and `vocoder.pt` (**not** `encoder.pt` — that's unused, the
  encoder above already covers it) from
  [huggingface.co/CorentinJ/SV2TTS](https://huggingface.co/CorentinJ/SV2TTS) (~424 MB combined)
  and place them at:
  ```
  <WEIGHTS_DIR>/synthesizer.pt
  <WEIGHTS_DIR>/vocoder.pt
  ```
  `WEIGHTS_DIR` defaults to `backend/weights/` and can be overridden via `.env`
  (`core/config.py`). Each file's SHA256 is checked against the pinned manifest at
  `backend/weights_manifest.json` before it is ever loaded — a corrupted download or a tampered
  file is rejected with a clear error, not silently loaded. `python -m backend.download_weights`
  exits non-zero and reports exactly which checkpoint is missing or fails verification, without
  making any network calls for these two files (a scripted, resumable `--fetch` download is
  tracked as a follow-up — HARDENING_PLAN.md Milestone C2.2).

## 🗺️ Roadmap

- **Phase 1:** Core Backend Architecture & AI Inference Pipeline (In Progress)
- **Phase 2:** Next.js Frontend Integration & Dashboard UI
- **Phase 3:** Advanced Features (GPU Acceleration, Cloud Storage, WebSockets)

## 📄 License

This project is licensed under the MIT License.

