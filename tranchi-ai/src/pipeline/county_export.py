"""
County Public-Records Export — CSV #3 (distressed properties).

Exports public-record foreclosure/sheriff-sale leads (source=COUNTY_RECORDS).
These come from public records, so they're sellable as a raw motivated-seller
list (the buyer skip-traces for phone). No opt-in consent applies — public data.
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

FIELDS = ["full_name", "address", "city", "state", "zip",
          "lead_type", "source_detail", "notes", "created_at"]


def export_county(states: Optional[list[str]] = None, out_path: str = None) -> str:
    rows = _sb().table("seller_leads").select("*").eq("source", "COUNTY_RECORDS").execute().data or []
    if states:
        ss = [s.upper() for s in states]
        rows = [r for r in rows if (r.get("state") or "").upper() in ss]

    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r.get("state", "?")] = by_state.get(r.get("state", "?"), 0) + 1

    print("=" * 48)
    print(f"  COUNTY DISTRESSED-PROPERTY INVENTORY — {date.today()}")
    print("=" * 48)
    print(f"  Total public-record leads: {len(rows)}")
    for st, n in sorted(by_state.items(), key=lambda x: -x[1]):
        print(f"    {st}: {n}")

    if not rows:
        print("  (none yet — run `python main.py county FL OH` to pull records)")
        return ""

    out_path = out_path or f"county_pack_{'_'.join(states) if states else 'ALL'}_{date.today()}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  Exported {len(rows)} distressed properties -> {out_path}")
    print(f"  (public records — sellable as raw motivated-seller list)")
    return out_path


if __name__ == "__main__":
    export_county()
