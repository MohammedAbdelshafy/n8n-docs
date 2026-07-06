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

# ── SOCRATA datasets (no auth). Verified-working endpoints only. ──
# distress = motivated-seller signal. Wrong IDs just 404 and are skipped.
SOURCES = [
    # ── Illinois ──
    {"name": "Chicago Building Violations", "city": "Chicago", "state": "IL", "distress": "code_violation",
     "url": "https://data.cityofchicago.org/resource/22u3-xenr.json"},
    {"name": "Chicago Vacant/Abandoned Buildings", "city": "Chicago", "state": "IL", "distress": "vacant",
     "url": "https://data.cityofchicago.org/resource/7nii-7srd.json"},
    # ── Ohio ──
    {"name": "Cincinnati Code Enforcement", "city": "Cincinnati", "state": "OH", "distress": "code_violation",
     "url": "https://data.cincinnati-oh.gov/resource/cncm-znd6.json"},
    # ── New York ──
    {"name": "NYC HPD Housing Violations", "city": "New York", "state": "NY", "distress": "housing_violation",
     "url": "https://data.cityofnewyork.us/resource/wvxf-dwi5.json"},
    {"name": "NYC DOB Complaints", "city": "New York", "state": "NY", "distress": "building_complaint",
     "url": "https://data.cityofnewyork.us/resource/eabe-havv.json"},
    # ── Texas ──
    {"name": "Dallas Code Violations", "city": "Dallas", "state": "TX", "distress": "code_violation",
     "url": "https://www.dallasopendata.com/resource/x9pz-kdq9.json"},
    # ── Washington ──
    {"name": "Seattle Code Complaints", "city": "Seattle", "state": "WA", "distress": "code_violation",
     "url": "https://data.seattle.gov/resource/ez4a-iug7.json"},
]

# ── ArcGIS FeatureServer sources. Many cities/counties (esp. Florida) publish
# distressed-property data on ArcGIS Hub, NOT Socrata. ArcGIS REST also returns
# JSON: {layer}/query?where=1=1&outFields=*&f=json — paginated via resultOffset.
# `item` = ArcGIS Online item id (service URL resolved at runtime); `url` = a
# direct FeatureServer *layer* URL (…/FeatureServer/0). One of the two required.
ARCGIS_SOURCES = [
    # ── Florida (user priority: Miami-Dade, Broward, Hillsborough) ──
    {"name": "Miami-Dade Code Compliance Violations", "city": "Miami", "state": "FL",
     "distress": "code_violation", "item": "da0e434c7a914bb983222393dab2b897", "layer": 0},
    {"name": "Fort Lauderdale (Broward) Code Cases", "city": "Fort Lauderdale", "state": "FL",
     "distress": "code_violation", "item": "6e36e6dc4bb04c069ceba3a50d9471d8", "layer": 0},
    {"name": "Cape Coral Code Enforcement Cases", "city": "Cape Coral", "state": "FL",
     "distress": "code_violation", "item": "5aae323b80e64301a8b2b1f7fee64912", "layer": 0},
    # ── Maryland (migrated off Socrata to ArcGIS) ──
    {"name": "Baltimore Vacant Building Notices", "city": "Baltimore", "state": "MD",
     "distress": "vacant",
     "url": "https://egisdata.baltimorecity.gov/egis/rest/services/Housing/DHCD_Open_Baltimore_Datasets/FeatureServer/1"},
]

ARCGIS_PAGE = 1000   # rows per ArcGIS query page
ARCGIS_CAP  = 5000   # max rows pulled per ArcGIS source (keeps runtime bounded)

_ADDR_KEYS  = ["address", "violation_address", "property_address", "full_address",
               "street_address", "incident_address", "addr", "location_address",
               "address_full", "situs_address", "streetaddress",
               # ArcGIS-style attribute names (parsed case-insensitively)
               "fulladdr", "full_addr", "site_addr", "siteaddr", "site_address",
               "prop_addr", "propaddr", "propertyaddr", "situs", "situs_addr",
               "addr_line", "addressline", "loc_addr", "locaddr", "casaddress"]
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
            row = _record_from(rec, src)
            if row:
                out.append(row)
    except Exception as e:
        print(f"  [OPENDATA] {src['name']} error: {e}")
    return out


