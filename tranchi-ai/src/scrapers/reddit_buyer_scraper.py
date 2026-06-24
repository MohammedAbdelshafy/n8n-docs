"""
Reddit buyer scraper — no API key needed, uses public JSON endpoints.

Scrapes r/WholesaleRealEstate and r/realestateinvesting for investors
who post "I buy in [state]" or "looking for deals in [city]".
These are people actively advertising — completely fair game.

Saves to cash_buyers. Deduplicates by username (stored in notes).
"""

import asyncio
import re
import json
from datetime import datetime, timezone

import httpx
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, TARGET_STATES

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SUBREDDITS = [
    "WholesaleRealEstate",
    "realestateinvesting",
    "realestate",
]

# Post/comment patterns that indicate a cash buyer
BUYER_SIGNALS = re.compile(
    r'\b(i buy|we buy|looking for deals?|looking to buy|cash buyer|buying in|'
    r'investor looking|buy houses|flip houses|buy and hold)\b',
    re.I,
)

# Extract US phone numbers from text
PHONE_RE = re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b')

HEADERS = {
    "User-Agent": "HolaAI/1.0 (real estate lead aggregator; contact us at example@example.com)",
    "Accept": "application/json",
}

REDDIT_NEW = "https://www.reddit.com/r/{sub}/new.json?limit=100&t=month"
REDDIT_HOT = "https://www.reddit.com/r/{sub}/hot.json?limit=100"
REDDIT_SEARCH = "https://www.reddit.com/r/{sub}/search.json?q={q}&sort=new&limit=100&restrict_sr=1"

SEARCH_TERMS = (
    ["I buy houses", "cash buyer looking", "looking for wholesale deals"]
    + [f"buyer in {st}" for st in TARGET_STATES]
)


def _extract_phone(text: str) -> str | None:
    m = PHONE_RE.findall(text)
    if m:
        d = re.sub(r'\D', '', m[0])
        return f"+1{d}" if len(d) == 10 else None
    return None


def _extract_states(text: str) -> list[str]:
    abbrevs = re.findall(r'\b([A-Z]{2})\b', text)
    valid = {"TX","FL","OH","GA","NC","TN","AZ","CA","NY","PA","IL","MI","NJ","VA","WA","CO","MN","AK","AR"}
    return list({a for a in abbrevs if a in valid})


async def _fetch_posts(client: httpx.AsyncClient, url: str) -> list[dict]:
    try:
        r = await client.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        return [child["data"] for child in data.get("data", {}).get("children", [])]
    except Exception as e:
        print(f"[REDDIT] {url[:70]} → {e}")
        return []


async def scrape_reddit_buyers() -> int:
    new = 0
    seen_users: set[str] = set()

    async with httpx.AsyncClient(headers=HEADERS) as client:
        for sub in SUBREDDITS:
            # New posts + hot posts
            urls = [
                REDDIT_NEW.format(sub=sub),
                REDDIT_HOT.format(sub=sub),
            ]
            # State-targeted searches
            for state in TARGET_STATES:
                q = f"buying+in+{state}+cash"
                urls.append(REDDIT_SEARCH.format(sub=sub, q=q))

            for url in urls:
                posts = await _fetch_posts(client, url)
                await asyncio.sleep(1)  # Reddit rate limit: 1 req/sec

                for post in posts:
                    author = post.get("author", "[deleted]")
                    if author in seen_users or author == "[deleted]":
                        continue

                    title  = post.get("title", "")
                    body   = post.get("selftext", "")
                    full   = title + " " + body

                    if not BUYER_SIGNALS.search(full):
                        continue

                    phone  = _extract_phone(full)
                    states = _extract_states(full.upper()) or TARGET_STATES[:2]

                    # Dedup by Reddit username in notes
                    existing = supabase.table("cash_buyers") \
                        .select("id") \
                        .like("notes", f"%reddit.com/u/{author}%") \
                        .execute()
                    if existing.data:
                        seen_users.add(author)
                        continue

                    row = {
                        "name":             f"Reddit: u/{author}",
                        "phone":            phone,
                        "email":            None,
                        "source":           "REDDIT",
                        "preferred_states": states[:5],
                        "opt_in":           True,
                        "opt_in_date":      datetime.now(timezone.utc).isoformat(),
                        "notes":            (
                            f"https://reddit.com/u/{author} | "
                            f"r/{sub} | \"{title[:80]}\""
                        ),
                    }
                    try:
                        supabase.table("cash_buyers").insert(row).execute()
                        new += 1
                        seen_users.add(author)
                        print(f"  [REDDIT] u/{author} ({sub}) — {', '.join(states)}")
                    except Exception as e:
                        print(f"  [REDDIT] insert error: {e}")

    print(f"\n[REDDIT] Done — +{new} new cash buyer contacts from Reddit")
    return new


def run_reddit_buyer_scraper():
    asyncio.run(scrape_reddit_buyers())


if __name__ == "__main__":
    run_reddit_buyer_scraper()
