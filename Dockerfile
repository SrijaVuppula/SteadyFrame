# SteadyFrame worker / local API image. Multi-arch: linux/arm64 is the primary target
# (ECS Fargate on Graviton), linux/amd64 builds the same way.
#
#   docker buildx build --platform linux/arm64 -t steadyframe-worker .
#   docker build --target api -t steadyframe-api .
#
# No apt ffmpeg: the opencv-python-headless wheel bundles FFmpeg for decoding and the
# imageio-ffmpeg wheel ships a static ffmpeg binary for encoding, on both architectures.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/mpl \
    STEADYFRAME_MODE=local

WORKDIR /app

# the cv2 wheel bundles FFmpeg/OpenBLAS/etc. and links only libz + libstdc++ from the system
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 zlib1g ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# runtime deps only: the lock also pins the dev tools, which the image does not need
COPY requirements.lock /tmp/requirements.lock
RUN grep -v -i -E '^(pytest|hypothesis|ruff|iniconfig|pluggy|sortedcontainers|Pygments)==' /tmp/requirements.lock \
        > /tmp/requirements.runtime \
    && pip install --no-cache-dir -r /tmp/requirements.runtime \
    && rm -rf /tmp/requirements.*

COPY pyproject.toml README.md ./
COPY steadyframe ./steadyframe
COPY synth ./synth
COPY config ./config
COPY service ./service
RUN pip install --no-cache-dir --no-deps . \
    && python -c "import cv2, sys; print('OpenCV', cv2.__version__); sys.exit(0 if cv2.__version__.startswith('5.') else 1)" \
    && python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /tmp/jobs /tmp/mpl /data \
    && chown -R app:app /tmp/jobs /tmp/mpl /data
USER app

# ---------------------------------------------------------------- local API (docker compose)
FROM base AS api
ENV LOCAL_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "--factory", "service.local_api:create_app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- worker (default target)
FROM base AS worker
ENV WORKER_WORKDIR=/tmp/jobs
ENTRYPOINT ["python", "-m", "service.worker"]
