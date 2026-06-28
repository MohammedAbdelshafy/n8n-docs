"""
Open-Data Scraper — government Socrata/ArcGIS APIs.  THE one that works.

Cities/counties publish distressed-property data (code violations, vacant
buildings, tax-delinquent, demolitions) as real JSON APIs — no captcha, no
bot-walls, no JavaScript. Built for automated querying, returns hundreds of
records per call. This is the reliable free source for CSV #3.

Output: seller_leads (source=OPEN_DATA, consent_given=FALSE) — public records,
sellable as a raw motivated-seller list (address + owner where available).

No LLM used — structured JSON parsed directly, so no rate limits.
"""

import os
import re
import httpx
from datetime import date
from typing import Optional

from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"

# Public Socrata datasets (no auth). distress = motivated-seller signal.
# $limit returns up to N records in one call. $where filters recent.
SOURCES = [
    {"name": "Chicago Building Violations", "city": "Chicago", "state": "IL", "distress": "code_violation",
     "url": "https://data.cityofchicago.org/resource/22u3-xenr.json", "limit": 500},
    {"name": "Chicago Vacant/Abandoned Buildings", "city": "Chicago", "state": "IL", "distress": "vacant",
     "url": "https://data.cityofchicago.org/resource/7nii-7srd.json", "limit": 500},
    {"name": "Dallas Code Violations", "city": "Dallas", "state": "TX", "distress": "code_violation",
     "url": "https://www.dallasopendata.com/resource/9se5-26gh.json", "limit": 500},
    {"name": "Austin Code Cases", "city": "Austin", "state": "TX", "distress": "code_violation",
     "url": "https://data.austintexas.gov/resource/x5p7-qyqv.json", "limit": 500},
    {"name": "Cincinnati Code Enforcement", "city": "Cincinnati", "state": "OH", "distress": "code_violation",
     "url": "https://data.cincinnati-oh.gov/resource/cncm-znd6.json", "limit": 500},
    {"name": "NYC HPD Violations", "city": "New York", "state": "NY", "distress": "housing_violation",
     "url": "https://data.cityofnewyork.us/resource/wvxf-dwi5.json", "limit": 500},
]

_ADDR_KEYS  = ["address", "violation_address", "property_address", "full_address",
               "street_address", "incident_address", "addr", "location_address"]
_OWNER_KEYS = ["owner", "owner_name", "ownername", "respondent", "legal_owner"]
_CITY_KEYS  = ["city", "property_city", "municipality"]
_ZIP_KEYS   = ["zip", "zip_code", "zipcode", "postal_code", "property_zip"]


def _first(rec: dict, keys: list[str]) -> Optional[str]:
    for k in keys:
        for rk in rec:
            if rk.lower() == k and rec[rk]:
                return str(rec[rk]).strip()
    # fuzzy contains
    for k in keys:
        for rk in rec:
            if k in rk.lower() and rec[rk]:
                v = rec[rk]
                if isinstance(v, dict):
                    continue
                return str(v).strip()
    return None


def _fetch(src: dict) -> list[dict]:
    out = []
    try:
        r = httpx.get(src["url"], params={"$limit": src.get("limit", 500)},
                      headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=30, follow_redirects=True)
        if r.status_code >= 400:
            print(f"  [OPENDATA] {src['name']}: HTTP {r.status_code} — skipping")
            return []
        data = r.json()
        if not isinstance(data, list):
            print(f"  [OPENDATA] {src['name']}: unexpected response")
            return []
        for rec in data:
            if not isinstance(rec, dict):
                continue
            addr = _first(rec, _ADDR_KEYS)
            if not addr or not re.search(r"\d", addr):
                continue
            out.append({
                "name":             _first(rec, _OWNER_KEYS) or "Owner of Record",
                "property_address": addr,
                "city":             _first(rec, _CITY_KEYS) or src.get("city", ""),
                "state":            src["state"],
                "zip":              _first(rec, _ZIP_KEYS) or "",
                "reason":           src["distress"].upper(),   # CODE_VIOLATION | VACANT ...
                "source":           f"OPEN_DATA:{src['name']}",
                "status":           "NEW",
                "consent_given":    False,
            })
    except Exception as e:
        print(f"  [OPENDATA] {src['name']} error: {e}")
    return out


def _save(records: list[dict]) -> int:
    saved = 0
    # de-dup within batch first
    seen = set()
    batch = []
    for r in records:
        key = (r["property_address"].lower(), r["state"])
        if key in seen:
            continue
        seen.add(key)
        batch.append(r)

    for r in batch:
        try:
            existing = (_sb().table("seller_leads").select("id")
                        .eq("property_address", r["property_address"])
                        .eq("state", r["state"]).execute())
            if existing.data:
                continue
            if _sb().table("seller_leads").insert(r).execute().data:
                saved += 1
        except Exception as e:
            print(f"  [OPENDATA] save error ({r.get('property_address')}): {e}")
    return saved


def run_open_data_scraper(states: Optional[list[str]] = None) -> dict:
    srcs = SOURCES
    if states:
        ss = [s.upper() for s in states]
        srcs = [s for s in SOURCES if s["state"] in ss]

    print(f"[OPENDATA] Government open-data pull | {date.today()}")
    all_recs = []
    for src in srcs:
        recs = _fetch(src)
        print(f"  {src['name']}: {len(recs)} records")
        all_recs.extend(recs)

    saved = _save(all_recs)
    print(f"\n[OPENDATA] Fetched: {len(all_recs)} distressed properties | saved: {saved} new")
    return {"total_found": len(all_recs), "saved": saved}


if __name__ == "__main__":
    run_open_data_scraper()
