"""
Deal Manager — daily summary, KPI tracking, and pipeline health report.
Prints to console and can post to Slack.
"""

import httpx
import json
from datetime import date, timedelta
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase
TARGET_DEALS_PER_DAY   = 2
TARGET_WEEKLY_REVENUE  = 18_000


# ============================================================
# DAILY DEAL SUMMARY
# ============================================================
def get_daily_summary() -> dict:
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    # Today's ingestion
    new_props = _sb().table("auction_properties") \
        .select("id", count="exact") \
        .gte("created_at", today) \
        .execute()

    # Approved today
    approved = _sb().table("auction_properties") \
        .select("id, address, city, state, ai_grade, estimated_arv, mao, sms_draft", count="exact") \
        .eq("ai_status", "APPROVE") \
        .gte("created_at", today) \
        .execute()

    # Active deals
    active_deals = _sb().table("active_deals") \
        .select("*") \
        .eq("status", "OPEN") \
        .execute()

    # Closed this week
    closed_week = _sb().table("closed_deals") \
        .select("net_profit") \
        .gte("closed_at", week_ago) \
        .execute()

    weekly_revenue = sum(d.get("net_profit", 0) for d in (closed_week.data or []))
    deals_closed   = len(closed_week.data or [])

    # Best current opportunity
    hot = _sb().table("auction_properties") \
        .select("address, city, state, ai_grade, estimated_arv, mao, opening_bid, sms_draft") \
        .eq("ai_status", "APPROVE") \
        .eq("status", "APPROVED") \
        .order("estimated_arv", desc=True) \
        .limit(1) \
        .execute()

    best_deal = hot.data[0] if hot.data else None

    return {
        "date":            today,
        "new_properties":  new_props.count or 0,
        "approved_today":  approved.count or 0,
        "approved_deals":  approved.data or [],
        "active_pipeline": len(active_deals.data or []),
        "deals_closed_7d": deals_closed,
        "revenue_7d":      weekly_revenue,
        "revenue_gap":     max(0, TARGET_WEEKLY_REVENUE - weekly_revenue),
        "best_deal":       best_deal,
    }


# ============================================================
# CLOSE A DEAL  (call when you've assigned/sold to a buyer)
# ============================================================
def close_deal(deal_id: str, sale_price: float, assignment_fee: float) -> dict:
    deal = _sb().table("active_deals") \
        .select("*, auction_properties(address, source)") \
        .eq("id", deal_id) \
        .single() \
        .execute()

    if not deal.data:
        return {"error": "Deal not found"}

    d    = deal.data
    prop = d.get("auction_properties", {})

    purchase = d.get("purchase_price", 0)
    title    = d.get("title_cost", 0) or 0
    holding  = d.get("holding_cost", 0) or 0
    misc     = d.get("misc_cost", 0) or 0
    net      = assignment_fee - title - holding - misc

    # Update active deal
    _sb().table("active_deals") \
        .update({
            "sale_price":       sale_price,
            "assignment_fee":   assignment_fee,
            "closing_date_sell": date.today().isoformat(),
            "status":           "CLOSED",
        }) \
        .eq("id", deal_id) \
        .execute()

    # Archive to closed_deals
    _sb().table("closed_deals").insert({
        "deal_id":          deal_id,
        "property_address": prop.get("address"),
        "purchase_price":   purchase,
        "sale_price":       sale_price,
        "net_profit":       net,
        "source":           prop.get("source"),
    }).execute()

    # Update property status
    if d.get("property_id"):
        _sb().table("auction_properties") \
            .update({"status": "CLOSED"}) \
            .eq("id", d["property_id"]) \
            .execute()

    print(f"[CLOSED] Deal {deal_id} | Net profit: ${net:,.0f}")
    return {"deal_id": deal_id, "net_profit": net, "status": "CLOSED"}


# ============================================================
# PRINT DAILY REPORT
# ============================================================
def print_daily_report() -> None:
    s = get_daily_summary()

    rev   = s["revenue_7d"]
    gap   = s["revenue_gap"]
    deals = s["deals_closed_7d"]

    pct   = min(100, int((rev / TARGET_WEEKLY_REVENUE) * 100))
    bar   = ("█" * (pct // 10)).ljust(10, "░")

    print("\n" + "=" * 60)
    print("  TRANCHI AI — DAILY DEAL REPORT")
    print("=" * 60)
    print(f"  Date:               {s['date']}")
    print(f"  New Properties:     {s['new_properties']}")
    print(f"  Approved Today:     {s['approved_today']}")
    print(f"  Active Pipeline:    {s['active_pipeline']} deals")
    print(f"  Closed (7 days):    {deals} deals")
    print(f"\n  Weekly Revenue:     ${rev:>10,.0f}")
    print(f"  Target ($18K/wk):   ${TARGET_WEEKLY_REVENUE:>10,.0f}")
    print(f"  Gap to Target:      ${gap:>10,.0f}")
    print(f"  Progress:           [{bar}] {pct}%")

    if s["best_deal"]:
        b = s["best_deal"]
        spread = (b.get("estimated_arv", 0) or 0) - (b.get("opening_bid", 0) or 0)
        print(f"\n  HOT DEAL [{b.get('ai_grade','')}]")
        print(f"  {b.get('address')}, {b.get('city')}, {b.get('state')}")
        print(f"  ARV: ${b.get('estimated_arv',0):,.0f}  |  Bid from: ${b.get('opening_bid',0):,.0f}")
        print(f"  MAO: ${b.get('mao',0):,.0f}  |  Spread: ${spread:,.0f}")
        if b.get("sms_draft"):
            print(f"\n  SMS: {b['sms_draft']}")

    print("=" * 60)

    # Next action recommendation
    if s["approved_today"] >= TARGET_DEALS_PER_DAY:
        print("  STATUS: On track. Send buyer outreach now.")
    elif s["new_properties"] == 0:
        print("  ACTION: Run scraper — no new properties ingested today.")
    else:
        print(f"  ACTION: Only {s['approved_today']} deals approved. Review REVIEW-status properties.")

    print()


if __name__ == "__main__":
    print_daily_report()
