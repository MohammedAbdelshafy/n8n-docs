FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY tranchi-ai/requirements-web.txt requirements.txt
RUN pip install -r requirements.txt

COPY tranchi-ai/ .

EXPOSE 8000

# serve.py starts the daily scheduler thread then hands off to uvicorn on $PORT
CMD ["python", "serve.py"]
