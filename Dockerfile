FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# System deps + Chromium system libraries (needed for Playwright)
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client curl ca-certificates \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Web-server deps (fast layer — cached unless this file changes)
COPY tranchi-ai/requirements-web.txt requirements-web.txt
RUN pip install -r requirements-web.txt

# Scraper deps separately so web layer cache survives scraper updates
RUN pip install playwright trafilatura

# Download Chromium (cached layer — only re-runs if playwright version changes)
RUN python -m playwright install chromium

COPY tranchi-ai/ .

EXPOSE 8000

CMD ["python", "serve.py"]
