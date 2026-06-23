"""
Multi-Touch Outreach Sequences
Runs automated follow-up cadence for each buyer × property pair.

Sequence (all via SMS since buyers opted in):
  Day 0:  Initial deal blast (sent by buyer_outreach.py)
  Day 1:  Follow-up if no reply — add urgency (auction date approaching)
  Day 3:  Final notice — "last chance, closing this out today"
  Reply YES at any point → auto-book Google Meet
  Reply NO → mark cold, move on
  Reply STOP → permanent opt-out
"""

from datetime import date, datetime, timedelta
from supabase import create_client
from twilio.rest import Client as TwilioClient
from config import SUPABASE_URL, SUPABASE_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
twilio   = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

QUIET_HOUR_START = 9
QUIET_HOUR_END   = 20


# ============================================================
# SEQUENCE TEMPLATES
# ============================================================
def build_day1_followup(buyer_name: str, address: str, city: str, arv: float, mao: float) -> str:
    first = buyer_name.split()[0] if buyer_name else "there"
    return (
        f"Hey {first}, following up on the {city} deal I sent yesterday. "
        f"ARV ${arv:,.0f}, asking ${mao:,.0f} AS-IS. "
        f"Auction's coming up fast — need to know if you're in. "
        f"Reply YES for details or NO to pass. -TranchiAI"
    )


def build_day3_final(buyer_name: str, address: str, city: str, arv: float, mao: float, auction_date: str) -> str:
    first = buyer_name.split()[0] if buyer_name else "there"
    return (
        f"{first} — last chance on {city}. "
        f"ARV ${arv:,.0f} / asking ${mao:,.0f}. "
        f"Auction {auction_date}. Closing my list today. "
        f"YES to lock in, else moving to next buyer. -TranchiAI"
    )


# ============================================================
# SEND ONE FOLLOW-UP
# ============================================================
def send_followup(to: str, message: str, buyer_id: str, property_id: str, sequence_day: int) -> bool:
    hour = datetime.now().hour
    if not (QUIET_HOUR_START <= hour < QUIET_HOUR_END):
        return False

    if "STOP" not in message:
        message += " Reply STOP to opt out."

    try:
        twilio.messages.create(body=message, from_=TWILIO_FROM_NUMBER, to=to)
        supabase.table("outreach_log").insert({
            "buyer_id":    buyer_id,
            "property_id": property_id,
            "channel":     "SMS",
            "message":     message,
            "status":      "SENT",
        }).execute()
        return True
    except Exception as e:
        print(f"[SEQUENCE] SMS error: {e}")
        return False


# ============================================================
# RUN ALL DUE FOLLOW-UPS
# ============================================================
def run_sequences() -> dict:
    print("=" * 60)
    print(f"TRANCHI AI — Outreach Sequences | {date.today()}")
    print("=" * 60)

    today     = date.today()
    sent_d1   = 0
    sent_d3   = 0

    # Find all SENT outreach (EMAIL or SMS) where status is still SENT (no reply)
    logs = supabase.table("outreach_log") \
        .select("*, cash_buyers(name, phone, email, opt_out), auction_properties(address, city, state, estimated_arv, mao, auction_date)") \
        .eq("status", "SENT") \
        .in_("channel", ["EMAIL", "SMS"]) \
        .execute()

    entries = logs.data or []

    for entry in entries:
        buyer    = entry.get("cash_buyers") or {}
        prop     = entry.get("auction_properties") or {}
        sent_at  = datetime.fromisoformat(entry["sent_at"].replace("Z", "+00:00")).date()
        days_ago = (today - sent_at).days

        if buyer.get("opt_out"):
            continue

        buyer_id    = entry["buyer_id"]
        property_id = entry["property_id"]
        phone       = buyer.get("phone")
        email       = buyer.get("email")
        name        = buyer.get("name", "Investor")
        city        = prop.get("city", "")
        address     = prop.get("address", "")
        arv         = prop.get("estimated_arv") or 0
        mao         = prop.get("mao") or 0
        auction_dt  = prop.get("auction_date") or "TBD"

        # Check if already received a follow-up today
        already = supabase.table("outreach_log") \
            .select("id") \
            .eq("buyer_id", buyer_id) \
            .eq("property_id", property_id) \
            .gte("sent_at", f"{today.isoformat()}T00:00:00") \
            .execute()

        if already.data:
            continue

        if days_ago == 1:
            # Email first, SMS fallback
            sent = False
            if email:
                from src.outreach.email_outreach import send_followup_email
                full_prop = supabase.table("auction_properties").select("*").eq("id", property_id).single().execute().data or {}
                full_buyer = supabase.table("cash_buyers").select("*").eq("id", buyer_id).single().execute().data or {}
                sent = send_followup_email(full_buyer, full_prop, day=1)
            if not sent and phone:
                msg = build_day1_followup(name, address, city, arv, mao)
                sent = send_followup(phone, msg, buyer_id, property_id, 1)
            if sent:
                sent_d1 += 1
                print(f"  [D1 FOLLOWUP] {name} — {city}")

        elif days_ago == 3:
            sent = False
            if email:
                from src.outreach.email_outreach import send_followup_email
                full_prop = supabase.table("auction_properties").select("*").eq("id", property_id).single().execute().data or {}
                full_buyer = supabase.table("cash_buyers").select("*").eq("id", buyer_id).single().execute().data or {}
                sent = send_followup_email(full_buyer, full_prop, day=3)
            if not sent and phone:
                msg = build_day3_final(name, address, city, arv, mao, str(auction_dt))
                sent = send_followup(phone, msg, buyer_id, property_id, 3)
            if sent:
                sent_d3 += 1
                print(f"  [D3 FINAL]    {name} — {city}")

        elif days_ago > 4:
            # No response after 4 days — mark cold
            supabase.table("outreach_log") \
                .update({"status": "NO_RESPONSE"}) \
                .eq("id", entry["id"]) \
                .execute()

    summary = {"day1_sent": sent_d1, "day3_sent": sent_d3}
    print(f"\nSequences fired: Day1={sent_d1} Day3={sent_d3}")
    return summary


if __name__ == "__main__":
    run_sequences()
