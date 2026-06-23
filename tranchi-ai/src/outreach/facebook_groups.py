"""
Facebook Group Outreach System.

Facebook bot scrapers = instant account ban. This does it right:
  - Curated list of the highest-traffic investor groups per state
  - One-command post generation (copy-paste ready)
  - Group post tracker saved to Supabase (so you know what's posted)
  - DM scripts for commenters who say INTERESTED

Daily workflow:
  python main.py fb-post deal         ← generate deal alert post
  python main.py fb-post buyers       ← generate "I have leads" post
  python main.py fb-post wanted       ← generate "looking for buyers" post
  python main.py fb-tracker           ← see what's been posted + results
"""

from datetime import datetime, timezone, date
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── TOP FACEBOOK GROUPS PER STATE ─────────────────────────────────────────────
# Groups with 10k+ members. Search these names in Facebook to find them.
# Join before posting — most are open to investors.
FB_GROUPS = {
    "TX": [
        "Real Estate Investors Texas",
        "DFW Real Estate Investors Network",
        "Houston Real Estate Investors",
        "Texas Wholesale Real Estate",
        "San Antonio Real Estate Investors Club",
        "Austin Real Estate Investors",
        "Texas Cash Buyers Network",
        "Wholesale Houses Texas",
        "Texas REIA Members",
        "Flip Houses Texas",
    ],
    "FL": [
        "Florida Real Estate Investors",
        "South Florida Real Estate Investors Network",
        "Tampa Bay Real Estate Investors",
        "Orlando Real Estate Investors",
        "Central Florida REIA",
        "Florida Cash Home Buyers",
        "Wholesale Real Estate Florida",
        "Jacksonville Real Estate Investors",
        "Florida House Flippers",
        "Miami Real Estate Investors Club",
    ],
    "OH": [
        "Ohio Real Estate Investors",
        "Cleveland Real Estate Investors Network",
        "Columbus Real Estate Investors",
        "Ohio Cash Buyers and Sellers",
        "Wholesale Real Estate Ohio",
        "Cincinnati Real Estate Investors",
        "Greater Cleveland REIA",
        "Ohio House Flippers",
    ],
    "GA": [
        "Atlanta Real Estate Investors",
        "Georgia Real Estate Investors Network",
        "Atlanta Wholesale Real Estate",
        "Georgia Cash Buyers",
        "Atlanta REIA Members Group",
        "Georgia House Flippers and Investors",
    ],
    "NC": [
        "North Carolina Real Estate Investors",
        "Charlotte Real Estate Investors",
        "Raleigh Durham Real Estate Investors",
        "Carolina Cash Buyers Network",
        "NC Wholesale Real Estate",
        "Triangle Real Estate Investors",
    ],
    "TN": [
        "Tennessee Real Estate Investors",
        "Nashville Real Estate Investors Network",
        "Memphis Real Estate Investors",
        "Tennessee Cash Home Buyers",
        "Nashville Wholesale Deals",
        "TN House Flippers",
    ],
    "AZ": [
        "Arizona Real Estate Investors",
        "Phoenix Real Estate Investors Network",
        "Arizona Cash Buyers",
        "Phoenix Wholesale Real Estate",
        "AZ House Flippers and Investors",
        "Tucson Real Estate Investors",
    ],
    "ALL": [
        "Wholesale Real Estate Nationwide",
        "Real Estate Investors USA",
        "Cash Buyers Network USA",
        "Wholesale Deals USA",
        "House Flippers USA",
        "Real Estate Wholesaling",
        "We Buy Houses — Investors USA",
        "Real Estate Investor Network",
        "REIA Members Nationwide",
        "Off Market Deals — Investors Only",
    ],
}

# ── POST TEMPLATES ────────────────────────────────────────────────────────────

def post_deal_alert(
    address: str,
    arv: int,
    asking: int,
    repairs: int,
    state: str,
    beds: int = None,
    auction_date: str = None,
) -> str:
    spread = arv - asking - repairs
    grade  = "🔥 A+" if spread > 30_000 else ("✅ A" if spread > 20_000 else "🟡 B+")
    bed_str = f"{beds}bd | " if beds else ""
    date_str = f"\n📅 Auction/Close: {auction_date}" if auction_date else ""

    return f"""{grade} DEAL ALERT — {state}

📍 {address}
{bed_str}ARV: ${arv:,}
Asking: ${asking:,}
Est. Repairs: ${repairs:,}
━━━━━━━━━━━━━━
💰 Spread: ${spread:,}

Cash only. 14-day close. As-is.{date_str}

Comment INTERESTED or DM me for full details.
Not assigned yet — first serious buyer gets it.

#WholesaleRealEstate #{state}RealEstate #CashBuyer #OffMarket"""


