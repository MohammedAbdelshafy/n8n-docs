"""
Seller Lead opt-in endpoint.
Captures homeowners who VOLUNTARILY request a cash offer.
Every lead records consent + timestamp + IP = legally workable & sellable.
Auto-scores motivation so you (or your buyers) work the hottest first.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, validator
from typing import Optional
import re
from config import SUPABASE_URL, SUPABASE_KEY

router = APIRouter()

# Lazy client — created on first request, not at import time, so the app
# boots even before env vars are present (Railway first deploy).
_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise HTTPException(status_code=503, detail="Database not configured")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


class SellerLead(BaseModel):
    name:           str
    address:        str
    phone:          str
    email:          str
    timeline:       Optional[str] = None
    condition:      Optional[str] = None
    reason:         Optional[str] = None
    consent_given:  bool
    consent_text:   Optional[str] = None

    @validator("phone")
    def clean_phone(cls, v):
        d = re.sub(r"\D", "", v)
        if len(d) == 10:
            return f"+1{d}"
        if len(d) == 11 and d[0] == "1":
            return f"+{d}"
        raise ValueError("Valid 10-digit US phone required.")

    @validator("email")
    def clean_email(cls, v):
        if "@" not in v:
            raise ValueError("Valid email required.")
        return v.lower().strip()

    @validator("consent_given")
    def must_consent(cls, v):
        if not v:
            raise ValueError("Consent is required to submit.")
        return v


# ── Motivation scoring (higher = more likely to sell now) ─────
def score_motivation(lead: SellerLead) -> int:
    score = 30  # baseline for opting in at all

    timeline_pts = {"ASAP": 40, "1-3_MONTHS": 25, "3-6_MONTHS": 10, "JUST_CURIOUS": 0}
    score += timeline_pts.get(lead.timeline or "", 5)

    reason_pts = {"FINANCIAL": 20, "RELOCATING": 15, "INHERITED": 15,
                  "REPAIRS": 12, "TIRED_LANDLORD": 12, "OTHER": 5}
    score += reason_pts.get(lead.reason or "", 5)

    condition_pts = {"POOR": 10, "FAIR": 6, "GOOD": 3, "EXCELLENT": 1}
    score += condition_pts.get(lead.condition or "", 0)

    return min(100, score)


def parse_location(address: str) -> dict:
    """Best-effort parse of city/state/zip from a free-text address."""
    state_match = re.search(r"\b([A-Z]{2})\b", address.upper())
    zip_match   = re.search(r"\b(\d{5})\b", address)
    parts       = [p.strip() for p in address.split(",")]
    city        = parts[-2].strip() if len(parts) >= 2 else ""
    return {
        "city":  city,
        "state": state_match.group(1) if state_match else "",
        "zip":   zip_match.group(1) if zip_match else "",
    }


@router.post("/api/seller-lead")
async def seller_lead(req: SellerLead, request: Request):
    # Dedup by phone
    existing = _sb().table("seller_leads") \
        .select("id") \
        .eq("phone", req.phone) \
        .execute()
    if existing.data:
        return {"status": "already_submitted", "message": "We already have your details — offer on the way."}

    loc   = parse_location(req.address)
    score = score_motivation(req)
    now   = datetime.now(timezone.utc).isoformat()
    ip    = request.client.host if request.client else None

    row = {
        "name":              req.name,
        "phone":             req.phone,
        "email":             req.email,
        "property_address":  req.address,
        "city":              loc["city"],
        "state":             loc["state"],
        "zip":               loc["zip"],
        "timeline":          req.timeline,
        "reason":            req.reason,
        "condition":         req.condition,
        "consent_given":     True,
        "consent_timestamp": now,
        "consent_ip":        ip,
        "consent_text":      req.consent_text,
        "source":            "SELLER_LANDING_PAGE",
        "lead_score":        score,
        "status":            "NEW",
    }

    _sb().table("seller_leads").insert(row).execute()

    # Email confirmation to the seller
    try:
        from src.outreach.email_outreach import send_email
        first = req.name.split()[0]
        html = f"""<!DOCTYPE html><html><body style="font-family:Inter,Arial,sans-serif;background:#0a0f0c;padding:32px;color:#f0f0f0">
        <table width="520" style="background:#121814;border:1px solid #1f2a22;border-radius:16px;padding:36px;margin:0 auto">
        <tr><td>
        <h2 style="color:#27c065;margin:0 0 12px">Thanks, {first} — we got your details.</h2>
        <p style="color:#cdd6cf;font-size:15px;line-height:1.6">We're reviewing <strong>{req.address}</strong> and will get a fair, no-obligation cash offer to you within 24 hours.</p>
        <p style="color:#8a978f;font-size:13px;margin-top:20px">No fees. No repairs. Sell on your timeline. Reply STOP anytime to opt out.</p>
        </td></tr></table></body></html>"""
        send_email(req.email, "Your cash offer is on the way", html)
    except Exception as e:
        print(f"[SELLER LEAD] confirmation email failed: {e}")

    return {"status": "received", "lead_score": score, "message": "Offer on the way."}
