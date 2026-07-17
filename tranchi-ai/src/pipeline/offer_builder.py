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

# FREE value source (replaces paid comps tools like Privy): the Miami-Dade
# Property Appraiser "Property Point View" — every property with just/assessed
# value, keyed by situs address. Matched by address, same as the owner layer.
VALUE_SOURCES = {
    "FL": {"name": "Miami-Dade Property Point View",
           "item": "bf92e51f90a8426cae904ebc15018067", "layer": 0},
}


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


MATCH_BATCH = 100        # normalized addresses per IN() query


def _match_parcels(url: str, det: dict, norm_addrs: list[str]) -> dict:
    """Query the parcel layer in batches by NORMALIZED situs address (the format
    the parcel feed already uses — '16 SE 2 ST'), keyed norm_addr ->
    {owner, mailing, value}. Avoids needing zips or a full-county pull."""
    out_fields = ",".join([f for f in (
        det["addr"], det["owner"], det["mail"], det["mcity"],
        det["mstate"], det["mzip"], det.get("value")) if f])
    parcels, sampled = {}, 0
    for i in range(0, len(norm_addrs), MATCH_BATCH):
        chunk = [a for a in norm_addrs[i:i + MATCH_BATCH] if a]
        if not chunk:
            continue
        vals = ",".join("'" + a.replace("'", "''") + "'" for a in chunk)
        try:
            # POST (form-encoded) — a GET puts all addresses in the URL, which
            # overflows the server's max URL length and 404s. POST has no limit.
            r = httpx.post(f"{url}/query",
                           data={"where": f"{det['addr']} IN ({vals})",
                                 "outFields": out_fields, "returnGeometry": "false",
                                 "f": "json"},
                           headers={"User-Agent": UA, "Accept": "application/json"},
                           timeout=50, follow_redirects=True)
            if r.status_code >= 400:
                print(f"  [OFFERS] match HTTP {r.status_code} (batch {i//MATCH_BATCH})")
                continue
            for f in (r.json() or {}).get("features", []) or []:
                at = f.get("attributes") or {}
                na = _norm(at.get(det["addr"]))
                if not na:
                    continue
                owner = str(at.get(det["owner"]) or "").strip()
                mail = re.sub(r"\s+", " ", " ".join(
                    str(at.get(det[k]) or "").strip()
                    for k in ("mail", "mcity", "mstate", "mzip") if det.get(k)).strip())
                val = _money(at.get(det["value"])) if det.get("value") else 0.0
                if sampled < 3:
                    print(f"  [OFFERS] sample match: addr={at.get(det['addr'])!r} "
                          f"owner={owner!r} mail={mail!r} value={val}")
                    sampled += 1
                if owner:
                    parcels[na] = {"owner": owner, "mailing": mail, "value": val}
        except Exception as e:
            print(f"  [OFFERS] match error (batch {i//MATCH_BATCH}): {e}")
    return parcels


def _resolve_value_layer(vsrc: dict) -> Optional[tuple]:
    """Return (url, addr_field, value_field) for a value layer; auto-detect fields."""
    for url in _candidate_urls(vsrc):
        try:
            meta = httpx.get(url, params={"f": "json"},
                             headers={"User-Agent": UA, "Accept": "application/json"},
                             timeout=30, follow_redirects=True).json()
        except Exception as e:
            print(f"  [OFFERS] value meta error {url}: {e}")
            continue
        fields = (meta or {}).get("fields")
        if not fields:
            continue
        names = [f.get("name") for f in fields if f.get("name")]
        addr = _pick_field(names, _ADDR_TOKENS)
        val = _pick_field(names, _VALUE_TOKENS)
        print(f"  [OFFERS] value layer {url} | addr={addr} value={val}")
        if addr and val:
            return url, addr, val
        print(f"  [OFFERS] value layer missing addr/value in {names[:30]}")
    return None


