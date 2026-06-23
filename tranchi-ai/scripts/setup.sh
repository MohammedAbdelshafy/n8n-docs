#!/usr/bin/env bash
# Tranchi AI — First-run setup validator
# Run from tranchi-ai/ directory:  bash scripts/setup.sh
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; ERRORS=$((ERRORS+1)); }

ERRORS=0

echo ""
echo "======================================"
echo "  TRANCHI AI — Environment Check"
echo "  Total cost to run: \$0/month"
echo "======================================"

# .env exists
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env not found — created from .env.example. Fill it in before running."
  echo ""
fi
source .env 2>/dev/null || true

echo ""
echo "[ Database (Supabase — free tier) ]"
[ -n "$SUPABASE_URL" ] && ok "SUPABASE_URL"  || fail "SUPABASE_URL missing — supabase.com → project → Settings → API"
[ -n "$SUPABASE_KEY" ] && ok "SUPABASE_KEY"  || fail "SUPABASE_KEY (service_role) missing"

echo ""
echo "[ AI / LLM — pick ONE free provider ]"
LLM_OK=0
[ -n "$GROQ_API_KEY" ]      && ok "GROQ_API_KEY (recommended — fastest, free)" && LLM_OK=1
[ -n "$GEMINI_API_KEY" ]    && ok "GEMINI_API_KEY (free — 1M tokens/day)"      && LLM_OK=1
[ -n "$ANTHROPIC_API_KEY" ] && ok "ANTHROPIC_API_KEY (paid fallback)"
if [ "$LLM_OK" -eq 0 ]; then
  fail "No LLM key found — get one FREE:
       GROQ:   console.groq.com   (no credit card, sign up in 60s)
       GEMINI: aistudio.google.com/app/apikey (Google account only)"
fi

echo ""
echo "[ Email (Gmail SMTP — free) ]"
[ -n "$EMAIL_ADDRESS" ]      && ok "EMAIL_ADDRESS"      || fail "EMAIL_ADDRESS missing"
[ -n "$EMAIL_APP_PASSWORD" ] && ok "EMAIL_APP_PASSWORD" || fail "EMAIL_APP_PASSWORD missing — myaccount.google.com → Security → App passwords"

echo ""
echo "[ SMS — optional, add when ready ]"
if [ -n "$TWILIO_ACCOUNT_SID" ]; then
  ok "TWILIO_ACCOUNT_SID (SMS enabled)"
  [ -n "$TWILIO_AUTH_TOKEN" ]  && ok "TWILIO_AUTH_TOKEN"  || fail "TWILIO_AUTH_TOKEN missing"
  [ -n "$TWILIO_FROM_NUMBER" ] && ok "TWILIO_FROM_NUMBER" || fail "TWILIO_FROM_NUMBER missing"
else
  warn "Twilio not configured — system runs email-only (perfectly fine to start)"
fi

echo ""
echo "[ Google Meet — optional ]"
if [ -f google_credentials.json ]; then
  ok "google_credentials.json found (auto-booking enabled)"
else
  warn "google_credentials.json not found — buyers flagged for manual callback instead"
fi

echo ""
echo "[ Python Packages ]"
pip install -r requirements.txt -q && ok "All packages installed" || fail "pip install failed"

echo ""
echo "[ Playwright Browsers ]"
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop()" 2>/dev/null \
  && ok "Playwright chromium ready" \
  || { warn "Playwright browser not installed — running: playwright install chromium"; playwright install chromium; }

echo ""
echo "[ Supabase Schema ]"
if [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_KEY" ]; then
  python - <<'PYEOF'
from supabase import create_client
import os
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
tables = ["auction_properties", "cash_buyers", "seller_leads", "outreach_log"]
missing = []
for t in tables:
    try:
        sb.table(t).select("id").limit(1).execute()
    except Exception:
        missing.append(t)
if not missing:
    print("  \033[0;32m  ✓\033[0m All tables exist")
else:
    print(f"  \033[1;33m  !\033[0m Missing tables: {', '.join(missing)}")
    print("       Run these SQL files in Supabase SQL Editor (in order):")
    print("         1. database/supabase_schema.sql")
    print("         2. database/rls_policies.sql")
    print("         3. database/seller_leads.sql")
    print("         4. database/fb_group_tracker.sql")
PYEOF
fi

echo ""
echo "======================================"
if [ "$ERRORS" -eq 0 ]; then
  echo -e "${GREEN}  Ready. Start your first deal hunt:${NC}"
  echo "  python main.py deal-hunt TX OH"
else
  echo -e "${RED}  $ERRORS item(s) need attention (see above).${NC}"
fi
echo "======================================"
echo ""
