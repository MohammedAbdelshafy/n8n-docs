"""
Offer Package Builder — turn distressed leads into a mail-ready offer list.

Format-robust enrichment: instead of exact address IN() (which missed at 0.25%
because the parcel feed formats addresses differently), we BULK-PULL the county
parcel layer for the ZIPs our leads live in, then join on a NORMALIZED address
key locally (ordinals/city/punct stripped on both sides). From the matched
parcel we capture everything an offer needs — owner name, owner MAILING address
(vacant/absentee owners don't live at the property), and MARKET VALUE.

Output: offer_package_top200_<date>.csv — ranked (vacant first, then value),
each priced `offer = value * (1 - DISCOUNT)`. This is a mail-merge source for
yellow-letter offers the USER reviews, signs, and sends. It does not transmit
anything.
"""

import csv
import re
import httpx
from datetime import date
from typing import Optional
from collections import defaultdict

from config import SUPABASE_URL, SUPABASE_KEY
from src.scrapers.parcel_enrich import (
    _norm, _pick_field, _candidate_urls, UA, PARCEL_SOURCES,
    _ADDR_TOKENS, _OWNER_TOKENS,
)

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

PUBLIC_PREFIXES = ("OPEN_DATA", "COUNTY_RECORDS", "LIS_PENDENS")
DISCOUNT = 0.25          # offer 25% under market value
TOP_N = 200
PARCEL_PAGE = 2000       # rows per parcel query page
PARCEL_CAP = 200000      # max parcels pulled per source (runtime bound)

# extra field-name detection for mailing address + value + zip
_MAIL_TOKENS   = ["TRUE_MAILING_ADDR1", "MAILING_ADDR1", "MAIL_ADDR1", "MAILING_ADDRESS",
                  "MAIL_ADDRESS", "MAILINGADDR", "OWNER_ADDR", "MAIL_ADDR", "MAILADDR"]
_MCITY_TOKENS  = ["TRUE_MAILING_CITY", "MAILING_CITY", "MAIL_CITY", "OWNER_CITY"]
_MSTATE_TOKENS = ["TRUE_MAILING_STATE", "MAILING_STATE", "MAIL_STATE", "OWNER_STATE"]
_MZIP_TOKENS   = ["TRUE_MAILING_ZIP", "MAILING_ZIP", "MAIL_ZIP", "OWNER_ZIP"]
_VALUE_TOKENS  = ["JUST_VALUE", "MARKET_VALUE", "TRUE_MARKET", "TOTAL_VALUE",
                  "ASSESSED_VALUE", "ASSD_VAL", "ASSESSED", "TAXABLE_VALUE", "JV", "LAND_VALUE"]
_ZIP_TOKENS    = ["TRUE_SITE_ZIP_CODE", "SITE_ZIP", "SITUS_ZIP", "PROP_ZIP",
                  "ZIP_CODE", "ZIPCODE", "ZIP"]

OUT_FIELDS = ["rank", "motivation", "owner_name", "mailing_address",
              "property_address", "city", "state", "zip", "reason",
              "market_value", "offer_price", "source"]


