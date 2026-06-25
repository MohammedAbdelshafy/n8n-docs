"""
Free Google Maps buyer scraper using Playwright.
Replaces the $49/mo Apify dependency entirely.
Technique from omkarcloud/google-maps-scraper:
  - Searches Google Maps for investor keywords per city
  - Extracts 15+ data points per result
  - Deduplicates by phone number
  - Scores and saves to Supabase
"""

import asyncio
import json
import re
import os
from datetime import date
from typing import Optional
from playwright.async_api import async_playwright, Page
from supabase import create_client
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

QUERIES     = CONFIG["google_maps_queries"]
CITIES      = CONFIG["target_cities"]
PW_SETTINGS = CONFIG["playwright_settings"]


# ── Score a buyer lead ─────────────────────────────────────────
def score_lead(lead: dict) -> int:
    score = 0
    if lead.get("phone"):                    score += 20
    if lead.get("email"):                    score += 20
    if lead.get("website"):                  score += 15
    if lead.get("facebook"):                 score += 10
    if lead.get("linkedin"):                 score += 10
    if len(lead.get("preferred_states",[])) > 2: score += 15
    return score


# ── Extract data from a single Google Maps result card ────────
async def extract_place(page: Page) -> Optional[dict]:
    try:
        # Name
        name_el = await page.query_selector('h1.DUwDvf, h1[class*="fontHeadline"]')
        name    = (await name_el.inner_text()).strip() if name_el else ""

        # Phone
        phone_el  = await page.query_selector('[data-tooltip="Copy phone number"], [aria-label*="Phone"]')
        phone_raw = (await phone_el.get_attribute("aria-label") or "").replace("Phone: ", "") if phone_el else ""
        phone     = clean_phone(phone_raw)

        # Website
        web_el  = await page.query_selector('a[data-item-id="authority"]')
        website = await web_el.get_attribute("href") if web_el else None

        # Address
        addr_el = await page.query_selector('[data-item-id="address"]')
        address = (await addr_el.inner_text()).strip() if addr_el else ""

        # Rating / reviews
        rating_el  = await page.query_selector('.F7nice span[aria-hidden]')
        rating     = (await rating_el.inner_text()).strip() if rating_el else None

        # Category
        cat_el   = await page.query_selector('[jsaction*="category"] button')
        category = (await cat_el.inner_text()).strip() if cat_el else ""

        if not name:
            return None

        return {
            "name":     name,
            "company":  name,
            "phone":    phone,
            "website":  website,
            "address":  address,
            "rating":   rating,
            "category": category,
        }
    except Exception:
        return None


# ── Scrape one search query in one city ───────────────────────
async def scrape_maps_query(page: Page, query: str, city: str, state: str) -> list[dict]:
    search_term = f"{query} {city} {state}"
    url = f"https://www.google.com/maps/search/{search_term.replace(' ', '+')}"

    results = []
    seen    = set()

    try:
        await page.goto(url, timeout=PW_SETTINGS["timeout_ms"])
        await page.wait_for_selector('[role="feed"]', timeout=10000)

        # Scroll to load more results
        feed = await page.query_selector('[role="feed"]')
        for _ in range(4):
            await page.evaluate("(el) => el.scrollTop += 800", feed)
            await asyncio.sleep(1.5)

        # Get all result cards
        cards = await page.query_selector_all('[role="feed"] > div > div[jsaction]')

        for card in cards[:PW_SETTINGS["max_results_per_query"]]:
            try:
                await card.click()
                await asyncio.sleep(2)

                data = await extract_place(page)
                if not data:
                    continue

                phone = data.get("phone")
                dedup_key = phone or data.get("name", "")
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Enrich with search context
                data.update({
                    "state":            state,
                    "city":             city,
                    "lead_type":        "CASH_BUYER",
                    "source":           f"GOOGLE_MAPS:{query}",
                    "opt_in":           False,
                    "status":           "NEW",
                    "buys_as_is":       True,
                    "preferred_states": [state],
                })
                data["score"] = score_lead(data)
                results.append(data)

            except Exception:
                continue

    except Exception as e:
        print(f"  [MAPS] {search_term}: {e}")

    return results


# ── Save to Supabase, dedup by phone ──────────────────────────
def save_buyers(buyers: list[dict]) -> int:
    saved = 0
    for b in buyers:
        phone = b.get("phone")
        email = b.get("email")
        if not phone and not email:
            continue

        query = _sb().table("cash_buyers").select("id")
        if phone:
            query = query.eq("phone", phone)
        elif email:
            query = query.eq("email", email)

        if query.execute().data:
            continue

        _sb().table("cash_buyers").insert(b).execute()
        saved += 1

    return saved


# ── Main runner ───────────────────────────────────────────────
async def run_playwright_buyer_scraper(
    states: Optional[list[str]] = None,
    queries_per_city: int = 2,
    cities_per_state: int = 3,
) -> dict:
    states  = states or TARGET_STATES
    all_results = []

    print(f"[PLAYWRIGHT] Starting buyer scrape | {date.today()}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=PW_SETTINGS["headless"],
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport=PW_SETTINGS["viewport"],
            user_agent=PW_SETTINGS["user_agent"],
        )
        page = await context.new_page()

        # Block images/fonts to speed up scraping
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda r: r.abort())

        for state in states:
            cities  = (CITIES.get(state) or [])[:cities_per_state]
            queries = QUERIES[:queries_per_city]

            for city in cities:
                for query in queries:
                    print(f"  Searching: {query} — {city}, {state}")
                    results = await scrape_maps_query(page, query, city, state)
                    all_results.extend(results)
                    await asyncio.sleep(2)  # polite rate limit

        await browser.close()

    saved = save_buyers(all_results)

    print(f"[PLAYWRIGHT] Found: {len(all_results)} | Saved: {saved} new buyers")
    return {"total_found": len(all_results), "saved": saved}


# ── Helpers ───────────────────────────────────────────────────
def clean_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    return None


if __name__ == "__main__":
    asyncio.run(run_playwright_buyer_scraper(
        states=["TN", "GA"],
        queries_per_city=2,
        cities_per_state=2,
    ))
