#!/usr/bin/env bash
# ============================================================
# TRANCHI AI — GO LIVE
# One command to migrate the database, install deps, verify,
# and launch the pipeline. Run from anywhere with network access
# to Supabase:  bash go_live.sh [mode]
#   mode defaults to "all" (full daily run). Other modes:
#   scrape | underwrite | buyers | outreach | report | webhook
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YEL}!${NC} $1"; }
die()  { echo -e "${RED}✗ $1${NC}"; exit 1; }

MODE="${1:-all}"

# ── 1. Load .env ────────────────────────────────────────────
[ -f .env ] || die ".env not found. Copy .env.example and fill it in."
set -a; source .env; set +a
ok ".env loaded"

# ── 2. Verify required secrets ──────────────────────────────
[ -n "${GROQ_API_KEY:-}" ]      || die "GROQ_API_KEY missing"
[ -n "${SUPABASE_URL:-}" ]      || die "SUPABASE_URL missing"
[ -n "${SUPABASE_KEY:-}" ]      || die "SUPABASE_KEY missing"
case "${SUPABASE_KEY}" in *service_role*|eyJ*) : ;; *) warn "SUPABASE_KEY may not be the service_role key" ;; esac
[ -n "${EMAIL_ADDRESS:-}" ] && [[ "${EMAIL_ADDRESS}" != your@* ]] || warn "EMAIL_ADDRESS not set — outreach will be skipped"
ok "secrets present"

# ── 3. Install dependencies ─────────────────────────────────
echo "Installing Python deps…"
pip install -q --user -r requirements.txt
python -m playwright install chromium >/dev/null 2>&1 || warn "playwright browser install skipped"
ok "dependencies installed"

# ── 4. Run database migration ───────────────────────────────
# Needs the DB password. Set SUPABASE_DB_PASSWORD in .env, or set
# a full SUPABASE_DB_URL. Migration is idempotent — safe to re-run.
DB_URL="${SUPABASE_DB_URL:-}"
if [ -z "$DB_URL" ] && [ -n "${SUPABASE_DB_PASSWORD:-}" ]; then
    REF="$(echo "$SUPABASE_URL" | sed -E 's#https://([^.]+)\..*#\1#')"
    DB_URL="postgresql://postgres.${REF}:${SUPABASE_DB_PASSWORD}@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
fi
if [ -n "$DB_URL" ]; then
    echo "Running migration…"
    psql "$DB_URL" -v ON_ERROR_STOP=1 -f database/migrate_all.sql >/dev/null
    ok "database migrated (5 core tables + seller_leads + fb_group_posts + RLS)"
else
    warn "No SUPABASE_DB_PASSWORD/SUPABASE_DB_URL set — skipping auto-migration."
    warn "Run database/migrate_all.sql once in the Supabase SQL editor, OR add"
    warn "SUPABASE_DB_PASSWORD=... to .env and re-run this script."
fi

# ── 5. Verify DB connectivity via service_role REST ─────────
echo "Verifying database…"
python - <<'PY' || die "DB verification failed — check tables exist and keys are correct"
from config import SUPABASE_URL, SUPABASE_KEY
from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)
for t in ("auction_properties","cash_buyers","seller_leads","fb_group_posts"):
    sb.table(t).select("id").limit(1).execute()
print("  all 4 key tables reachable")
PY
ok "database verified"

# ── 6. Launch ───────────────────────────────────────────────
echo -e "${GREEN}=== TRANCHI AI is LIVE — running mode: ${MODE} ===${NC}"
exec python main.py "$MODE"
