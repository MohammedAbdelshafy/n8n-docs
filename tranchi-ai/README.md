# Hola AI — Government Auction Deal Engine

Autonomous pipeline targeting $18K+/week from government-auctioned properties.
Finds deals, underwrites with Claude AI, locates cash buyers, runs outreach sequences,
and auto-books Google Meet when a buyer says YES.

**You close. The machine handles everything else.**

---

## Full Pipeline

```
07:00  python main.py scrape       →  scrape HUD, Fannie Mae, tax sales, auction.com
07:10  python main.py underwrite   →  Claude 3.5 Sonnet scores every property (MAO, ARV, grade)
07:30  python main.py buyers       →  find new cash buyers (Google Maps, Craigslist, Connected Investors)
08:00  python main.py outreach     →  SMS approved deals to opted-in buyers (max 3 per deal)
        [background process]
        python main.py webhook     →  listen for buyer replies
        Buyer replies YES          →  Google Meet auto-booked, link sent by SMS
        Buyer replies NO           →  marked cold, next buyer contacted
        Buyer replies STOP         →  permanent opt-out
        Day 1 follow-up            →  auto-sent if no reply
        Day 3 final notice         →  auto-sent if still no reply
        You win auction            →  python main.py → close_deal()
09:00  python main.py report       →  daily P&L vs $18K/week target
```

---

## Setup (30 minutes)

### 1. Install dependencies

```bash
cd tranchi-ai
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your keys
```

### 2. API Keys to Gather

| Key | Get It Here | Est. Cost |
|-----|------------|-----------|
| `SUPABASE_URL` + `SUPABASE_KEY` | supabase.com → Project Settings → API | Free |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys | ~$0.003/underwrite |
| `TWILIO_ACCOUNT_SID/TOKEN` | twilio.com → Console | $0.0075/SMS |
| `TWILIO_FROM_NUMBER` | Twilio → Buy Number | $1/mo |
| `APIFY_API_TOKEN` | apify.com → Settings → Integrations | $49/mo |
| `BATCHDATA_API_KEY` | batchdata.com | Pay per call |
| Google Service Account | See step 4 below | Free |

### 3. Supabase Setup

Paste and run `database/supabase_schema.sql` in Supabase SQL Editor.

### 4. Google Calendar / Meet Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → Enable **Google Calendar API**
3. IAM & Admin → Service Accounts → Create Service Account
4. Download the JSON key → save as `tranchi-ai/google_credentials.json`
5. Open Google Calendar → Settings → Share your calendar → add the service account email with "Make changes to events" permission

### 5. Twilio Webhook Setup

1. Buy a phone number in Twilio
2. Go to: Active Numbers → your number → Messaging → "A MESSAGE COMES IN"
3. Set Webhook URL to: `https://your-server.com/sms/inbound`
4. Deploy the webhook server (see Deploy section below)

### 6. Add Your First Buyers Manually (optional seed)

```sql
INSERT INTO cash_buyers (name, company, phone, email, state,
    preferred_states, max_purchase_price, opt_in, opt_in_date, status)
VALUES
  ('Marcus Johnson', 'MJ Capital', '+15551234567', 'marcus@mjcap.com',
   'TX', ARRAY['TX','FL'], 150000, TRUE, NOW(), 'ACTIVE');
```

Only buyers with `opt_in = TRUE` ever receive SMS.

---

## Daily Cron (automated)

```bash
# Run full pipeline at 7am and sequences again at noon
0 7  * * 1-5  cd /path/to/tranchi-ai && python main.py >> logs/morning.log 2>&1
0 12 * * 1-5  cd /path/to/tranchi-ai && python main.py sequences >> logs/noon.log 2>&1
```

---

## Deploy Webhook Server

The webhook server must be public so Twilio can reach it.
Easiest free options:

```bash
# Railway (recommended — free tier)
# 1. Push this repo to GitHub
# 2. New project → Deploy from GitHub → set start command:
#    python main.py webhook

# Or run locally with ngrok for testing:
ngrok http 8000
# Then set Twilio webhook to: https://xxxx.ngrok.io/sms/inbound
python main.py webhook
```

---

## The Math

```
MAO = (ARV × 0.70) - Repairs

Example:
  Gov auction opens at:   $9,000
  You bid and win at:     $22,000
  ARV (market value):     $90,000
  Repairs estimate:       $18,000
  MAO (your ceiling):     $45,000

  You assign to cash buyer at: $34,000
  Assignment fee:              $12,000
  Your costs (title/misc):     ~$1,500
  NET PROFIT:                  ~$10,500

2 deals/day × $10,500 = $21,000/week
```

---

## Buyer Sources (automatic)

| Source | Method | Volume |
|--------|--------|--------|
| Google Maps — "we buy houses" | Apify scraper | ~50/city |
| Craigslist Real Estate Wanted | Direct scrape | ~20/market |
| Connected Investors directory | Apify scraper | ~100/state |
| Inbound replies (they contact you) | Twilio webhook | varies |

---

## Property Sources (automatic)

| Source | URL | Notes |
|--------|-----|-------|
| HUD Homes | hudhomestore.gov | FHA foreclosures |
| Fannie Mae | homepath.com | FNMA REO |
| Freddie Mac | homesteps.com | FHLMC REO |
| GovEase Tax Sales | govease.com | County tax auctions |
| Auction.com | auction.com | Bank + gov REO |
| USDA Rural Dev | properties.sc.egov.usda.gov | Rural deep discounts |

---

## Closing a Deal

When you win an auction and assign it:

```python
from src.pipeline.deal_manager import close_deal

close_deal(
    deal_id="uuid-from-active-deals-table",
    sale_price=34000,
    assignment_fee=12000,
)
# Automatically archives to closed_deals and updates KPIs
```

---

## You Handle

- Bidding at the actual auction (online or in person)
- Signing paperwork / assignment contracts
- Any call a buyer requests (Google Meet is auto-booked for you)

## The Machine Handles

- Finding properties 24/7 across 7 states
- Underwriting every deal in seconds
- Building and scoring your buyer database
- Sending deal alerts to the right buyers
- Following up on days 1 and 3
- Booking Google Meet when someone says YES
- Tracking all KPIs toward your $18K+ weekly target
