"""
Cash-Buyer Finder — Google Places API (official, not scraping).

Why this works when the Playwright Google-Maps scraper returns 0:
  Maps blocks headless browsers. The Places API is Google's *front door* —
  reliable, legal, and free within the $200/month credit (thousands of lookups).

What it does:
  1. Text Search for investor queries ("we buy houses", "cash home buyer", ...)
     across each target city.
  2. Place Details → phone, website, address for each result.
  3. Fetches each website to extract EMAIL + FACEBOOK page (legitimacy filter).
  4. Keeps only buyers with real contact info; flags Facebook-verified ones.
  5. Saves to cash_buyers (opt_in=FALSE — these are public business contacts you
     may call/mail; they opt in via the funnel before automated email blasts).

Setup (free):
  console.cloud.google.com → new project → enable "Places API"
  → Credentials → API key → set GOOGLE_MAPS_API_KEY secret.
  Stays inside the free $200/mo credit.

Env:
  GOOGLE_MAPS_API_KEY   — required
  REQUIRE_FACEBOOK      — "1" (default) keeps only buyers with a Facebook page
"""

import os
import re
import time
import httpx
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


import json as _json
_CFG_PATH = os.path.join(os.path.dirname(__file__), "scraper_configs.json")
with open(_CFG_PATH) as f:
    _CFG = _json.load(f)

QUERIES = _CFG["google_maps_queries"]
CITIES  = _CFG["target_cities"]

API_KEY          = os.getenv("GOOGLE_MAPS_API_KEY", "")
REQUIRE_FACEBOOK = os.getenv("REQUIRE_FACEBOOK", "1") == "1"

TEXT_SEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS     = "https://maps.googleapis.com/maps/api/place/details/json"

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_FB_RE    = re.compile(r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9.\-/_]+", re.I)


# ── Contact enrichment: pull email + Facebook from the business website ──
def _enrich_from_site(url: str) -> tuple[Optional[str], Optional[str]]:
    if not url:
        return None, None
    try:
        r = httpx.get(url, timeout=12, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"})
        html = r.text
        email = None
        m = _EMAIL_RE.search(html)
        if m and not m.group(0).lower().endswith((".png", ".jpg", ".gif", ".webp")):
            email = m.group(0).lower()
        fb = None
        fm = _FB_RE.search(html)
        if fm:
            fb = fm.group(0).split("?")[0].rstrip("/")
            # ignore facebook's own sharer/plugin links
            if any(x in fb.lower() for x in ["sharer", "plugins", "/tr", "dialog"]):
                fb = None
        return email, fb
    except Exception:
        return None, None


def _score(b: dict) -> int:
    s = 0
    if b.get("phone"):    s += 25
    if b.get("email"):    s += 25
    if b.get("website"):  s += 15
    if b.get("facebook"): s += 20
    return s


# ── One Text Search query for one city ───────────────────────────────
def _search_city(client: httpx.Client, query: str, city: str, state: str) -> list[dict]:
    out = []
    try:
        r = client.get(TEXT_SEARCH, params={
            "query": f"{query} in {city}, {state}",
            "key": API_KEY,
        }, timeout=20)
        data = r.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            print(f"  [PLACES] {city} '{query}': API status {data.get('status')} — {data.get('error_message','')}")
            return out

        for place in data.get("results", [])[:20]:
            pid = place.get("place_id")
            if not pid:
                continue
            # Place Details for phone + website
            d = client.get(DETAILS, params={
                "place_id": pid,
                "fields": "name,formatted_phone_number,international_phone_number,website,formatted_address",
                "key": API_KEY,
            }, timeout=20).json().get("result", {})

            phone   = d.get("international_phone_number") or d.get("formatted_phone_number")
            website = d.get("website")
            email, facebook = _enrich_from_site(website) if website else (None, None)

            out.append({
                "name":             d.get("name") or place.get("name"),
                "company":          d.get("name") or place.get("name"),
                "phone":            _clean_phone(phone),
                "email":            email,
                "website":          website,
                "facebook":         facebook,
                "address":          d.get("formatted_address") or place.get("formatted_address"),
                "city":             city,
                "state":            state,
                "lead_type":        "CASH_BUYER",
                "source":           f"PLACES_API:{query}",
                "opt_in":           False,
                "status":           "NEW",
                "buys_as_is":       True,
                "preferred_states": [state],
            })
            time.sleep(0.1)  # gentle on the API
    except Exception as e:
        print(f"  [PLACES] {city} '{query}' error: {e}")
    return out


def _clean_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    if digits:
        return f"+{digits}"
    return None


# ── Save, dedup by phone/email ───────────────────────────────────────
def save_buyers(buyers: list[dict]) -> int:
    saved = 0
    for b in buyers:
        if not b.get("phone") and not b.get("email"):
            continue
        if REQUIRE_FACEBOOK and not b.get("facebook"):
            continue
        b["score"] = _score(b)

        q = _sb().table("cash_buyers").select("id")
        if b.get("phone"):
            q = q.eq("phone", b["phone"])
        else:
            q = q.eq("email", b["email"])
        if q.execute().data:
            continue
        try:
            _sb().table("cash_buyers").insert(b).execute()
            saved += 1
        except Exception as e:
            print(f"  [PLACES] save error ({b.get('name')}): {e}")
    return saved


# ── Main runner ──────────────────────────────────────────────────────
def run_places_buyer_scraper(
    states: Optional[list[str]] = None,
    queries_per_city: int = 3,
    cities_per_state: int = 4,
) -> dict:
    if not API_KEY:
        print("[PLACES] GOOGLE_MAPS_API_KEY not set — get a free key at "
              "console.cloud.google.com (enable Places API). Skipping.")
        return {"total_found": 0, "saved": 0, "facebook_verified": 0}

    states = states or TARGET_STATES
    print(f"[PLACES] Cash-buyer search via Google Places API | {date.today()}")
    print(f"  Require Facebook page: {REQUIRE_FACEBOOK}")

    all_buyers: list[dict] = []
    with httpx.Client() as client:
        for state in states:
            for city in (CITIES.get(state) or [])[:cities_per_state]:
                for query in QUERIES[:queries_per_city]:
                    print(f"  Searching: {query} — {city}, {state}")
                    found = _search_city(client, query, city, state)
                    all_buyers.extend(found)
                    time.sleep(0.3)

    fb_verified = sum(1 for b in all_buyers if b.get("facebook"))
    with_contact = sum(1 for b in all_buyers if b.get("phone") or b.get("email"))
    saved = save_buyers(all_buyers)

    print(f"\n[PLACES] Found: {len(all_buyers)} businesses | "
          f"with contact: {with_contact} | Facebook-verified: {fb_verified} | "
          f"saved: {saved}")
    return {"total_found": len(all_buyers), "saved": saved, "facebook_verified": fb_verified}


if __name__ == "__main__":
    run_places_buyer_scraper(states=["TX"], cities_per_state=2, queries_per_city=2)
