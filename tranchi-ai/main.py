"""
TRANCHI AI — Full Pipeline Orchestrator

  1. scrape          — pull government auction properties (free Playwright)
  2. underwrite      — Claude AI scores every new property
  3. buyers          — find cash buyers: Google Maps (free)
  4. prospects       — find FSBO + Craigslist + Reddit leads (free)
  5. outreach        — email approved deals to opted-in buyers
  6. sequences       — fire Day 1 / Day 3 follow-ups
  7. report          — daily KPI dashboard
  8. leads           — show sellable opt-in lead inventory + post templates
  9. export          — export opt-in seller leads to CSV
  10. import-zillow  — import Property Data Labs CSV export
  11. outreach-fsbo  — AI-draft emails to FSBO prospects
  12. webhook        — start the inbound SMS/form server
  13. lis-pendens    — scrape pre-foreclosure filings from county clerk portals (FREE)

Usage:
  python main.py                            # full daily run
  python main.py scrape                     # auction property scraper
  python main.py underwrite                 # AI underwriting
  python main.py buyers                     # find cash buyers (Google Maps)
  python main.py prospects                  # FSBO + Craigslist + Reddit
  python main.py outreach                   # email deals to opted-in buyers
  python main.py sequences                  # Day 1 / Day 3 follow-ups
  python main.py report                     # KPI dashboard
  python main.py leads                      # sellable leads + post templates
  python main.py export                     # export opt-in leads to CSV
  python main.py import-zillow file.csv     # import Zillow Data Exporter CSV
  python main.py outreach-fsbo              # AI emails to FSBO prospects
  python main.py buyers-all                 # ALL buyer scrapers in one shot
  python main.py lis-pendens                # scrape lis pendens (all FL counties)
  python main.py lis-pendens Miami-Dade     # single county
  python main.py webhook                    # start inbound server (Railway)
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

    if mode == "import-zillow":
        csv_path = sys.argv[2] if len(sys.argv) > 2 else None
        if not csv_path:
            print("Usage: python main.py import-zillow path/to/export.csv")
            sys.exit(1)
        from scripts.import_zillow_export import import_zillow_csv
        import_zillow_csv(csv_path)
        return

    if mode == "outreach-fsbo":
        from src.outreach.fsbo_outreach import run_fsbo_outreach
        run_fsbo_outreach()
        return

    if mode == "lis-pendens":
        from src.scrapers.lis_pendens_scraper import run_lis_pendens_scraper
        counties = sys.argv[2:] if len(sys.argv) > 2 else None
        result = asyncio.run(run_lis_pendens_scraper(counties=counties))
        print(f"\n[LIS_PENDENS] {result['total_found']} filings found | {result['saved']} new leads saved")
        print(f"  Counties: {', '.join(result['counties'])}")
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
        print("\n[1/8] SCRAPING GOVERNMENT AUCTIONS (Crawl4AI — free)...")
        result = asyncio.run(run_crawl4ai_scraper())
        print(f"     Found: {result['total_found']} | Saved: {result['saved']}")

        print("\n[1b/8] LIS PENDENS — pre-foreclosure leads (county clerk — free)...")
        from src.scrapers.lis_pendens_scraper import run_lis_pendens_scraper
        lp = asyncio.run(run_lis_pendens_scraper())
        print(f"     Found: {lp['total_found']} | Saved: {lp['saved']}")

    if mode in ("all", "underwrite"):
        print("\n[2/7] AI UNDERWRITING...")
        result = run_underwriting()
        print(f"     Approved: {result['approved']} | Rejected: {result['rejected']}")
        from src.notifications.discord_notify import notify_daily_summary
        notify_daily_summary(result)

    if mode == "deal-hunt":
        # Full pipeline: county + national scrape → AI underwrite → show top deals
        from src.pipeline.deal_hunter import run_deal_hunter
        states = [a for a in sys.argv[2:] if len(a) == 2 and a.isupper()] or None
        fast   = "--fast" in sys.argv
        run_deal_hunter(states=states, fast=fast)
        return

    if mode == "deals":
        # Show current approved deal dashboard (no scraping)
        from src.pipeline.deal_hunter import deal_dashboard
        deal_dashboard()
        return

    if mode == "buyers-all":
        from src.scrapers.buyer_aggregator import run_buyer_aggregator
        run_buyer_aggregator()
        return

    if mode == "fb-post":
        from src.outreach.facebook_groups import run_facebook_post_generator
        post_type = sys.argv[2] if len(sys.argv) > 2 else "buyers"
        state     = sys.argv[3] if len(sys.argv) > 3 else "TX"
        run_facebook_post_generator(post_type=post_type, state=state)
        return

    if mode == "fb-tracker":
        from src.outreach.facebook_groups import run_fb_tracker
        run_fb_tracker()
        return

    if mode == "fb-log":
        from src.outreach.facebook_groups import log_group_post
        group     = sys.argv[2] if len(sys.argv) > 2 else "Unknown Group"
        post_type = sys.argv[3] if len(sys.argv) > 3 else "deal"
        state     = sys.argv[4] if len(sys.argv) > 4 else ""
        log_group_post(group, post_type, state)
        return

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
