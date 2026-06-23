"""
Smart auction site scraper using Crawl4AI + Claude for extraction.
Technique from kaymen99/ai-web-scraper:
  - Config-driven: add new sources by editing scraper_configs.json only
  - LLM extraction: Claude reads the HTML and returns structured JSON
  - Works on any auction portal regardless of HTML structure changes
  - Falls back to CSS selectors for known stable sites
"""

import asyncio
import json
import os
from datetime import date
from typing import Optional
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

with open(os.path.join(os.path.dirname(__file__), "scraper_configs.json")) as f:
    CONFIG = json.load(f)

SOURCES     = CONFIG["auction_sources"]
STATE_SLUGS = CONFIG["state_slugs"]


# ── LLM extraction using Claude ───────────────────────────────
def llm_extract_properties(html: str, prompt: str, source_name: str) -> list[dict]:
    """Send raw HTML to LLM, get back structured property list. Uses free providers first."""
    from src.utils.free_llm import call_llm

    system = (
        "You are a data extraction assistant. Extract structured data from HTML. "
        "Return ONLY a valid JSON array. No markdown, no explanation. "
        "If no properties found, return an empty array []."
    )
    try:
        raw   = call_llm(system, f"{prompt}\n\nHTML:\n{html[:80_000]}", max_tokens=4096)
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  [CRAWL4AI] {source_name}: {e}")
        return []


# ── CSS-based extraction for structured sites ─────────────────
async def css_extract(page, source_config: dict) -> list[dict]:
    from playwright.async_api import Page
    fields  = source_config.get("fields", {})
    results = []

    cards = await page.query_selector_all(source_config["property_selector"])
    for card in cards:
        item = {}
        for key, selector in fields.items():
            el = await card.query_selector(selector)
            if el:
                item[key] = (await el.inner_text()).strip()
        if item.get("address"):
            results.append(item)

    return results


# ── Scrape one source for one state ──────────────────────────
async def scrape_source(source: dict, state: str) -> list[dict]:
    from playwright.async_api import async_playwright
    import asyncio

    name     = source["name"]
    base_url = source["url"]
    slug     = STATE_SLUGS.get(state, state.lower())

    url = base_url.replace("{state}", state).replace("{state_slug}", slug)
    if source.get("params"):
        params = {k: v.replace("{state}", state).replace("{state_slug}", slug)
                  for k, v in source["params"].items()}
        query  = "&".join(f"{k}={v}" for k, v in params.items())
        url    = f"{url}?{query}" if "?" not in url else f"{url}&{query}"

    print(f"  [{name}] {state}: {url}")

    results = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                user_agent=CONFIG["playwright_settings"]["user_agent"]
            )
            page = await context.new_page()
            await page.route("**/*.{png,jpg,jpeg,gif,svg,woff}", lambda r: r.abort())

            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(3)  # let JS render

            if source.get("llm_extract"):
                html    = await page.content()
                items   = llm_extract_properties(html, source["llm_prompt"], name)
                results = [normalize_auction(item, name, state) for item in items]
            else:
                items   = await css_extract(page, source)
                results = [normalize_auction(item, name, state) for item in items]

            await browser.close()

    except Exception as e:
        print(f"  [{name}] {state} error: {e}")

    return [r for r in results if r.get("address") and r.get("opening_bid")]


# ── Normalize any source format to our schema ─────────────────
def normalize_auction(raw: dict, source: str, state: str) -> dict:
    def num(v) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        cleaned = str(v).replace("$", "").replace(",", "").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    return {
        "address":      raw.get("address") or raw.get("street"),
        "city":         raw.get("city"),
        "state":        raw.get("state") or state,
        "zip":          str(raw.get("zip") or raw.get("zipCode") or ""),
        "county":       raw.get("county", ""),
        "source":       source,
        "source_url":   raw.get("url") or raw.get("listingUrl"),
        "auction_date": raw.get("auction_date") or raw.get("auctionDate"),
        "listing_id":   str(raw.get("parcel_id") or raw.get("id") or ""),
        "opening_bid":  num(raw.get("opening_bid") or raw.get("list_price") or raw.get("startingBid")),
        "bedrooms":     int(raw.get("bedrooms") or raw.get("beds") or 0) or None,
        "bathrooms":    float(raw.get("bathrooms") or raw.get("baths") or 0) or None,
        "sqft":         int(raw.get("sqft") or raw.get("squareFeet") or 0) or None,
        "year_built":   int(raw.get("year_built") or raw.get("yearBuilt") or 0) or None,
        "property_type": "SFR",
        "condition":    "FAIR",
        "ai_status":    "PENDING",
        "status":       "NEW",
    }


# ── Dedup and save to Supabase ────────────────────────────────
def save_properties(properties: list[dict]) -> int:
    saved = 0
    for prop in properties:
        addr   = prop.get("address")
        source = prop.get("source")
        if not addr:
            continue

        existing = supabase.table("auction_properties") \
            .select("id") \
            .eq("address", addr) \
            .eq("source", source) \
            .execute()

        if existing.data:
            continue

        supabase.table("auction_properties").insert(prop).execute()
        saved += 1

    return saved


# ── Main runner ───────────────────────────────────────────────
async def run_crawl4ai_scraper(
    states: Optional[list[str]] = None,
    source_names: Optional[list[str]] = None,
) -> dict:
    states  = states or TARGET_STATES
    sources = [s for s in SOURCES
               if not source_names or s["name"] in source_names]

    print(f"[CRAWL4AI] Starting auction scrape | {date.today()}")
    print(f"  Sources: {[s['name'] for s in sources]}")
    print(f"  States:  {states}")

    all_props = []

    for source in sources:
        for state in states:
            props = await scrape_source(source, state)
            all_props.extend(props)
            await asyncio.sleep(source.get("rate_limit_seconds", 2))

    saved = save_properties(all_props)
    print(f"[CRAWL4AI] Found: {len(all_props)} | Saved: {saved} new properties")

    return {"total_found": len(all_props), "saved": saved}


if __name__ == "__main__":
    asyncio.run(run_crawl4ai_scraper(
        states=["TN"],
        source_names=["GOVEASE_TAX_SALE", "BID4ASSETS"]
    ))
