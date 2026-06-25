FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Runtime defaults — override in Railway Variables for production
ENV SUPABASE_URL=https://ozklxelerpfctetmtpqf.supabase.co \
    SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im96a2x4ZWxlcnBmY3RldG10cHFmIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MjIxMjg5OCwiZXhwIjoyMDk3Nzg4ODk4fQ.KLkPE0PyUyuWh2qRoaxlzaokkni4_lrLw7TljpKUYoM \
    GLM_API_KEY=9cb0afa0459843a7ab81b713da3f2e4d.zSHt6wyTKeQxJrbg \
    EMAIL_ADDRESS=Moeaiagenticteamz@gmail.com \
    REPLY_TO_EMAIL=Moeaiagenticteamz@gmail.com \
    YOUR_TIMEZONE=America/Chicago \
    RUN_HOUR_UTC=13

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
