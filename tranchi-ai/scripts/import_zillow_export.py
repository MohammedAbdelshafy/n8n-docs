"""
Zillow Data Exporter (Property Data Labs) CSV importer.

How to use:
  1. Install the free "Zillow Data Exporter" extension from Property Data Labs
  2. Go to Zillow → filter: For Sale By Owner + your target state
  3. Run the extension → export CSV
  4. python main.py import-zillow path/to/export.csv

Columns handled (extension export format):
  address, price, beds, baths, sqft, year_built, days_on_zillow,
  zestimate, price_reduced, agent_name, agent_phone, agent_email,
  listing_url, property_type, status

Motivation scoring:
  - FSBO (no agent listed)    → +25
  - Days on market 30-60      → +15
  - Days on market 60+        → +30
  - Price reduced             → +20
  - Year built < 1980         → +10 (older = more likely needs work)
"""

import csv
import re
import sys
from datetime import datetime, timezone
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Map common Property Data Labs column names to our schema
# The extension varies slightly by version, so we check multiple aliases
COLUMN_MAP = {
    "address":       ["address", "full_address", "street_address", "Address", "Full Address"],
    "price":         ["price", "list_price", "listing_price", "Price", "List Price"],
    "beds":          ["beds", "bedrooms", "bed", "Beds", "Bedrooms"],
    "baths":         ["baths", "bathrooms", "bath", "Baths", "Bathrooms"],
    "sqft":          ["sqft", "square_feet", "living_area", "Sqft", "Square Feet"],
    "year_built":    ["year_built", "built_year", "Year Built"],
    "days_on_mkt":   ["days_on_zillow", "days_on_market", "dom", "Days on Zillow", "Days on Market"],
    "zestimate":     ["zestimate", "Zestimate"],
    "price_reduced": ["price_reduced", "price_cut", "Price Reduced", "Price Cut"],
    "phone":         ["agent_phone", "phone", "contact_phone", "Phone", "Agent Phone"],
    "email":         ["agent_email", "email", "contact_email", "Email", "Agent Email"],
    "owner_name":    ["agent_name", "owner", "contact_name", "Agent Name", "Owner"],
    "url":           ["listing_url", "url", "zillow_url", "URL", "Listing URL"],
    "city":          ["city", "City"],
    "state":         ["state", "State"],
    "zip":           ["zip", "zipcode", "zip_code", "Zip", "ZIP"],
}


def _get(row: dict, field: str, default=None):
    """Case-insensitive column lookup with aliases."""
    for alias in COLUMN_MAP.get(field, [field]):
        val = row.get(alias) or row.get(alias.lower()) or row.get(alias.upper())
        if val and str(val).strip():
            return str(val).strip()
    return default


def _parse_price(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r'[\d,]+', text.replace('$', ''))
    return int(m.group().replace(',', '')) if m else None


def _parse_int(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r'\d+', str(text))
    return int(m.group()) if m else None


def _clean_phone(text: str) -> str | None:
    if not text:
        return None
    d = re.sub(r'\D', '', text)
    if len(d) == 10:
        return f"+1{d}"
    if len(d) == 11 and d[0] == '1':
        return f"+{d}"
    return None


def _score_motivation(row_data: dict) -> int:
    score = 20  # baseline: publicly listed

    dom = _parse_int(row_data.get("days_on_mkt") or "0") or 0
    if dom >= 60:
        score += 30
    elif dom >= 30:
        score += 15

    price_reduced = str(row_data.get("price_reduced") or "").lower()
    if price_reduced in ("yes", "true", "1", "y"):
        score += 20

    year_built = _parse_int(row_data.get("year_built") or "0") or 0
    if 0 < year_built < 1980:
        score += 10

    # FSBO = no agent name means owner is selling direct
    owner = str(row_data.get("owner_name") or "").strip()
    if not owner or owner.lower() in ("", "none", "n/a", "fsbo", "owner"):
        score += 25

    return min(100, score)


