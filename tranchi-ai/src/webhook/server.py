"""
Twilio Webhook Server (FastAPI)
Handles inbound SMS replies from buyers:
  "YES" / "INTERESTED" → auto-book Google Meet, send link
  "NO" / "PASS"        → mark cold in DB
  "STOP"               → permanent opt-out
  Other                → log the reply for manual review

Deploy this on Railway / Render / Fly.io and point your Twilio
phone number's "A MESSAGE COMES IN" webhook to:
  https://your-app.railway.app/sms/inbound
"""

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import re
import hashlib
import hmac
import base64
import os
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, TWILIO_AUTH_TOKEN
from src.meetings.google_meet import book_meeting_for_buyer
from src.outreach.buyer_outreach import handle_opt_out
from src.webhook.opt_in import router as opt_in_router

app      = FastAPI(title="Tranchi AI")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Mount the opt-in API
app.include_router(opt_in_router)

# Serve the funnel HTML files
FUNNEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "funnel")

@app.get("/")
async def landing():
    return FileResponse(os.path.join(FUNNEL_DIR, "index.html"))

@app.get("/thank-you.html")
async def thank_you():
    return FileResponse(os.path.join(FUNNEL_DIR, "thank-you.html"))

YES_PATTERNS  = re.compile(r"\b(yes|yeah|yep|interested|in|send|tell me more|details|absolutely|sure|let'?s go)\b", re.I)
NO_PATTERNS   = re.compile(r"\b(no|nope|pass|not interested|remove|don'?t|stop texting)\b", re.I)
STOP_PATTERNS = re.compile(r"^\s*stop\s*$", re.I)


# ============================================================
# TWILIO SIGNATURE VALIDATION
# ============================================================
def validate_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    s = request_url + sorted_params
    mac = hmac.new(TWILIO_AUTH_TOKEN.encode(), s.encode(), hashlib.sha1)
    computed = base64.b64encode(mac.digest()).decode()
    return hmac.compare_digest(computed, signature)


# ============================================================
# FIND WHICH PROPERTY THIS REPLY IS ABOUT
# ============================================================
def find_active_outreach(buyer_phone: str) -> tuple[str | None, str | None]:
    """Return (buyer_id, property_id) for the most recent SENT outreach to this number."""
    buyer_res = supabase.table("cash_buyers") \
        .select("id") \
        .eq("phone", buyer_phone) \
        .single() \
        .execute()

    if not buyer_res.data:
        return None, None

    buyer_id = buyer_res.data["id"]

    log_res = supabase.table("outreach_log") \
        .select("property_id") \
        .eq("buyer_id", buyer_id) \
        .eq("status", "SENT") \
        .order("sent_at", desc=True) \
        .limit(1) \
        .execute()

    if not log_res.data:
        return buyer_id, None

    property_id = log_res.data[0]["property_id"]
    return buyer_id, property_id


# ============================================================
# INBOUND SMS ENDPOINT
# ============================================================
@app.post("/sms/inbound", response_class=PlainTextResponse)
async def inbound_sms(
    request: Request,
    From: str  = Form(...),
    Body: str  = Form(...),
    To:   str  = Form(default=""),
):
    # Validate Twilio signature
    sig = request.headers.get("X-Twilio-Signature", "")
    params = dict(await request.form())
    if not validate_twilio_signature(str(request.url), params, sig):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    phone   = From.strip()
    message = Body.strip()
    print(f"[INBOUND] {phone}: {message}")

    # Hard stop — permanent opt-out
    if STOP_PATTERNS.match(message):
        handle_opt_out(phone)
        supabase.table("outreach_log") \
            .update({"status": "OPTED_OUT", "reply_text": message}) \
            .eq("status", "SENT") \
            .execute()
        # Twilio auto-handles STOP — no reply needed
        return ""

    buyer_id, property_id = find_active_outreach(phone)

    if not buyer_id:
        # Unknown number — log and ignore
        print(f"[INBOUND] Unknown number: {phone}")
        return ""

    # Update reply in outreach log
    supabase.table("outreach_log").insert({
        "buyer_id":    buyer_id,
        "property_id": property_id,
        "channel":     "SMS",
        "message":     message,
        "status":      "REPLIED",
        "reply_text":  message,
    }).execute()

    # Mark previous SENT record as replied
    supabase.table("outreach_log") \
        .update({"status": "REPLIED", "reply_text": message}) \
        .eq("buyer_id", buyer_id) \
        .eq("property_id", property_id) \
        .eq("status", "SENT") \
        .execute()

    if YES_PATTERNS.search(message):
        # Book the meeting automatically
        try:
            result = book_meeting_for_buyer(buyer_id, property_id)
            print(f"[MEET BOOKED] {result.get('meet_link')}")
        except Exception as e:
            print(f"[MEET ERROR] {e}")
            # Fallback — flag for manual callback
            supabase.table("cash_buyers") \
                .update({"status": "ACTIVE"}) \
                .eq("id", buyer_id) \
                .execute()

    elif NO_PATTERNS.search(message):
        # Mark cold — don't contact about this property again
        supabase.table("outreach_log") \
            .update({"status": "REJECTED"}) \
            .eq("buyer_id", buyer_id) \
            .eq("property_id", property_id) \
            .execute()
        print(f"[PASS] {phone} passed on property {property_id}")

    # Return empty 200 — Twilio doesn't need a reply body unless you want to auto-respond
    return ""


# ============================================================
# HEALTH CHECK
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "service": "Tranchi AI SMS Webhook"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.webhook.server:app", host="0.0.0.0", port=8000, reload=True)
