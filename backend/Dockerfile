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
#     on the host, requires the CUDA build of torch. The image ships the CPU
#     build by default; build a GPU image with
#     `--build-arg TORCH_INDEX_URL=https://pypi.org/simple`.
# Builder stage (HARDENING_PLAN.md finding P2-H3): resemblyzer depends on
# `webrtcvad`, which publishes no py3.11 binary wheel, so pip compiles it from
# source and needs a C compiler. The compiler lives only in this stage; the
# runtime stage below copies the finished virtualenv and ships no toolchain.
FROM python:3.11-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied on its own so this (multi-hundred-MB, torch-heavy) layer is cached
# across ordinary code changes. Only requirements.txt (runtime deps) is
# installed — dev/test tooling lives in requirements-dev.txt and never ships
# into this image (HARDENING_PLAN.md finding L7). requirements.lock.txt
# (HARDENING_PLAN.md finding P2-L9) pins every transitive dependency by
# hash; see its header for how it's kept in sync with requirements.txt.
COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt

# torch is installed first, from its own index (HARDENING_PLAN.md finding
# P2-H3). The default PyPI wheel is the CUDA build and pulls ~6 GB of nvidia-*
# libraries this CPU-default image never loads (7.9 GB vs 1.5 GB measured).
# The version is read from requirements.txt so the pin lives in one place, and
# the next step finds it already satisfied (`torch==X` also matches `X+cpu`)
# without mixing package indexes. It's deliberately absent from
# requirements.lock.txt (P2-L9's header explains why) so the hash-checked
# install below can never try to re-verify/reinstall it against a CUDA-wheel
# hash.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN grep -E '^torch==' /tmp/requirements.txt > /tmp/torch-requirement.txt \
    && pip install --no-cache-dir --index-url "${TORCH_INDEX_URL}" \
        -r /tmp/torch-requirement.txt
# --require-hashes (P2-L9): every package below torch must match one of the
# hashes pinned in requirements.lock.txt, not just resolve to a version that
# merely satisfies requirements.txt's ranges/transitive deps.
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock.txt

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

# Dependencies come pre-built from the builder stage (no compiler here).
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Fail the build, not the first request, if the copied virtualenv is unusable
# (HARDENING_PLAN.md finding P2-H3): imports the compiled webrtcvad, torch and
# the audio stack against this stage's system libraries.
RUN python -c "import torch, webrtcvad, resemblyzer, librosa, soundfile"

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

# The port is $PORT when the platform injects one (Railway), else 8000. The
# shell form lets the healthcheck expand it.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health/live" || exit 1

# The entrypoint (backend/serve.py) reads $PORT, chowns a root-owned volume and
# drops to this user when started as root, optionally downloads the model
# weights (FETCH_WEIGHTS_ON_START), then execs uvicorn so it stays PID 1 and
# receives SIGTERM directly. The uvicorn flags live there, in one testable
# place: `--workers 1` is load-bearing (the inference semaphore and the rate
# limiter are process-local, HARDENING_PLAN.md H6/M3/H7; scale with more
# containers behind a shared-state limiter, never a higher worker count) and
# `--timeout-graceful-shutdown` is sized with docker-compose's
# `stop_grace_period` and Railway's `drainingSeconds` (P2-L4).
CMD ["python", "-m", "backend.serve"]