def _match_values(url: str, addr_field: str, value_field: str,
                  norm_addrs: list[str]) -> dict:
    """norm_addr -> market value, via batched POST (same as owner matching)."""
    out, sampled = {}, 0
    for i in range(0, len(norm_addrs), MATCH_BATCH):
        chunk = [a for a in norm_addrs[i:i + MATCH_BATCH] if a]
        if not chunk:
            continue
        vals = ",".join("'" + a.replace("'", "''") + "'" for a in chunk)
        try:
            r = httpx.post(f"{url}/query",
                           data={"where": f"{addr_field} IN ({vals})",
                                 "outFields": f"{addr_field},{value_field}",
                                 "returnGeometry": "false", "f": "json"},
                           headers={"User-Agent": UA, "Accept": "application/json"},
                           timeout=50, follow_redirects=True)
            if r.status_code >= 400:
                continue
            for f in (r.json() or {}).get("features", []) or []:
                at = f.get("attributes") or {}
                na = _norm(at.get(addr_field))
                v = _money(at.get(value_field))
                if na and v > 0:
                    out[na] = v
                    if sampled < 3:
                        print(f"  [OFFERS] sample value: {at.get(addr_field)!r} -> ${int(v):,}")
                        sampled += 1
        except Exception as e:
            print(f"  [OFFERS] value match error (batch {i//MATCH_BATCH}): {e}")
    return out


_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_ENTITY = re.compile(r"\b(LLC|INC|CORP|TRUST|CO|LP|LTD|PROPERTIES|HOLDINGS|"
                     r"ENTERP|BANK|ASSOC|PARTNERS|GROUP)\b", re.I)


