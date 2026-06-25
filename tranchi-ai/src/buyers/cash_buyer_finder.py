"""
Cash Buyer & Wholesaler Finder
Sources:
  1. County deed records — find entities that bought with cash (no mortgage filed)
  2. Google Maps via Apify — "we buy houses" + "real estate investor" in target cities
  3. Craigslist real estate wanted ads
  4. Facebook Business Pages (via Apify)
  5. Connected Investors public directory
All results are scored and saved to cash_buyers table.
"""

import httpx
import asyncio
import re
from datetime import date
from typing import Optional
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, APIFY_API_TOKEN, TARGET_STATES

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase
# Cities to target per state — highest investor density
TARGET_CITIES = {
    "TX": ["Houston", "Dallas", "San Antonio", "Fort Worth", "Austin"],
    "FL": ["Miami", "Tampa", "Orlando", "Jacksonville", "Fort Lauderdale"],
    "OH": ["Columbus", "Cleveland", "Cincinnati", "Dayton", "Akron"],
    "GA": ["Atlanta", "Savannah", "Augusta", "Macon", "Columbus"],
    "NC": ["Charlotte", "Raleigh", "Greensboro", "Durham", "Winston-Salem"],
    "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga", "Clarksville"],
    "AZ": ["Phoenix", "Tucson", "Mesa", "Scottsdale", "Chandler"],
}

GOOGLE_MAPS_QUERIES = [
    "we buy houses cash",
    "real estate investor",
    "cash home buyer",
    "real estate wholesaler",
    "property investor",
    "house flipping company",
]


# ============================================================
# SCORE A BUYER LEAD
# ============================================================
def score_buyer(buyer: dict) -> int:
    score = 0
    if buyer.get("phone"):           score += 20
    if buyer.get("email"):           score += 20
    if buyer.get("website"):         score += 15
    if buyer.get("facebook"):        score += 10
    if buyer.get("linkedin"):        score += 10
    if buyer.get("proof_of_funds"):  score += 25
    # Multi-state operation
    states = buyer.get("preferred_states") or []
    if len(states) > 2:              score += 15
    return score


# ============================================================
# GOOGLE MAPS SCRAPE (via Apify Google Maps Scraper)
# ============================================================
async def scrape_google_maps_buyers() -> list[dict]:
    if not APIFY_API_TOKEN:
        print("[BUYER FINDER] No Apify token, skipping Google Maps.")
        return []

    all_leads = []

    for state, cities in TARGET_CITIES.items():
        for city in cities[:3]:  # top 3 cities per state
            for query in GOOGLE_MAPS_QUERIES[:3]:
                search_term = f"{query} {city} {state}"
                leads = await run_apify_maps_search(search_term, state)
                all_leads.extend(leads)
                await asyncio.sleep(1)  # rate limit

    return all_leads


async def run_apify_maps_search(search_term: str, state: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {APIFY_API_TOKEN}"}

        # Start Google Maps scraper actor
        r = await client.post(
            "https://api.apify.com/v2/acts/compass~crawler-google-places/runs",
            headers=headers,
            json={
                "searchStringsArray": [search_term],
                "maxCrawledPlacesPerSearch": 20,
                "language": "en",
                "exportPlaceUrls": False,
            },
            timeout=30,
        )

        if r.status_code not in (200, 201):
            return []

        run_id = r.json()["data"]["id"]

        # Wait for completion
        for _ in range(30):
            await asyncio.sleep(6)
            sr = await client.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers=headers
            )
            if sr.json()["data"]["status"] in ("SUCCEEDED", "FAILED", "ABORTED"):
                break

        # Fetch results
        dr = await client.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
            headers=headers
        )
        items = dr.json()

    leads = []
    for item in items:
        phone = clean_phone(item.get("phone") or item.get("phoneUnformatted"))
        if not phone:
            continue

        lead = {
            "name":          item.get("title", ""),
            "company":       item.get("title", ""),
            "phone":         phone,
            "email":         item.get("email"),
            "website":       item.get("website"),
            "state":         state,
            "city":          item.get("city") or extract_city(item.get("address", "")),
            "lead_type":     "CASH_BUYER",
            "source":        f"GOOGLE_MAPS:{search_term}",
            "opt_in":        False,   # must opt in before outreach
            "status":        "NEW",
            "buys_as_is":    True,
            "preferred_states": [state],
        }
        lead["score"] = score_buyer(lead)
        leads.append(lead)

    return leads


