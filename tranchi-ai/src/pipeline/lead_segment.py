"""
Lead Segmentation — split the public-record distressed-property file into
usable buckets so a buyer knows what each lead IS.

IMPORTANT — these are all PUBLIC-RECORD PROPERTY OWNERS (sellers). There are no
"cash buyers" hiding in property records; buyers come from the /buyers funnel
(cash_buyers table). What we CAN do is read the owner name to tell apart:

  • an individual who owns one distressed house  -> motivated SELLER
  • an LLC / "Properties" / "Holdings" entity     -> investor-owned
  • an owner that appears on many properties      -> active investor / landlord /
        wholesaler = a CASH-BUYER PROSPECT you could recruit as a buyer
  • a bank / government / housing-authority owner -> REO, not sellable (excluded)

Plus a motivation tier from the distress reason:
  VACANT -> HOT, *VIOLATION -> WARM, *COMPLAINT -> COOL.

Reads seller_leads (public records, consent_given=FALSE), writes one master CSV
with added `category` + `motivation` columns and one CSV per category.
"""

import csv
import re
from collections import Counter
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

PUBLIC_PREFIXES = ("OPEN_DATA", "COUNTY_RECORDS", "LIS_PENDENS")
PORTFOLIO_MIN = 3          # owner on >= this many properties -> active investor

OUT_FIELDS = ["category", "motivation", "name", "property_address", "city",
              "state", "zip", "reason", "source", "status", "created_at"]

# Owner-name entity signals -----------------------------------------------
_BUSINESS = re.compile(
    r"\b(LLC|L\.L\.C|INC|CORP|CO|LTD|LP|L\.P|PLLC|PLC|TRUST|PROPERTIES|PROPERTY|"
    r"HOLDINGS|HOMES|REALTY|REAL ESTATE|INVESTMENT|INVESTMENTS|CAPITAL|GROUP|"
    r"ENTERPRISE|ENTERPRISES|ASSOCIATES|PARTNERS|VENTURES|MANAGEMENT|RENTAL|"
    r"RENTALS|ACQUISITION|ACQUISITIONS|EQUITY|FUND|DEVELOPMENT|BUILDERS|ESTATES)\b",
    re.I)
_INSTITUTIONAL = re.compile(
    r"\b(BANK|MORTGAGE|N\.A|NATIONAL ASSOCIATION|FEDERAL|FANNIE|FREDDIE|HUD|"
    r"CITY OF|COUNTY OF|STATE OF|HOUSING AUTHORITY|REDEVELOPMENT|DEPARTMENT|"
    r"AUTHORITY|COMMISSION|SCHOOL|CHURCH|UNITED STATES|SECRETARY)\b", re.I)

_UNKNOWN_NAMES = {"", "owner of record", "owner", "n/a", "na", "unknown", "none"}


