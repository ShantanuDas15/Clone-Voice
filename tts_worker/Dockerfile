# syntax=docker/dockerfile:1

# CloneVoice inference worker (SPEECH_QUALITY_PLAN.md S4.3). Build from the REPO ROOT:
#   docker build -f tts_worker/Dockerfile -t clonevoice-tts-worker .
#
# NOT BUILT OR RUN IN CI YET: Docker was unavailable where this was written. The same lock file was
# installed into a fresh virtualenv and the worker ran from it (see tts_worker/README.md); the image
# itself is unverified. Needs an NVIDIA GPU host with nvidia-container-toolkit for TTS_WORKER_DEVICE=cuda.
FROM python:3.11-slim

# git: two requirements are installed from commits (chatterbox-tts and resemble-perth).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tts_worker/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt

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
