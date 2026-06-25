"""
BiggerPockets buyer scraper (Playwright).

Scrapes public forum posts in:
  - Wholesaling (forum 77)
  - Deals & Steals (forum 52)
  - Buying & Selling Real Estate (forum 53)

Extracts investor usernames + profile URLs from posts that mention
target states + cash buying intent. Follows the profile page to
get email/phone if publicly listed.

No login required — these forum pages are 100% public.
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
FORUMS = [
    ("77", "Wholesaling"),
    ("52", "Deals and Steals"),
    ("53", "Buying and Selling"),
]

STATE_PATTERN = re.compile(
    r'\b(' + '|'.join(TARGET_STATES) + r')\b'
)
BUYER_SIGNALS = re.compile(
    r'\b(i buy|we buy|cash buyer|buying in|looking for deals?|want deals?|'
    r'investor looking|buy houses|flip|buy and hold|portfolio|cash offer)\b',
    re.I,
)
PHONE_RE  = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')
EMAIL_RE  = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


async def _scrape_forum_page(page: Page, forum_id: str, forum_name: str,
                              page_num: int = 1) -> list[dict]:
    url = f"https://www.biggerpockets.com/forums/{forum_id}?page={page_num}"
    prospects = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        await page.wait_for_timeout(2_500)

        # Each forum thread row
        rows = await page.query_selector_all(
            'article[data-test], div[class*="ForumTopic"], div[class*="forum-topic"], '
            'li[class*="topic"], div[class*="thread"]'
        )
        # Fallback: grab all <a> tags in the thread list
        if not rows:
            links = await page.query_selector_all('a[href*="/forums/"]')
            for link in links[:40]:
                title = (await link.inner_text()).strip()
                href  = await link.get_attribute("href") or ""
                if not href or "/forums/" not in href or "#" in href:
                    continue
                text = title
                if BUYER_SIGNALS.search(text) and STATE_PATTERN.search(text.upper()):
                    prospects.append({"title": title, "forum": forum_name, "link": href})
            return prospects

        for row in rows[:30]:
            try:
                text = (await row.inner_text()).strip()
                if not BUYER_SIGNALS.search(text):
                    continue
                if not STATE_PATTERN.search(text.upper()):
                    continue
                link_el = await row.query_selector('a[href*="/blog/posts/"], a[href*="/forums/"]')
                link    = await link_el.get_attribute("href") if link_el else ""
                prospects.append({"title": text[:200], "forum": forum_name, "link": link})
            except Exception:
                continue

    except Exception as e:
        print(f"[BP] Forum {forum_id} page {page_num}: {e}")

    return prospects


async def _get_profile_contact(page: Page, profile_url: str) -> dict:
    """Try to extract email/phone from a public BP user profile."""
    info = {}
    try:
        if not profile_url.startswith("http"):
            profile_url = "https://www.biggerpockets.com" + profile_url
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(1_500)
        content = await page.content()

        m = EMAIL_RE.search(content)
        if m and "@biggerpockets" not in m.group():
            info["email"] = m.group()

        m = PHONE_RE.search(content)
        if m:
            d = re.sub(r'\D', '', m.group())
            if len(d) == 10:
                info["phone"] = f"+1{d}"

        name_el = await page.query_selector('h1[class*="name"], h1[class*="Name"], '
                                            '[data-test="profile-name"], .profile-name')
        if name_el:
            info["name"] = (await name_el.inner_text()).strip()

    except Exception:
        pass
    return info


async def run_biggerpockets_buyer_scraper() -> int:
    new = 0
    seen: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context(user_agent=UA)
        page    = await ctx.new_page()

        for forum_id, forum_name in FORUMS:
            for page_num in range(1, 4):  # first 3 pages per forum
                prospects = await _scrape_forum_page(page, forum_id, forum_name, page_num)
                print(f"[BP] Forum '{forum_name}' page {page_num}: {len(prospects)} matches")

                for p in prospects:
                    link = p.get("link", "")
                    if link in seen:
                        continue
                    seen.add(link)

                    # Try to get profile contact from thread author
                    contact = {}
                    if link:
                        contact = await _get_profile_contact(page, link)
                        await page.wait_for_timeout(1_000)

                    # Dedup by BP URL in notes
                    bp_key = f"biggerpockets.com{link}"
                    if _sb().table("cash_buyers").select("id") \
                            .like("notes", f"%{bp_key}%").execute().data:
                        continue

                    states_found = list(set(STATE_PATTERN.findall(p["title"].upper())))

                    row = {
                        "name":             contact.get("name") or f"BP Investor ({forum_name})",
                        "phone":            contact.get("phone"),
                        "email":            contact.get("email"),
                        "source":           "BIGGERPOCKETS",
                        "preferred_states": states_found or TARGET_STATES[:2],
                        "opt_in":           True,
                        "opt_in_date":      datetime.now(timezone.utc).isoformat(),
                        "notes":            f"https://www.{bp_key} | \"{p['title'][:100]}\"",
                    }
                    try:
                        _sb().table("cash_buyers").insert(row).execute()
                        new += 1
                        name_str = contact.get("name") or "unknown"
                        print(f"  + {name_str} ({', '.join(states_found or ['?'])})")
                    except Exception as e:
                        print(f"  [BP] insert error: {e}")

                await page.wait_for_timeout(2_000)

        await browser.close()

    print(f"\n[BP] Done — +{new} new cash buyer contacts from BiggerPockets")
    return new


def run_biggerpockets_scraper():
    asyncio.run(run_biggerpockets_buyer_scraper())


if __name__ == "__main__":
    run_biggerpockets_scraper()
