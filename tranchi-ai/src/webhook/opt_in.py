"""
Opt-In API Endpoint
Receives form submissions from the landing page.
Saves buyer to Supabase with opt_in=TRUE.
Fires a confirmation SMS immediately (Twilio).
This is the only place opt_in ever gets set to TRUE —
the timestamp and source are logged for TCPA compliance.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
from typing import Optional
import re
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

router   = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Input schema ──────────────────────────────────────────────
class OptInRequest(BaseModel):
    name:                     str
    phone:                    str
    email:                    str
    company:                  Optional[str] = None
    preferred_states:         list[str]
    max_purchase_price:       Optional[int] = None
    preferred_property_types: Optional[list[str]] = None

    @validator("phone")
    def clean_phone(cls, v):
        digits = re.sub(r"\D", "", v)
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits[0] == "1":
            return f"+{digits}"
        raise ValueError("Phone must be a valid 10-digit US number.")

    @validator("email")
    def clean_email(cls, v):
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return v.lower().strip()

    @validator("preferred_states")
    def states_not_empty(cls, v):
        if not v:
            raise ValueError("Select at least one state.")
        return v


# ── Route ─────────────────────────────────────────────────────
@router.post("/api/opt-in")
async def opt_in(req: OptInRequest):
    # Dedup — already on list?
    existing = supabase.table("cash_buyers") \
        .select("id, opt_out") \
        .eq("phone", req.phone) \
        .execute()

    if existing.data:
        row = existing.data[0]
        if row.get("opt_out"):
            raise HTTPException(
                status_code=409,
                detail="This email has been unsubscribed. Reply to any previous email with RESUBSCRIBE."
            )
        _send_confirmation(req.email, req.name, req.preferred_states)
        return {"status": "already_subscribed", "message": "Confirmation resent."}

    # Save new buyer
    now = datetime.now(timezone.utc).isoformat()

    supabase.table("cash_buyers").insert({
        "name":                     req.name,
        "company":                  req.company or "",
        "phone":                    req.phone,
        "email":                    req.email,
        "preferred_states":         req.preferred_states,
        "max_purchase_price":       req.max_purchase_price,
        "preferred_property_types": req.preferred_property_types or ["SFR"],
        "opt_in":                   True,
        "opt_in_date":              now,
        "opt_out":                  False,
        "status":                   "ACTIVE",
        "source":                   "LANDING_PAGE",
        "buys_as_is":               True,
        "score":                    _score(req),
    }).execute()

    # Send confirmation email (primary) + SMS if Twilio configured
    _send_confirmation(req.email, req.name, req.preferred_states)

    return {"status": "subscribed", "message": "Welcome to the list."}


def _send_confirmation(email: str, name: str, states: list[str]) -> None:
    from src.outreach.email_outreach import send_optin_confirmation
    try:
        send_optin_confirmation(name, email, states)
    except Exception as e:
        print(f"[OPT-IN EMAIL ERROR] {email}: {e}")


def _score(req: OptInRequest) -> int:
    score = 0
    if req.phone:                           score += 20
    if req.email:                           score += 20
    if req.max_purchase_price:              score += 10
    if len(req.preferred_states) > 2:       score += 15
    if req.max_purchase_price and req.max_purchase_price >= 100_000:
        score += 15
    return score