def _infer_timeline(dom: int) -> str:
    if dom >= 60:
        return "ASAP"
    if dom >= 30:
        return "1-3_MONTHS"
    return "3-6_MONTHS"


def import_zillow_csv(csv_path: str) -> dict:
    """
    Import a Property Data Labs / Zillow Data Exporter CSV.
    Returns {"imported": N, "skipped": N, "errors": [...]}.
    """
    imported = 0
    skipped  = 0
    errors   = []

    try:
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows   = list(reader)
    except FileNotFoundError:
        print(f"[IMPORT] File not found: {csv_path}")
        return {"imported": 0, "skipped": 0, "errors": [f"File not found: {csv_path}"]}

    print(f"[IMPORT] Reading {len(rows)} rows from {csv_path}")
    print(f"[IMPORT] Columns detected: {list(rows[0].keys())[:8] if rows else '—'}\n")

    for i, raw in enumerate(rows, 1):
        try:
            addr = _get(raw, "address")
            if not addr:
                skipped += 1
                continue

            # Dedup by address
            if supabase.table("seller_leads").select("id").eq("property_address", addr).execute().data:
                skipped += 1
                continue

            row_data = {
                "address":      addr,
                "price":        _get(raw, "price"),
                "beds":         _get(raw, "beds"),
                "days_on_mkt":  _get(raw, "days_on_mkt"),
                "year_built":   _get(raw, "year_built"),
                "price_reduced":_get(raw, "price_reduced"),
                "owner_name":   _get(raw, "owner_name"),
                "phone":        _get(raw, "phone"),
                "email":        _get(raw, "email"),
                "city":         _get(raw, "city"),
                "state":        _get(raw, "state"),
                "zip":          _get(raw, "zip"),
                "url":          _get(raw, "url"),
            }

            dom   = _parse_int(row_data["days_on_mkt"] or "0") or 0
            score = _score_motivation(row_data)
            price = _parse_price(row_data["price"] or "")
            phone = _clean_phone(row_data["phone"] or "")

            notes_parts = []
            if price:
                notes_parts.append(f"Asking ${price:,}")
            if row_data["beds"]:
                notes_parts.append(f"{row_data['beds']}bd")
            if dom:
                notes_parts.append(f"{dom} DOM")
            if row_data["price_reduced"] in ("yes","true","1","y","Yes","True"):
                notes_parts.append("PRICE REDUCED")
            if row_data["year_built"]:
                notes_parts.append(f"Built {row_data['year_built']}")
            if row_data["url"]:
                notes_parts.append(f"Zillow: {row_data['url']}")

            lead = {
                "name":             row_data["owner_name"] or "FSBO Owner",
                "phone":            phone,
                "email":            row_data["email"],
                "property_address": addr,
                "city":             row_data["city"] or "",
                "state":            row_data["state"] or "",
                "zip":              row_data["zip"] or "",
                "timeline":         _infer_timeline(dom),
                "reason":           None,
                "condition":        None,
                "consent_given":    False,    # ← for your outreach; not yet sellable
                "source":           "ZILLOW_EXPORT",
                "lead_score":       score,
                "status":           "NEW",
                "notes":            " | ".join(notes_parts),
            }

            supabase.table("seller_leads").insert(lead).execute()
            imported += 1

            flag = " ← HOT" if score >= 70 else (" ← WARM" if score >= 50 else "")
            print(f"  [{i:03d}] {addr} | score={score}{flag}")

        except Exception as e:
            errors.append(f"Row {i}: {e}")
            print(f"  [ERR] Row {i}: {e}")

    print(f"\n[IMPORT] Done — {imported} imported, {skipped} skipped (dupes), {len(errors)} errors")
    print(f"[IMPORT] Run: python main.py outreach-fsbo  ← to AI-draft emails to these leads")
    return {"imported": imported, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_zillow_export.py path/to/export.csv")
        sys.exit(1)
    import_zillow_csv(sys.argv[1])
