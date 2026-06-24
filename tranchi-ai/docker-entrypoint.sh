#!/usr/bin/env bash
# Container entrypoint: run the idempotent migration (if DB creds present),
# then start the always-on web + scheduler process.
set -euo pipefail

# Build the migration URL from SUPABASE_DB_PASSWORD, or use SUPABASE_DB_URL directly.
DB_URL="${SUPABASE_DB_URL:-}"
if [ -z "$DB_URL" ] && [ -n "${SUPABASE_DB_PASSWORD:-}" ] && [ -n "${SUPABASE_URL:-}" ]; then
    REF="$(echo "$SUPABASE_URL" | sed -E 's#https://([^.]+)\..*#\1#')"
    DB_URL="postgresql://postgres.${REF}:${SUPABASE_DB_PASSWORD}@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
fi

if [ -n "$DB_URL" ]; then
    echo "[entrypoint] running idempotent migration…"
    psql "$DB_URL" -v ON_ERROR_STOP=1 -f database/migrate_all.sql >/dev/null \
        && echo "[entrypoint] migration OK" \
        || echo "[entrypoint] migration skipped/failed — continuing (tables may already exist)"
else
    echo "[entrypoint] no SUPABASE_DB_PASSWORD/URL — assuming schema already migrated"
fi

exec python serve.py
