# 🎙️ CloneVoice — AI-Powered Voice Cloning Web Application

> A full-stack web application that enables users to clone a person's voice from short audio samples and synthesize new speech that mimics the original speaker's tone, pitch, and speaking style — powered by deep generative models.

---

## 📌 Project Overview

**CloneVoice** is a solo full-stack project that combines modern speech synthesis AI with a clean, production-ready web interface. Users can upload a short audio sample of a target speaker, train or fine-tune a voice model on that sample, and then generate new speech in that voice by simply typing text.

The initial scope is intentionally minimal: get the core voice cloning pipeline working end-to-end, with proper user authentication, a clean UI, and a reliable backend. Advanced features (voice library, batch synthesis, real-time streaming, etc.) are planned for future iterations only after the core use case is stable.

---

## 🎯 Core Use Case (v1.0 — Initial Development)

1. **User signs up / logs in** via email+password or Google OAuth.
2. **User uploads 1–3 short audio clips** (10–30 seconds each) of the target speaker.
3. The system **extracts acoustic features** (mel-spectrograms) from the clips.
4. A **pre-trained TTS model** (SV2TTS / Tacotron 2 based) is conditioned on the speaker's voice embedding.
5. User **types any text** into the UI and clicks "Generate".
6. The backend synthesizes audio in the cloned voice and **streams/returns the audio** to the user.
7. User can **play back, download**, or regenerate with different text.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     CLIENT (Browser)                    │
│              Next.js + Tailwind CSS + NextAuth          │
└────────────────────────┬────────────────────────────────┘
                         │ HTTPS / REST API
