# ── TRANCHI AI — always-on container (Railway / Render / Fly.io) ──
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# System deps: postgres client (for the idempotent migration on boot)
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps first (layer cache)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Playwright Chromium + its system libraries
RUN python -m playwright install --with-deps chromium

# App code
COPY . .

RUN chmod +x docker-entrypoint.sh

# Web service port (platforms override $PORT)
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
