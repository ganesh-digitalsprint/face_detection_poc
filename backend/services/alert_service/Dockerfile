FROM ghcr.io/astral-sh/uv:0.11.2 AS uv
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/home/app \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY backend/services/alert_service/pyproject.toml backend/services/alert_service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/services/alert_service/app ./app
RUN chown -R app:app /app /home/app

USER 10001:10001
EXPOSE 8012
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8012/health', timeout=4).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
