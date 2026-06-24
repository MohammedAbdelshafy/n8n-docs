"""
Email outreach via Gmail SMTP.
Zero cost. Works immediately with a Gmail App Password.
No Twilio needed — this is the primary channel until phone is configured.

Setup (2 minutes):
  1. Google Account → Security → 2-Step Verification → enable
  2. Google Account → Security → App passwords → Mail → Generate
  3. Copy the 16-char password → paste into .env as EMAIL_APP_PASSWORD
"""

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, datetime
from typing import Optional
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from src.outreach.email_templates import (
    deal_alert, opt_in_confirmation, followup_email, meeting_confirmed
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

EMAIL_ADDRESS     = os.getenv("EMAIL_ADDRESS", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_SMTP_HOST   = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT   = int(os.getenv("EMAIL_SMTP_PORT", "587"))
REPLY_TO_EMAIL    = os.getenv("REPLY_TO_EMAIL", EMAIL_ADDRESS)


# ── Core send function ────────────────────────────────────────
def send_email(to: str, subject: str, html: str, from_name: str = "Hola AI") -> bool:
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print(f"[EMAIL] Not configured — set EMAIL_ADDRESS + EMAIL_APP_PASSWORD in .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{EMAIL_ADDRESS}>"
    msg["To"]      = to
    msg["Reply-To"] = REPLY_TO_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL] Send error to {to}: {e}")
        return False


# ── Send deal alert to one buyer ──────────────────────────────
def send_deal_email(buyer: dict, prop: dict) -> bool:
    email = buyer.get("email")
    if not email:
        return False

    subject, html = deal_alert(
        buyer_name  = buyer.get("name", "Investor"),
        address     = prop.get("address", ""),
        city        = prop.get("city", ""),
        state       = prop.get("state", ""),
        ai_grade    = prop.get("ai_grade", "B"),
        arv         = float(prop.get("estimated_arv") or 0),
        mao         = float(prop.get("mao") or 0),
        opening_bid = float(prop.get("opening_bid") or 0),
        beds        = int(prop.get("bedrooms") or 0),
        baths       = float(prop.get("bathrooms") or 0),
        sqft        = int(prop.get("sqft") or 0),
        auction_date= str(prop.get("auction_date") or "TBD"),
        source      = prop.get("source", ""),
        reply_email = REPLY_TO_EMAIL,
    )

    sent = send_email(email, subject, html)

    if sent:
        supabase.table("outreach_log").insert({
            "buyer_id":    buyer["id"],
            "property_id": prop["id"],
            "channel":     "EMAIL",
            "message":     subject,
            "status":      "SENT",
        }).execute()

    return sent


# ── Opt-in confirmation email ─────────────────────────────────
def send_optin_confirmation(name: str, email: str, states: list[str]) -> bool:
    subject, html = opt_in_confirmation(name, states)
    return send_email(email, subject, html)


# ── Follow-up emails ──────────────────────────────────────────
def send_followup_email(buyer: dict, prop: dict, day: int) -> bool:
    email = buyer.get("email")
    if not email:
        return False

    subject, html = followup_email(
        buyer_name  = buyer.get("name", "Investor"),
        address     = prop.get("address", ""),
        city        = prop.get("city", ""),
        state       = prop.get("state", ""),
        arv         = float(prop.get("estimated_arv") or 0),
        mao         = float(prop.get("mao") or 0),
        auction_date= str(prop.get("auction_date") or "TBD"),
        day         = day,
        reply_email = REPLY_TO_EMAIL,
    )

    sent = send_email(email, subject, html)

    if sent:
        supabase.table("outreach_log").insert({
            "buyer_id":    buyer["id"],
            "property_id": prop["id"],
            "channel":     "EMAIL",
            "message":     f"Day {day} followup: {subject}",
            "status":      "SENT",
        }).execute()

    return sent


# ── Meeting confirmation email ────────────────────────────────
def send_meeting_email(
    buyer_email: str,
    buyer_name: str,
    meet_link: str,
    start_time: datetime,
    property_address: str,
) -> bool:
    import pytz
    tz = pytz.timezone(os.getenv("YOUR_TIMEZONE", "America/Chicago"))
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time).astimezone(tz)
    time_str = start_time.strftime("%A %B %d @ %I:%M %p %Z")

    subject, html = meeting_confirmed(buyer_name, meet_link, time_str, property_address)
    return send_email(buyer_email, subject, html)


# ── Main outreach run (email-first) ──────────────────────────
def run_email_outreach() -> dict:
    print("=" * 60)
    print(f"TRANCHI AI — Email Outreach | {date.today()}")
    print("=" * 60)

    props = supabase.table("auction_properties") \
        .select("*") \
        .eq("ai_status", "APPROVE") \
        .eq("status", "APPROVED") \
        .execute()

    properties = props.data or []
    print(f"Approved deals to broadcast: {len(properties)}")

    total_sent = 0

    for prop in properties:
        prop_id = prop["id"]

        buyers = supabase.table("cash_buyers") \
            .select("*") \
            .eq("opt_in", True) \
            .eq("opt_out", False) \
            .eq("status", "ACTIVE") \
            .execute()

        sent_this_deal = 0

        for buyer in (buyers.data or []):
            if sent_this_deal >= 5:
                break

            # State match
            pref = buyer.get("preferred_states") or []
            if pref and prop.get("state") not in pref:
                continue

            # Already contacted?
            already = supabase.table("outreach_log") \
                .select("id") \
                .eq("buyer_id", buyer["id"]) \
                .eq("property_id", prop_id) \
                .execute()
            if already.data:
                continue

            sent = send_deal_email(buyer, prop)
            if sent:
                total_sent += 1
                sent_this_deal += 1
                print(f"  EMAIL → {buyer.get('name')} ({buyer.get('email')})")

        if sent_this_deal > 0:
            supabase.table("auction_properties") \
                .update({"status": "BIDDING"}) \
                .eq("id", prop_id) \
                .execute()

    print(f"\nEmails sent: {total_sent}")
    return {"emails_sent": total_sent}


if __name__ == "__main__":
    run_email_outreach()
