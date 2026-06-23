"""
AI Underwriter — sends each PENDING property to Claude 3.5 Sonnet,
gets back a structured investment decision, and updates Supabase.
"""

import json
import asyncio
from datetime import date
from anthropic import Anthropic
from supabase import create_client
from config import (
    SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY, CLAUDE_MODEL,
    MAO_MULTIPLIER, FLAT_CLOSING_COST, FLAT_HOLDING_COST,
    REPAIR_RATE, CONDITION_MULTIPLIER, MIN_NET_PROFIT
)

client    = Anthropic(api_key=ANTHROPIC_API_KEY)
supabase  = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load the system prompt once
with open("prompts/underwriter_system_prompt.txt") as f:
    SYSTEM_PROMPT = f.read()


# ============================================================
# REPAIR COST ESTIMATE  (local fallback before Claude)
# ============================================================
def estimate_repairs(sqft: int, year_built: int, condition: str) -> float:
    if not sqft or not year_built:
        return 20_000  # default if missing

    if year_built < 1960:
        rate = REPAIR_RATE["pre_1960"]
    elif year_built < 1990:
        rate = REPAIR_RATE["1960_1990"]
    elif year_built < 2005:
        rate = REPAIR_RATE["1990_2005"]
    else:
        rate = REPAIR_RATE["post_2005"]

    multiplier = CONDITION_MULTIPLIER.get(condition, 1.0)
    if multiplier is None:
        return float("inf")  # TEARDOWN

    base = sqft * rate * multiplier
    return base + FLAT_CLOSING_COST + FLAT_HOLDING_COST


# ============================================================
# FETCH COMPS — free Zillow sold data (no API key needed)
# ============================================================
def fetch_comps(zip_code: str, sqft: int, beds: int = 0) -> list[dict]:
    """Pull recent sold comps from Zillow. Free, no API key needed."""
    from src.underwriter.free_comps import get_comps
    return get_comps(zip_code, sqft=sqft, beds=beds)


# ============================================================
# CORE: UNDERWRITE ONE PROPERTY
# ============================================================
def underwrite_property(prop: dict) -> dict:
    """
    Send property data to Claude, get back an investment decision.
    Returns the parsed JSON decision dict.
    """
    condition = prop.get("condition", "FAIR")

    # Auto-reject teardowns before spending API tokens
    if condition == "TEARDOWN":
        return {
            "status": "REJECT",
            "ai_grade": None,
            "reject_reason": "Property condition is TEARDOWN — not suitable for flip strategy.",
            "sms_draft": None,
        }

    comps = fetch_comps(prop.get("zip", ""), prop.get("sqft", 0), prop.get("bedrooms", 0))

    payload = {
        "address":       prop.get("address"),
        "city":          prop.get("city"),
        "state":         prop.get("state"),
        "year_built":    prop.get("year_built", 0),
        "sqft":          prop.get("sqft", 0),
        "bedrooms":      prop.get("bedrooms", 0),
        "bathrooms":     prop.get("bathrooms", 0),
        "condition":     condition,
        "property_type": prop.get("property_type", "SFR"),
        "opening_bid":   prop.get("opening_bid", 0),
        "source":        prop.get("source"),
        "nearby_comps":  comps,
    }

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Underwrite this property:\n\n{json.dumps(payload, indent=2)}"
            }
        ]
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude added them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    decision = json.loads(raw)
    return decision


# ============================================================
# SAVE DECISION BACK TO SUPABASE
# ============================================================
def save_decision(property_id: str, decision: dict) -> None:
    update = {
        "ai_status":          decision.get("status", "REVIEW"),
        "ai_grade":           decision.get("ai_grade"),
        "ai_notes":           decision.get("reject_reason") or json.dumps({
            "arv_basis":    decision.get("arv_basis"),
            "repair_basis": decision.get("repair_basis"),
            "flags":        decision.get("flags", []),
        }),
        "sms_draft":          decision.get("sms_draft"),
        "estimated_arv":      decision.get("estimated_arv"),
        "estimated_repairs":  decision.get("estimated_repairs"),
        "mao":                decision.get("mao"),
        "status": "APPROVED" if decision.get("status") == "APPROVE" else "NEW",
    }

    supabase.table("auction_properties") \
        .update(update) \
        .eq("id", property_id) \
        .execute()


# ============================================================
# BATCH: UNDERWRITE ALL PENDING PROPERTIES
# ============================================================
def run_underwriting() -> dict:
    print("=" * 60)
    print(f"TRANCHI AI — AI Underwriter | {date.today()}")
    print("=" * 60)

    # Pull all PENDING properties
    result = supabase.table("auction_properties") \
        .select("*") \
        .eq("ai_status", "PENDING") \
        .execute()

    properties = result.data or []
    print(f"Properties to underwrite: {len(properties)}")

    approved = 0
    rejected = 0
    errors   = 0

    for prop in properties:
        prop_id = prop["id"]
        addr    = prop.get("address", "Unknown")

        try:
            print(f"  Underwriting: {addr}...", end=" ")
            decision = underwrite_property(prop)
            save_decision(prop_id, decision)

            status = decision.get("status")
            grade  = decision.get("ai_grade", "")
            profit = decision.get("net_profit_estimate", 0)

            if status == "APPROVE":
                approved += 1
                print(f"APPROVED [{grade}] Est. profit: ${profit:,.0f}")
            else:
                rejected += 1
                reason = decision.get("reject_reason", "")
                print(f"REJECTED — {reason[:60]}")

        except json.JSONDecodeError as e:
            errors += 1
            print(f"JSON PARSE ERROR: {e}")
            supabase.table("auction_properties") \
                .update({"ai_status": "REVIEW", "ai_notes": f"Parse error: {e}"}) \
                .eq("id", prop_id) \
                .execute()

        except Exception as e:
            errors += 1
            print(f"ERROR: {e}")

    summary = {
        "total":    len(properties),
        "approved": approved,
        "rejected": rejected,
        "errors":   errors,
    }

    print(f"\nSummary: {approved} approved | {rejected} rejected | {errors} errors")
    return summary


if __name__ == "__main__":
    run_underwriting()
