"""
Discord deal alerts — posts rich embeds to a channel webhook.

Set DISCORD_WEBHOOK_URL in Railway Variables to enable.
If the var is missing, all calls are silent no-ops.
"""

import os
import httpx
from datetime import date

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

GRADE_COLOR = {"A": 0x00C851, "B": 0x33B5E5, "C": 0xFFBB33}
REJECT_COLOR = 0xFF4444
SUMMARY_COLOR = 0x7289DA


def _post(payload: dict) -> None:
    if not WEBHOOK_URL:
        return
    try:
        httpx.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"[DISCORD] notify failed: {e}")


def notify_approved_deal(prop: dict, decision: dict) -> None:
    grade  = decision.get("ai_grade", "C") or "C"
    profit = decision.get("net_profit_estimate") or 0
    arv    = decision.get("estimated_arv") or 0
    mao    = decision.get("mao") or 0
    bid    = prop.get("opening_bid") or 0
    addr   = prop.get("address", "Unknown")
    city   = prop.get("city", "")
    state  = prop.get("state", "")
    source = prop.get("source", "")
    url    = prop.get("source_url") or ""

    color = GRADE_COLOR.get(grade, 0x00C851)

    embed = {
        "title": f"🏠 Grade {grade} Deal — {addr}",
        "description": f"{city}, {state} · Source: {source}",
        "color": color,
        "url": url or None,
        "fields": [
            {"name": "Opening Bid",      "value": f"${bid:,.0f}",    "inline": True},
            {"name": "MAO (70% rule)",   "value": f"${mao:,.0f}",    "inline": True},
            {"name": "Est. ARV",         "value": f"${arv:,.0f}",    "inline": True},
            {"name": "Est. Net Profit",  "value": f"${profit:,.0f}", "inline": True},
            {"name": "AI Grade",         "value": grade,             "inline": True},
        ],
        "footer": {"text": f"Hola AI · {date.today()}"},
    }

    if not url:
        del embed["url"]

    _post({"embeds": [embed]})


def notify_daily_summary(summary: dict) -> None:
    total    = summary.get("total", 0)
    approved = summary.get("approved", 0)
    rejected = summary.get("rejected", 0)
    errors   = summary.get("errors", 0)

    embed = {
        "title": f"📊 Daily Pipeline Summary — {date.today()}",
        "color": SUMMARY_COLOR,
        "fields": [
            {"name": "Underwritten", "value": str(total),    "inline": True},
            {"name": "✅ Approved",  "value": str(approved), "inline": True},
            {"name": "❌ Rejected",  "value": str(rejected), "inline": True},
            {"name": "⚠️ Errors",   "value": str(errors),   "inline": True},
        ],
        "footer": {"text": "Hola AI · check Supabase for full deal details"},
    }

    _post({"embeds": [embed]})


def notify_pipeline_started(mode: str = "all") -> None:
    _post({
        "embeds": [{
            "title": "🚀 Pipeline Started",
            "description": f"Mode: `{mode}` · {date.today()}",
            "color": 0x99AAB5,
            "footer": {"text": "Hola AI"},
        }]
    })
