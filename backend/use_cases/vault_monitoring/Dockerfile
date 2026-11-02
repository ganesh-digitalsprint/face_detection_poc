FROM ghcr.io/astral-sh/uv:0.11.2 AS uv
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/home/app \
    PATH=/app/.venv/bin:$PATH \
    FEDBANK_SHARED_PATH=/opt/fedbank/shared \
    INFERENCE_CONFIG_PATH=/opt/fedbank/config/inference.yaml \
    VAULT_FACE_LANDMARKER_MODEL=/app/models/face_landmarker.task

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libgomp1 libsm6 libxext6 libxrender1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY backend/use_cases/vault_monitoring/pyproject.toml backend/use_cases/vault_monitoring/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/use_cases/vault_monitoring/app ./app
COPY backend/use_cases/vault_monitoring/config ./config
COPY backend/shared /opt/fedbank/shared
COPY config/inference.yaml /opt/fedbank/config/inference.yaml

# This asset is required for active liveness and intentionally stays out of Git.
RUN mkdir -p /app/models /app/uploads /app/var /home/app/.deepface /home/app/.cache \
    && python -c "from urllib.request import urlretrieve; urlretrieve('https://storage.googleapis.com/mediapipe-assets/face_landmarker_v2.task', '/app/models/face_landmarker.task')" \
    && chown -R app:app /app /home/app

USER 10001:10001
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=8s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/v1/health', timeout=6).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
