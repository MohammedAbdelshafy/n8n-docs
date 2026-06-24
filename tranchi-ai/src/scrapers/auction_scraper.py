"""
Scrapes government auction sources for deeply discounted properties.
Sources: HUD Homes, Fannie Mae HomePath, Freddie Mac HomeSteps,
         USDA Rural Dev, Auction.com, County Tax Sales.
"""

import httpx
import asyncio
import json
from datetime import date, timedelta
from typing import Optional
from supabase import create_client
from config import (
    SUPABASE_URL, SUPABASE_KEY, APIFY_API_TOKEN,
    TARGET_STATES, AUCTION_SOURCES
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================
# HUD HOMES  (hudhomestore.gov has a JSON API)
# ============================================================
async def scrape_hud_homes(client: httpx.AsyncClient, states: list[str]) -> list[dict]:
    results = []
    for state in states:
        try:
            # HUD public search endpoint
            url = "https://www.hudhomestore.gov/HudHomeStore/SearchProperties.aspx"
            params = {
                "stateCode": state,
                "statusCode": "ACT",   # Active listings only
                "pageSize": 100,
                "page": 1,
            }
            r = await client.get(url, params=params, timeout=30)
            if r.status_code != 200:
                print(f"[HUD] {state}: HTTP {r.status_code}")
                continue

            # HUD returns HTML — use Apify actor for structured data
            properties = await scrape_via_apify(
                actor_id="apify/hud-homes-scraper",
                input_data={"state": state, "limit": 50},
                source_label="HUD"
            )
            results.extend(properties)
        except Exception as e:
            print(f"[HUD] {state} error: {e}")

    return results


# ============================================================
# FANNIE MAE HOMEPATH
# ============================================================
async def scrape_fannie_mae(client: httpx.AsyncClient, states: list[str]) -> list[dict]:
    results = []
    for state in states:
        try:
            properties = await scrape_via_apify(
                actor_id="apify/homepath-scraper",
                input_data={"state": state, "maxPrice": 150000, "limit": 50},
                source_label="FANNIE_MAE"
            )
            results.extend(properties)
        except Exception as e:
            print(f"[FANNIE_MAE] {state} error: {e}")
    return results


# ============================================================
# COUNTY TAX SALES (via Apify Google Maps scraper + direct portals)
# ============================================================
async def scrape_tax_sales(client: httpx.AsyncClient, states: list[str]) -> list[dict]:
    results = []

    # GovEase is the largest county tax sale platform
    govease_states = {
        "GA": "georgia", "FL": "florida", "OH": "ohio",
        "TX": "texas",   "NC": "north-carolina", "TN": "tennessee", "AZ": "arizona"
    }

    for state in states:
        slug = govease_states.get(state)
        if not slug:
            continue
        try:
            # Scrape upcoming tax auctions
            url = f"https://www.govease.com/auctions/search?state={slug}&status=upcoming"
            r = await client.get(url, timeout=30, follow_redirects=True)

            # Use Apify for structured extraction
            properties = await scrape_via_apify(
                actor_id="apify/website-content-crawler",
                input_data={
                    "startUrls": [{"url": url}],
                    "maxCrawlPages": 5,
                    "saveHtml": False,
                },
                source_label="TAX_SALE",
                post_process=True
            )
            results.extend(properties)
        except Exception as e:
            print(f"[TAX_SALE] {state} error: {e}")

    return results


# ============================================================
# AUCTION.COM (bank/government REO)
# ============================================================
async def scrape_auction_com(client: httpx.AsyncClient, states: list[str]) -> list[dict]:
    all_results = []
    state_list = ",".join(states)

    try:
        properties = await scrape_via_apify(
            actor_id="apify/auction-com-scraper",
            input_data={
                "states": states,
                "maxPrice": 150000,
                "propertyType": "Single Family",
                "limit": 100,
            },
            source_label="AUCTION_COM"
        )
        all_results.extend(properties)
    except Exception as e:
        print(f"[AUCTION_COM] error: {e}")

    return all_results


# ============================================================
# APIFY GATEWAY  (all structured scraping runs through here)
# ============================================================
async def scrape_via_apify(
    actor_id: str,
    input_data: dict,
    source_label: str,
    post_process: bool = False
) -> list[dict]:
    """Run an Apify actor and return normalized property dicts."""
    if not APIFY_API_TOKEN:
        print(f"[APIFY] No token set, skipping {actor_id}")
        return []

    async with httpx.AsyncClient() as client:
        # Start actor run
        run_url = f"https://api.apify.com/v2/acts/{actor_id}/runs"
        headers = {"Authorization": f"Bearer {APIFY_API_TOKEN}"}

        r = await client.post(run_url, json=input_data, headers=headers, timeout=30)
        if r.status_code not in (200, 201):
            print(f"[APIFY] Failed to start {actor_id}: {r.status_code}")
            return []

        run_id = r.json()["data"]["id"]

        # Poll until finished (max 5 minutes)
        for _ in range(60):
            await asyncio.sleep(5)
            status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
            sr = await client.get(status_url, headers=headers)
            run_status = sr.json()["data"]["status"]
            if run_status in ("SUCCEEDED", "FAILED", "ABORTED"):
                break

        if run_status != "SUCCEEDED":
            print(f"[APIFY] {actor_id} run {run_id} ended with {run_status}")
            return []

        # Fetch dataset
        dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
        dr = await client.get(dataset_url, headers=headers)
        items = dr.json()

    return [normalize_property(item, source_label) for item in items if is_valid_property(item)]


# ============================================================
# NORMALIZATION  — map any source format → our schema
# ============================================================
def normalize_property(raw: dict, source: str) -> dict:
    """Convert raw scrape output into auction_properties schema."""
    return {
        "address":    raw.get("address") or raw.get("propertyAddress") or raw.get("street"),
        "city":       raw.get("city"),
        "state":      raw.get("state") or raw.get("stateCode"),
        "zip":        str(raw.get("zip") or raw.get("zipCode") or ""),
        "county":     raw.get("county", ""),
        "source":     source,
        "source_url": raw.get("url") or raw.get("listingUrl"),
        "auction_date": raw.get("auctionDate") or raw.get("openDate"),
        "listing_id": str(raw.get("id") or raw.get("mlsId") or raw.get("caseNumber") or ""),
        "opening_bid": float(raw.get("openingBid") or raw.get("listPrice") or raw.get("startingBid") or 0),
        "bedrooms":   int(raw.get("beds") or raw.get("bedrooms") or 0),
        "bathrooms":  float(raw.get("baths") or raw.get("bathrooms") or 0),
        "sqft":       int(raw.get("sqft") or raw.get("squareFeet") or raw.get("livingArea") or 0),
        "year_built": int(raw.get("yearBuilt") or raw.get("year_built") or 0),
        "property_type": map_property_type(raw.get("propertyType") or raw.get("type")),
        "condition":  map_condition(raw.get("condition") or raw.get("propertyCondition")),
        "ai_status":  "PENDING",
        "status":     "NEW",
    }


def map_property_type(raw_type: Optional[str]) -> str:
    if not raw_type:
        return "SFR"
    t = raw_type.upper()
    if any(x in t for x in ["SINGLE", "SFR", "HOUSE"]):
        return "SFR"
    if any(x in t for x in ["MULTI", "DUPLEX", "TRIPLEX", "4PLEX"]):
        return "MF"
    if "CONDO" in t:
        return "CONDO"
    if "LAND" in t or "LOT" in t:
        return "LAND"
    return "SFR"


def map_condition(raw_cond: Optional[str]) -> str:
    if not raw_cond:
        return "FAIR"
    c = raw_cond.upper()
    if any(x in c for x in ["EXCEL", "MINT", "MOVE"]):
        return "EXCELLENT"
    if "GOOD" in c:
        return "GOOD"
    if any(x in c for x in ["POOR", "BAD", "SEVERE"]):
        return "POOR"
    if any(x in c for x in ["TEAR", "DEMO", "RAZE"]):
        return "TEARDOWN"
    return "FAIR"


def is_valid_property(raw: dict) -> bool:
    has_address = bool(raw.get("address") or raw.get("propertyAddress") or raw.get("street"))
    has_price   = bool(raw.get("openingBid") or raw.get("listPrice") or raw.get("startingBid"))
    return has_address and has_price


# ============================================================
# SAVE TO SUPABASE
# ============================================================
def save_properties(properties: list[dict]) -> int:
    if not properties:
        return 0

    saved = 0
    for prop in properties:
        # Deduplicate by address + source
        existing = supabase.table("auction_properties") \
            .select("id") \
            .eq("address", prop["address"]) \
            .eq("source", prop["source"]) \
            .execute()

        if existing.data:
            continue  # already in DB

        result = supabase.table("auction_properties").insert(prop).execute()
        if result.data:
            saved += 1

    return saved


# ============================================================
# MAIN ENTRY
# ============================================================
async def run_ingestion() -> dict:
    print("=" * 60)
    print(f"TRANCHI AI — Auction Ingestion | {date.today()}")
    print("=" * 60)

    async with httpx.AsyncClient(headers={
        "User-Agent": "Mozilla/5.0 (compatible; HolaBot/1.0)"
    }) as client:

        # Run all scrapers concurrently
        hud, fannie, tax, auc = await asyncio.gather(
            scrape_hud_homes(client, TARGET_STATES),
            scrape_fannie_mae(client, TARGET_STATES),
            scrape_tax_sales(client, TARGET_STATES),
            scrape_auction_com(client, TARGET_STATES),
        )

    all_props = hud + fannie + tax + auc
    print(f"\nRaw finds: HUD={len(hud)} FannieMae={len(fannie)} TaxSale={len(tax)} AuctionCom={len(auc)}")

    saved = save_properties(all_props)
    print(f"Saved to Supabase: {saved} new properties")

    return {
        "total_found": len(all_props),
        "saved": saved,
        "sources": {
            "HUD": len(hud),
            "FANNIE_MAE": len(fannie),
            "TAX_SALE": len(tax),
            "AUCTION_COM": len(auc),
        }
    }


if __name__ == "__main__":
    asyncio.run(run_ingestion())
