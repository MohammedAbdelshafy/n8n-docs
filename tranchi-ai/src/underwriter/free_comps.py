"""
Free comp puller — Zillow recently-sold data by zip code.

Replaces the BatchData paid API for ARV estimation.
Playwright fetches Zillow sold listings and returns structured comps
that feed directly into the AI underwriter.

Call: get_comps(zip_code, sqft, bedrooms)
"""

import asyncio
import re
import json
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


async def _fetch_zillow_sold(zip_code: str, max_price: int = 300_000) -> list[dict]:
    comps = []
    url   = f"https://www.zillow.com/homes/recently_sold/{zip_code}_rb/"

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx     = await browser.new_context(
                user_agent=UA,
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await page.wait_for_timeout(3_000)

            content = await page.content()

            # Zillow embeds listing data in a JSON script tag
            m = re.search(
                r'"cat1":\{"searchResults":\{"listResults":(\[.*?\])',
                content, re.DOTALL
            )
            if m:
                try:
                    listings = json.loads(m.group(1))
                    for l in listings[:20]:
                        price = l.get("unformattedPrice") or 0
                        if price > max_price or price < 10_000:
                            continue
                        sqft_raw = l.get("area") or l.get("livingArea") or 0
                        comps.append({
                            "address":    l.get("address", ""),
                            "sold_price": int(price),
                            "sqft":       int(sqft_raw) if sqft_raw else None,
                            "beds":       l.get("beds"),
                            "baths":      l.get("baths"),
                            "sold_date":  l.get("variableData", {}).get("text", "recent"),
                            "zpid":       l.get("zpid"),
                        })
                except Exception:
                    pass

            # Fallback: parse price cards from DOM
            if not comps:
                cards = await page.query_selector_all('[data-test="property-card"]')
                for card in cards[:20]:
                    try:
                        text  = (await card.inner_text()).strip()
                        price_m = re.search(r'\$(\d[\d,]+)', text)
                        sqft_m  = re.search(r'([\d,]+)\s*sqft', text, re.I)
                        addr_el = await card.query_selector('[data-test="property-card-addr"]')
                        addr    = (await addr_el.inner_text()).strip() if addr_el else ""
                        if price_m:
                            p = int(price_m.group(1).replace(',',''))
                            if 10_000 < p < max_price:
                                comps.append({
                                    "address":    addr,
                                    "sold_price": p,
                                    "sqft":       int(sqft_m.group(1).replace(',','')) if sqft_m else None,
                                    "sold_date":  "recent",
                                })
                    except Exception:
                        continue

            await browser.close()
    except Exception as e:
        print(f"[COMPS] Zillow {zip_code}: {e}")

    return comps


def _filter_comps(comps: list[dict], sqft: int, beds: int) -> list[dict]:
    """Keep comps within ±300 sqft and ±1 bedroom if possible."""
    if not comps:
        return []

    filtered = []
    for c in comps:
        c_sqft = c.get("sqft") or 0
        c_beds = c.get("beds") or 0
        if sqft and c_sqft and abs(c_sqft - sqft) > 400:
            continue
        if beds and c_beds and abs(c_beds - beds) > 1:
            continue
        filtered.append(c)

    return filtered or comps[:5]  # if filters are too tight, return first 5 raw


def get_comps(zip_code: str, sqft: int = 0, beds: int = 0,
              max_price: int = 300_000) -> list[dict]:
    """
    Synchronous entry point for the underwriter.
    Returns up to 5 comparable sold properties.
    """
    if not zip_code or len(zip_code) < 5:
        return []

    raw    = asyncio.run(_fetch_zillow_sold(zip_code, max_price))
    comps  = _filter_comps(raw, sqft, beds)
    result = comps[:5]

    if result:
        prices = [c["sold_price"] for c in result]
        avg    = sum(prices) // len(prices)
        print(f"  [COMPS] {zip_code}: {len(result)} comps | avg ${avg:,} | "
              f"range ${min(prices):,}–${max(prices):,}")
    else:
        print(f"  [COMPS] {zip_code}: no comps found")

    return result


if __name__ == "__main__":
    import sys
    zc = sys.argv[1] if len(sys.argv) > 1 else "77001"
    comps = get_comps(zc, sqft=1200, beds=3)
    for c in comps:
        print(f"  ${c['sold_price']:,} | {c.get('sqft','?')} sqft | {c['address']}")
