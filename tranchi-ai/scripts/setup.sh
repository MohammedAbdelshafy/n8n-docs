#!/usr/bin/env bash
# Tranchi AI — First-run setup validator
# Run: bash scripts/setup.sh
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; ERRORS=$((ERRORS+1)); }

ERRORS=0

echo ""
echo "======================================"
echo "  TRANCHI AI — Environment Check"
echo "======================================"

# .env exists
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env not found — created from .env.example. Fill it in before running."
  echo ""
fi
source .env 2>/dev/null || true

echo ""
echo "[ API Keys ]"
[ -n "$SUPABASE_URL" ]       && ok "SUPABASE_URL"         || fail "SUPABASE_URL missing"
[ -n "$SUPABASE_KEY" ]       && ok "SUPABASE_KEY"         || fail "SUPABASE_KEY missing"
[ -n "$ANTHROPIC_API_KEY" ]  && ok "ANTHROPIC_API_KEY"    || fail "ANTHROPIC_API_KEY missing"
[ -n "$TWILIO_ACCOUNT_SID" ] && ok "TWILIO_ACCOUNT_SID"   || fail "TWILIO_ACCOUNT_SID missing"
[ -n "$TWILIO_AUTH_TOKEN" ]  && ok "TWILIO_AUTH_TOKEN"    || fail "TWILIO_AUTH_TOKEN missing"
[ -n "$TWILIO_FROM_NUMBER" ] && ok "TWILIO_FROM_NUMBER"   || fail "TWILIO_FROM_NUMBER missing"
[ -n "$APIFY_API_TOKEN" ]    && ok "APIFY_API_TOKEN"      || warn "APIFY_API_TOKEN missing (auction scraping disabled)"
[ -n "$BATCHDATA_API_KEY" ]  && ok "BATCHDATA_API_KEY"    || warn "BATCHDATA_API_KEY missing (comps disabled)"

echo ""
echo "[ Google Credentials ]"
if [ -f google_credentials.json ]; then
  ok "google_credentials.json found"
else
  warn "google_credentials.json not found — Google Meet auto-booking disabled"
  echo "     Get it: console.cloud.google.com → IAM → Service Accounts → Create → Download JSON"
fi

echo ""
echo "[ Python Packages ]"
pip install -r requirements.txt -q && ok "All packages installed" || fail "pip install failed"

echo ""
echo "[ Supabase Schema ]"
if [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_KEY" ]; then
  python - <<'PYEOF'
from supabase import create_client
import os
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
try:
    sb.table("auction_properties").select("id").limit(1).execute()
    print("  \033[0;32m  ✓\033[0m Supabase connected, schema exists")
except Exception:
    print("  \033[1;33m  !\033[0m Schema not yet applied — run database/supabase_schema.sql in Supabase SQL Editor")
    print("       https://supabase.com/dashboard → SQL Editor → paste database/supabase_schema.sql")
PYEOF
fi

echo ""
echo "======================================"
if [ "$ERRORS" -eq 0 ]; then
  echo -e "${GREEN}  All required keys set. Ready to run:${NC}"
  echo "  python main.py"
else
  echo -e "${RED}  $ERRORS required item(s) missing. Fix above then re-run.${NC}"
fi
echo "======================================"
echo ""
