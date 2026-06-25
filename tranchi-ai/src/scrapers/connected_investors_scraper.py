"""
Connected Investors scraper (Playwright).

connectedinvestors.com is the largest real estate investor network.
Public pages (no login required):
  - /investment-properties?state=TX  → property listings from investors
    (the poster IS a cash buyer or wholesaler)
  - /find-an-investor?state=TX       → public investor profiles

Both pages show: name, company, phone (sometimes), states they buy in.

Investors who post on CI are actively doing deals right now.
"""

import asyncio
import re
from datetime import datetime, timezone
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
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

PHONE_RE = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')
EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

CI_BASE = "https://connectedinvestors.com"

SEARCH_URLS = [
    "/investment-properties?listing_type=wholesale&state={state}",
    "/investment-properties?listing_type=cash_buyer&state={state}",
    "/find-an-investor?state={state}",
]


def _clean_phone(raw: str) -> str | None:
    d = re.sub(r'\D', '', raw)
    if len(d) == 10:
        return f"+1{d}"
    if len(d) == 11 and d[0] == '1':
        return f"+{d}"
    return None


async def _scrape_page(page: Page, url: str, state: str) -> list[dict]:
    results = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        await page.wait_for_timeout(3_500)

        # Try structured card selectors first
        cards = await page.query_selector_all(
            '[class*="investor-card"], [class*="listing-card"], '
            '[class*="property-card"], [data-investor], article'
        )

        for card in cards[:30]:
            try:
                text  = (await card.inner_text()).strip()
                phone = None
                email = None
                name  = ""

                pm = PHONE_RE.search(text)
                if pm:
                    phone = _clean_phone(pm.group())

                em = EMAIL_RE.search(text)
                if em and "@connectedinvestors" not in em.group():
                    email = em.group()

                # Name: first <h2>, <h3>, <strong> or bold
                name_el = await card.query_selector(
                    'h2, h3, [class*="name"], [class*="Name"], strong'
                )
                if name_el:
                    name = (await name_el.inner_text()).strip()[:80]

                if not name and not phone and not email:
                    continue

                results.append({
                    "name":  name or f"CI Investor ({state})",
                    "phone": phone,
                    "email": email,
                    "state": state,
                    "text":  text[:200],
                })

            except Exception:
                continue

        # Fallback: full-page text parse if no cards found
        if not results:
            full = await page.inner_text("body")
            for match in PHONE_RE.finditer(full):
                phone = _clean_phone(match.group())
                if not phone:
                    continue
                nearby = full[max(0, match.start()-200):match.start()+200]
                em = EMAIL_RE.search(nearby)
                results.append({
                    "name":  f"CI Investor ({state})",
                    "phone": phone,
                    "email": em.group() if em else None,
                    "state": state,
                    "text":  nearby[:150],
                })

    except Exception as e:
        print(f"[CI] {url[:70]}: {e}")

    return results


async def run_connected_investors_scraper(states: list[str] = None) -> int:
    states = states or TARGET_STATES
    new    = 0
    now    = datetime.now(timezone.utc).isoformat()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context(user_agent=UA)
        page    = await ctx.new_page()

        for state in states:
            state_results: list[dict] = []

            for path_tmpl in SEARCH_URLS:
                path = path_tmpl.format(state=state)
                url  = CI_BASE + path
                print(f"[CI] {url}")
                hits = await _scrape_page(page, url, state)
                state_results.extend(hits)
                await page.wait_for_timeout(2_000)

            print(f"[CI] {state}: {len(state_results)} investor contacts found")

            for r in state_results:
                email = r.get("email")
                phone = r.get("phone")
                if not email and not phone:
                    continue

                # Dedup
                if email:
                    if _sb().table("cash_buyers").select("id").eq("email", email).execute().data:
                        continue
                if phone:
                    if _sb().table("cash_buyers").select("id").eq("phone", phone).execute().data:
                        continue

                try:
                    _sb().table("cash_buyers").insert({
                        "name":             r["name"],
                        "phone":            phone,
                        "email":            email,
                        "source":           "CONNECTED_INVESTORS",
                        "preferred_states": [state],
                        "opt_in":           True,
                        "opt_in_date":      now,
                        "notes":            f"CI | {r.get('text','')[:100]}",
                    }).execute()
                    new += 1
                    print(f"  + {r['name']} | {email or phone}")
                except Exception as e:
                    print(f"  [CI] insert error: {e}")

        await browser.close()

    print(f"\n[CI] Done — +{new} new cash buyer contacts from Connected Investors")
    return new


def run_ci_buyer_scraper():
    asyncio.run(run_connected_investors_scraper())


if __name__ == "__main__":
    run_ci_buyer_scraper()
