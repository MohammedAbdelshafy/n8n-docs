"""
Deal Hunter — full end-to-end pipeline in one shot.

  1. Scrape all auction sources (county + national)
  2. Pull free Zillow comps for each new property
  3. AI underwrite every PENDING property
  4. Print approved deals ranked by profit
  5. Generate email + Facebook posts for top deals

Run: python main.py deal-hunt
"""

import asyncio
from datetime import date
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase
def deal_dashboard() -> list[dict]:
    """Print all APPROVED deals ranked by estimated profit."""
    deals = _sb().table("auction_properties") \
        .select("*") \
        .eq("ai_status", "APPROVED") \
        .order("estimated_arv", desc=True) \
        .limit(50) \
        .execute().data or []

    if not deals:
        print("\n  No approved deals yet. Run: python main.py deal-hunt\n")
        return []

    print(f"\n{'='*65}")
    print(f"  APPROVED DEALS — {date.today()} ({len(deals)} total)")
    print(f"{'='*65}")
    print(f"  {'GRADE':<6} {'ADDRESS':<35} {'BID':>8} {'ARV':>8} {'PROFIT':>9}")
    print(f"  {'-'*62}")

    for d in deals:
        grade  = d.get("ai_grade") or "?"
        addr   = (d.get("address") or "")[:33]
        bid    = d.get("opening_bid") or 0
        arv    = d.get("estimated_arv") or 0
        profit = (arv - bid - (d.get("estimated_repairs") or 0))
        stars  = "🔥" if grade == "A+" else ("✅" if grade == "A" else "")
        print(f"  {stars}{grade:<5} {addr:<35} ${bid:>7,.0f} ${arv:>7,.0f} ${profit:>8,.0f}")

    total_profit = sum(
        (d.get("estimated_arv") or 0) - (d.get("opening_bid") or 0) - (d.get("estimated_repairs") or 0)
        for d in deals
    )
    print(f"  {'-'*62}")
    print(f"  {'Total est. profit across all deals':42} ${total_profit:>8,.0f}")
    print(f"{'='*65}\n")

    return deals


def top_deal_post(deal: dict) -> str:
    """Generate a ready-to-post deal alert for the top deal."""
    addr    = deal.get("address", "")
    city    = deal.get("city", "")
    state   = deal.get("state", "")
    arv     = deal.get("estimated_arv") or 0
    bid     = deal.get("opening_bid") or 0
    repairs = deal.get("estimated_repairs") or 0
    grade   = deal.get("ai_grade") or "B"
    beds    = deal.get("bedrooms")
    sqft    = deal.get("sqft")
    source  = deal.get("source", "")
    sms     = deal.get("sms_draft") or ""
    spread  = arv - bid - repairs

    bed_str  = f"{beds}bd / " if beds else ""
    sqft_str = f"{sqft:,} sqft" if sqft else ""
    src_str  = source.split("_")[0] if source else "Auction"

    return f"""🔥 [{grade} DEAL] {city}, {state}

📍 {addr}
{bed_str}{sqft_str}
💰 Opening bid: ${bid:,.0f}
🏠 ARV (after repair): ${arv:,.0f}
🔧 Est. repairs: ${repairs:,.0f}
━━━━━━━━━━━━━━━━━━━━━━━━
📈 Spread: ${spread:,.0f}
Source: {src_str}

Cash only. 14-day close. As-is.

Reply INTERESTED or DM for full package (photos, comps, scope).

📱 SMS BLAST (copy this):
{sms}"""


async def run_deal_hunt(states: list[str] = None, fast: bool = False) -> dict:
    """
    Full pipeline: scrape → underwrite → show top deals.
    fast=True skips county scraper, only runs national sources.
    """
    from src.underwriter.ai_underwriter import run_underwriting

    print(f"\n{'='*65}")
    print(f"  TRANCHI AI — DEAL HUNT | {date.today()}")
    print(f"{'='*65}\n")

    # Step 1: County tax sales (best deals)
    if not fast:
        print("[STEP 1/3] COUNTY TAX SALES — direct from county websites...")
        from src.scrapers.county_tax_sale_scraper import run_county_scraper
        r1 = await run_county_scraper(states)
        print(f"  → {r1['saved']} new properties\n")
    else:
        r1 = {"saved": 0}

    # Step 2: National auction aggregators
    print("[STEP 2/3] NATIONAL AUCTION SOURCES (HUD, Bid4Assets, Govease)...")
    from src.scrapers.crawl4ai_auction_scraper import run_crawl4ai_scraper
    r2 = await run_crawl4ai_scraper(states=states)
    print(f"  → {r2['saved']} new properties\n")

    total_new = r1["saved"] + r2["saved"]

    if total_new == 0:
        print("  No new properties found this run. Checking existing PENDING...")

    # Step 3: Underwrite everything PENDING
    print("[STEP 3/3] AI UNDERWRITING (Claude + free Zillow comps)...")
    summary = run_underwriting()
    print()

    # Show dashboard
    deals = deal_dashboard()

    # Print top deal post
    approved = [d for d in deals if d.get("ai_grade") in ("A+", "A")]
    if approved:
        top = approved[0]
        print("── TOP DEAL — COPY THIS TO FACEBOOK / EMAIL ──────────────\n")
        print(top_deal_post(top))
        print()

    return {
        "county_saved":    r1["saved"],
        "national_saved":  r2["saved"],
        "underwritten":    summary["total"],
        "approved":        summary["approved"],
        "rejected":        summary["rejected"],
        "top_deals":       len([d for d in deals if d.get("ai_grade") in ("A+", "A")]),
    }


def run_deal_hunter(states: list[str] = None, fast: bool = False):
    asyncio.run(run_deal_hunt(states, fast))


if __name__ == "__main__":
    import sys
    states = [a for a in sys.argv[1:] if len(a) == 2 and a.isupper()] or None
    fast   = "--fast" in sys.argv
    run_deal_hunter(states, fast)
