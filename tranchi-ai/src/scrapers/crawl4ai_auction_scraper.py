"""
Smart auction/foreclosure scraper — Playwright + free LLM extraction.

Resilience features:
  - Config-driven: add sources by editing scraper_configs.json only.
  - LLM extraction: the page text is sent to a free LLM that returns
    structured JSON, so site redesigns don't break the scraper.
  - Realistic browser fingerprint (headers, locale, timezone).
  - Auto-scroll to trigger lazy-loaded listings.
  - Bot-wall detection (Cloudflare / captcha) so we log instead of saving junk.
  - Clean-text extraction via trafilatura to cut tokens and boost accuracy.
  - One automatic retry on timeout, with graceful per-source failure.
"""

import asyncio
import json
import os
from datetime import date
from typing import Optional
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

with open(os.path.join(os.path.dirname(__file__), "scraper_configs.json")) as f:
    CONFIG = json.load(f)

SOURCES     = CONFIG["auction_sources"]
STATE_SLUGS = CONFIG["state_slugs"]
PW          = CONFIG["playwright_settings"]

# Telltale strings that mean we hit a bot wall, not real content.
_BOT_WALL_MARKERS = [
    "just a moment", "checking your browser", "verify you are human",
    "captcha", "access denied", "request blocked", "enable javascript and cookies",
    "unusual traffic",
]


# ── Clean text extraction (reduces tokens, improves LLM accuracy) ──
def _clean_text(html: str) -> str:
    try:
        import trafilatura
        extracted = trafilatura.extract(
            html, include_links=True, include_tables=True, no_fallback=False
        )
        if extracted and len(extracted) > 200:
            return extracted
    except Exception:
        pass
    return html


# ── LLM extraction using free providers ───────────────────────
def llm_extract_properties(content: str, prompt: str, source_name: str) -> list[dict]:
    """Send page content to a free LLM, get back a structured property list."""
    from src.utils.free_llm import call_llm

    system = (
        "You are a precise real-estate data extraction engine. "
        "Extract structured property data from the page content. "
        "Return ONLY a valid JSON array — no markdown, no prose. "
        "If no properties are present, return []."
    )
    try:
        raw = call_llm(system, f"{prompt}\n\nPAGE CONTENT:\n{content[:60_000]}", max_tokens=4096)
        raw = raw.strip()
        # Strip accidental code fences
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  [CRAWL4AI] {source_name}: LLM extract failed: {e}")
        return []


# ── Auto-scroll to load lazy content ──────────────────────────
async def _auto_scroll(page, rounds: int = 6) -> None:
    try:
        for _ in range(rounds):
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await asyncio.sleep(1.2)
    except Exception:
        pass


# ── Scrape one source for one state ──────────────────────────
async def scrape_source(context, source: dict, state: str) -> list[dict]:
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

    for attempt in (1, 2):
        page = await context.new_page()
        try:
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,mp4,webp,ico}",
                lambda r: r.abort(),
            )
            await page.goto(url, timeout=PW["timeout_ms"], wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass

            if source.get("scroll"):
                await _auto_scroll(page)

            html = await page.content()

            # Bot-wall detection
            low = html.lower()
            if len(html) < 1500 or any(m in low for m in _BOT_WALL_MARKERS):
                if attempt == 1:
                    print(f"  [{name}] {state}: possible bot wall, retrying...")
                    await page.close()
                    await asyncio.sleep(3)
                    continue
                print(f"  [{name}] {state}: blocked or empty page — skipping")
                await page.close()
                return []

            content = _clean_text(html) if source.get("llm_extract") else html
            items   = llm_extract_properties(content, source.get("llm_prompt", ""), name)
            results = [normalize_auction(item, name, state) for item in items]

            await page.close()
            kept = [r for r in results if r.get("address")]
            if not kept:
                print(f"  [{name}] {state}: 0 properties parsed (page len={len(html)})")
            return kept

        except Exception as e:
            print(f"  [{name}] {state} attempt {attempt} error: {e}")
            try:
                await page.close()
            except Exception:
                pass
            if attempt == 1:
                await asyncio.sleep(3)
                continue
            return []

    return []


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

    def to_int(v):
        n = num(v)
        return int(n) if n else None

    bid = num(raw.get("opening_bid") or raw.get("list_price") or raw.get("startingBid")
              or raw.get("price") or raw.get("current_bid"))

    return {
        "address":       raw.get("address") or raw.get("street"),
        "city":          raw.get("city"),
        "state":         raw.get("state") or state,
        "zip":           str(raw.get("zip") or raw.get("zipCode") or raw.get("zip_code") or ""),
        "county":        raw.get("county", ""),
        "source":        source,
        "source_url":    raw.get("url") or raw.get("listingUrl") or raw.get("link"),
        "auction_date":  raw.get("auction_date") or raw.get("auctionDate"),
        "listing_id":    str(raw.get("parcel_id") or raw.get("case_number") or raw.get("id") or ""),
        "opening_bid":   bid,
        "estimated_arv": num(raw.get("estimated_value") or raw.get("zestimate")),
        "bedrooms":      to_int(raw.get("bedrooms") or raw.get("beds")),
        "bathrooms":     num(raw.get("bathrooms") or raw.get("baths")),
        "sqft":          to_int(raw.get("sqft") or raw.get("squareFeet")),
        "year_built":    to_int(raw.get("year_built") or raw.get("yearBuilt")),
        "property_type": "SFR",
        "condition":     "FAIR",
        "ai_status":     "PENDING",
        "status":        "NEW",
    }


# ── Dedup and save to Supabase ────────────────────────────────
def save_properties(properties: list[dict]) -> int:
    saved = 0
    for prop in properties:
        addr   = prop.get("address")
        source = prop.get("source")
        if not addr:
            continue

        existing = _sb().table("auction_properties") \
            .select("id") \
            .eq("address", addr) \
            .eq("source", source) \
            .execute()

        if existing.data:
            continue

        try:
            _sb().table("auction_properties").insert(prop).execute()
            saved += 1
        except Exception as e:
            print(f"  [CRAWL4AI] save error for {addr}: {e}")

    return saved


# ── Main runner ───────────────────────────────────────────────
async def run_crawl4ai_scraper(
    states: Optional[list[str]] = None,
    source_names: Optional[list[str]] = None,
) -> dict:
    from playwright.async_api import async_playwright

    states  = states or TARGET_STATES
    sources = [s for s in SOURCES
               if not source_names or s["name"] in source_names]

    print(f"[CRAWL4AI] Starting auction scrape | {date.today()}")
    print(f"  Sources: {[s['name'] for s in sources]}")
    print(f"  States:  {states}")

    all_props = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=PW["user_agent"],
            viewport=PW.get("viewport", {"width": 1366, "height": 900}),
            locale=PW.get("locale", "en-US"),
            timezone_id=PW.get("timezone", "America/Chicago"),
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        # Light stealth: hide webdriver flag
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        for source in sources:
            for state in states:
                try:
                    props = await scrape_source(context, source, state)
                    all_props.extend(props)
                except Exception as e:
                    print(f"  [{source['name']}] {state} fatal: {e}")
                await asyncio.sleep(source.get("rate_limit_seconds", 3))

        await browser.close()

    saved = save_properties(all_props)
    print(f"[CRAWL4AI] Found: {len(all_props)} | Saved: {saved} new properties")

    return {"total_found": len(all_props), "saved": saved}


if __name__ == "__main__":
    asyncio.run(run_crawl4ai_scraper(
        states=["TN", "FL"],
        source_names=["AUCTION_COM", "BID4ASSETS"],
    ))
