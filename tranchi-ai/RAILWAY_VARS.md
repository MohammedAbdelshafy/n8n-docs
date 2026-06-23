# Railway Environment Variables

Paste these into: Railway Dashboard → your project → Variables tab

## Required (nothing works without these)

| Variable | Where to get it |
|----------|----------------|
| `SUPABASE_URL` | supabase.com → Project Settings → API → Project URL |
| `SUPABASE_KEY` | supabase.com → Project Settings → API → service_role key |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `TWILIO_ACCOUNT_SID` | console.twilio.com → Account Info (top of dashboard) |
| `TWILIO_AUTH_TOKEN` | console.twilio.com → Account Info (top of dashboard) |
| `TWILIO_FROM_NUMBER` | Your Twilio number in E.164 format e.g. `+15551234567` |

## Optional (enhances the system)

| Variable | Where to get it |
|----------|----------------|
| `APIFY_API_TOKEN` | apify.com → Settings → Integrations |
| `BATCHDATA_API_KEY` | batchdata.com → API Keys |
| `YOUR_EMAIL` | Your email address for Google Meet invites |
| `YOUR_TIMEZONE` | e.g. `America/Chicago` or `America/New_York` |

## Root Directory Setting

In Railway → your service → Settings → Source:
Set **Root Directory** to `tranchi-ai`

This tells Railway your app lives in the `tranchi-ai/` folder, not the repo root.

## After Variables Are Set

Railway will redeploy automatically. Once the deploy is green, copy your
public URL (e.g. `https://tranchi-ai.up.railway.app`) and run:

```bash
cd tranchi-ai
python scripts/setup_twilio.py https://your-app.up.railway.app
```

That's it — Twilio is wired and the server is live.