def post_buyers_wanted(state: str, cities: list[str] = None) -> str:
    city_str = ", ".join(cities) if cities else f"{state} (statewide)"
    return f"""🏠 LOOKING FOR CASH BUYERS — {state}

I source off-market deals in {city_str} weekly from:
✅ Government tax auctions
✅ HUD / Fannie Mae / Sheriff sales
✅ Verified FSBO motivated sellers

What I send you:
📍 Address + ARV
💰 Asking price (already below 70% ARV)
🔧 Repair estimate
📋 Deal grade (A+/A/B)

Cash only, 14-day close, as-is deals.

If you're actively buying in {state} reply BUYER or DM me your buy box (price range, areas, property type) and I'll match deals to you automatically.

FREE to join the list. #WholesaleRealEstate #{state}"""


def post_leads_for_sale(
    state: str,
    total: int,
    hot: int,
    price_single: int = 75,
    price_bulk_5: int = 60,
) -> str:
    return f"""📋 MOTIVATED SELLER LEADS FOR SALE — {state}

{total} verified opt-in seller leads available now.
🔥 {hot} HOT (ASAP timeline, score 70+/100)

✅ All consent-verified — homeowners who requested a cash offer
✅ NOT cold data — signed TCPA disclosure with timestamp + IP
✅ Includes: name, phone, email, address, timeline, motivation score

💵 Pricing:
• 1 lead = ${price_single}
• 5 leads = ${price_bulk_5}/each
• 10+ leads = ${int(price_bulk_5 * 0.85)}/each

DM me for a sample (PII redacted) before buying.
Zelle / PayPal / Venmo accepted.

Comment LEADS or DM me 👇 #{state}RealEstate #MotivatedSellers #WholesaleLeads"""


def post_wholesalers_collab(state: str) -> str:
    return f"""🤝 LOOKING TO CO-WHOLESALE — {state}

I have buyers. You have deals. Let's split the fee.

I run a buyer list in {state} with active cash investors.
If you're a wholesaler sitting on a deal that needs a buyer:

✅ DM me the address + asking
✅ I'll shop it to my list same day
✅ 50/50 on the assignment fee

No exclusivity needed — just first right of refusal for 48hrs.

Serious wholesalers only. I move fast.
DM "COLLAB {state}" to get started 👇

#Wholesaling #CoWholesale #{state}RealEstate #RealEstateInvesting"""


# ── GROUP POST TRACKER ─────────────────────────────────────────────────────────

def log_group_post(group_name: str, post_type: str, state: str, notes: str = ""):
    """Record that you posted in a group. Prevents double-posting."""
    try:
        supabase.table("fb_group_posts").insert({
            "group_name": group_name,
            "post_type":  post_type,
            "state":      state,
            "posted_at":  datetime.now(timezone.utc).isoformat(),
            "notes":      notes,
        }).execute()
        print(f"[FB] Logged: '{group_name}' ({post_type})")
    except Exception:
        # Table may not exist yet — just print
        print(f"[FB] Posted to: '{group_name}' ({post_type})")


def get_post_history(days: int = 7) -> list[dict]:
    """Show what's been posted in the last N days."""
    try:
        rows = supabase.table("fb_group_posts") \
            .select("*") \
            .order("posted_at", desc=True) \
            .limit(100) \
            .execute().data or []
        return rows
    except Exception:
        return []


# ── DM SCRIPTS ────────────────────────────────────────────────────────────────

