"""
FSBO Outreach — AI-personalized cash offer emails to FSBO prospects.

Flow:
  1. Reads seller_leads WHERE source IN ('ZILLOW_FSBO','ZILLOW_EXPORT','CRAIGSLIST_FSBO')
     AND consent_given = FALSE AND status = 'NEW'
  2. Claude drafts a short, natural-sounding email for each property
  3. You review + send (or auto-send if EMAIL_AUTO_SEND=true in env)
  4. If they reply → update consent, mark status='RESPONDED' → now sellable

Goal: convert public FSBO listings into opt-in seller leads at $0 cost.
"""

import os
from anthropic import Anthropic
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, CLAUDE_MODEL, EMAIL_ADDRESS

supabase  = create_client(SUPABASE_URL, SUPABASE_KEY)
anthropic = Anthropic()

AUTO_SEND = os.getenv("EMAIL_AUTO_SEND", "false").lower() == "true"
MAX_PER_RUN = int(os.getenv("FSBO_OUTREACH_LIMIT", "20"))


SYSTEM = """You write short, human-sounding cold emails from a cash home buyer to
homeowners who listed their property For Sale By Owner on Zillow or Craigslist.

Rules:
- 4-6 sentences max. No fluff. No corporate language.
- Sound like a real person, not a company blast.
- Mention the specific address so they know you saw their listing.
- One clear ask: reply if interested in a cash offer.
- No clickbait subject lines. No "I came across your listing" clichés.
- Include STOP opt-out instruction at the end.
- Return ONLY valid JSON: {"subject": "...", "body": "..."}
  body = plain text (no HTML), under 200 words."""


def _draft_email(lead: dict) -> dict | None:
    addr   = lead.get("property_address", "")
    city   = lead.get("city", "")
    state  = lead.get("state", "")
    notes  = lead.get("notes", "")
    score  = lead.get("lead_score", 0)
    timeline = lead.get("timeline", "")

    urgency = ""
    if "DOM" in notes:
        import re
        m = re.search(r'(\d+) DOM', notes)
        if m:
            dom = int(m.group(1))
            if dom > 60:
                urgency = f"The property has been listed for {dom} days."
            elif dom > 30:
                urgency = f"It's been on market about {dom} days."
    if "PRICE REDUCED" in notes:
        urgency += " I noticed the price was recently reduced."

    prompt = f"""Write a cash buyer outreach email for this FSBO property:

Address: {addr}, {city}, {state}
Property notes: {notes}
Timeline urgency context: {urgency}
Seller motivation score: {score}/100

The buyer (me) pays cash, closes in 14 days, buys as-is, no agent fees.
Ask them to reply or call/text if they want a no-obligation cash offer."""

    try:
        resp = anthropic.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = resp.content[0].text.strip()
        # Strip markdown fences if present
        text = text.strip('`').strip()
        if text.startswith('json'):
            text = text[4:].strip()
        return json.loads(text)
    except Exception as e:
        print(f"  [FSBO AI] Draft error for {addr}: {e}")
        return None


def _send_email(to: str, subject: str, body: str) -> bool:
    try:
        from src.outreach.email_outreach import send_email
        # Wrap in minimal HTML for deliverability
        html = f"""<html><body style="font-family:Arial,sans-serif;font-size:15px;color:#222;line-height:1.7">
<p>{body.replace(chr(10), '<br>')}</p>
</body></html>"""
        send_email(to, subject, html)
        return True
    except Exception as e:
        print(f"  [FSBO EMAIL] Send error: {e}")
        return False


def run_fsbo_outreach(auto_send: bool = AUTO_SEND) -> dict:
    """
    Draft (and optionally send) outreach emails to FSBO prospects.
    Returns counts of drafted/sent/skipped.
    """
    leads = supabase.table("seller_leads") \
        .select("*") \
        .in_("source", ["ZILLOW_FSBO", "ZILLOW_EXPORT", "CRAIGSLIST_FSBO"]) \
        .eq("consent_given", False) \
        .eq("status", "NEW") \
        .order("lead_score", desc=True) \
        .limit(MAX_PER_RUN) \
        .execute().data or []

    print(f"\n[FSBO OUTREACH] {len(leads)} prospects to contact\n")

    drafted = 0
    sent    = 0
    skipped = 0

    for lead in leads:
        addr  = lead.get("property_address", "unknown")
        email = lead.get("email")

        # Draft the email regardless (for review)
        draft = _draft_email(lead)
        if not draft:
            skipped += 1
            continue

        drafted += 1

        print(f"  {'='*56}")
        print(f"  Property: {addr}")
        print(f"  Score:    {lead.get('lead_score',0)}/100")
        if email:
            print(f"  Email:    {email}")
        print(f"\n  SUBJECT: {draft['subject']}")
        print(f"\n  BODY:\n{draft['body']}")
        print()

        if email and auto_send:
            ok = _send_email(email, draft["subject"], draft["body"])
            if ok:
                sent += 1
                # Mark outreach attempted
                supabase.table("seller_leads") \
                    .update({"status": "OUTREACH_SENT"}) \
                    .eq("id", lead["id"]) \
                    .execute()
                print(f"  [SENT] → {email}")
        elif not email:
            print(f"  [NO EMAIL] Contact via phone: {lead.get('phone','—')} or Zillow listing")
        else:
            print(f"  [REVIEW] Set EMAIL_AUTO_SEND=true to auto-send, or copy above and send manually.")

    print(f"\n[FSBO OUTREACH] Drafted: {drafted} | Sent: {sent} | Skipped: {skipped}")
    print(f"[FSBO OUTREACH] When they reply → update status='RESPONDED', consent_given=TRUE")
    print(f"                Then: python main.py leads  ← to see sellable inventory\n")

    return {"drafted": drafted, "sent": sent, "skipped": skipped}


def mark_responded(lead_id: str, email: str = None, phone: str = None):
    """Call this when an FSBO prospect replies to your outreach. Makes them sellable."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    updates = {
        "status":            "RESPONDED",
        "consent_given":     True,
        "consent_timestamp": now,
        "consent_text":      (
            "Homeowner replied to direct outreach requesting a cash offer. "
            "Implied consent recorded at time of response."
        ),
    }
    if email:
        updates["email"] = email
    if phone:
        updates["phone"] = phone
    supabase.table("seller_leads").update(updates).eq("id", lead_id).execute()
    print(f"[RESPONDED] Lead {lead_id} is now consent_given=TRUE — sellable.")


if __name__ == "__main__":
    run_fsbo_outreach()