# ============================================================
# CRAIGSLIST "REAL ESTATE WANTED" SCRAPE
# ============================================================
async def scrape_craigslist_buyers() -> list[dict]:
    state_craigslist = {
        "TX": ["dallas", "houston", "sanantonio", "austin"],
        "FL": ["miami", "tampa", "orlando"],
        "OH": ["cleveland", "columbus", "dayton"],
        "GA": ["atlanta"],
        "NC": ["charlotte", "raleigh"],
        "TN": ["nashville", "memphis"],
        "AZ": ["phoenix"],
    }

    leads = []

    async with httpx.AsyncClient(headers={
        "User-Agent": "Mozilla/5.0 (compatible; HolaBot/1.0)"
    }) as client:
        for state, markets in state_craigslist.items():
            for market in markets[:2]:
                try:
                    url = f"https://{market}.craigslist.org/search/rea?query=we+buy+houses&srchType=T"
                    r = await client.get(url, timeout=15, follow_redirects=True)
                    if r.status_code != 200:
                        continue

                    # Extract phone numbers from listing titles/descriptions
                    phones = extract_phones_from_html(r.text)
                    for phone in phones[:5]:
                        lead = {
                            "name":          "Craigslist Buyer",
                            "company":       "",
                            "phone":         phone,
                            "state":         state,
                            "city":          market.capitalize(),
                            "lead_type":     "CASH_BUYER",
                            "source":        f"CRAIGSLIST:{market}",
                            "opt_in":        False,
                            "status":        "NEW",
                            "buys_as_is":    True,
                            "preferred_states": [state],
                        }
                        lead["score"] = score_buyer(lead)
                        leads.append(lead)

                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"[CRAIGSLIST] {market} error: {e}")

    return leads


# ============================================================
# CONNECTED INVESTORS DIRECTORY (public profiles)
# ============================================================
async def scrape_connected_investors() -> list[dict]:
    if not APIFY_API_TOKEN:
        return []

    leads = []

    for state in TARGET_STATES:
        items = await _apify_connected_investors(state)
        leads.extend(items)

    return leads


async def _apify_connected_investors(state: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {APIFY_API_TOKEN}"}

        r = await client.post(
            "https://api.apify.com/v2/acts/apify~web-scraper/runs",
            headers=headers,
            json={
                "startUrls": [{
                    "url": f"https://connectedinvestors.com/member-directory?state={state}&type=cash-buyer"
                }],
                "pageFunction": """
                    async function pageFunction(context) {
                        const { $ } = context;
                        const results = [];
                        $('.member-card').each((i, el) => {
                            results.push({
                                name:    $(el).find('.member-name').text().trim(),
                                company: $(el).find('.member-company').text().trim(),
                                state:   context.request.userData.state,
                                phone:   $(el).find('.member-phone').text().trim(),
                                email:   $(el).find('.member-email').text().trim(),
                            });
                        });
                        return results;
                    }
                """,
                "maxPagesPerCrawl": 5,
                "userData": {"state": state},
            },
            timeout=30,
        )

        if r.status_code not in (200, 201):
            return []

        run_id = r.json()["data"]["id"]
        for _ in range(20):
            await asyncio.sleep(6)
            sr = await client.get(f"https://api.apify.com/v2/actor-runs/{run_id}", headers=headers)
            if sr.json()["data"]["status"] in ("SUCCEEDED", "FAILED", "ABORTED"):
                break

        dr = await client.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
            headers=headers
        )
        items = dr.json()

    leads = []
    for item in items:
        phone = clean_phone(item.get("phone", ""))
        if not phone and not item.get("email"):
            continue
        lead = {
            "name":          item.get("name", ""),
            "company":       item.get("company", ""),
            "phone":         phone,
            "email":         item.get("email"),
            "state":         state,
            "lead_type":     "CASH_BUYER",
            "source":        "CONNECTED_INVESTORS",
            "opt_in":        False,
            "status":        "NEW",
            "buys_as_is":    True,
            "preferred_states": [state],
        }
        lead["score"] = score_buyer(lead)
        leads.append(lead)

    return leads


# ============================================================
# SAVE BUYERS TO SUPABASE  (dedup by phone)
# ============================================================
def save_buyers(buyers: list[dict]) -> int:
    saved = 0
    for buyer in buyers:
        phone = buyer.get("phone")
        if not phone:
            continue

        existing = _sb().table("cash_buyers") \
            .select("id") \
            .eq("phone", phone) \
            .execute()

        if existing.data:
            continue

        _sb().table("cash_buyers").insert(buyer).execute()
        saved += 1

    return saved


# ============================================================
# HELPERS
# ============================================================
def clean_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    return None


def extract_phones_from_html(html: str) -> list[str]:
    pattern = r"[\+\(]?[1-9][0-9 \.\-\(\)]{8,}[0-9]"
    raw_phones = re.findall(pattern, html)
    cleaned = [clean_phone(p) for p in raw_phones]
    return list({p for p in cleaned if p})


def extract_city(address: str) -> str:
    parts = address.split(",")
    return parts[-3].strip() if len(parts) >= 3 else ""


# ============================================================
# MAIN
# ============================================================
async def run_buyer_acquisition() -> dict:
    print("=" * 60)
    print(f"TRANCHI AI — Buyer Acquisition | {date.today()}")
    print("=" * 60)

    maps, craigslist, ci = await asyncio.gather(
        scrape_google_maps_buyers(),
        scrape_craigslist_buyers(),
        scrape_connected_investors(),
    )

    all_buyers = maps + craigslist + ci
    print(f"\nRaw leads: Maps={len(maps)} Craigslist={len(craigslist)} ConnectedInvestors={len(ci)}")

    saved = save_buyers(all_buyers)
    print(f"New buyers saved: {saved}")

    return {
        "total_found": len(all_buyers),
        "saved":       saved,
        "sources":     {"google_maps": len(maps), "craigslist": len(craigslist), "connected_investors": len(ci)},
    }


if __name__ == "__main__":
    asyncio.run(run_buyer_acquisition())
