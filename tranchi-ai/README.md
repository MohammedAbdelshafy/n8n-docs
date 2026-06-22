# Tranchi AI — Government Auction Deal Engine

Finds government-auctioned properties (tax sales, HUD, sheriff sales, Fannie Mae, Freddie Mac, USDA), AI-underwrites them in seconds, and pings your cash buyers list for fast exits.

**Target:** 2 closed deals/day → $18,000/week

---

## How It Works

```
Government Auctions
    ↓
Scraper (Apify + direct APIs)
    ↓
Supabase (auction_properties)
    ↓
Claude 3.5 Sonnet (MAO, ARV, grade)
    ↓
Filter: net profit > $10K
    ↓
Twilio SMS → Opted-in Cash Buyers
    ↓
Deal Closed → closed_deals table
```

---

## Setup (15 minutes)

### Step 1 — Clone & Install

```bash
cd tranchi-ai
pip install -r requirements.txt
cp .env.example .env
```

### Step 2 — API Keys to Gather

| Key | Where to Get It | Cost |
|-----|----------------|------|
| `SUPABASE_URL` + `SUPABASE_KEY` | supabase.com → Project Settings → API | Free tier works |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys | ~$0.003 per underwrite |
| `TWILIO_ACCOUNT_SID/TOKEN` | twilio.com → Console | ~$0.0075/SMS |
| `TWILIO_FROM_NUMBER` | Buy a number in Twilio ($1/month) | $1/mo |
| `APIFY_API_TOKEN` | apify.com → Settings → Integrations | $49/mo plan covers this |
| `BATCHDATA_API_KEY` | batchdata.com → API Keys | Pay per call |

### Step 3 — Set Up Supabase

1. Go to supabase.com → New Project
2. Open SQL Editor
3. Paste and run: `database/supabase_schema.sql`
4. All tables, indexes, and views are created automatically

### Step 4 — Add Your First Cash Buyers

In Supabase SQL Editor:

```sql
INSERT INTO cash_buyers (name, company, phone, email, state,
    preferred_states, max_purchase_price, opt_in, opt_in_date, status)
VALUES
  ('Marcus Johnson', 'MJ Capital', '+15551234567', 'marcus@mjcap.com',
   'TX', ARRAY['TX','FL'], 150000, TRUE, NOW(), 'ACTIVE'),
  ('Sandra Lee', 'Quick Flip LLC', '+15559876543', 'sandra@quickflip.com',
   'GA', ARRAY['GA','NC','TN'], 100000, TRUE, NOW(), 'ACTIVE');
```

**Only buyers with `opt_in = TRUE` ever receive SMS.**

### Step 5 — Run the Full Pipeline

```bash
# Full daily run (scrape → underwrite → outreach → report)
python main.py

# Or run individual stages:
python main.py scrape       # Step 1: pull from gov auctions
python main.py underwrite   # Step 2: Claude underwriting
python main.py outreach     # Step 3: SMS to buyers
python main.py report       # Step 4: daily summary
```

### Step 6 — Automate (run at 7am daily)

```bash
# Add to crontab
crontab -e

# Add this line:
0 7 * * * cd /path/to/tranchi-ai && python main.py >> logs/daily.log 2>&1
```

---

## The MAO Math (70% Rule)

```
MAO = (ARV × 0.70) - Repair Costs

Example:
  ARV:      $90,000
  Repairs:  $18,000
  MAO:      ($90,000 × 0.70) - $18,000 = $45,000

  Gov auction opening bid: $9,000
  You bid up to: $34,000 (leaving margin buffer)
  Assignment fee to buyer: $12,000
  Net profit: ~$10,500 after costs
```

---

## Where to Find Auctions (Free)

| Source | URL | Best States |
|--------|-----|------------|
| HUD Homes | hudhomestore.gov | All 50 |
| Fannie Mae | homepath.com | All 50 |
| Freddie Mac | homesteps.com | All 50 |
| GovEase Tax Sales | govease.com | TX, FL, GA, OH |
| Auction.com | auction.com | All 50 |
| USDA Rural Dev | properties.sc.egov.usda.gov | Rural markets |
| Texas Tax Sales | tax-sale.info | TX |
| Maricopa County | maricopa.gov/tax-lien | AZ |

---

## Deal Pipeline Stages

```
NEW → UNDERWRITING → APPROVED → BIDDING → WON → ASSIGNED → CLOSED
                                                  └→ LOST
```

---

## Closing a Deal

When you've won an auction and assigned to a buyer:

```python
from src.pipeline.deal_manager import close_deal

close_deal(
    deal_id="uuid-of-deal",
    sale_price=45000,
    assignment_fee=12000
)
```

---

## KPIs to Hit $18K/Week

| Metric | Daily Target |
|--------|-------------|
| Properties scraped | 50+ |
| AI approved (>$10K profit) | 5–10 |
| Buyer SMS sent | 10–20 |
| Auctions bid | 3–5 |
| Auctions won | 2 |
| Assignments closed | 2 |
| Assignment fees | $9,000+ |

Two deals/day at $9K avg = $18K/week. The math works — the variable is deal flow and buyer depth.
