FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

WORKDIR /app
COPY backend/use_cases/face_mask/requirements.txt ./
RUN python -m venv /app/.venv && pip install --no-cache-dir -r requirements.txt

COPY backend/use_cases/face_mask/app ./app
COPY backend/use_cases/face_mask/config ./config

RUN mkdir -p /app/storage && chown -R app:app /app /home/app

USER 10001:10001
EXPOSE 8014
HEALTHCHECK --interval=30s --timeout=8s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8014/api/health', timeout=6).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8014", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
