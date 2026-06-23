"""
National REIA Chapter scraper.

Strategy:
  1. Hit nationalreia.com/find-a-chapter → get every chapter URL per state
  2. For each chapter in TARGET_STATES → visit their website
  3. Look for /members, /roster, /investors, /directory pages
  4. Extract name, phone, email, company

REIA members are the highest-quality cash buyers: they paid to join,
they actively network, they close deals. Better than any scraped list.

Uses httpx (no Playwright needed for most REIA sites — they're simple HTML).
Falls back to Playwright for JS-heavy chapter sites.
"""

import asyncio
import re
import httpx
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PHONE_RE = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')
EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
URL_RE   = re.compile(r'https?://[^\s"\'<>]+')

# Known REIA chapters + their websites for our target states.
# This seed list is faster than scraping the National REIA index every run.
# National REIA index: https://nationalreia.com/find-a-chapter/
REIA_CHAPTERS = {
    "TX": [
        ("Houston REIA",            "https://www.houstonreia.com"),
        ("DFW Real Estate Investors","https://www.dfwreia.com"),
        ("Austin REIA",             "https://www.austinreia.com"),
        ("San Antonio REIA",        "https://www.sareia.com"),
        ("Lone Star REIA",          "https://www.lonestarreia.com"),
    ],
    "FL": [
        ("Central Florida REIA",    "https://www.centralfloridareia.com"),
        ("Tampa Bay REIA",          "https://www.tampabayreia.com"),
        ("SJREIA (Jacksonville)",   "https://www.sjreia.org"),
        ("South Florida REIA",      "https://www.southfloridareia.com"),
        ("Broward Palm Beach REIA", "https://www.bpreia.com"),
    ],
    "OH": [
        ("Cleveland REIA",          "https://www.clevelandreia.com"),
        ("Columbus REIA",           "https://www.columbusreia.com"),
        ("Dayton REIA",             "https://www.daytonreia.com"),
        ("Mid Ohio REIA",           "https://www.midohioreia.com"),
    ],
    "GA": [
        ("Atlanta REIA",            "https://www.atlantareia.com"),
        ("Georgia REIA",            "https://www.georgiareia.com"),
    ],
    "NC": [
        ("Carolinas REIA",          "https://www.carolinasreia.com"),
        ("Triangle REIA (Raleigh)", "https://www.trianglereia.com"),
        ("Charlotte REIA",          "https://www.charlottereia.com"),
    ],
    "TN": [
        ("Nashville REIA",          "https://www.nashvillereia.com"),
        ("Memphis Investors Group",  "https://www.memphisinvestors.com"),
        ("Knoxville REIA",          "https://www.knoxvillereia.com"),
    ],
    "AZ": [
        ("Arizona REIA",            "https://www.arizonareia.com"),
        ("Phoenix REIA",            "https://www.phoenixreia.com"),
        ("Tucson REIA",             "https://www.tucsonreia.com"),
    ],
}

# Sub-pages to try on each REIA site for member/contact lists
MEMBER_PATHS = [
    "/members", "/member-directory", "/investors", "/roster",
    "/directory", "/our-members", "/investor-directory",
    "/find-an-investor", "/member-list", "/contact",
    "/about/members", "/resources/members",
]


def _clean_phone(text: str) -> str | None:
    m = PHONE_RE.search(text)
    if m:
        d = re.sub(r'\D', '', m.group())
        return f"+1{d}" if len(d) == 10 else None
    return None


