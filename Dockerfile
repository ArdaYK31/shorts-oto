# ChronoShorts cloud renderer — Linux CPU (Kokoro + Whisper + FFmpeg)
# Build:  docker build -t chronoshorts .
# Run:    docker run --rm -v "$(pwd)/credentials:/app/credentials:ro" chronoshorts
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface \
    TORCH_HOME=/root/.cache/torch \
    ESPEAK_DATA_PATH=/usr/lib/x86_64-linux-gnu/espeak-ng-data

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        espeak-ng \
        espeak-ng-data \
        libsndfile1 \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && (test -f "$ESPEAK_DATA_PATH/phontab" \
        || ln -sfn /usr/share/espeak-ng-data "$ESPEAK_DATA_PATH" \
        || true) \
    && echo "ESPEAK_DATA_PATH=$ESPEAK_DATA_PATH" \
    && ls -la "$ESPEAK_DATA_PATH/phontab" || ls -la /usr/share/espeak-ng-data/phontab

WORKDIR /app

# CPU torch first (Kokoro / Whisper), then project deps
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements-cloud.txt

COPY config.yaml ./
COPY src ./src
COPY topics ./topics
COPY scenarios ./scenarios
COPY prompts ./prompts
COPY bgm ./bgm
COPY scripts/.gitkeep scripts/
COPY audio/.gitkeep audio/
COPY media ./media
COPY captions/.gitkeep captions/
COPY out/.gitkeep out/
COPY seo/.gitkeep seo/
COPY logs/.gitkeep logs/

# Empty credentials dir — mount secrets at runtime
RUN mkdir -p credentials \
    && mkdir -p media/raw media/processed \
    && chmod -R a+rwX topics scripts audio media captions out seo logs

# Default: one scheduled Short (upload if credentials present + schedule.auto_upload)
CMD ["python", "src/scheduled_run.py"]
