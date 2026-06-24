# Hola AI — Launch Checklist

Follow top to bottom. Total time: ~45 minutes.

---

## Step 1 — Supabase (5 min)

1. Go to https://database.new → create a project (any region)
2. Project Settings → API → copy `Project URL` and `service_role` key
3. SQL Editor → paste `database/supabase_schema.sql` → Run
4. SQL Editor → paste `database/seller_leads.sql` → Run
5. SQL Editor → paste `database/rls_policies.sql` → Run  ← **security critical, do not skip**

---

## Step 2 — Get API Keys (5 min)

Minimum required to go live:

| Key | Where to get it |
|-----|-----------------|
| `SUPABASE_URL` | Supabase → Project Settings → API |
| `SUPABASE_KEY` | Supabase → service_role key (backend only) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `EMAIL_ADDRESS` | Your Gmail address |
| `EMAIL_APP_PASSWORD` | Google Account → Security → 2-Step Verification → App Passwords → create one named "Hola" |

Optional (add later when you get a Twilio number):

| Key | Where to get it |
|-----|-----------------|
| `TWILIO_ACCOUNT_SID` | https://console.twilio.com |
| `TWILIO_AUTH_TOKEN` | https://console.twilio.com |
| `TWILIO_FROM_NUMBER` | Twilio phone numbers dashboard |

The system runs on email-only until Twilio is configured. SMS fires automatically once those three keys exist.

---

## Step 3 — Google Meet Auto-Booking (10 min)

Skip this on Day 1 if you want — the system flags interested buyers for manual callback.

1. https://console.cloud.google.com → New Project → name it "Hola AI"
2. APIs & Services → Enable → search "Google Calendar API" → Enable
3. IAM & Admin → Service Accounts → Create → name "tranchi-calendar"
4. Click the account → Keys → Add Key → JSON → Download
5. Save as `tranchi-ai/google_credentials.json`
6. Open https://calendar.google.com → Settings → your calendar → Share with specific people
7. Add the service account email (ends in `.iam.gserviceaccount.com`) → "Make changes to events"

---

## Step 4 — Deploy to Railway (5 min)

1. Railway is already connected to your GitHub — push triggers auto-deploy
2. Go to your Railway project → Variables tab → add every key from Step 2
3. Settings → Networking → **Generate Domain** (your public URL)
4. Wait ~2 min for deploy → visit `https://your-url.up.railway.app/health` → should return `{"status":"ok"}`

Your seller funnel is live at `https://your-url.up.railway.app/sell`

---

## Step 5 — Wire Twilio Webhook (when you add a number)

```bash
python scripts/setup_twilio.py https://your-app.up.railway.app
```

This auto-points your Twilio number at your live server.

---

## Step 6 — A2P 10DLC Registration (required before marketing SMS)

Open `marketing/a2p_10dlc_registration.txt` — answers are pre-filled.
Register at: https://console.twilio.com/us1/develop/sms/regulatory-compliance

Free, takes 1-3 days. You cannot send marketing SMS until this is approved.

---

## Step 7 — Drive Traffic to Your Seller Funnel

### Free (do this first — costs nothing, takes 15 min)

Post to these communities while the server is warming up:

- **BiggerPockets** → https://www.biggerpockets.com/forums/52  
  Copy from `marketing/biggerpockets_post.txt`

- **Facebook Groups** → search "real estate investors TX" / FL / OH etc → join top 3 → post  
  Copy from `marketing/facebook_post.txt`

- **Reddit** → r/realestateinvesting + r/WholesaleRealEstate  
  Copy from `marketing/reddit_post.txt`

### Paid Facebook Lead Ads ($20–40 budget)

Facebook Lead Ads let homeowners submit their info without leaving Facebook — they convert well for seller lead gen.

**Setup (20 min):**

1. Go to https://www.facebook.com/ads/manager → Create → Lead generation
2. **Campaign name:** "Cash Offer — [State]"
3. **Budget:** $10/day (run 3-4 days, pause when you hit budget)
4. **Audience:**
   - Location: TX, FL, OH, GA, NC, TN (one state per ad set)
   - Age: 35–65+
   - Homeowners: Detailed Targeting → "Homeowner" OR "Home ownership" → "Owns"
   - Interest: "Real estate" + "For sale by owner" (exclude renters)
5. **Placement:** Facebook Feed only (cheapest CPL)
6. **Ad creative:**
   - Headline: `Get a Cash Offer in 24 Hours — No Repairs Needed`
   - Description: `We buy houses as-is in [City]. No fees, no agents, close on your timeline.`
   - Image: any house photo (use Unsplash — free, commercial use ok)
   - CTA: `Get Quote`
7. **Lead form:** Link to `https://your-url.up.railway.app/sell`  
   *(Or use Facebook's native lead form — lower friction, but you'll export leads manually from Ads Manager)*

**Realistic expectations at $40 total:**
- Cost per seller lead: $8–15
- Leads generated: 3–5
- If you sell leads at $75–100 each: **$225–500 revenue from $40 spend**
- Best state to start: TX or FL — highest cash buyer demand, more competition = more buyers paying for leads

**Rule of thumb:** Only run paid ads after your server is live and the health check passes. Paid traffic to a down server = wasted money.

---

## Step 8 — First Pipeline Run

```bash
cd tranchi-ai
python main.py
```

Or run stages individually:
```bash
python main.py scrape       # find today's auctions
python main.py underwrite   # AI scores all new properties
python main.py buyers       # find more cash buyers
python main.py outreach     # email approved deals to opted-in buyers
python main.py sequences    # fire Day 1 / Day 3 follow-ups
python main.py report       # today's P&L dashboard
```

Lead export (when you have opt-in seller leads to sell):
```bash
python -c "from src.pipeline.lead_export import export_seller_leads; export_seller_leads()"
```

---

## Step 9 — Automate Daily

On any Linux server (Railway doesn't have cron — use a free cron service like cron-job.org to hit your `/health` endpoint and keep it warm, then run the pipeline locally or add a scheduler):

```
0 7  * * 1-5  cd /path/to/tranchi-ai && python main.py >> logs/morning.log 2>&1
0 12 * * 1-5  cd /path/to/tranchi-ai && python main.py sequences >> logs/noon.log 2>&1
```

---

## What Runs vs. What You Do

| Machine handles | You handle |
|-----------------|------------|
| Find auction properties daily | Bid at the auction (10 min online) |
| AI underwrite every deal | Join the Google Meet when auto-booked |
| Score and grow buyer list | Sign assignment contract |
| Email deals to matched buyers | Collect check |
| Day 1 + Day 3 follow-ups | |
| Auto-book Google Meet on YES | |
| Capture seller leads from `/sell` page | |
| Track KPIs vs $18K/week target | |