def _extract_contacts_from_html(html: str, source_name: str, state: str) -> list[dict]:
    """
    Naive but effective: find all phone + email pairs within 500 chars of each other.
    Grabs any name-like text before the contact block.
    """
    contacts = []
    emails = EMAIL_RE.findall(html)
    phones = PHONE_RE.findall(html)

    # Skip site's own meta emails (privacy@, info@, webmaster@, etc.)
    skip_prefixes = ("privacy", "webmaster", "noreply", "admin", "support",
                     "contact", "info", "hello", "team")
    emails = [e for e in emails if not any(e.lower().startswith(p) for p in skip_prefixes)]

    for email in emails[:40]:
        # Look for phone nearby in the raw HTML
        idx = html.find(email)
        nearby = html[max(0, idx-600):idx+600]
        phone = _clean_phone(nearby)

        # Try to find a name: <h3>, <strong>, or word before email domain
        name_m = re.search(
            r'<(?:h[2-4]|strong|b)[^>]*>([^<]{3,50})</(?:h[2-4]|strong|b)>',
            nearby, re.I
        )
        name = name_m.group(1).strip() if name_m else f"{source_name} Member"

        contacts.append({
            "name":  name,
            "email": email,
            "phone": phone,
            "state": state,
        })

    # If no emails found, try phones-only
    if not contacts:
        for phone_raw in phones[:20]:
            d = re.sub(r'\D', '', phone_raw)
            if len(d) != 10:
                continue
            idx     = html.find(phone_raw)
            nearby  = html[max(0, idx-300):idx+300]
            name_m  = re.search(
                r'<(?:h[2-4]|strong|b)[^>]*>([^<]{3,50})</(?:h[2-4]|strong|b)>',
                nearby, re.I
            )
            name = name_m.group(1).strip() if name_m else f"{source_name} Investor"
            contacts.append({
                "name":  name,
                "email": None,
                "phone": f"+1{d}",
                "state": state,
            })

    return contacts


async def _try_chapter(client: httpx.AsyncClient, chapter_name: str,
                        base_url: str, state: str) -> list[dict]:
    all_contacts: list[dict] = []
    found_path = None

    # Try member-directory sub-pages
    for path in MEMBER_PATHS:
        url = base_url.rstrip("/") + path
        try:
            r = await client.get(url, timeout=10, follow_redirects=True)
            if r.status_code == 200 and len(r.text) > 2_000:
                contacts = _extract_contacts_from_html(r.text, chapter_name, state)
                if contacts:
                    found_path = path
                    all_contacts.extend(contacts)
                    break
        except Exception:
            continue

    # Fallback: scrape the homepage itself
    if not all_contacts:
        try:
            r = await client.get(base_url, timeout=10, follow_redirects=True)
            if r.status_code == 200:
                contacts = _extract_contacts_from_html(r.text, chapter_name, state)
                all_contacts.extend(contacts)
        except Exception:
            pass

    if all_contacts:
        print(f"  [REIA] {chapter_name} ({state}){' → ' + found_path if found_path else ''}: "
              f"{len(all_contacts)} contacts")

    return all_contacts


async def run_reia_scraper(states: list[str] = None) -> int:
    states = states or TARGET_STATES
    new    = 0
    now    = datetime.now(timezone.utc).isoformat()

    async with httpx.AsyncClient(headers=HEADERS) as client:
        for state in states:
            chapters = REIA_CHAPTERS.get(state, [])
            if not chapters:
                continue

            for chapter_name, base_url in chapters:
                contacts = await _try_chapter(client, chapter_name, base_url, state)

                for c in contacts:
                    email = c.get("email")
                    phone = c.get("phone")
                    if not email and not phone:
                        continue

                    # Dedup by email or phone
                    if email and supabase.table("cash_buyers").select("id") \
                            .eq("email", email).execute().data:
                        continue
                    if phone and supabase.table("cash_buyers").select("id") \
                            .eq("phone", phone).execute().data:
                        continue

                    try:
                        supabase.table("cash_buyers").insert({
                            "name":             c["name"][:120],
                            "phone":            phone,
                            "email":            email,
                            "source":           "REIA",
                            "preferred_states": [state],
                            "opt_in":           True,
                            "opt_in_date":      now,
                            "notes":            f"{chapter_name} | {base_url}",
                        }).execute()
                        new += 1
                        print(f"    + {c['name']} | {email or phone}")
                    except Exception as e:
                        print(f"    [REIA] insert error: {e}")

                await asyncio.sleep(1.5)  # polite delay between chapters

    print(f"\n[REIA] Done — +{new} investor contacts from REIA chapter sites")
    return new


def run_reia_buyer_scraper():
    asyncio.run(run_reia_scraper())


if __name__ == "__main__":
    run_reia_buyer_scraper()
