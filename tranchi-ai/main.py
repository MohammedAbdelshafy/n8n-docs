"""
TRANCHI AI — Full Pipeline Orchestrator
Run daily (or multiple times/day) to work the full funnel:

  1. scrape     — pull new properties from government auctions
  2. underwrite — Claude AI scores every new property
  3. buyers     — find & add new cash buyers to your list
  4. outreach   — SMS approved deals to opted-in buyers
  5. sequences  — fire Day 1 / Day 3 follow-ups
  6. report     — daily KPI dashboard
  7. webhook    — start the SMS reply server (separate process)

Usage:
  python main.py              # full daily run (steps 1–6)
  python main.py scrape       # just step 1
  python main.py underwrite   # just step 2
  python main.py buyers       # just step 3
  python main.py outreach     # just step 4
  python main.py sequences    # just step 5
  python main.py report       # just step 6
  python main.py webhook      # start inbound SMS server
"""

import asyncio
import sys
from src.scrapers.auction_scraper   import run_ingestion
from src.underwriter.ai_underwriter import run_underwriting
from src.buyers.cash_buyer_finder   import run_buyer_acquisition
from src.outreach.buyer_outreach    import run_outreach
from src.sequences.outreach_sequence import run_sequences
from src.pipeline.deal_manager      import print_daily_report


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "webhook":
        import uvicorn
        uvicorn.run("src.webhook.server:app", host="0.0.0.0", port=8000, reload=False)
        return

    if mode in ("all", "scrape"):
        print("\n[1/6] SCRAPING GOVERNMENT AUCTIONS...")
        result = asyncio.run(run_ingestion())
        print(f"     Found: {result['total_found']} | Saved: {result['saved']}")

    if mode in ("all", "underwrite"):
        print("\n[2/6] AI UNDERWRITING...")
        result = run_underwriting()
        print(f"     Approved: {result['approved']} | Rejected: {result['rejected']}")

    if mode in ("all", "buyers"):
        print("\n[3/6] BUYER ACQUISITION...")
        result = asyncio.run(run_buyer_acquisition())
        print(f"     Found: {result['total_found']} | New saved: {result['saved']}")

    if mode in ("all", "outreach"):
        print("\n[4/6] INITIAL BUYER OUTREACH...")
        result = run_outreach()
        print(f"     SMS sent: {result['sms_sent']}")

    if mode in ("all", "sequences"):
        print("\n[5/6] FOLLOW-UP SEQUENCES...")
        result = run_sequences()
        print(f"     Day-1: {result['day1_sent']} | Day-3: {result['day3_sent']}")

    if mode in ("all", "report"):
        print("\n[6/6] DAILY REPORT")
        print_daily_report()


if __name__ == "__main__":
    main()
