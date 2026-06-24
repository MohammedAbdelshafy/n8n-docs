#!/usr/bin/env bash
# Run on YOUR machine to set Railway env vars via the CLI.
# Fill in the values below from your .env before running.
set -euo pipefail

if ! command -v railway &>/dev/null; then
  echo "Installing Railway CLI..."
  curl -fsSL https://install.railway.app | sh
  export PATH="$HOME/.railway/bin:$PATH"
fi

echo "Railway CLI: $(railway --version)"
railway login
railway link

railway variables set \
  GROQ_API_KEY="YOUR_GROQ_API_KEY" \
  GLM_API_KEY="YOUR_GLM_API_KEY" \
  SUPABASE_URL="YOUR_SUPABASE_URL" \
  SUPABASE_KEY="YOUR_SUPABASE_SERVICE_ROLE_KEY" \
  EMAIL_ADDRESS="YOUR_GMAIL_ADDRESS" \
  EMAIL_APP_PASSWORD="YOUR_GMAIL_APP_PASSWORD" \
  REPLY_TO_EMAIL="YOUR_GMAIL_ADDRESS" \
  YOUR_TIMEZONE="America/Chicago" \
  RUN_HOUR_UTC="13"

echo "Done — Railway redeploying now."