def _record_from(rec: dict, src: dict) -> Optional[dict]:
    """Map a raw attribute dict (Socrata row or ArcGIS attributes) -> lead."""
    addr = _build_address(rec)
    if not addr:
        return None
    return {
        "name":             _first(rec, _OWNER_KEYS) or "Owner of Record",
        "property_address": addr,
        "city":             _first(rec, _CITY_KEYS) or src.get("city", ""),
        "state":            src["state"],
        "zip":              _first(rec, _ZIP_KEYS) or "",
        "reason":           src["distress"].upper(),   # CODE_VIOLATION | VACANT ...
        "source":           f"OPEN_DATA:{src['name']}",
        "status":           "NEW",
        "consent_given":    False,
    }


def _arcgis_layer_url(src: dict) -> Optional[str]:
    """Resolve an ArcGIS source to a queryable FeatureServer *layer* URL."""
    if src.get("url"):
        return src["url"].rstrip("/")
    item = src.get("item")
    if not item:
        return None
    try:
        r = httpx.get(f"https://www.arcgis.com/sharing/rest/content/items/{item}",
                      params={"f": "json"},
                      headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=30, follow_redirects=True)
        base = (r.json() or {}).get("url")
        if not base:
            print(f"  [ARCGIS] {src['name']}: item {item} has no service url")
            return None
        return f"{base.rstrip('/')}/{src.get('layer', 0)}"
    except Exception as e:
        print(f"  [ARCGIS] {src['name']} item resolve error: {e}")
        return None


def _fetch_arcgis(src: dict) -> list[dict]:
    layer_url = _arcgis_layer_url(src)
    if not layer_url:
        return []
    out, offset = [], 0
    while offset < ARCGIS_CAP:
        try:
            r = httpx.get(f"{layer_url}/query",
                          params={"where": "1=1", "outFields": "*", "f": "json",
                                  "returnGeometry": "false",
                                  "resultRecordCount": ARCGIS_PAGE, "resultOffset": offset},
                          headers={"User-Agent": UA, "Accept": "application/json"},
                          timeout=40, follow_redirects=True)
            if r.status_code >= 400:
                print(f"  [ARCGIS] {src['name']}: HTTP {r.status_code} — skipping")
                break
            data = r.json()
            feats = data.get("features") if isinstance(data, dict) else None
            if not feats:
                break
            for f in feats:
                rec = _record_from(f.get("attributes") or {}, src)
                if rec:
                    out.append(rec)
            if len(feats) < ARCGIS_PAGE or not data.get("exceededTransferLimit"):
                break
            offset += ARCGIS_PAGE
        except Exception as e:
            print(f"  [ARCGIS] {src['name']} error: {e}")
            break
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
    socrata, arcgis = SOURCES, ARCGIS_SOURCES
    if states:
        ss = [s.upper() for s in states]
        socrata = [s for s in SOURCES if s["state"] in ss]
        arcgis  = [s for s in ARCGIS_SOURCES if s["state"] in ss]

    print(f"[OPENDATA] Government open-data pull | {date.today()}")
    all_recs = []

    print(f"[OPENDATA] Socrata sources: {len(socrata)}")
    for src in socrata:
        recs = _fetch(src)
        print(f"  {src['name']} ({src['state']}): {len(recs)} records")
        all_recs.extend(recs)

    print(f"[OPENDATA] ArcGIS sources: {len(arcgis)}")
    for src in arcgis:
        recs = _fetch_arcgis(src)
        print(f"  {src['name']} ({src['state']}): {len(recs)} records")
        all_recs.extend(recs)

    saved = _save(all_recs)
    print(f"\n[OPENDATA] Fetched: {len(all_recs)} distressed properties | saved: {saved} new")
    return {"total_found": len(all_recs), "saved": saved}


if __name__ == "__main__":
    run_open_data_scraper()
