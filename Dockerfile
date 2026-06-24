# Railway builds from the repo root. The actual app lives in tranchi-ai/.
# We install only web-server deps (no Playwright/Chromium) so the build
# finishes in ~60s. Scrapers run as a daily subprocess and install their
# own deps at runtime if needed.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Use the slim web-only requirements (no Playwright / crawl4ai)
COPY tranchi-ai/requirements-web.txt requirements.txt
RUN pip install -r requirements.txt

# App code
COPY tranchi-ai/ .

RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

CMD ["bash", "docker-entrypoint.sh"]
