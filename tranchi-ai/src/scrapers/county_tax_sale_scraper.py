"""
County Tax Sale + Sheriff Sale scraper.

These are the REAL Hola AI deal sources — direct from county websites.
Opening bids often start at $500–$15,000. ARV can be $60K–$150K.
That's the $9K→$90K spread Hola AI is built on.

Auctions are public records. Most counties post upcoming sales online.

Supported counties (with verified URLs as of 2025):
  TX: Harris, Dallas, Tarrant, Bexar, Travis, Collin
  FL: Hillsborough, Broward, Duval, Orange, Palm Beach
  OH: Cuyahoga, Franklin, Hamilton, Summit
  GA: Fulton, Gwinnett, DeKalb
  TN: Shelby, Davidson
  NC: Mecklenburg, Wake

Uses LLM extraction — adapts to any HTML structure automatically.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from playwright.async_api import async_playwright, Page
from supabase import create_client
from src.utils.free_llm import call_llm
from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ── COUNTY AUCTION SOURCES ────────────────────────────────────────────────────
# Each entry: (state, county, url, sale_type, notes)
COUNTY_SOURCES = [
    # TEXAS — monthly first Tuesday auctions
    ("TX", "Harris",   "https://www.harriscountytax.com/tax-sale",                           "TAX_DEED",  "Houston area"),
    ("TX", "Dallas",   "https://www.dallascounty.org/departments/countyclerk/foreclosure-sales.php", "FORECLOSURE", "Dallas area"),
    ("TX", "Tarrant",  "https://www.tarrantcounty.com/en/tax-assessor-collector/property-tax/delinquent-tax-sale.html", "TAX_DEED", "Fort Worth"),
    ("TX", "Bexar",    "https://www.bexar.org/2232/Tax-Sales",                               "TAX_DEED",  "San Antonio"),
    ("TX", "Travis",   "https://tax.traviscountytx.gov/pages/taxsales",                      "TAX_DEED",  "Austin"),
    ("TX", "Collin",   "https://www.collincounty.com/government/departments/tax-assessor-collector/tax-sales", "TAX_DEED", "Plano/McKinney"),

    # FLORIDA — online foreclosure auctions (Realauction)
    ("FL", "Hillsborough", "https://hillsborough.realforeclose.com",                         "FORECLOSURE", "Tampa"),
    ("FL", "Broward",      "https://broward.realforeclose.com",                               "FORECLOSURE", "Fort Lauderdale"),
    ("FL", "Duval",        "https://duval.realforeclose.com",                                 "FORECLOSURE", "Jacksonville"),
    ("FL", "Orange",       "https://orange.realforeclose.com",                                "FORECLOSURE", "Orlando"),
    ("FL", "Palm Beach",   "https://pbcgov.com/papa/index.aspx",                              "FORECLOSURE", "West Palm Beach"),

    # OHIO — sheriff sales
    ("OH", "Cuyahoga",  "https://www.cuyahogacounty.gov/law-enforcement/sheriff/sheriff-sales", "SHERIFF", "Cleveland"),
    ("OH", "Franklin",  "https://sheriff.franklincountyohio.gov/Real-Estate/Sheriff-Sales",    "SHERIFF", "Columbus"),
    ("OH", "Hamilton",  "https://www.hcso.org/divisions/civil/sheriffs-sales",                 "SHERIFF", "Cincinnati"),
    ("OH", "Summit",    "https://www.sheriff.summitoh.net/index.php/civil-department/sheriff-sales", "SHERIFF", "Akron"),

    # GEORGIA — courthouse steps (first Tuesday)
    ("GA", "Fulton",   "https://www.fultoncountyga.gov/inside-fulton-county/fulton-county-departments/superior-court/foreclosures", "FORECLOSURE", "Atlanta"),
    ("GA", "Gwinnett", "https://www.gwinnettcounty.com/portal/gwinnett/County+Departments/Support+Services/Tax+Commissioner/tax+sales", "TAX_DEED", "Lawrenceville"),
    ("GA", "DeKalb",   "https://www.dekalbcountyga.gov/tax-commissioner/tax-sale-information", "TAX_DEED", "Decatur"),

    # TENNESSEE
    ("TN", "Shelby",   "https://www.shelbycountytrustee.com/defaultProperties.aspx",          "TAX_DEED", "Memphis"),
    ("TN", "Davidson", "https://www.nashville.gov/departments/law/circuit-civil/tax-sales",   "TAX_DEED", "Nashville"),

    # NORTH CAROLINA — foreclosure by advertisement
    ("NC", "Mecklenburg", "https://www.mecknc.gov/TaxCollections/Pages/ForeclosureSales.aspx","FORECLOSURE","Charlotte"),
    ("NC", "Wake",        "https://www.wake.gov/departments-agencies/revenue/foreclosure-sales","FORECLOSURE","Raleigh"),
]

EXTRACT_PROMPT = """Extract upcoming real estate auction/sale listings from this HTML.

