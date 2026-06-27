"""
Cash-Buyer Finder — YellowPages directory + AI extraction.  ZERO setup.

No API key, no card, no signup. YellowPages publicly lists "we buy houses"
companies and real-estate investors WITH phone numbers, and it's a directory
(far less bot-protected than Google/Zillow).

Flow:
  1. Playwright loads the YP search page for each query/city.
  2. Groq (free, already configured) extracts the business listings from the
     page text — robust to layout changes, no brittle CSS selectors.
  3. Each business website is fetched to pull EMAIL + FACEBOOK page.
  4. Keeps only buyers with contact info; FB filter optional (REQUIRE_FACEBOOK).
  5. Saves to cash_buyers (opt_in=FALSE — public business contacts to call/mail).

Env:
  REQUIRE_FACEBOOK  — "1" (default) keeps only buyers with a Facebook page.
"""

import os
import re
import json
import asyncio
from datetime import date
from typing import Optional

import httpx
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

_CFG = json.load(open(os.path.join(os.path.dirname(__file__), "scraper_configs.json")))
QUERIES = _CFG["google_maps_queries"]
CITIES  = _CFG["target_cities"]
UA = _CFG["playwright_settings"]["user_agent"]

REQUIRE_FACEBOOK = os.getenv("REQUIRE_FACEBOOK", "1") == "1"

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_FB_RE    = re.compile(r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9.\-/_]+", re.I)


# ── Pull email + Facebook from a business website ─────────────────────
def _enrich_from_site(url: str) -> tuple[Optional[str], Optional[str]]:
    if not url:
        return None, None
    try:
        r = httpx.get(url, timeout=12, follow_redirects=True,
                      headers={"User-Agent": UA})
        html = r.text
        email = None
        m = _EMAIL_RE.search(html)
        if m and not m.group(0).lower().endswith((".png", ".jpg", ".gif", ".webp")):
            email = m.group(0).lower()
        fb = None
        fm = _FB_RE.search(html)
        if fm:
            cand = fm.group(0).split("?")[0].rstrip("/")
            if not any(x in cand.lower() for x in ["sharer", "plugins", "/tr", "dialog", "/sharer"]):
                fb = cand
        return email, fb
    except Exception:
        return None, None


# ── Groq extraction of YP business listings ───────────────────────────
import time as _time

def _extract_listings(page_text: str, city: str, state: str) -> list[dict]:
    from src.utils.free_llm import call_llm
    system = (
        "You extract business listings from a YellowPages results page. "
        "Return ONLY a JSON array. Each item: {name, phone, website, address}. "
        "Only real-estate investor / 'we buy houses' / cash-buyer businesses. "
        "If none, return []."
    )
    _time.sleep(3)  # throttle so we never trip Groq's per-minute rate limit
    try:
        raw = call_llm(system, f"City: {city}, {state}.\n\nPAGE:\n{page_text[:14000]}",
                       max_tokens=2000).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"  [YP] {city} extract failed: {e}")
        return []


def _clean_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    d = re.sub(r"\D", "", raw)
    if len(d) == 10:
        return f"+1{d}"
    if len(d) == 11 and d[0] == "1":
        return f"+{d}"
    return f"+{d}" if d else None


def _score(b: dict) -> int:
    return (25 if b.get("phone") else 0) + (25 if b.get("email") else 0) \
         + (15 if b.get("website") else 0) + (20 if b.get("facebook") else 0)


# ── Scrape one query in one city ──────────────────────────────────────
async def _scrape_city(context, query: str, city: str, state: str) -> list[dict]:
    from urllib.parse import quote_plus
    url = (f"https://www.yellowpages.com/search?search_terms={quote_plus(query)}"
           f"&geo_location_terms={quote_plus(city + ', ' + state)}")
    page = await context.new_page()
    out = []
    try:
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ico,mp4}", lambda r: r.abort())
        await page.goto(url, timeout=35000, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        text = await page.inner_text("body")
        low = text.lower()
        if any(m in low for m in ["captcha", "access denied", "are you a human", "request blocked"]):
            print(f"  [YP] {city}: blocked — skipping")
            return []
        listings = _extract_listings(text, city, state)
        for b in listings:
            website = b.get("website")
            email, facebook = _enrich_from_site(website) if website else (None, None)
            out.append({
                "name": b.get("name"), "company": b.get("name"),
                "phone": _clean_phone(b.get("phone")), "email": email,
                "website": website, "facebook": facebook,
                "address": b.get("address"), "city": city, "state": state,
                "lead_type": "CASH_BUYER", "source": f"YELLOWPAGES:{query}",
                "opt_in": False, "status": "NEW", "buys_as_is": True,
                "preferred_states": [state],
            })
    except Exception as e:
        print(f"  [YP] {city} '{query}' error: {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return out


# ── Save, dedup ───────────────────────────────────────────────────────
def save_buyers(buyers: list[dict]) -> int:
    saved = 0
    for b in buyers:
        if not b.get("phone") and not b.get("email"):
            continue
        if REQUIRE_FACEBOOK and not b.get("facebook"):
            continue
        b["score"] = _score(b)
        q = _sb().table("cash_buyers").select("id")
        q = q.eq("phone", b["phone"]) if b.get("phone") else q.eq("email", b["email"])
        if q.execute().data:
            continue
        try:
            _sb().table("cash_buyers").insert(b).execute()
            saved += 1
        except Exception as e:
            print(f"  [YP] save error ({b.get('name')}): {e}")
    return saved


# ── Main runner ───────────────────────────────────────────────────────
async def run_yellowpages_buyer_scraper(
    states: Optional[list[str]] = None,
    queries_per_city: int = 1,
    cities_per_state: int = 2,
) -> dict:
    from playwright.async_api import async_playwright
    states = states or TARGET_STATES
    print(f"[YP] Cash-buyer search via YellowPages | {date.today()} | require_fb={REQUIRE_FACEBOOK}")

    all_buyers = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=UA, locale="en-US")
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        for state in states:
            for city in (CITIES.get(state) or [])[:cities_per_state]:
                for query in QUERIES[:queries_per_city]:
                    print(f"  Searching: {query} — {city}, {state}")
                    all_buyers.extend(await _scrape_city(context, query, city, state))
                    await asyncio.sleep(1.5)
        await browser.close()

    fb = sum(1 for b in all_buyers if b.get("facebook"))
    contact = sum(1 for b in all_buyers if b.get("phone") or b.get("email"))
    saved = save_buyers(all_buyers)
    print(f"\n[YP] Found: {len(all_buyers)} | with contact: {contact} | "
          f"Facebook-verified: {fb} | saved: {saved}")
    return {"total_found": len(all_buyers), "saved": saved, "facebook_verified": fb}


if __name__ == "__main__":
    asyncio.run(run_yellowpages_buyer_scraper(states=["TX"], cities_per_state=2, queries_per_city=2))
