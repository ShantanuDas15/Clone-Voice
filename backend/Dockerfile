# syntax=docker/dockerfile:1

# CloneVoice backend image (HARDENING_PLAN.md finding H7).
#
# Build from the REPO ROOT so this can COPY backend/ as a package:
#   docker build -f backend/Dockerfile -t clonevoice-backend .
# (docker-compose.yml does this via `context: .` / `dockerfile: backend/Dockerfile`.)
#
# Resource requirements — see README.md "Resource Requirements" for the full
# writeup and how these numbers were derived:
#   - CPU-only (DEVICE=cpu): 2+ cores, 4 GB RAM minimum.
#   - GPU (DEVICE=cuda): NVIDIA GPU with 4 GB+ VRAM, nvidia-container-toolkit
#     on the host, requires the CUDA build of torch (not swapped in here).
FROM python:3.11-slim

# System dependencies:
# - libsndfile1: required by the `soundfile` package (services/tts_pipeline.py
#   `save_output()` calls `sf.write`) — without it, writing any output WAV
#   raises at import time.
# - ffmpeg: required by librosa/audioread to decode the MP3 and WEBM upload
#   formats `validate_audio_file()` accepts (services/audio_processing.py).
#   WAV decodes fine without it, but MP3/WEBM uploads would fail.
# - curl: used by the HEALTHCHECK below to probe `/health/live` (liveness only).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libsndfile1 \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user — standard container-hardening baseline, not one of
# HARDENING_PLAN.md's numbered findings but cheap to do while writing this
# Dockerfile from scratch.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Install Python dependencies before copying the rest of the source so this
# (multi-hundred-MB, torch-heavy) layer is cached across ordinary code
# changes. requirements.txt still ships dev/test tooling (pytest, black,
# isort) into the runtime image per HARDENING_PLAN.md finding L7 — tracked
# there as a separate not-yet-fixed item, not addressed by this Dockerfile.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Application code. Model checkpoints (backend/weights/), uploads/, and
# outputs/ are deliberately NOT baked into the image — see .dockerignore and
# the volumes declared in docker-compose.yml. Checkpoints must be provisioned
# separately (README.md "Model Weights") since they're too large and
# sensitive to ship in a built image.
COPY backend/ backend/

# WEIGHTS_DIR, UPLOAD_DIR and OUTPUT_DIR (core/config.py) are all anchored to
# BASE_DIR (backend/), so they resolve to /app/backend/{weights,uploads,outputs}
# regardless of the process CWD (HARDENING_PLAN.md finding M9). The volume
# mounts in docker-compose.yml match these paths.
RUN mkdir -p backend/weights backend/uploads backend/outputs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# --workers 1 is load-bearing, not a placeholder default (HARDENING_PLAN.md
# finding H7). Both the inference semaphore (services/tts_pipeline.py
# `_inference_semaphore`, HARDENING_PLAN.md H6) and the rate limiter
# (core/rate_limit.py, slowapi's default in-memory storage, HARDENING_PLAN.md
# M3) are process-local state. A second uvicorn worker process would get its
# own independent semaphore and its own independent rate-limit buckets,
# silently doubling the real inference concurrency and the effective rate
# limits this hardening pass relies on. Scale horizontally with multiple
# *containers* behind a shared-state limiter (once M3's `storage_uri` fix
# lands) instead of raising this value.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
