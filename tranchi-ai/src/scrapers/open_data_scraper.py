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
LIMIT = 1000  # Socrata returns up to 1000 rows per call without an app token

# Public Socrata open-data datasets (no auth). distress = motivated-seller signal.
# Wrong/renamed dataset IDs just 404 and are skipped — the run reports which hit.
SOURCES = [
    # ── Illinois ──
    {"name": "Chicago Building Violations", "city": "Chicago", "state": "IL", "distress": "code_violation",
     "url": "https://data.cityofchicago.org/resource/22u3-xenr.json"},
    {"name": "Chicago Vacant/Abandoned Buildings", "city": "Chicago", "state": "IL", "distress": "vacant",
     "url": "https://data.cityofchicago.org/resource/7nii-7srd.json"},
    # ── Ohio ──
    {"name": "Cincinnati Code Enforcement", "city": "Cincinnati", "state": "OH", "distress": "code_violation",
     "url": "https://data.cincinnati-oh.gov/resource/cncm-znd6.json"},
    # ── Maryland ──
    {"name": "Baltimore Vacant Buildings", "city": "Baltimore", "state": "MD", "distress": "vacant",
     "url": "https://data.baltimorecity.gov/resource/rw5h-nvv4.json"},
    # ── New York ──
    {"name": "NYC HPD Housing Violations", "city": "New York", "state": "NY", "distress": "housing_violation",
     "url": "https://data.cityofnewyork.us/resource/wvxf-dwi5.json"},
    {"name": "NYC DOB Complaints", "city": "New York", "state": "NY", "distress": "building_complaint",
     "url": "https://data.cityofnewyork.us/resource/eabe-havv.json"},
    # ── Texas ──
    {"name": "Dallas Code Violations", "city": "Dallas", "state": "TX", "distress": "code_violation",
     "url": "https://www.dallasopendata.com/resource/vfmm-cfhh.json"},
    {"name": "Austin Code Cases", "city": "Austin", "state": "TX", "distress": "code_violation",
     "url": "https://data.austintexas.gov/resource/56r5-uw7z.json"},
    # ── Tennessee ──
    {"name": "Nashville Codes Violations", "city": "Nashville", "state": "TN", "distress": "code_violation",
     "url": "https://data.nashville.gov/resource/6zjh-2wu4.json"},
    # ── Kentucky ──
    {"name": "Louisville Code Enforcement", "city": "Louisville", "state": "KY", "distress": "code_violation",
     "url": "https://data.louisvilleky.gov/resource/9ca3-h4dw.json"},
    # ── Massachusetts ──
    {"name": "Boston Building Violations", "city": "Boston", "state": "MA", "distress": "code_violation",
     "url": "https://data.boston.gov/resource/800a-2b39.json"},
    # ── Washington ──
    {"name": "Seattle Code Complaints", "city": "Seattle", "state": "WA", "distress": "code_violation",
     "url": "https://data.seattle.gov/resource/ez4a-iug7.json"},
    # ── Missouri ──
    {"name": "Kansas City Dangerous Buildings", "city": "Kansas City", "state": "MO", "distress": "dangerous_building",
     "url": "https://data.kcmo.org/resource/j9x4-tv6t.json"},
    # ── Colorado ──
    {"name": "Denver Neighborhood Code Violations", "city": "Denver", "state": "CO", "distress": "code_violation",
     "url": "https://data.denvergov.org/resource/9zbh-9qjx.json"},
]

_ADDR_KEYS  = ["address", "violation_address", "property_address", "full_address",
               "street_address", "incident_address", "addr", "location_address",
               "address_full", "situs_address", "streetaddress"]
_HN_KEYS    = ["house_number", "housenumber", "house_no", "street_number", "address_number", "propertyhousenumber"]
_ST_KEYS    = ["street_name", "streetname", "street", "propertystreetname", "streetdescription"]
_OWNER_KEYS = ["owner", "owner_name", "ownername", "respondent", "legal_owner", "current_owner"]
_CITY_KEYS  = ["city", "property_city", "municipality", "boro", "borough"]
_ZIP_KEYS   = ["zip", "zip_code", "zipcode", "postal_code", "property_zip", "zipcode5"]


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


def _build_address(rec: dict) -> Optional[str]:
    """Single address field, else combine house-number + street-name."""
    addr = _first(rec, _ADDR_KEYS)
    if addr and re.search(r"\d", addr):
        return addr
    hn = _first(rec, _HN_KEYS)
    st = _first(rec, _ST_KEYS)
    if hn and st:
        combined = f"{hn} {st}".strip()
        if re.search(r"\d", combined):
            return combined
    return None


def _fetch(src: dict) -> list[dict]:
    out = []
    try:
        r = httpx.get(src["url"], params={"$limit": LIMIT},
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
            addr = _build_address(rec)
            if not addr:
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
