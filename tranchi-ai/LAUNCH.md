# Tranchi AI — Launch Checklist

Everything in order. Follow top to bottom. Total time: ~45 minutes.

---

## Step 1 — Supabase (5 min)

1. Go to https://database.new
2. Create a project, pick a region close to you
3. Project Settings → API → copy `Project URL` and `service_role` key
4. SQL Editor → paste entire contents of `database/supabase_schema.sql` → Run

---

## Step 2 — Get API Keys (10 min)

Open each link, create account if needed, copy key into `.env`

| Key | Link |
|-----|------|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `TWILIO_ACCOUNT_SID` + `AUTH_TOKEN` | https://console.twilio.com |
| `TWILIO_FROM_NUMBER` | https://console.twilio.com/us1/develop/phone-numbers/manage/search?isoCountry=US&type=local |
| `APIFY_API_TOKEN` | https://console.apify.com/account/integrations |
| `BATCHDATA_API_KEY` | https://batchdata.com/account/api |

---

## Step 3 — Google Meet (10 min)

1. https://console.cloud.google.com → New Project → name it "Tranchi AI"
2. APIs & Services → Enable APIs → search "Google Calendar API" → Enable
3. IAM & Admin → Service Accounts → Create Service Account → name "tranchi-calendar"
4. Click the account → Keys → Add Key → JSON → Download
5. Save the downloaded file as `tranchi-ai/google_credentials.json`
6. Open https://calendar.google.com → Settings → your calendar → Share with specific people
7. Add the service account email (ends in `.iam.gserviceaccount.com`) → "Make changes to events"
8. Add `YOUR_EMAIL` to `.env`

---

## Step 4 — Validate Everything (2 min)

```bash
cd tranchi-ai
bash scripts/setup.sh
```

Fix anything it flags before continuing.

---

## Step 5 — Deploy to Railway (5 min)

1. Push this repo to your GitHub if not already there
2. Go to https://railway.app/new
3. "Deploy from GitHub Repo" → select this repo
4. Set **Root Directory** to `tranchi-ai`
5. Variables tab → add every key from your `.env`
6. Deploy → wait ~2 min → copy your public URL (e.g. `https://tranchi-ai.up.railway.app`)

**Auto-deploy after this:** every push to your branch redeploys via GitHub Actions.
(Add `RAILWAY_TOKEN` to GitHub repo → Settings → Secrets — get token at https://railway.app/account/tokens)

---

## Step 6 — Wire Twilio Webhook (1 min — automated)

Once Railway gives you a URL:
```bash
python scripts/setup_twilio.py https://your-app.up.railway.app
```

This auto-points your Twilio number at your live server.

---

## Step 7 — A2P 10DLC Registration (10 min, then 1-3 day wait)

Open `marketing/a2p_10dlc_registration.txt` — all answers are pre-filled.
Register at: https://console.twilio.com/us1/develop/sms/regulatory-compliance

You cannot send marketing SMS until this is approved. It's free and takes 1-3 days.

---

## Step 8 — Post on Buyer Forums (10 min)

While waiting for A2P approval, build your buyer list:

Replace `[YOUR RAILWAY URL]` in each file with your actual URL, then post:

- **BiggerPockets** → https://www.biggerpockets.com/forums/52 (Deals & Steals)
  → Copy from `marketing/biggerpockets_post.txt`

- **Facebook** → Search "real estate investors [TX/FL/GA/etc]" → join top 3 groups → post
  → Copy from `marketing/facebook_post.txt`

- **Reddit** → https://reddit.com/r/realestateinvesting + https://reddit.com/r/WholesaleRealEstate
  → Copy from `marketing/reddit_post.txt`

---

## Step 9 — First Pipeline Run

```bash
cd tranchi-ai
python main.py
```

Or run stages individually:
```bash
python main.py scrape       # find today's auctions
python main.py underwrite   # AI scores all new properties
python main.py buyers       # find more cash buyers
python main.py outreach     # SMS approved deals to opted-in buyers
python main.py sequences    # fire Day 1 / Day 3 follow-ups
python main.py report       # today's P&L dashboard
```

---

## Step 10 — Automate Daily (cron)

```bash
crontab -e
```

Add:
```
0 7  * * 1-5  cd /path/to/tranchi-ai && python main.py >> logs/morning.log 2>&1
0 12 * * 1-5  cd /path/to/tranchi-ai && python main.py sequences >> logs/noon.log 2>&1
```

---

## You're live. The machine runs from here.

| Done by machine | Done by you |
|-----------------|-------------|
| Find auction properties daily | Bid at the auction (~10 min online) |
| AI underwrite every deal | Answer the Google Meet when booked |
| Score and grow buyer list | Sign assignment contract |
| SMS deals to matched buyers | Collect your check |
| Day 1 + Day 3 follow-ups | |
| Auto-book Google Meet on YES | |
| Track KPIs vs $18K/week target | |
