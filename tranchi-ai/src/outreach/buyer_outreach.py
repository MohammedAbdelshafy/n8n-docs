"""
Buyer Outreach — matches APPROVED properties to opted-in cash buyers
and sends Twilio SMS. Only contacts buyers who have opt_in=True.
"""

import json
from datetime import date, datetime
from twilio.rest import Client as TwilioClient
from supabase import create_client
from config import (
    SUPABASE_URL, SUPABASE_KEY,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio   = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

# Quiet hours: no texts before 9am or after 8pm local time
QUIET_HOUR_START = 9
QUIET_HOUR_END   = 20


# ============================================================
# MATCH BUYERS TO A PROPERTY
# ============================================================
def find_matching_buyers(prop: dict) -> list[dict]:
    state     = prop.get("state")
    arv       = prop.get("estimated_arv", 0)
    prop_type = prop.get("property_type", "SFR")

    result = supabase.table("cash_buyers") \
        .select("*") \
        .eq("opt_in", True) \
        .eq("opt_out", False) \
        .eq("status", "ACTIVE") \
        .execute()

    buyers = result.data or []

    matched = []
    for buyer in buyers:
        # State match
        preferred = buyer.get("preferred_states") or []
        if preferred and state not in preferred:
            continue

        # Property type match
        pref_types = buyer.get("preferred_property_types") or []
        if pref_types and prop_type not in pref_types:
            continue

        # Price ceiling check
        max_price = buyer.get("max_purchase_price")
        mao       = prop.get("mao", 0)
        if max_price and mao and mao > max_price:
            continue

        matched.append(buyer)

    return matched


# ============================================================
# SEND SMS VIA TWILIO
# ============================================================
def send_sms(to_number: str, message: str, buyer_id: str, property_id: str) -> dict:
    if not twilio:
        return {"status": "SKIPPED", "reason": "Twilio not configured — email-only mode"}

    current_hour = datetime.now().hour
    if not (QUIET_HOUR_START <= current_hour < QUIET_HOUR_END):
        return {
            "status": "SKIPPED",
            "reason": f"Quiet hours ({QUIET_HOUR_START}–{QUIET_HOUR_END}). Queued."
        }

    # Ensure STOP instructions included (carrier compliance)
    if "STOP" not in message:
        message += " Reply STOP to opt out."

    try:
        msg = twilio.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=to_number,
        )

        # Log the outreach
        supabase.table("outreach_log").insert({
            "buyer_id":    buyer_id,
            "property_id": property_id,
            "channel":     "SMS",
            "message":     message,
            "status":      "SENT",
        }).execute()

        return {"status": "SENT", "sid": msg.sid}

    except Exception as e:
        supabase.table("outreach_log").insert({
            "buyer_id":    buyer_id,
            "property_id": property_id,
            "channel":     "SMS",
            "message":     message,
            "status":      "FAILED",
        }).execute()
        return {"status": "FAILED", "error": str(e)}


# ============================================================
# HANDLE INBOUND STOP / OPT-OUT  (call from Twilio webhook)
# ============================================================
def handle_opt_out(phone: str) -> None:
    supabase.table("cash_buyers") \
        .update({"opt_out": True, "status": "BLACKLISTED"}) \
        .eq("phone", phone) \
        .execute()
    print(f"[OPT-OUT] {phone} removed from all future outreach.")


# ============================================================
# MAIN: SEND OUTREACH FOR ALL APPROVED PROPERTIES
# ============================================================
def run_outreach() -> dict:
    print("=" * 60)
    print(f"TRANCHI AI — Buyer Outreach | {date.today()}")
    print("=" * 60)

    # Get properties that are approved but haven't been sent yet
    result = supabase.table("auction_properties") \
        .select("*") \
        .eq("ai_status", "APPROVE") \
        .eq("status", "APPROVED") \
        .execute()

    properties = result.data or []
    print(f"Approved deals to broadcast: {len(properties)}")

    total_sent   = 0
    total_skipped = 0

    for prop in properties:
        prop_id  = prop["id"]
        sms_body = prop.get("sms_draft")
        addr     = prop.get("address", "?")

        if not sms_body:
            print(f"  [{addr}] No SMS draft — skipping")
            continue

        buyers = find_matching_buyers(prop)
        print(f"  [{addr}] Matched buyers: {len(buyers)}")

        sent_to_this_deal = 0

        for buyer in buyers:
            buyer_id = buyer["id"]
            phone    = buyer.get("phone")

            if not phone:
                continue

            # Don't spam — max 3 buyers per property per day
            if sent_to_this_deal >= 3:
                break

            # Check if already contacted about this property
            already_sent = supabase.table("outreach_log") \
                .select("id") \
                .eq("buyer_id", buyer_id) \
                .eq("property_id", prop_id) \
                .execute()

            if already_sent.data:
                continue

            result = send_sms(phone, sms_body, buyer_id, prop_id)

            if result["status"] == "SENT":
                total_sent += 1
                sent_to_this_deal += 1
                print(f"    -> {buyer.get('name')} ({phone}): SENT")
            else:
                total_skipped += 1
                print(f"    -> {buyer.get('name')} ({phone}): {result['status']}")

        # Mark as outreach initiated
        if sent_to_this_deal > 0:
            supabase.table("auction_properties") \
                .update({"status": "BIDDING"}) \
                .eq("id", prop_id) \
                .execute()

    summary = {"sms_sent": total_sent, "skipped": total_skipped}
    print(f"\nOutreach complete: {total_sent} SMS sent, {total_skipped} skipped")
    return summary


if __name__ == "__main__":
    run_outreach()