┌────────────────────────▼────────────────────────────────┐
│                    BACKEND (Python)                     │
│               FastAPI + PyTorch + Librosa               │
│                                                         │
│   ┌─────────────┐    ┌──────────────┐   ┌───────────┐  │
│   │  Auth Module│    │  TTS Pipeline│   │ File Store│  │
│   │  (JWT/OAuth)│    │ (SV2TTS/Taco)│   │ (Local/S3)│  │
│   └─────────────┘    └──────────────┘   └───────────┘  │
└─────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                     DATABASE                            │
│               PostgreSQL (via SQLAlchemy)               │
│           Users · VoiceProfiles · Generations           │
└─────────────────────────────────────────────────────────┘
```

---

## 🛠️ Finalized Tech Stack

### 🖥️ Frontend
| Tool | Purpose |
|---|---|
| **Next.js 14** (App Router) | Full React framework with SSR/SSG, routing, API proxy |
| **Tailwind CSS** | Utility-first styling — fast, consistent UI |
| **shadcn/ui** | Pre-built accessible components (buttons, modals, forms) |
| **NextAuth.js v5** | Authentication — handles Google OAuth + credentials sessions |
| **React Query (TanStack)** | Server state, async data fetching and caching |
| **Axios** | HTTP client for backend API calls |

> **Why Next.js over plain React?** Next.js includes server-side rendering, file-based routing, built-in API routes, and first-class NextAuth integration — significantly less boilerplate for a solo developer.

---

### ⚙️ Backend
| Tool | Purpose |
|---|---|
| **Python 3.11+** | Primary backend language |
| **FastAPI** | High-performance async REST API framework |
| **PyTorch 2.x** | Deep learning inference engine for TTS model |
| **SV2TTS (Real-Time Voice Cloning)** | Pre-trained speaker encoder + Tacotron 2 + WaveRNN pipeline — minimal training required |
| **Librosa** | Audio loading, mel-spectrogram extraction, feature processing |
| **NumPy / SciPy** | Waveform data manipulation and audio signal processing |
| **SQLAlchemy 2.0** | ORM for database interaction |
| **Alembic** | Database schema migrations |
| **Pydantic v2** | Data validation and request/response schemas |
| **python-jose / passlib** | JWT token generation and password hashing |
| **Authlib** | Google OAuth 2.0 integration on the backend |
| **python-multipart** | File upload handling |
| **Uvicorn** | ASGI server for running FastAPI |

> **Why SV2TTS over vanilla Tacotron 2?** SV2TTS (Real-Time Voice Cloning) uses a pre-trained speaker encoder — it generates a voice embedding from uploaded clips **without requiring per-speaker fine-tuning**. This makes it practical for a v1.0 solo project: no GPU training required per user, just inference.

---

### 🗄️ Database
| Tool | Purpose |
|---|---|
| **PostgreSQL 15** | Primary relational database |
| **SQLite** (dev only) | Lightweight alternative during local development |

---

### 📁 File Storage
| Tool | Purpose |
|---|---|
| **Local filesystem** (v1.0) | Store uploaded audio and generated outputs during development |
| **AWS S3 / Cloudflare R2** (v1.1+) | Production-grade object storage (upgrade path) |

---

### 🐳 DevOps & Infrastructure
| Tool | Purpose |
|---|---|
| **Docker + Docker Compose** | Containerize frontend, backend, and database for consistent local dev |
| **GitHub** | Version control and code hosting |
| **.env files** | Environment-based configuration management |

---

## 📂 Project Structure

```
clone-voice/
├── frontend/                        # Next.js App
│   ├── app/
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx
│   │   │   └── signup/page.tsx
│   │   ├── dashboard/page.tsx       # Main app — upload + generate
│   │   ├── profile/page.tsx         # Profile + voice history
│   │   └── layout.tsx
│   ├── components/
│   │   ├── AudioUploader.tsx
│   │   ├── TextToSpeechForm.tsx
│   │   ├── AudioPlayer.tsx
│   │   └── ProfileCard.tsx
│   ├── lib/
│   │   └── api.ts                   # Axios API client
│   └── next.config.ts
│
├── backend/                         # FastAPI App
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py              # Login, signup, OAuth endpoints
│   │   │   ├── voice.py             # Upload audio, create voice profile
│   │   │   └── synthesize.py        # Text → speech endpoint
│   │   ├── core/
│   │   │   ├── config.py            # Settings / env vars
│   │   │   ├── security.py          # JWT, password hashing
│   │   │   └── database.py          # SQLAlchemy setup
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   └── voice_profile.py
│   │   ├── schemas/
│   │   │   ├── auth.py
│   │   │   └── voice.py
│   │   ├── services/
│   │   │   ├── tts_pipeline.py      # SV2TTS inference logic
│   │   │   └── audio_processing.py  # Librosa feature extraction
│   │   └── main.py
│   ├── models/                      # Pre-trained model weights (gitignored)
│   │   ├── encoder/
│   │   ├── synthesizer/
│   │   └── vocoder/
│   └── requirements.txt
│
├── docker-compose.yml
└── README.md
```

---

## 🔐 Authentication & Authorization

### Flows Supported (v1.0)
| Flow | Method |
|---|---|
| **Email + Password Signup** | Hash with bcrypt, store in PostgreSQL |
| **Email + Password Login** | Verify hash → issue JWT access token |
| **Google OAuth Login/Signup** | NextAuth.js on frontend + Authlib on backend |
| **Protected Routes** | JWT middleware on all `/api/voice` and `/api/synthesize` endpoints |
| **Profile Screen** | View account info, linked OAuth provider, voice profile history |

### Token Strategy
- **Access Token**: Short-lived JWT (15 min), stored in memory
- **Refresh Token**: Long-lived (7 days), stored in `httpOnly` cookie
- All sensitive endpoints require `Authorization: Bearer <token>`

---

## 🧠 AI / ML Pipeline (v1.0 — Inference Only)

The voice cloning pipeline uses the **SV2TTS architecture** with pre-trained weights:

```
Audio Upload (WAV/MP3)
        │
        ▼
   Librosa Preprocessing
   (resample → 16kHz, trim silence, normalize)
        │
        ▼
   Speaker Encoder (GE2E-trained LSTM)
   → 256-dim speaker embedding vector
        │
        ▼
   Tacotron 2 Synthesizer
   (text + speaker embedding → mel-spectrogram)
        │
        ▼
   WaveRNN / HiFi-GAN Vocoder
   (mel-spectrogram → raw waveform)
        │
        ▼
   Output: WAV file → returned to user
