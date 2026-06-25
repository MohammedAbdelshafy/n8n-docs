"""
Lead Marketplace — sell your opt-in seller leads on free platforms.

Revenue model:
  - You have consent_given=TRUE seller leads from your /sell funnel
  - Investors pay $50–150 per verified opt-in motivated seller lead
  - You post anonymized teasers; serious buyers DM you for the full lead

Free channels to post on:
  1. Reddit: r/WholesaleRealEstate, r/realestateinvesting
  2. Facebook: "Real Estate Investors [TX/FL/OH/etc]" groups
  3. BiggerPockets: Marketplace > Wholesale Deals
  4. Craigslist: services/real estate in target cities

Run this to see your inventory and get copy-paste posts.
"""

from datetime import date
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase
LEAD_PRICE = 75   # your default ask per lead ($50 bulk, $100 hot)


def get_sellable_inventory() -> dict:
    """Fetch all sellable (consent_given=TRUE) leads, grouped by state."""
    leads = _sb().table("seller_leads") \
        .select("state, lead_score, timeline, status, city") \
        .eq("consent_given", True) \
        .eq("opt_out", False) \
        .neq("status", "SOLD") \
        .execute().data or []

    by_state: dict[str, list] = {}
    for l in leads:
        st = l.get("state") or "??"
        by_state.setdefault(st, []).append(l)

    hot  = [l for l in leads if (l.get("lead_score") or 0) >= 70]
    warm = [l for l in leads if 40 <= (l.get("lead_score") or 0) < 70]
    asap = [l for l in leads if l.get("timeline") == "ASAP"]

    return {
        "total":    len(leads),
        "hot":      hot,
        "warm":     warm,
        "asap":     asap,
        "by_state": by_state,
    }


def print_inventory():
    inv = get_sellable_inventory()
    print(f"\n{'='*55}")
    print(f"  SELLABLE LEAD INVENTORY — {date.today()}")
    print(f"{'='*55}")
    print(f"  Total opt-in leads:   {inv['total']}")
    print(f"  Hot (score 70+):      {len(inv['hot'])}")
    print(f"  Warm (40-69):         {len(inv['warm'])}")
    print(f"  ASAP timeline:        {len(inv['asap'])}")
    print(f"\n  By state:")
    for state, leads in sorted(inv["by_state"].items(), key=lambda x: -len(x[1])):
        hot_ct = sum(1 for l in leads if (l.get("lead_score") or 0) >= 70)
        hot_tag = f"  ({hot_ct} hot)" if hot_ct else ""
        print(f"    {state}: {len(leads)} leads{hot_tag}")
    rev = inv["total"] * LEAD_PRICE
    print(f"\n  Est. revenue @ ${LEAD_PRICE}/lead:  ${rev:,}")
    print(f"{'='*55}\n")
    return inv


def generate_reddit_post(inv: dict) -> str:
    """
    Ready-to-paste Reddit post for r/WholesaleRealEstate.
    Anonymous — no PII. Investors DM you, then you negotiate.
    """
    lines = ["[LEADS FOR SALE] Verified opt-in motivated seller leads\n"]
    lines.append(
        f"Have {inv['total']} seller leads available. All are consent-verified "
        f"— homeowners who voluntarily filled out a cash offer request form. "
        f"Consent timestamp + IP + signed disclosure on every record.\n"
    )

    if inv["by_state"]:
        lines.append("**Available by state:**")
        for state, leads in sorted(inv["by_state"].items(), key=lambda x: -len(x[1])):
            hot_ct = sum(1 for l in leads if (l.get("lead_score") or 0) >= 70)
            cities = list({l.get("city","") for l in leads if l.get("city")})[:3]
            city_str = f" ({', '.join(cities)})" if cities else ""
            hot_str = f" — {hot_ct} HOT" if hot_ct else ""
            lines.append(f"- **{state}**: {len(leads)} leads{city_str}{hot_str}")

    lines.append(f"\n**Pricing:**")
    lines.append(f"- Single lead: ${LEAD_PRICE}")
    lines.append(f"- 5+ leads: ${int(LEAD_PRICE * 0.85)}/each (15% off)")
    lines.append(f"- 10+ leads: ${int(LEAD_PRICE * 0.70)}/each (30% off)")
    lines.append("\n**What's included per lead:** name, phone, email, address, ")
    lines.append("timeline, condition, reason, motivation score, consent timestamp + IP")
    lines.append("\nDM me with what states/volume you need. Payment via Zelle/PayPal/Venmo.")
    lines.append("\n*Not a scrape — these are people who requested a cash offer on their home.*")

    return "\n".join(lines)


def generate_facebook_post(inv: dict) -> str:
    states = list(inv["by_state"].keys())
    state_str = ", ".join(states[:5])
    hot_ct = len(inv["hot"])
    total  = inv["total"]

    return f"""🏠 MOTIVATED SELLER LEADS — {state_str}

I have {total} verified opt-in leads available right now.
{hot_ct} are HOT (ASAP timeline, scored 70+).

✅ All consent-verified with timestamp + IP + signed disclosure
✅ Homeowners who requested a cash offer — NOT cold scrapes
✅ Includes: name, phone, email, address, timeline, condition, motivation score

Pricing:
• 1 lead = $75
• 5 leads = $60/each
• 10+ leads = $50/each

DM me with your target state(s) and volume.
Payment: Zelle · PayPal · Venmo

Comment "INTERESTED" below and I'll reach out. 👇"""


def generate_biggerpockets_post(inv: dict) -> str:
    states = list(inv["by_state"].keys())
    return f"""Verified Opt-In Motivated Seller Leads — {', '.join(states)}

I run a cash offer funnel (seller.html page) where homeowners voluntarily request a cash offer on their home. These aren't cold scraped contacts — every lead signed a TCPA-compliant consent form with timestamp, IP, and disclosure text.

Current inventory: {inv['total']} leads across {len(states)} states.
Hot leads (ASAP / score 70+): {len(inv['hot'])}

What you get per lead:
- Full contact info (name, phone, email, address)
- Motivation score (30–100 scale)
- Timeline (ASAP / 1-3 mo / 3-6 mo)
- Condition, reason for selling
- Consent timestamp + IP (your legal protection if you contact them)

Pricing: $75 single / $60 for 5-pack / $50 for 10+

DM me or reply here if you want to see a sample (redacted PII) before buying."""


def mark_lead_sold(lead_id: str):
    """Mark a lead as SOLD after you've transferred it to the buyer."""
    _sb().table("seller_leads").update({"status": "SOLD"}).eq("id", lead_id).execute()
    print(f"[MARKETPLACE] Lead {lead_id} marked SOLD.")


def run_lead_marketplace():
    inv = print_inventory()

    if inv["total"] == 0:
        print("No sellable leads yet. Drive traffic to /sell to collect opt-ins.")
        print("Run: python main.py prospects  ← to find FSBO prospects to invite\n")
        return

    print("\n── REDDIT POST (paste into r/WholesaleRealEstate) ──\n")
    print(generate_reddit_post(inv))

    print("\n── FACEBOOK POST (paste into investor groups) ──\n")
    print(generate_facebook_post(inv))

    print("\n── BIGGERPOCKETS MARKETPLACE ──\n")
    print(generate_biggerpockets_post(inv))


if __name__ == "__main__":
    run_lead_marketplace()