def _fetch_fl_leads(state: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        page = (_sb().table("seller_leads")
                .select("id,name,property_address,city,state,zip,reason,source")
                .eq("state", state).eq("consent_given", False)
                .range(offset, offset + 999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return [r for r in rows if (r.get("source") or "").startswith(PUBLIC_PREFIXES)
            and r.get("property_address")]


def _money(v) -> float:
    try:
        return float(re.sub(r"[^0-9.]", "", str(v))) if v not in (None, "") else 0.0
    except Exception:
        return 0.0


def _motivation(reason: str) -> str:
    r = (reason or "").upper()
    if "VACANT" in r or "ABANDON" in r or "DEMOLITION" in r:
        return "HOT"
    if "COMPLAINT" in r:
        return "COOL"
    return "WARM"


def _resolve_parcel(src: dict) -> Optional[tuple]:
    """Return (url, fields dict) with detected addr/owner/mailing/value/zip fields."""
    for url in _candidate_urls(src):
        try:
            meta = httpx.get(url, params={"f": "json"},
                             headers={"User-Agent": UA, "Accept": "application/json"},
                             timeout=30, follow_redirects=True).json()
        except Exception as e:
            print(f"  [OFFERS] meta error {url}: {e}")
            continue
        fields = (meta or {}).get("fields")
        if not fields:
            continue
        names = [f.get("name") for f in fields if f.get("name")]
        det = {
            "addr":   _pick_field(names, _ADDR_TOKENS),
            "owner":  _pick_field(names, _OWNER_TOKENS),
            "mail":   _pick_field(names, _MAIL_TOKENS),
            "mcity":  _pick_field(names, _MCITY_TOKENS),
            "mstate": _pick_field(names, _MSTATE_TOKENS),
            "mzip":   _pick_field(names, _MZIP_TOKENS),
            "value":  _pick_field(names, _VALUE_TOKENS),
            "zip":    _pick_field(names, _ZIP_TOKENS),
        }
        print(f"  [OFFERS] layer {url}")
        print(f"  [OFFERS] detected fields: {det}")
        if not det["addr"] or not det["owner"]:
            print(f"  [OFFERS] !! missing addr/owner in {names[:30]}")
            continue
        return url, det
    return None


def _pull_parcels(url: str, det: dict, zips: list[str]) -> dict:
    """Bulk-pull parcels (filtered by zip when we have them), keyed by
    normalized situs address -> {owner, mailing, value}."""
    out_fields = ",".join([f for f in (
        det["addr"], det["owner"], det["mail"], det["mcity"],
        det["mstate"], det["mzip"], det["value"], det["zip"]) if f])

    # build where: zip filter if we have zips + a zip field, else all
    where = "1=1"
    if zips and det["zip"]:
        # quote values; ArcGIS accepts quoted even for numeric fields on most servers
        vals = ",".join("'" + z + "'" for z in zips)
        where = f"{det['zip']} IN ({vals})"

    parcels, offset, sampled = {}, 0, 0
    while offset < PARCEL_CAP:
        try:
            r = httpx.get(f"{url}/query",
                          params={"where": where, "outFields": out_fields,
                                  "returnGeometry": "false", "resultRecordCount": PARCEL_PAGE,
                                  "resultOffset": offset, "f": "json"},
                          headers={"User-Agent": UA, "Accept": "application/json"},
                          timeout=60, follow_redirects=True)
            if r.status_code == 400 and where != "1=1":
                print(f"  [OFFERS] zip filter rejected — retrying unquoted")
                vals = ",".join(z for z in zips)
                where = f"{det['zip']} IN ({vals})"
                continue
            if r.status_code >= 400:
                print(f"  [OFFERS] parcel HTTP {r.status_code} at offset {offset}")
                break
            data = r.json()
            feats = data.get("features") if isinstance(data, dict) else None
            if not feats:
                break
            for f in feats:
                at = f.get("attributes") or {}
                na = _norm(at.get(det["addr"]))
                if not na:
                    continue
                owner = str(at.get(det["owner"]) or "").strip()
                mail = " ".join(str(at.get(det[k]) or "").strip()
                                for k in ("mail", "mcity", "mstate", "mzip") if det.get(k)).strip()
                mail = re.sub(r"\s+", " ", mail)
                val = _money(at.get(det["value"])) if det.get("value") else 0.0
                if sampled < 3:
                    print(f"  [OFFERS] sample parcel: addr={at.get(det['addr'])!r} "
                          f"owner={owner!r} mail={mail!r} value={val}")
                    sampled += 1
                if owner:
                    parcels[na] = {"owner": owner, "mailing": mail, "value": val}
            if len(feats) < PARCEL_PAGE or not data.get("exceededTransferLimit"):
                break
            offset += PARCEL_PAGE
        except Exception as e:
            print(f"  [OFFERS] parcel pull error at {offset}: {e}")
            break
    return parcels


def build_offers(states: Optional[list[str]] = None) -> dict:
    srcs = PARCEL_SOURCES
    if states:
        ss = [s.upper() for s in states]
        srcs = [s for s in PARCEL_SOURCES if s["state"] in ss]

    all_matched = []
    for src in srcs:
        leads = _fetch_fl_leads(src["state"])
        if not leads:
            print(f"  [OFFERS] {src['name']}: no leads")
            continue
        zips = sorted({(r.get("zip") or "").strip()[:5]
                       for r in leads if (r.get("zip") or "").strip()})
        zip_cov = sum(1 for r in leads if (r.get("zip") or "").strip()) / len(leads)
        print(f"  [OFFERS] {src['name']}: {len(leads):,} leads | "
              f"{len(zips)} distinct zips | zip coverage {zip_cov*100:.0f}%")

        resolved = _resolve_parcel(src)
        if not resolved:
            print(f"  [OFFERS] {src['name']}: could not resolve parcel layer")
            continue
        url, det = resolved

        parcels = _pull_parcels(url, det, zips)
        print(f"  [OFFERS] pulled {len(parcels):,} parcels with owners")

        # join
        by_norm = defaultdict(list)
        for r in leads:
            by_norm[_norm(r["property_address"])].append(r)
        matched = 0
        for na, pdata in parcels.items():
            for r in by_norm.get(na, []):
                mot = _motivation(r.get("reason"))
                all_matched.append({
                    "motivation": mot,
                    "owner_name": pdata["owner"],
                    "mailing_address": pdata["mailing"],
                    "property_address": r["property_address"],
                    "city": r.get("city", ""), "state": r.get("state", ""),
                    "zip": r.get("zip", ""), "reason": r.get("reason", ""),
                    "market_value": pdata["value"],
                    "source": r.get("source", ""),
                })
                matched += 1
        rate = 100 * matched / len(leads) if leads else 0
        print(f"  [OFFERS] {src['name']}: matched {matched:,}/{len(leads):,} ({rate:.1f}%)")

    if not all_matched:
        print("\n[OFFERS] 0 matched — no offer package produced.")
        return {"matched": 0, "written": 0}

    # rank: vacant first, then highest value; only rows we can price
    priced = [m for m in all_matched if m["market_value"] > 0]
    order = {"HOT": 0, "WARM": 1, "COOL": 2}
    priced.sort(key=lambda m: (order.get(m["motivation"], 1), -m["market_value"]))
    top = priced[:TOP_N]

    out = f"offer_package_top{TOP_N}_{date.today()}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for i, m in enumerate(top, 1):
            offer = round(m["market_value"] * (1 - DISCOUNT) / 500) * 500
            w.writerow({**m, "rank": i,
                        "market_value": int(m["market_value"]),
                        "offer_price": int(offer)})

    print("=" * 60)
    print(f"  OFFER PACKAGE — {date.today()}")
    print(f"  matched w/ owner: {len(all_matched):,} | priced (value>0): {len(priced):,}")
    print(f"  wrote top {len(top)} -> {out}  (offer = {int(DISCOUNT*100)}% under value)")
    if top:
        print(f"  #1: {top[0]['owner_name']} | {top[0]['property_address']} | "
              f"value ${int(top[0]['market_value']):,} | "
              f"offer ${int(round(top[0]['market_value']*(1-DISCOUNT)/500)*500):,}")
    print("=" * 60)
    return {"matched": len(all_matched), "priced": len(priced), "written": len(top), "file": out}


if __name__ == "__main__":
    build_offers()