```

> **No GPU required for v1.0 inference** on short clips (~3–5 sec generation time on CPU). GPU support can be toggled via `DEVICE=cuda` env var for production.

---

## 📋 Database Schema (v1.0)

```sql
-- Users
users (id, email, name, avatar_url, provider, hashed_password, created_at)

-- Voice Profiles
voice_profiles (id, user_id→users, name, embedding_path, audio_sample_path, created_at)

-- Generated Outputs
generations (id, user_id→users, voice_profile_id→voice_profiles, input_text, output_audio_path, created_at)
```

---

## 🌐 API Endpoints (v1.0)

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/signup` | Register with email + password |
| `POST` | `/api/auth/login` | Login → returns JWT |
| `POST` | `/api/auth/refresh` | Refresh access token |
| `GET` | `/api/auth/me` | Get current user profile |
| `GET` | `/api/auth/google` | Initiate Google OAuth flow |
| `GET` | `/api/auth/google/callback` | Handle OAuth callback |

### Voice
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/voice/upload` | Upload audio sample(s), create voice profile |
| `GET` | `/api/voice/profiles` | List user's voice profiles |
| `DELETE` | `/api/voice/profiles/{id}` | Delete a voice profile |

### Synthesis
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/synthesize` | Generate speech from text + voice profile ID |
| `GET` | `/api/synthesize/history` | List user's generated audio history |

---

## 📱 UI Screens (v1.0)

| Screen | Route | Description |
|---|---|---|
| **Landing** | `/` | Product intro, CTA to sign up |
| **Login** | `/login` | Email/password + Google OAuth button |
| **Signup** | `/signup` | Register form + Google OAuth |
| **Dashboard** | `/dashboard` | Upload audio, select voice profile, enter text, generate |
| **Profile** | `/profile` | User info, linked accounts, voice profile list, generation history |

---

## 🗺️ Development Roadmap

### ✅ Phase 1 — Core MVP (Initial Development)
- [ ] Project scaffolding (Next.js + FastAPI + Docker Compose)
- [ ] Authentication (email/password + Google OAuth)
- [ ] Profile screen
- [ ] Audio upload + preprocessing pipeline
- [ ] SV2TTS inference integration
- [ ] Text → speech generation endpoint
- [ ] Audio playback + download in UI
- [ ] Basic error handling and loading states

### 🔜 Phase 2 — Stability & Polish
- [ ] Input validation and robust error messages
- [ ] Audio format support (MP3, M4A, OGG → auto-convert to WAV)
- [ ] Rate limiting per user
- [ ] Progress indicator during synthesis
- [ ] Mobile-responsive UI

### 🔮 Phase 3 — Advanced Features (Post-MVP)
- [ ] GPU-accelerated synthesis
- [ ] Multiple voice profiles per user
- [ ] Fine-tuning on larger user audio sets
- [ ] Real-time audio streaming (WebSockets)
- [ ] Cloud storage (S3 / Cloudflare R2)
- [ ] Shareable voice generation links
- [ ] Admin dashboard

---

## ⚙️ Local Development Setup (Summary)

```bash
# Clone and setup
git clone <repo-url> && cd clone-voice

# Start all services
docker-compose up --build

# Services running at:
# Frontend  → http://localhost:3000
# Backend   → http://localhost:8000
# API Docs  → http://localhost:8000/docs (Swagger UI)
# DB        → localhost:5432
```

---

## 🔑 Key Design Decisions for Solo Development

| Decision | Rationale |
|---|---|
| Use **SV2TTS pre-trained weights** | Eliminates the need to train models from scratch — inference only in v1.0 |
| **Next.js** over plain React | Built-in routing, SSR, NextAuth, API proxying — less boilerplate |
| **FastAPI** over Flask/Django | Async support, auto-generated docs, Pydantic validation — modern and fast |
| **PostgreSQL** as single DB | One database for all data — users, profiles, generations |
| **Docker Compose** from day 1 | Consistent dev environment, easy onboarding and deployment |
| **JWT + httpOnly cookies** | Secure, stateless auth without the complexity of session stores |
| **Local file storage in v1.0** | Avoid AWS setup complexity during initial development |

---

*Document version: 1.0 — September 2026*
*Scope: Solo Full-Stack Developer, Initial Development Phase*
