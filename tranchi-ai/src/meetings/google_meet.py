"""
Google Meet Auto-Scheduler
When a buyer replies YES to an SMS, this module:
  1. Creates a Google Calendar event with a Meet link
  2. Sends the link back via Twilio SMS
  3. Logs the meeting in Supabase
Requires: Google Calendar API credentials (service account or OAuth2)
"""

import json
import pytz
from typing import Optional
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from supabase import create_client
from twilio.rest import Client as TwilioClient
from config import (
    SUPABASE_URL, SUPABASE_KEY,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
)

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase
twilio   = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

GOOGLE_CREDENTIALS_FILE = "google_credentials.json"   # service account JSON
CALENDAR_ID             = "primary"                    # or specific calendar ID
YOUR_TIMEZONE           = "America/Chicago"            # adjust to your timezone
YOUR_NAME               = "Hola AI Acquisitions"
YOUR_EMAIL              = "your@email.com"             # override in .env


# ============================================================
# BUILD CALENDAR SERVICE
# ============================================================
def get_calendar_service():
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds)


# ============================================================
# FIND NEXT AVAILABLE SLOT  (next business day, 10am–4pm window)
# ============================================================
def find_next_slot(service, duration_minutes: int = 30) -> datetime:
    tz    = pytz.timezone(YOUR_TIMEZONE)
    now   = datetime.now(tz)
    start = now + timedelta(hours=2)  # minimum 2 hours notice

    # Push to next business day morning if after 3pm
    if start.hour >= 15:
        start = (start + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    # Skip weekends
    while start.weekday() >= 5:
        start += timedelta(days=1)
        start = start.replace(hour=10, minute=0, second=0, microsecond=0)

    # Round to next 30-min slot
    minutes = start.minute
    if minutes < 30:
        start = start.replace(minute=30)
    else:
        start = start.replace(minute=0) + timedelta(hours=1)

    # Check for conflicts
    end = start + timedelta(minutes=duration_minutes)
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
    ).execute()

    if events_result.get("items"):
        # Slot taken — try 1 hour later
        start = start + timedelta(hours=1)
        if start.hour >= 17:
            start = (start + timedelta(days=1)).replace(hour=10, minute=0)

    return start


# ============================================================
# CREATE GOOGLE MEET EVENT
# ============================================================
def create_meet_event(
    buyer_name: str,
    buyer_email: Optional[str],
    property_address: str,
    slot: datetime,
    duration_minutes: int = 30,
) -> dict:
    service = get_calendar_service()

    if slot is None:
        slot = find_next_slot(service, duration_minutes)

    tz  = pytz.timezone(YOUR_TIMEZONE)
    end = slot + timedelta(minutes=duration_minutes)

    event_body = {
        "summary": f"Deal Call — {property_address}",
        "description": (
            f"Hola AI deal review call with {buyer_name}.\n\n"
            f"Property: {property_address}\n"
            f"Agenda: Review deal details, answer questions, confirm interest."
        ),
        "start":  {"dateTime": slot.isoformat(), "timeZone": YOUR_TIMEZONE},
        "end":    {"dateTime": end.isoformat(),   "timeZone": YOUR_TIMEZONE},
        "conferenceData": {
            "createRequest": {
                "requestId": f"tranchi-{int(slot.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "attendees": [{"email": YOUR_EMAIL, "displayName": YOUR_NAME}],
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup",  "minutes": 30},
                {"method": "email",  "minutes": 60},
            ],
        },
    }

    if buyer_email:
        event_body["attendees"].append({"email": buyer_email, "displayName": buyer_name})

    event = service.events().insert(
        calendarId=CALENDAR_ID,
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates="all",
    ).execute()

    meet_link = event.get("hangoutLink") or \
        event.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri", "")

    return {
        "event_id":   event["id"],
        "meet_link":  meet_link,
        "start_time": slot.isoformat(),
        "end_time":   end.isoformat(),
    }


# ============================================================
# SEND MEET LINK VIA SMS
# ============================================================
def send_meet_confirmation(
    buyer_phone: str,
    buyer_name: str,
    meet_link: str,
    start_time: datetime,
    property_address: str,
) -> str:
    tz    = pytz.timezone(YOUR_TIMEZONE)
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time).astimezone(tz)

    time_str = start_time.strftime("%A %b %d @ %I:%M%p %Z")

    msg = (
        f"Hi {buyer_name.split()[0]}! Confirmed: Deal call {time_str}. "
        f"Property: {property_address}. "
        f"Join here: {meet_link} "
        f"Reply STOP to opt out."
    )

    twilio.messages.create(
        body=msg,
        from_=TWILIO_FROM_NUMBER,
        to=buyer_phone,
    )

    return msg


# ============================================================
# FULL FLOW: BUYER SAYS YES → MEET BOOKED → SMS SENT
# ============================================================
def book_meeting_for_buyer(
    buyer_id: str,
    property_id: str,
    slot: Optional[datetime] = None,
) -> dict:
    # Load buyer
    b_res = _sb().table("cash_buyers").select("*").eq("id", buyer_id).single().execute()
    buyer = b_res.data
    if not buyer:
        return {"error": "Buyer not found"}

    # Load property
    p_res = _sb().table("auction_properties").select("*").eq("id", property_id).single().execute()
    prop  = p_res.data
    if not prop:
        return {"error": "Property not found"}

    addr  = f"{prop.get('address')}, {prop.get('city')}, {prop.get('state')}"
    name  = buyer.get("name", "Investor")
    email = buyer.get("email")
    phone = buyer.get("phone")

    # Create the Meet
    event = create_meet_event(name, email, addr, slot)

    # SMS confirmation
    confirmation_sms = send_meet_confirmation(
        buyer_phone=phone,
        buyer_name=name,
        meet_link=event["meet_link"],
        start_time=event["start_time"],
        property_address=addr,
    )

    # Log in outreach
    _sb().table("outreach_log").insert({
        "buyer_id":    buyer_id,
        "property_id": property_id,
        "channel":     "SMS",
        "message":     confirmation_sms,
        "status":      "SENT",
    }).execute()

    # Mark property as having meeting booked
    _sb().table("auction_properties") \
        .update({"status": "BIDDING", "ai_notes": f"Meeting booked: {event['meet_link']}"}) \
        .eq("id", property_id) \
        .execute()

    print(f"[MEET BOOKED] {name} | {addr} | {event['meet_link']}")

    return {
        "buyer":     name,
        "property":  addr,
        "meet_link": event["meet_link"],
        "time":      event["start_time"],
    }
