"""
Parcel / Assessor Owner Enrichment.

The open-data violation feeds give us the distressed *address* but usually not
the *owner* (98% land as "Owner of Record"). County parcel/assessor layers —
also free, also ArcGIS — DO carry the owner name keyed by situs address. This
backfills seller_leads.name by matching each unknown-owner lead's address
against the county parcel layer.

Matching: we send the lead addresses to the parcel layer in batched
`addr_field IN (...)` queries (no giant full-county pull), then join the
returned owner back to our leads on a normalized address key. Only leads whose
name is still "Owner of Record" are touched; real names are never overwritten.

Once names are populated, `python main.py segment` splits homeowner vs.
investor vs. cash-buyer far better than the 1.4% we get today.
"""

import re
import httpx
from typing import Optional
from collections import defaultdict

from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"
UNKNOWN = {"", "owner of record", "owner", "n/a", "na", "unknown", "none"}

# County parcel layers with owner + situs-address fields.
# `item` = ArcGIS Online item id (resolved to its service URL at runtime) OR
# `url` = a direct FeatureServer/MapServer *layer* URL. owner_fields tried in
# order; first non-empty wins.
PARCEL_SOURCES = [
    {"name": "Miami-Dade Parcels", "state": "FL",
     "item": "347bce97227c4b54b04a3e626b558950", "layer": 0,
     "owner_fields": ["TRUE_OWNER1", "TRUE_OWNER2"], "addr_field": "TRUE_SITE_ADDR"},
]

BATCH = 120          # addresses per IN() query
MAX_LEADS = 20000    # cap leads processed per source per run (runtime bound)


def _norm(addr: str) -> str:
    """Normalize an address for joining: drop unit/city/zip, strip ordinal
    suffixes (52ND->52), remove punctuation, collapse spaces."""
    if not addr:
        return ""
    a = str(addr).upper().split(",")[0]            # keep street part only
    a = re.sub(r"[.#,]", " ", a)
    a = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", a)  # 52ND -> 52
    a = re.sub(r"\s+", " ", a).strip()
    return a


def _layer_url(src: dict) -> Optional[str]:
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
        return f"{base.rstrip('/')}/{src.get('layer', 0)}" if base else None
    except Exception as e:
        print(f"  [ENRICH] {src['name']} resolve error: {e}")
        return None


def _unknown_leads(state: str) -> list[dict]:
    """seller_leads in `state` whose owner name is still unknown."""
    out, offset = [], 0
    while len(out) < MAX_LEADS:
        page = (_sb().table("seller_leads")
                .select("id,property_address,name")
                .eq("state", state).eq("consent_given", False)
                .range(offset, offset + 999).execute().data or [])
        for r in page:
            if (r.get("name") or "").strip().lower() in UNKNOWN and r.get("property_address"):
                out.append(r)
        if len(page) < 1000:
            break
        offset += 1000
    return out


def _query_owners(layer_url: str, addr_field: str, owner_fields: list[str],
                  addrs: list[str]) -> dict[str, str]:
    """Return {normalized_addr: owner} for the given raw addresses."""
    found = {}
    flds = ",".join([addr_field] + owner_fields)
    for i in range(0, len(addrs), BATCH):
        chunk = addrs[i:i + BATCH]
        vals = ",".join("'" + a.replace("'", "''") + "'" for a in chunk)
        try:
            r = httpx.get(f"{layer_url}/query",
                          params={"where": f"{addr_field} IN ({vals})",
                                  "outFields": flds, "returnGeometry": "false",
                                  "f": "json"},
                          headers={"User-Agent": UA, "Accept": "application/json"},
                          timeout=45, follow_redirects=True)
            if r.status_code >= 400:
                print(f"  [ENRICH] query HTTP {r.status_code} (batch {i//BATCH})")
                continue
            for feat in (r.json() or {}).get("features", []) or []:
                at = feat.get("attributes") or {}
                owner = next((str(at[f]).strip() for f in owner_fields
                              if at.get(f) and str(at[f]).strip()), "")
                padr = _norm(at.get(addr_field))
                if owner and padr:
                    found[padr] = owner
        except Exception as e:
            print(f"  [ENRICH] query error (batch {i//BATCH}): {e}")
    return found


def _apply(updates: dict[int, str]) -> int:
    saved = 0
    global _supabase
    for lead_id, owner in updates.items():
        for attempt in (1, 2):
            try:
                _sb().table("seller_leads").update({"name": owner}).eq("id", lead_id).execute()
                saved += 1
                break
            except Exception as e:
                if attempt == 1:
                    _supabase = None
                else:
                    print(f"  [ENRICH] update error id={lead_id}: {e}")
    return saved


def run_parcel_enrich(states: Optional[list[str]] = None) -> dict:
    srcs = PARCEL_SOURCES
    if states:
        ss = [s.upper() for s in states]
        srcs = [s for s in PARCEL_SOURCES if s["state"] in ss]

    total_updated = 0
    for src in srcs:
        leads = _unknown_leads(src["state"])
        if not leads:
            print(f"  [ENRICH] {src['name']}: no unknown-owner leads")
            continue
        layer = _layer_url(src)
        if not layer:
            print(f"  [ENRICH] {src['name']}: could not resolve layer")
            continue

        # distinct raw addresses -> lead ids (joined via normalized key)
        by_norm: dict[str, list[int]] = defaultdict(list)
        raw_addrs = {}
        for r in leads:
            n = _norm(r["property_address"])
            by_norm[n].append(r["id"])
            raw_addrs[r["property_address"].upper()] = True

        owners = _query_owners(layer, src["addr_field"], src["owner_fields"],
                               list(raw_addrs.keys()))

        updates = {}
        for n, owner in owners.items():
            for lead_id in by_norm.get(n, []):
                updates[lead_id] = owner

        matched = len(updates)
        applied = _apply(updates)
        rate = 100 * matched / len(leads) if leads else 0
        print(f"  [ENRICH] {src['name']} ({src['state']}): "
              f"{len(leads):,} unknown | matched {matched:,} ({rate:.1f}%) | updated {applied:,}")
        total_updated += applied

    print(f"\n[ENRICH] owner names backfilled: {total_updated:,}")
    return {"updated": total_updated}


if __name__ == "__main__":
    run_parcel_enrich()