DM_SCRIPTS = {
    "interested_deal": """Hey {name}! Thanks for commenting — glad this one caught your eye.

Here's the full rundown on {address}:
ARV: ${arv:,} | Asking: ${asking:,} | Est. repairs: ${repairs:,}
Spread: ${spread:,}

It's unassigned — cash only, 14-day close, as-is.
Are you in a position to move on this? If so I can send the full package (photos, comps, inspection notes).

What's your typical buy box for {state}?""",

    "interested_leads": """Hey {name}! I saw you commented on the leads post — great.

Here's what I've got available in {state} right now: {total} verified opt-in motivated seller leads. All came through my cash offer funnel — homeowners who voluntarily requested a quote. Consent-verified with timestamp.

I can send a sample (3 leads, PII redacted) so you can see the format before committing. Just confirm your preferred payment method and I'll shoot it over.""",

    "buyer_inquiry": """Hey {name}, thanks for reaching out! Happy to add you to the list.

Quick questions so I can match you the right deals:
1. What states / cities are you buying in?
2. What's your price range (purchase price)?
3. Property type preference? (SFR, multi, any?)
4. How fast can you close once you see something you like?

Once I have that I'll only send you deals that actually fit your box — no spam.""",

    "wholesaler_collab": """Hey {name}! Appreciate you reaching out on the co-wholesale.

Send me:
📍 Address
💰 Your asking price
🔧 Any repair notes or photos if you have them

I'll shop it to my buyer list today and let you know if anyone bites within 24 hours. If we close I'll split the assignment fee 50/50, no drama.

Sound good?""",
}


# ── MAIN RUNNER ────────────────────────────────────────────────────────────────

def run_facebook_post_generator(post_type: str = "buyers", state: str = "TX", **kwargs):
    groups = FB_GROUPS.get(state, []) + FB_GROUPS.get("ALL", [])

    print(f"\n{'='*60}")
    print(f"  FACEBOOK GROUP POST — {post_type.upper()} / {state}")
    print(f"{'='*60}\n")

    if post_type == "deal":
        post = post_deal_alert(
            address=kwargs.get("address", "123 Main St, [City]"),
            arv=kwargs.get("arv", 120_000),
            asking=kwargs.get("asking", 55_000),
            repairs=kwargs.get("repairs", 20_000),
            state=state,
            beds=kwargs.get("beds"),
            auction_date=kwargs.get("auction_date"),
        )
    elif post_type == "leads":
        post = post_leads_for_sale(
            state=state,
            total=kwargs.get("total", 0),
            hot=kwargs.get("hot", 0),
        )
    elif post_type == "collab":
        post = post_wholesalers_collab(state=state)
    else:  # buyers (default)
        post = post_buyers_wanted(
            state=state,
            cities=kwargs.get("cities"),
        )

    print("── COPY THIS POST ──────────────────────────────────────\n")
    print(post)
    print("\n── POST TO THESE GROUPS (search names in Facebook) ────\n")
    for i, g in enumerate(groups, 1):
        print(f"  {i:02d}. {g}")

    print(f"\n── DM SCRIPTS (use after people comment) ──────────────\n")
    if post_type == "deal":
        script = DM_SCRIPTS["interested_deal"].format(
            name="[their name]",
            address=kwargs.get("address", "the property"),
            arv=kwargs.get("arv", 0),
            asking=kwargs.get("asking", 0),
            repairs=kwargs.get("repairs", 0),
            spread=(kwargs.get("arv", 0) - kwargs.get("asking", 0) - kwargs.get("repairs", 0)),
            state=state,
        )
    elif post_type == "leads":
        script = DM_SCRIPTS["interested_leads"].format(
            name="[their name]", state=state,
            total=kwargs.get("total", 0),
        )
    else:
        script = DM_SCRIPTS["buyer_inquiry"].format(name="[their name]")

    print(script)
    print(f"\n{'='*60}")
    print(f"  Tip: Post in 3-5 groups per day to avoid spam flags.")
    print(f"  Space posts 30+ min apart. Use a real profile, not a new one.")
    print(f"{'='*60}\n")


def run_fb_tracker():
    history = get_post_history(days=14)
    print(f"\n{'='*55}")
    print(f"  FACEBOOK GROUP POST HISTORY (last 14 days)")
    print(f"{'='*55}")
    if not history:
        print("  No posts logged yet.")
        print("  After posting, run: python main.py fb-log 'Group Name' deal TX")
    else:
        by_group: dict[str, list] = {}
        for row in history:
            g = row.get("group_name", "unknown")
            by_group.setdefault(g, []).append(row)
        for group, posts in by_group.items():
            last = posts[0].get("posted_at", "")[:10]
            types = ", ".join(set(p.get("post_type","") for p in posts))
            print(f"  {group}")
            print(f"    Last post: {last} | Types: {types} | Count: {len(posts)}")
    print(f"{'='*55}\n")