For EACH property return a JSON object with these fields:
  address      - full street address
  city         - city name
  state        - 2-letter state code
  county       - county name
  zip          - zip code if shown
  opening_bid  - minimum bid / starting bid as number (no $ or commas)
  auction_date - date of auction (string)
  parcel_id    - parcel/case/property ID if shown
  bedrooms     - number of bedrooms if shown
  sqft         - square footage if shown
  year_built   - year built if shown
  property_type - SFR / Condo / Multi / Land (guess from context)
  url          - direct link to listing if available
  sale_type    - TAX_DEED / FORECLOSURE / SHERIFF

Return ONLY a JSON array. If no properties found, return [].
Do not include any explanation or markdown."""


async def _llm_extract(html: str, county: str, state: str) -> list[dict]:
    """Send page HTML to LLM for structured extraction. Uses free providers first."""
    try:
        raw   = call_llm(
            "You extract structured real estate auction data from HTML. Return only valid JSON arrays.",
            f"{EXTRACT_PROMPT}\n\nCounty: {county}, {state}\n\nHTML:\n{html[:80_000]}",
            max_tokens=4096,
        )
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  [EXTRACT] {county},{state}: {e}")
        return []


def _normalize(item: dict, state: str, county: str, sale_type: str) -> dict:
    def num(v):
        if v is None:
            return None
        try:
            return float(str(v).replace('$','').replace(',','').strip())
        except Exception:
            return None

    return {
        "address":       item.get("address", "").strip(),
        "city":          item.get("city", ""),
        "state":         item.get("state") or state,
        "zip":           str(item.get("zip") or ""),
        "county":        item.get("county") or county,
        "source":        f"{sale_type}_{state}_{county.upper().replace(' ','_')}",
        "source_url":    item.get("url", ""),
        "auction_date":  str(item.get("auction_date") or ""),
        "listing_id":    str(item.get("parcel_id") or ""),
        "opening_bid":   num(item.get("opening_bid")),
        "bedrooms":      int(item.get("bedrooms") or 0) or None,
        "sqft":          int(item.get("sqft") or 0) or None,
        "year_built":    int(item.get("year_built") or 0) or None,
        "property_type": item.get("property_type") or "SFR",
        "condition":     "FAIR",
        "ai_status":     "PENDING",
        "status":        "NEW",
    }


async def scrape_county(page: Page, state: str, county: str,
                         url: str, sale_type: str) -> list[dict]:
    results = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)
        html    = await page.content()
        items   = await _llm_extract(html, county, state)
        results = [_normalize(i, state, county, sale_type) for i in items
                   if i.get("address")]
        print(f"  [{state}/{county}] {len(results)} properties from {url[:60]}")
    except Exception as e:
        print(f"  [{state}/{county}] ERROR: {e}")
    return results


def _save(properties: list[dict]) -> int:
    saved = 0
    for p in properties:
        addr = p.get("address", "").strip()
        if not addr or not p.get("opening_bid"):
            continue
        existing = _sb().table("auction_properties") \
            .select("id") \
            .eq("address", addr) \
            .eq("source", p["source"]) \
            .execute()
        if existing.data:
            continue
        try:
            _sb().table("auction_properties").insert(p).execute()
            saved += 1
        except Exception as e:
            print(f"  [SAVE] {addr}: {e}")
    return saved


async def run_county_scraper(states: list[str] = None) -> dict:
    sources = COUNTY_SOURCES
    if states:
        sources = [s for s in COUNTY_SOURCES if s[0] in states]

    print(f"[COUNTY] Scraping {len(sources)} county auction sources...")

    all_props: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx  = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda r: r.abort())

        for state, county, url, sale_type, note in sources:
            props = await scrape_county(page, state, county, url, sale_type)
            all_props.extend(props)
            await page.wait_for_timeout(2_000)

        await browser.close()

    saved = _save(all_props)
    print(f"\n[COUNTY] Done — {len(all_props)} found | {saved} new saved to Supabase")
    return {"total_found": len(all_props), "saved": saved}


def run_county_tax_sale_scraper(states: list[str] = None):
    asyncio.run(run_county_scraper(states))


if __name__ == "__main__":
    import sys
    states = sys.argv[1:] or None
    run_county_tax_sale_scraper(states)
