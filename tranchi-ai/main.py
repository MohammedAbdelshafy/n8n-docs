"""
TRANCHI AI — Full Pipeline Orchestrator
Run daily (or multiple times/day) to work the full funnel:

  1. scrape     — pull properties: Crawl4AI (free) + Apify fallback
  2. underwrite — Claude AI scores every new property
  3. buyers     — find cash buyers: Playwright Google Maps (free)
  4. outreach   — SMS approved deals to opted-in buyers
  5. sequences  — fire Day 1 / Day 3 follow-ups
  6. report     — daily KPI dashboard
  7. webhook    — start the SMS reply server (separate process)

Usage:
  python main.py              # full daily run (steps 1–6)
  python main.py scrape       # just step 1 (auction properties)
  python main.py underwrite   # just step 2
  python main.py buyers       # just step 3 (find cash buyers)
  python main.py outreach     # just step 4
  python main.py sequences    # just step 5
  python main.py report       # just step 6
  python main.py webhook      # start inbound SMS server
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

    if mode in ("all", "scrape"):
        print("\n[1/6] SCRAPING GOVERNMENT AUCTIONS (Crawl4AI — free)...")
        result = asyncio.run(run_crawl4ai_scraper())
        print(f"     Found: {result['total_found']} | Saved: {result['saved']}")

    if mode in ("all", "underwrite"):
        print("\n[2/6] AI UNDERWRITING...")
        result = run_underwriting()
        print(f"     Approved: {result['approved']} | Rejected: {result['rejected']}")

    if mode in ("all", "buyers"):
        print("\n[3/6] BUYER ACQUISITION (Playwright — free)...")
        result = asyncio.run(run_playwright_buyer_scraper())
        print(f"     Found: {result['total_found']} | New saved: {result['saved']}")

    if mode in ("all", "outreach"):
        print("\n[4/6] BUYER OUTREACH (email primary, SMS fallback)...")
        result = run_email_outreach()
        print(f"     Emails sent: {result['emails_sent']}")
        # SMS fallback if Twilio is configured
        import os
        if os.getenv("TWILIO_ACCOUNT_SID"):
            sms = run_outreach()
            print(f"     SMS sent: {sms['sms_sent']}")

    if mode in ("all", "sequences"):
        print("\n[5/6] FOLLOW-UP SEQUENCES...")
        result = run_sequences()
        print(f"     Day-1: {result['day1_sent']} | Day-3: {result['day3_sent']}")

    if mode in ("all", "report"):
        print("\n[6/6] DAILY REPORT")
        print_daily_report()


if __name__ == "__main__":
    main()
