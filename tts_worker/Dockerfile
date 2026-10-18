# syntax=docker/dockerfile:1

# CloneVoice inference worker (SPEECH_QUALITY_PLAN.md S4.3). Build from the REPO ROOT:
#   docker build -f tts_worker/Dockerfile -t clonevoice-tts-worker .                       # GPU host (CUDA torch)
#   docker build -f tts_worker/Dockerfile --build-arg TORCH_BACKEND=cpu -t clonevoice-tts-worker:cpu .
#
# Built and smoke-tested on real Docker by .github/workflows/worker-docker-build.yml (non-root, no
# baked token, pinned libraries, health, authentication and one real CPU synthesis). A GPU run is not
# covered: TTS_WORKER_DEVICE=cuda needs an NVIDIA host with nvidia-container-toolkit.
FROM python:3.11-slim

# git: two requirements are installed from commits (chatterbox-tts and resemble-perth).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tts_worker/requirements.lock.txt /tmp/requirements.lock.txt
# TORCH_BACKEND=cuda (the default) installs the lock as pinned: PyPI's torch with its CUDA runtime
# (an image of about 6.4 GB, for a GPU host). TORCH_BACKEND=cpu installs torch and torchaudio from
# PyTorch's CPU index and leaves out the CUDA runtime packages (nvidia-*) and triton, which a CPU
# host never loads: a far smaller image (CHATTERBOX_ROLLOUT_PLAN.md R0.6). Same pins either way
# (`torch==2.6.0` also matches `2.6.0+cpu`).
ARG TORCH_BACKEND=cuda
# The lock is already fully resolved, so pip must not resolve again: chatterbox-tts asks for
# resemble-perth from Git `master` while the lock pins it to a commit, and pip refuses two URLs for one
# package (ResolutionImpossible; uv accepts it). --no-deps installs exactly what is pinned, and
# `pip check` then proves every installed package's requirements are met.
RUN set -eu; \
    case "${TORCH_BACKEND}" in \
      cuda) cp /tmp/requirements.lock.txt /tmp/requirements.install.txt ;; \
      cpu) grep -E '^(torch|torchaudio)==' /tmp/requirements.lock.txt > /tmp/requirements.torch.txt; \
           pip install --no-cache-dir --no-deps --index-url https://download.pytorch.org/whl/cpu \
               -r /tmp/requirements.torch.txt; \
           grep -v -E '^(nvidia-[a-z0-9-]+|triton|torch|torchaudio)==' /tmp/requirements.lock.txt \
               > /tmp/requirements.install.txt ;; \
      *) echo "TORCH_BACKEND must be cuda or cpu, not ${TORCH_BACKEND}" >&2; exit 1 ;; \
    esac; \
    pip install --no-cache-dir --no-deps -r /tmp/requirements.install.txt; \
    pip check

COPY tts_worker /app/tts_worker

# Not root. Model weights are downloaded on first start into HF_HOME: mount a volume there.
RUN useradd --system --uid 10001 --create-home worker
USER worker
ENV HF_HOME=/home/worker/.cache/huggingface \
    TTS_WORKER_MODEL=nano

EXPOSE 8100
# TTS_WORKER_TOKEN is deliberately not set here: pass it at run time.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "tts_worker.main:app", "--host", "0.0.0.0", "--port", "8100"]