def _norm_owner(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()


def _motivation(reason: str) -> str:
    r = (reason or "").upper()
    if "VACANT" in r or "ABANDON" in r or "DEMOLITION" in r:
        return "HOT"
    if "COMPLAINT" in r:
        return "COOL"
    if "VIOLATION" in r or "CODE" in r or "LIS_PENDENS" in r or "FORECLOS" in r:
        return "WARM"
    return "WARM"


def _categorize(name: str, owner_count: int) -> str:
    raw = (name or "").strip()
    if _norm_owner(raw) in _UNKNOWN_NAMES:
        return "UNKNOWN_OWNER"
    if _INSTITUTIONAL.search(raw):
        return "BANK_GOVT_REO"                       # not sellable
    is_business = bool(_BUSINESS.search(raw))
    if owner_count >= PORTFOLIO_MIN:
        # repeat owner = active buyer/holder -> recruit as a cash buyer
        return "PORTFOLIO_INVESTOR_BUYER"
    if is_business:
        return "INVESTOR_LLC"
    return "DISTRESSED_HOMEOWNER"


# Human-readable file + label per category
_CAT_META = {
    "DISTRESSED_HOMEOWNER":      ("Distressed homeowner (motivated seller)", "seg_distressed_homeowners"),
    "INVESTOR_LLC":              ("Investor / LLC-owned (seller or buyer)",  "seg_investor_llc"),
    "PORTFOLIO_INVESTOR_BUYER":  ("Portfolio investor — CASH-BUYER/WHOLESALER prospect", "seg_cash_buyers_wholesalers"),
    "UNKNOWN_OWNER":             ("Owner name not in record (address-only seller lead)", "seg_unknown_owner"),
    "BANK_GOVT_REO":             ("Bank / Govt / REO (not sellable — excluded)", "seg_bank_govt_reo"),
}


def _fetch_all_public() -> list[dict]:
    rows, offset = [], 0
    while True:
        page = (_sb().table("seller_leads").select("*")
                .eq("consent_given", False)
                .range(offset, offset + 999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return [r for r in rows if (r.get("source") or "").startswith(PUBLIC_PREFIXES)]


def segment_leads(out_prefix: str = None) -> dict:
    rows = _fetch_all_public()
    if not rows:
        print("  (no public-record leads yet — run `python main.py opendata` first)")
        return {}

    # count how many properties each owner appears on (portfolio signal)
    owner_counts = Counter(_norm_owner(r.get("name"))
                           for r in rows
                           if _norm_owner(r.get("name")) not in _UNKNOWN_NAMES)

    buckets: dict[str, list[dict]] = {c: [] for c in _CAT_META}
    for r in rows:
        oc = owner_counts.get(_norm_owner(r.get("name")), 0)
        cat = _categorize(r.get("name"), oc)
        out = {
            "category":   cat,
            "motivation": _motivation(r.get("reason")),
            "name":       r.get("name", ""),
            "property_address": r.get("property_address", ""),
            "city":       r.get("city", ""),
            "state":      r.get("state", ""),
            "zip":        r.get("zip", ""),
            "reason":     r.get("reason", ""),
            "source":     r.get("source", ""),
            "status":     r.get("status", ""),
            "created_at": r.get("created_at", ""),
        }
        buckets[cat].append(out)

    today = date.today()
    prefix = out_prefix or "leads"

    # master file (everything, with the two new columns)
    master = f"{prefix}_segmented_ALL_{today}.csv"
    with open(master, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for cat in _CAT_META:
            for row in buckets[cat]:
                w.writerow(row)

    # per-category files
    written = {}
    for cat, (label, fname) in _CAT_META.items():
        recs = buckets[cat]
        if not recs:
            continue
        path = f"{prefix}_{fname}_{today}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OUT_FIELDS, extrasaction="ignore")
            w.writeheader()
            for row in recs:
                w.writerow(row)
        written[cat] = (path, len(recs))

    # ---- report ----
    total = len(rows)
    print("=" * 60)
    print(f"  LEAD SEGMENTATION — {today}  ({total:,} public-record leads)")
    print("=" * 60)
    for cat, (label, _) in _CAT_META.items():
        n = len(buckets[cat])
        if n:
            pct = 100 * n / total
            print(f"  {label}")
            print(f"      {cat}: {n:,} ({pct:.1f}%)")
    # motivation split (sellable only — exclude REO)
    sellable = [r for c in buckets for r in buckets[c] if c != "BANK_GOVT_REO"]
    mot = Counter(r["motivation"] for r in sellable)
    print("-" * 60)
    print(f"  Motivation (sellable {len(sellable):,}):  "
          f"HOT {mot.get('HOT',0):,} | WARM {mot.get('WARM',0):,} | COOL {mot.get('COOL',0):,}")
    buyers = len(buckets["PORTFOLIO_INVESTOR_BUYER"])
    print(f"  >>> Cash-buyer / wholesaler prospects extracted: {buyers:,}")
    print("=" * 60)
    print(f"  Master file: {master}")
    for cat, (path, n) in written.items():
        print(f"    {path}  ({n:,})")

    return {"total": total, "master": master,
            "categories": {c: len(buckets[c]) for c in _CAT_META},
            "files": {c: p for c, (p, _) in written.items()}}


if __name__ == "__main__":
    segment_leads()
