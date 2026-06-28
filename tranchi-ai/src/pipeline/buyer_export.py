"""
Buyer-List Export — turns your opted-in cash-buyer list into a sellable CSV.

Only exports buyers with opt_in = TRUE (and not opted out) — the legally
sellable kind, since the opt-in form discloses that contact details may be
shared with investors / partner lead services. Consent provenance is included
so the agency buying the list has proof.

Usage:
  python main.py export-buyers              # all states
  python main.py export-buyers TX FL        # filter states
"""

import csv
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


EXPORT_FIELDS = [
    "name", "company", "phone", "email", "website", "facebook",
    "address", "city", "state", "preferred_states", "max_purchase_price",
    "preferred_property_types", "score", "opt_in", "opt_in_date",
    "source", "created_at",
]


def export_buyers(states: Optional[list[str]] = None, out_path: str = None) -> str:
    q = _sb().table("cash_buyers").select("*").eq("opt_in", True)
    try:
        q = q.eq("opt_out", False)
    except Exception:
        pass
    rows = q.execute().data or []

    if states:
        rows = [r for r in rows if (r.get("state") or "").upper() in [s.upper() for s in states]]

    if not rows:
        print("No opted-in buyers to export yet.")
        print("  The list fills when investors sign up at /buyers (share the link).")
        return ""

    out_path = out_path or f"buyer_pack_{'_'.join(states) if states else 'ALL'}_{date.today()}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            for k in ("preferred_states", "preferred_property_types"):
                if isinstance(r.get(k), list):
                    r[k] = ", ".join(map(str, r[k]))
            w.writerow(r)

    fb = sum(1 for r in rows if r.get("facebook"))
    print(f"Exported {len(rows)} opt-in buyers → {out_path}")
    print(f"  Facebook-verified: {fb} | all consented (sellable with provenance)")
    print(f"  Suggested list price: ${len(rows) * 70:,} (@ $70/lead)")
    return out_path


def export_summary() -> dict:
    rows = _sb().table("cash_buyers").select("state,opt_in,facebook").eq("opt_in", True).execute().data or []
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r.get("state", "?")] = by_state.get(r.get("state", "?"), 0) + 1
    print("=" * 48)
    print(f"  SELLABLE BUYER INVENTORY — {date.today()}")
    print("=" * 48)
    print(f"  Total opted-in buyers: {len(rows)}")
    for st, n in sorted(by_state.items(), key=lambda x: -x[1]):
        print(f"    {st}: {n}")
    print(f"  Est. list value @ $70/lead: ${len(rows) * 70:,}")
    return {"total": len(rows), "by_state": by_state, "value_usd": len(rows) * 70}


if __name__ == "__main__":
    export_summary()
    export_buyers()
