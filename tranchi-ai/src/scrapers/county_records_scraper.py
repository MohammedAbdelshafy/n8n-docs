"""
County Public-Records Scraper — distressed properties (CSV #3).

Pulls foreclosure / sheriff-sale auction records from county sites that run on
the RealAuction platform (Florida = *.realforeclose.com, Ohio sheriff sales =
*.sheriffsaleauction.ohio.gov). These are PUBLIC RECORDS: property address +
owner/defendant name + case number + judgment/assessed amount.

No phone/email (records never contain that). To act on them:
  - direct-mail the property address, OR
  - skip-trace name->phone (see county_skiptrace.py), OR
  - bid at the public auction.

Output: seller_leads rows (source=COUNTY_RECORDS, consent_given=FALSE,
lead_type=PRE_FORECLOSURE). These are public records → sellable as a raw
motivated-seller list; the buyer skip-traces.
"""

import os
import json
import asyncio
import time as _time
from datetime import date
from typing import Optional

from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# RealAuction-powered county sites. "UPCOMING" view lists scheduled auctions.
COUNTIES = [
    # ── Florida foreclosure (realforeclose.com) ──
    {"name": "Miami-Dade", "state": "FL", "url": "https://www.miami-dade.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Broward",    "state": "FL", "url": "https://broward.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Hillsborough","state": "FL","url": "https://hillsborough.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Orange",     "state": "FL", "url": "https://myorangeclerk.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Duval",      "state": "FL", "url": "https://duval.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Pinellas",   "state": "FL", "url": "https://pinellas.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Lee",        "state": "FL", "url": "https://lee.realforeclose.com/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    # ── Ohio sheriff sales (sheriffsaleauction.ohio.gov) ──
    {"name": "Cuyahoga",   "state": "OH", "url": "https://cuyahoga.sheriffsaleauction.ohio.gov/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Franklin",   "state": "OH", "url": "https://franklin.sheriffsaleauction.ohio.gov/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Hamilton",   "state": "OH", "url": "https://hamilton.sheriffsaleauction.ohio.gov/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
    {"name": "Montgomery", "state": "OH", "url": "https://montgomery.sheriffsaleauction.ohio.gov/index.cfm?zaction=AUCTION&Zmethod=UPCOMING"},
]


def _extract(page_text: str, county: str, state: str) -> list[dict]:
    from src.utils.free_llm import call_llm
    system = (
        "You extract foreclosure / sheriff-sale auction records from a county "
        "auction page. Return ONLY a JSON array. Each item: "
        "{owner_name, property_address, city, zip, case_number, parcel_id, "
        "assessed_value, opening_bid, auction_date}. "
        "owner_name = the defendant / property owner. If none, return []."
    )
    _time.sleep(3)  # throttle to stay under Groq's per-minute limit
    try:
        raw = call_llm(system, f"County: {county}, {state}.\n\nPAGE:\n{page_text[:16000]}",
                       max_tokens=2500).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  [COUNTY] {county} extract failed: {e}")
        return []


async def _scrape_county(context, c: dict) -> list[dict]:
    page = await context.new_page()
    out = []
    try:
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ico,mp4}", lambda r: r.abort())
        await page.goto(c["url"], timeout=40000, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(3)  # let the auction list render
        try:
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
        except Exception:
            pass
        text = await page.inner_text("body")
        low = text.lower()
        if any(m in low for m in ["captcha", "access denied", "are you a human", "request blocked"]):
            print(f"  [COUNTY] {c['name']}: blocked — skipping")
            return []
        if len(text) < 400:
            print(f"  [COUNTY] {c['name']}: empty page (len {len(text)})")
            return []

        for r in _extract(text, c["name"], c["state"]):
            addr = (r.get("property_address") or "").strip()
            if not addr:
                continue
            out.append({
                "full_name":     (r.get("owner_name") or "").strip() or "Owner of Record",
                "address":       addr,
                "city":          r.get("city") or "",
                "state":         c["state"],
                "zip":           str(r.get("zip") or ""),
                "source":        "COUNTY_RECORDS",
                "source_detail": f"{c['name']} County, {c['state']} — foreclosure/sheriff sale",
                "lead_type":     "PRE_FORECLOSURE",
                "notes":         f"Case: {r.get('case_number','')} | Parcel: {r.get('parcel_id','')} | "
                                 f"Assessed: {r.get('assessed_value','')} | Opening bid: {r.get('opening_bid','')} | "
                                 f"Auction: {r.get('auction_date','')}",
                "consent_given": False,
            })
    except Exception as e:
        print(f"  [COUNTY] {c['name']} error: {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return out


def _save(records: list[dict]) -> int:
    saved = 0
    for r in records:
        try:
            existing = (_sb().table("seller_leads").select("id")
                        .eq("address", r["address"])
                        .eq("source", "COUNTY_RECORDS").execute())
            if existing.data:
                continue
            if _sb().table("seller_leads").insert(r).execute().data:
                saved += 1
        except Exception as e:
            print(f"  [COUNTY] save error ({r.get('address')}): {e}")
    return saved


async def run_county_records_scraper(states: Optional[list[str]] = None) -> dict:
    from playwright.async_api import async_playwright
    targets = COUNTIES
    if states:
        ss = [s.upper() for s in states]
        targets = [c for c in COUNTIES if c["state"] in ss]

    print(f"[COUNTY] Public-records scrape | {date.today()} | "
          f"counties: {[c['name'] for c in targets]}")
    all_recs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=UA, locale="en-US")
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        for c in targets:
            print(f"  Scraping: {c['name']}, {c['state']} — {c['url']}")
            recs = await _scrape_county(context, c)
            print(f"    -> {len(recs)} records")
            all_recs.extend(recs)
            await asyncio.sleep(1.5)
        await browser.close()

    saved = _save(all_recs)
    print(f"\n[COUNTY] Found: {len(all_recs)} distressed properties | saved: {saved} new")
    return {"total_found": len(all_recs), "saved": saved}


if __name__ == "__main__":
    asyncio.run(run_county_records_scraper(states=["FL"]))
