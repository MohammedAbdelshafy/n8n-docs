"""
TRANCHI AI — Main Orchestrator
Run this daily (cron or manual) to execute the full pipeline:
  1. Scrape government auctions
  2. AI underwrite all new properties
  3. Send buyer outreach for approved deals
  4. Print daily report
"""

import asyncio
import sys
from src.scrapers.auction_scraper import run_ingestion
from src.underwriter.ai_underwriter import run_underwriting
from src.outreach.buyer_outreach import run_outreach
from src.pipeline.deal_manager import print_daily_report


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode in ("all", "scrape"):
        print("\n[1/4] SCRAPING GOVERNMENT AUCTIONS...")
        ingestion_summary = asyncio.run(run_ingestion())
        print(f"     Found: {ingestion_summary['total_found']} | Saved: {ingestion_summary['saved']}")

    if mode in ("all", "underwrite"):
        print("\n[2/4] AI UNDERWRITING...")
        uw_summary = run_underwriting()
        print(f"     Approved: {uw_summary['approved']} | Rejected: {uw_summary['rejected']}")

    if mode in ("all", "outreach"):
        print("\n[3/4] BUYER OUTREACH...")
        outreach_summary = run_outreach()
        print(f"     SMS Sent: {outreach_summary['sms_sent']}")

    if mode in ("all", "report"):
        print("\n[4/4] DAILY REPORT")
        print_daily_report()


if __name__ == "__main__":
    main()
