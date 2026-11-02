FROM ghcr.io/astral-sh/uv:0.11.2 AS uv
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/home/app \
    PATH=/app/.venv/bin:$PATH \
    FEDBANK_SHARED_PATH=/opt/fedbank/shared \
    INFERENCE_CONFIG_PATH=/opt/fedbank/config/inference.yaml \
    HF_HOME=/home/app/.cache/huggingface \
    TORCH_HOME=/home/app/.cache/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libgomp1 libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY backend/use_cases/branch_exterior/pyproject.toml backend/use_cases/branch_exterior/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/use_cases/branch_exterior/app ./app
COPY backend/shared /opt/fedbank/shared
COPY config/inference.yaml /opt/fedbank/config/inference.yaml

RUN mkdir -p /app/config /app/storage /home/app/.cache /home/app/.roboflow \
    && chown -R app:app /app /home/app

USER 10001:10001
EXPOSE 8011
HEALTHCHECK --interval=30s --timeout=8s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8011/api/health', timeout=6).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
