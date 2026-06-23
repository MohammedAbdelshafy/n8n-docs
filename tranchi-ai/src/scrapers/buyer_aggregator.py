"""
Buyer Aggregator — runs ALL cash buyer scrapers in sequence.
One command finds buyers from every free source:

  Source                  Type            Cost
  ──────────────────────  ──────────────  ─────
  Google Maps             Business search  $0
  Craigslist RSS          Ad posts         $0
  Reddit (JSON API)       Forum posts      $0
  BiggerPockets forums    Forum posts      $0
  National REIA chapters  Member dirs      $0
  Connected Investors     Investor network $0

Run: python main.py buyers-all
"""

import asyncio
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def buyer_count() -> int:
    r = supabase.table("cash_buyers").select("id", count="exact").eq("opt_in", True).execute()
    return r.count or 0


async def run_all_buyer_scrapers() -> dict:
    start_count = buyer_count()
    results: dict[str, int] = {}

    # 1. Google Maps (already runs in buyers command)
    print("\n" + "="*55)
    print("  [1/6] GOOGLE MAPS — 'we buy houses' per city")
    print("="*55)
    try:
        from src.scrapers.playwright_buyer_scraper import run_playwright_buyer_scraper
        r = await run_playwright_buyer_scraper()
        results["google_maps"] = r.get("saved", 0)
    except Exception as e:
        print(f"  [SKIP] Google Maps: {e}")
        results["google_maps"] = 0

    # 2. Craigslist RSS
    print("\n" + "="*55)
    print("  [2/6] CRAIGSLIST — 'we buy houses' RSS ads")
    print("="*55)
    try:
        from src.scrapers.craigslist_scraper import scrape_buyers
        results["craigslist"] = await scrape_buyers()
    except Exception as e:
        print(f"  [SKIP] Craigslist: {e}")
        results["craigslist"] = 0

    # 3. Reddit JSON API
    print("\n" + "="*55)
    print("  [3/6] REDDIT — r/WholesaleRealEstate + r/realestateinvesting")
    print("="*55)
    try:
        from src.scrapers.reddit_buyer_scraper import scrape_reddit_buyers
        results["reddit"] = await scrape_reddit_buyers()
    except Exception as e:
        print(f"  [SKIP] Reddit: {e}")
        results["reddit"] = 0

    # 4. BiggerPockets forums
    print("\n" + "="*55)
    print("  [4/6] BIGGERPOCKETS — Wholesaling + Deals forums")
    print("="*55)
    try:
        from src.scrapers.biggerpockets_buyer_scraper import run_biggerpockets_buyer_scraper
        results["biggerpockets"] = await run_biggerpockets_buyer_scraper()
    except Exception as e:
        print(f"  [SKIP] BiggerPockets: {e}")
        results["biggerpockets"] = 0

    # 5. National REIA chapters
    print("\n" + "="*55)
    print("  [5/6] REIA CHAPTERS — member directories per state")
    print("="*55)
    try:
        from src.scrapers.national_reia_scraper import run_reia_scraper
        results["reia"] = await run_reia_scraper()
    except Exception as e:
        print(f"  [SKIP] REIA: {e}")
        results["reia"] = 0

    # 6. Connected Investors
    print("\n" + "="*55)
    print("  [6/6] CONNECTED INVESTORS — investor network")
    print("="*55)
    try:
        from src.scrapers.connected_investors_scraper import run_connected_investors_scraper
        results["connected_investors"] = await run_connected_investors_scraper()
    except Exception as e:
        print(f"  [SKIP] Connected Investors: {e}")
        results["connected_investors"] = 0

    end_count = buyer_count()
    total_new = end_count - start_count

    print("\n" + "="*55)
    print("  BUYER ACQUISITION COMPLETE")
    print("="*55)
    print(f"  Buyer list before:  {start_count:,}")
    print(f"  Buyer list after:   {end_count:,}")
    print(f"  New contacts added: {total_new:,}")
    print()
    for source, count in results.items():
        print(f"  {source:<22} +{count}")
    print("="*55)
    print(f"  Next: python main.py outreach  ← email them your deals\n")

    return results


def run_buyer_aggregator():
    asyncio.run(run_all_buyer_scrapers())


if __name__ == "__main__":
    run_buyer_aggregator()
