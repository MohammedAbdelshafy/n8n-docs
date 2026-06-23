"""
Lead Export — turns opt-in seller leads into a sellable CSV pack.
Only exports leads with consent_given = TRUE (the legally sellable kind).
Includes the consent timestamp + text so the buyer has provenance.
"""

import csv
import io
from datetime import date
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def export_seller_leads(
    state: str = None,
    min_score: int = 0,
    status: str = "NEW",
    out_path: str = None,
) -> str:
    """Export opt-in seller leads to CSV. Returns the file path."""
    q = supabase.table("seller_leads") \
        .select("*") \
        .eq("consent_given", True) \
        .eq("opt_out", False) \
        .gte("lead_score", min_score)

    if state:
        q = q.eq("state", state)
    if status:
        q = q.eq("status", status)

    leads = (q.order("lead_score", desc=True).execute().data) or []

    if not leads:
        print("No exportable leads match the filter.")
        return ""

    out_path = out_path or f"lead_pack_{state or 'ALL'}_{date.today()}.csv"

    fields = [
        "name", "phone", "email", "property_address", "city", "state", "zip",
        "timeline", "reason", "condition", "lead_score",
        "consent_given", "consent_timestamp", "source", "created_at",
    ]

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

    print(f"Exported {len(leads)} opt-in leads → {out_path}")
    print(f"  (consent provenance included — these are legally sellable)")
    return out_path


def export_summary() -> dict:
    """Quick stats on your sellable lead inventory."""
    all_leads = supabase.table("seller_leads") \
        .select("state, lead_score, status, consent_given") \
        .eq("consent_given", True) \
        .eq("opt_out", False) \
        .execute().data or []

    by_state = {}
    hot = 0
    for l in all_leads:
        st = l.get("state") or "??"
        by_state[st] = by_state.get(st, 0) + 1
        if (l.get("lead_score") or 0) >= 70:
            hot += 1

    print("\n" + "=" * 44)
    print("  SELLABLE LEAD INVENTORY (opt-in only)")
    print("=" * 44)
    print(f"  Total leads:     {len(all_leads)}")
    print(f"  Hot (score 70+): {hot}")
    print(f"  By state:        {by_state}")
    print("=" * 44 + "\n")

    return {"total": len(all_leads), "hot": hot, "by_state": by_state}


if __name__ == "__main__":
    export_summary()
    export_seller_leads(min_score=50)