def _skiptrace_probe(deals: list[dict]) -> None:
    """Honest, bounded attempt to get a phone free. Individuals only (LLCs need
    SunBiz, not people-search). These sites bot-wall datacenter IPs, so this
    mostly tells us definitively whether free auto skip-trace is even possible."""
    print("  ---- SKIP-TRACE PROBE (free) ----")
    tried = 0
    for m in deals:
        name = (m.get("owner_name") or "").strip()
        if _ENTITY.search(name):
            print(f"  [SKIPTRACE] {name}: entity-owned -> needs SunBiz, skipping people-search")
            continue
        parts = [p for p in re.sub(r"[^A-Za-z ]", "", name).split() if len(p) > 1]
        if len(parts) < 2:
            continue
        first, last = parts[0], parts[-1]
        city = (m.get("city") or "").replace(" ", "-")
        url = f"https://www.fastpeoplesearch.com/name/{first}-{last}_{city}-FL".lower()
        tried += 1
        try:
            r = httpx.get(url, timeout=15, follow_redirects=True,
                          headers={"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                  "Chrome/126 Safari/537.36")})
            phones = _PHONE_RE.findall(r.text) if r.status_code == 200 else []
            if phones:
                print(f"  [SKIPTRACE] {first} {last} ({city}): {r.status_code} -> {phones[:3]}")
            else:
                print(f"  [SKIPTRACE] {first} {last} ({city}): HTTP {r.status_code}, no phone "
                      f"(len {len(r.text)}) — likely blocked/captcha")
        except Exception as e:
            print(f"  [SKIPTRACE] {first} {last}: error {type(e).__name__}: {e}")
        if tried >= 4:
            break
    if not tried:
        print("  [SKIPTRACE] top deals are all entity-owned — free people-search N/A")


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

        # match by normalized situs address in batches (parcel feed is already
        # ordinal-stripped like '16 SE 2 ST', which is what _norm produces)
        by_norm = defaultdict(list)
        for r in leads:
            by_norm[_norm(r["property_address"])].append(r)
        parcels = _match_parcels(url, det, list(by_norm.keys()))
        print(f"  [OFFERS] matched {len(parcels):,} parcels with owners")

        # FREE value enrichment: if the owner layer has no value field, pull
        # just/assessed value from the county Property Appraiser layer by address.
        values = {}
        if not det.get("value") and src["state"] in VALUE_SOURCES:
            vres = _resolve_value_layer(VALUE_SOURCES[src["state"]])
            if vres:
                vurl, vaddr, vfield = vres
                values = _match_values(vurl, vaddr, vfield, list(parcels.keys()))
                print(f"  [OFFERS] enriched {len(values):,} parcels with a value")

        matched = 0
        for na, pdata in parcels.items():
            mv = pdata["value"] or values.get(na, 0.0)
            for r in by_norm.get(na, []):
                all_matched.append({
                    "motivation": _motivation(r.get("reason")),
                    "owner_name": pdata["owner"],
                    "mailing_address": pdata["mailing"],
                    "property_address": r["property_address"],
                    "city": r.get("city", ""), "state": r.get("state", ""),
                    "zip": r.get("zip", ""), "reason": r.get("reason", ""),
                    "market_value": mv,
                    "source": r.get("source", ""),
                })
                matched += 1
        rate = 100 * matched / len(leads) if leads else 0
        print(f"  [OFFERS] {src['name']}: matched {matched:,}/{len(leads):,} ({rate:.1f}%)")

    if not all_matched:
        print("\n[OFFERS] 0 matched — no offer package produced.")
        return {"matched": 0, "written": 0}

    # rank: vacant (HOT) first, then by value when we have it. Value is optional —
    # a yellow-letter offer works without a printed price ("cash, call for offer").
    order = {"HOT": 0, "WARM": 1, "COOL": 2}
    all_matched.sort(key=lambda m: (order.get(m["motivation"], 1), -m["market_value"]))
    top = all_matched[:TOP_N]
    priced = sum(1 for m in all_matched if m["market_value"] > 0)

    def _write(path, rows):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OUT_FIELDS, extrasaction="ignore")
            w.writeheader()
            for i, m in enumerate(rows, 1):
                mv = m["market_value"]
                offer = (int(round(mv * (1 - DISCOUNT) / 500) * 500) if mv > 0
                         else "CASH — CALL FOR OFFER")
                w.writerow({**m, "rank": i,
                            "market_value": int(mv) if mv > 0 else "",
                            "offer_price": offer})

    out = f"offer_package_top{TOP_N}_{date.today()}.csv"
    _write(out, top)
    # full mail-merge file — every matched owner, for a full mailing campaign
    full = f"offer_package_ALL_{date.today()}.csv"
    _write(full, all_matched)

    # masked TEASER — proof of quality to send a buyer before they pay. Real
    # city/zip/value/reason (shows it's legit), owner name + house number masked
    # and mailing address dropped (so the rows aren't usable until purchased).
    def _mask_name(n):
        parts = (n or "").split()
        return " ".join(p[0] + "***" for p in parts[:3]) if parts else "————"

    def _mask_addr(a):
        return re.sub(r"^\d+", lambda m: "X" * len(m.group()), a or "")

    teaser = f"teaser_sample_{date.today()}.csv"
    tfields = ["motivation", "owner_name", "property_address", "city", "state",
               "zip", "reason", "market_value", "offer_price"]
    with open(teaser, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tfields, extrasaction="ignore")
        w.writeheader()
        for m in top[:50]:
            mv = m["market_value"]
            offer = (int(round(mv * (1 - DISCOUNT) / 500) * 500) if mv > 0 else "CALL")
            w.writerow({"motivation": m["motivation"],
                        "owner_name": _mask_name(m["owner_name"]),
                        "property_address": _mask_addr(m["property_address"]),
                        "city": m["city"], "state": m["state"], "zip": m["zip"],
                        "reason": m["reason"],
                        "market_value": int(mv) if mv > 0 else "",
                        "offer_price": offer})

    # HOT DEALS — the biggest-spread targets worth a phone call. Estimated gross
    # spread = value * DISCOUNT (buy 25% under, resell near value). Ranked; only
    # deals with a real value. NOTE: value is the county ASSESSED value (often
    # below true market) and there's no repair estimate — treat as leads to
    # verify with real comps, not confirmed profit.
    # Rank the call list even when values are missing: vacant (HOT) first, then
    # ABSENTEE owners (mailing address != property = lives elsewhere = motivated),
    # then by spread when we have a value.
    def _absentee(m):
        pa = _norm(m.get("property_address"))
        ma = _norm(m.get("mailing_address"))
        return 0 if (pa and pa in ma) else 1     # 1 = absentee, ranked first
    for m in all_matched:
        m["_spread"] = int(round(m["market_value"] * DISCOUNT)) if m["market_value"] > 0 else 0
        m["_abs"] = _absentee(m)
    ranked = sorted(all_matched, key=lambda m: (0 if m["motivation"] == "HOT" else 1,
                                                0 if m["_abs"] else 1, -m["_spread"]))
    hot = ranked[:50]
    if hot:
        hpath = f"hot_deals_call_list_{date.today()}.csv"
        hfields = ["rank", "motivation", "absentee", "owner_name", "mailing_address",
                   "property_address", "city", "zip", "reason",
                   "assessed_value", "est_offer_25pct_under", "est_gross_spread"]
        with open(hpath, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hfields, extrasaction="ignore")
            w.writeheader()
            for i, m in enumerate(hot, 1):
                v = m["market_value"]
                w.writerow({"rank": i, "motivation": m["motivation"],
                            "absentee": "YES" if m["_abs"] else "no",
                            "owner_name": m["owner_name"],
                            "mailing_address": m["mailing_address"],
                            "property_address": m["property_address"],
                            "city": m["city"], "zip": m["zip"], "reason": m["reason"],
                            "assessed_value": int(v) if v > 0 else "",
                            "est_offer_25pct_under": int(round(v * (1 - DISCOUNT) / 500) * 500) if v > 0 else "",
                            "est_gross_spread": m["_spread"] if v > 0 else ""})
        print(f"  wrote {len(hot)} priority deals -> {hpath}")
        # print the top 10 so the user gets the actual list (CSV isn't visible in logs)
        print("  ---- TOP 10 DEALS TO CALL ----")
        for i, m in enumerate(hot[:10], 1):
            val = f"${int(m['market_value']):,}" if m["market_value"] > 0 else "n/a"
            abs_tag = "ABSENTEE" if m["_abs"] else "owner-occ"
            print(f"  {i}. {m['owner_name']} | {m['property_address']}, {m['city']} {m['zip']} "
                  f"| {m['motivation']}/{abs_tag} {m['reason']} | assessed {val} "
                  f"| mail-> {m['mailing_address']}")
        # honest free skip-trace PROBE on the top individual owners
        _skiptrace_probe(hot[:6])

    print("=" * 60)
    print(f"  OFFER PACKAGE — {date.today()}")
    print(f"  matched w/ owner+mailing: {len(all_matched):,} | with value: {priced:,}")
    print(f"  wrote top {len(top)} -> {out}")
    print(f"  wrote ALL {len(all_matched):,} -> {full}")
    print(f"  wrote masked teaser (50 rows) -> {teaser}")

    # BUYER prospects: an owner on 3+ distressed properties is an active
    # investor/landlord = a cash buyer to sell the packs to (and to assign
    # contracts to). We already have their mailing address.
    from collections import Counter as _C
    prop_by_owner: dict = defaultdict(set)
    mail_by_owner: dict = {}
    for m in all_matched:
        o = (m["owner_name"] or "").strip().upper()
        if not o or o in {"OWNER OF RECORD", ""}:
            continue
        prop_by_owner[o].add(m["property_address"])
        mail_by_owner.setdefault(o, m["mailing_address"])
    buyers = sorted(((o, len(p)) for o, p in prop_by_owner.items() if len(p) >= 3),
                    key=lambda x: -x[1])
    if buyers:
        bpath = f"buyer_prospects_{date.today()}.csv"
        with open(bpath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["owner_name", "mailing_address", "num_distressed_properties"])
            for o, n in buyers:
                w.writerow([o, mail_by_owner.get(o, ""), n])
        print(f"  wrote {len(buyers):,} cash-buyer prospects (3+ props) -> {bpath}")
    if top:
        t = top[0]
        print(f"  #1: {t['owner_name']} | {t['property_address']} ({t['motivation']}) "
              f"| mail-> {t['mailing_address']}")
    print("=" * 60)
    return {"matched": len(all_matched), "priced": priced,
            "written": len(top), "file": out, "full": full}


if __name__ == "__main__":
    build_offers()
