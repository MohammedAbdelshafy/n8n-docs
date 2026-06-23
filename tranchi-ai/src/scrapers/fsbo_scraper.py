"""
Zillow FSBO scraper — finds homes listed for sale by owner.

People who list FSBO are often motivated: no agent means they want to
sell quickly and avoid commissions. Great targets for a cash offer.

These are saved to seller_leads with consent_given=FALSE and
source=ZILLOW_FSBO so they're excluded from paid lead exports.
Use them for your own outreach (call/email to offer cash) — if they
respond and request an offer, they've opted in and you can add them
to the sellable pool.

Runs Playwright headless. Use after `playwright install chromium`.
"""

import asyncio
import re
import json
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Zillow FSBO search by state + major city
FSBO_CITIES = {
    "TX": ["Houston", "Dallas", "San-Antonio", "Austin", "Fort-Worth"],
    "FL": ["Miami", "Tampa", "Orlando", "Jacksonville"],
    "OH": ["Columbus", "Cleveland", "Cincinnati"],
    "GA": ["Atlanta", "Savannah"],
    "NC": ["Charlotte", "Raleigh"],
    "TN": ["Nashville", "Memphis"],
    "AZ": ["Phoenix", "Tucson"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_price(text: str) -> int | None:
    m = re.search(r'\$[\d,]+', text)
    if m:
        return int(m.group().replace('$', '').replace(',', ''))
    return None


def _parse_beds(text: str) -> int | None:
    m = re.search(r'(\d+)\s*bd', text)
    return int(m.group(1)) if m else None


async def scrape_zillow_fsbo_city(page, state: str, city: str) -> list[dict]:
    """Scrape one city's FSBO results from Zillow."""
    results = []
    url = f"https://www.zillow.com/homes/fsbo/{city}-{state}_rb/"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)

        # Zillow renders a JSON blob in a script tag — fastest and most reliable
        content = await page.content()
        m = re.search(r'"listResults":\s*(\[.*?\])', content, re.DOTALL)
        if not m:
            # Fallback: try property cards
            cards = await page.query_selector_all('[data-test="property-card"]')
            for card in cards[:20]:
                text = (await card.inner_text()).strip()
                addr_el = await card.query_selector('[data-test="property-card-addr"]')
                addr = (await addr_el.inner_text()).strip() if addr_el else ""
                price = _parse_price(text)
                results.append({
                    "address": addr,
                    "price":   price,
                    "state":   state,
                    "city":    city,
                    "source":  "ZILLOW_FSBO",
                })
            return results

        listing_data = json.loads(m.group(1))
        for listing in listing_data[:20]:
            addr  = listing.get("address", "")
            price = listing.get("unformattedPrice") or _parse_price(listing.get("price", ""))
            beds  = listing.get("beds") or _parse_beds(listing.get("statusText", ""))
            dom   = listing.get("daysOnZillow", 0)  # days on market
            results.append({
                "address":      addr,
                "price":        price,
                "beds":         beds,
                "days_on_mkt":  dom,
                "state":        state,
                "city":         city,
                "source":       "ZILLOW_FSBO",
                "motivated":    dom > 30,  # stale = frustrated seller
            })

    except Exception as e:
        print(f"[FSBO] {city},{state} error: {e}")

    return results


async def run_fsbo_scraper(states: list[str] = None) -> int:
    states = states or TARGET_STATES
    new_leads = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await ctx.new_page()

        for state in states:
            if state not in FSBO_CITIES:
                continue
            for city in FSBO_CITIES[state]:
                print(f"[FSBO] Scraping {city}, {state}...")
                listings = await scrape_zillow_fsbo_city(page, state, city)

                for listing in listings:
                    addr = listing.get("address", "").strip()
                    if not addr:
                        continue

                    # Dedup by address
                    existing = supabase.table("seller_leads") \
                        .select("id") \
                        .eq("property_address", addr) \
                        .execute()
                    if existing.data:
                        continue

                    row = {
                        "name":              "FSBO Owner",
                        "phone":             None,
                        "email":             None,
                        "property_address":  addr,
                        "city":              listing.get("city", ""),
                        "state":             listing.get("state", ""),
                        "zip":               "",
                        "timeline":          "ASAP" if listing.get("motivated") else None,
                        "reason":            None,
                        "condition":         None,
                        "consent_given":     False,   # ← NOT sellable yet
                        "source":            "ZILLOW_FSBO",
                        "lead_score":        50 if listing.get("motivated") else 30,
                        "status":            "NEW",
                        "notes":             (
                            f"Asking ${listing.get('price',0):,} | "
                            f"{listing.get('beds','?')} bd | "
                            f"{listing.get('days_on_mkt','?')} DOM"
                        ),
                    }
                    try:
                        supabase.table("seller_leads").insert(row).execute()
                        new_leads += 1
                        flag = " ← MOTIVATED" if listing.get("motivated") else ""
                        print(f"  + {addr}{flag}")
                    except Exception as e:
                        print(f"  [FSBO] insert error: {e}")

                await page.wait_for_timeout(2_500)  # be polite

        await browser.close()

    print(f"\n[FSBO] Done — {new_leads} FSBO prospects saved for outreach")
    print("  Next: call them with a cash offer or send them to /sell to opt in.")
    return new_leads


if __name__ == "__main__":
    asyncio.run(run_fsbo_scraper())
