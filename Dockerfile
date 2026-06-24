# ── Root-level Dockerfile ──────────────────────────────────────────────────────
# Railway watches the `main` branch and builds from the repo root. The actual
# app lives in tranchi-ai/, so this Dockerfile builds that subfolder.
# (The n8n documentation in this repo is unaffected — it has no build step.)
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
COPY tranchi-ai/requirements.txt .
RUN pip install -r requirements.txt

# Playwright Chromium + its system libraries
RUN python -m playwright install --with-deps chromium

# App code (only the tranchi-ai subfolder)
COPY tranchi-ai/ .

RUN chmod +x docker-entrypoint.sh

# Web service port (Railway overrides $PORT)
EXPOSE 8000

# Runs the idempotent migration (if DB creds present) then serve.py
CMD ["bash", "docker-entrypoint.sh"]
