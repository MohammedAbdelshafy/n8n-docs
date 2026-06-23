"""
TRANCHI AI — Full Pipeline Orchestrator

  1. scrape       — pull government auction properties (free Playwright)
  2. underwrite   — Claude AI scores every new property
  3. buyers       — find cash buyers: Google Maps (free)
  4. prospects    — find FSBO + Craigslist + Reddit leads (free)
  5. outreach     — email approved deals to opted-in buyers
  6. sequences    — fire Day 1 / Day 3 follow-ups
  7. report       — daily KPI dashboard
  8. leads        — show sellable opt-in lead inventory + post templates
  9. export       — export opt-in seller leads to CSV
  10. webhook     — start the inbound SMS/form server

Usage:
  python main.py              # full daily run (steps 1–7)
  python main.py scrape       # auction property scraper
  python main.py underwrite   # AI underwriting
  python main.py buyers       # find cash buyers (Google Maps)
  python main.py prospects    # find FSBO + Craigslist + Reddit leads
  python main.py outreach     # email deals to opted-in buyers
  python main.py sequences    # Day 1 / Day 3 follow-ups
  python main.py report       # KPI dashboard
  python main.py leads        # show sellable leads + post templates
  python main.py export       # export opt-in leads to CSV
  python main.py webhook      # start inbound server (Railway uses this)
"""

import asyncio
import sys
from src.scrapers.crawl4ai_auction_scraper  import run_crawl4ai_scraper
from src.scrapers.playwright_buyer_scraper  import run_playwright_buyer_scraper
from src.underwriter.ai_underwriter         import run_underwriting
from src.outreach.email_outreach            import run_email_outreach
from src.outreach.buyer_outreach            import run_outreach
from src.sequences.outreach_sequence        import run_sequences
from src.pipeline.deal_manager              import print_daily_report


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "webhook":
        import uvicorn
        uvicorn.run("src.webhook.server:app", host="0.0.0.0", port=8000, reload=False)
        return

    if mode == "leads":
        from src.pipeline.lead_marketplace import run_lead_marketplace
        run_lead_marketplace()
        return

    if mode == "export":
        from src.pipeline.lead_export import export_seller_leads, export_summary
        export_summary()
        export_seller_leads()
        return

    if mode == "prospects":
        print("\n[PROSPECTS] Craigslist FSBO + buyers (RSS — free)...")
        from src.scrapers.craigslist_scraper import run_craigslist_scraper
        run_craigslist_scraper()

        print("\n[PROSPECTS] Reddit buyer contacts (free API)...")
        from src.scrapers.reddit_buyer_scraper import run_reddit_buyer_scraper
        run_reddit_buyer_scraper()

        print("\n[PROSPECTS] Zillow FSBO (Playwright — free)...")
        from src.scrapers.fsbo_scraper import run_fsbo_scraper
        asyncio.run(run_fsbo_scraper())
        return

    if mode in ("all", "scrape"):
        print("\n[1/7] SCRAPING GOVERNMENT AUCTIONS (Crawl4AI — free)...")
        result = asyncio.run(run_crawl4ai_scraper())
        print(f"     Found: {result['total_found']} | Saved: {result['saved']}")

    if mode in ("all", "underwrite"):
        print("\n[2/7] AI UNDERWRITING...")
        result = run_underwriting()
        print(f"     Approved: {result['approved']} | Rejected: {result['rejected']}")

    if mode in ("all", "buyers"):
        print("\n[3/7] BUYER ACQUISITION (Playwright — free)...")
        result = asyncio.run(run_playwright_buyer_scraper())
        print(f"     Found: {result['total_found']} | New saved: {result['saved']}")

    if mode in ("all", "outreach"):
        print("\n[4/7] BUYER OUTREACH (email primary, SMS fallback)...")
        result = run_email_outreach()
        print(f"     Emails sent: {result['emails_sent']}")
        import os
        if os.getenv("TWILIO_ACCOUNT_SID"):
            sms = run_outreach()
            print(f"     SMS sent: {sms['sms_sent']}")

    if mode in ("all", "sequences"):
        print("\n[5/7] FOLLOW-UP SEQUENCES...")
        result = run_sequences()
        print(f"     Day-1: {result['day1_sent']} | Day-3: {result['day3_sent']}")

    if mode in ("all", "report"):
        print("\n[6/7] DAILY REPORT")
        print_daily_report()

    if mode == "all":
        print("\n[7/7] LEAD INVENTORY")
        from src.pipeline.lead_marketplace import print_inventory
        print_inventory()


if __name__ == "__main__":
    main()
