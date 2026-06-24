"""HTML email templates for every outreach touchpoint."""


def deal_alert(
    buyer_name: str,
    address: str,
    city: str,
    state: str,
    ai_grade: str,
    arv: float,
    mao: float,
    opening_bid: float,
    beds: int,
    baths: float,
    sqft: int,
    auction_date: str,
    source: str,
    reply_email: str,
) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    first   = buyer_name.split()[0] if buyer_name else "Investor"
    spread  = arv - opening_bid
    grade_color = {"A+": "#22c55e", "A": "#22c55e", "B+": "#f59e0b", "B": "#f59e0b"}.get(ai_grade, "#6b7280")

    subject = f"[{ai_grade}] {beds}bd/{baths}ba {city}, {state} — ARV ${arv:,.0f} / Asking ${mao:,.0f}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0b;font-family:Inter,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0b;padding:32px 16px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#141416;border:1px solid #242428;border-radius:16px;overflow:hidden;max-width:100%;">

  <!-- Header -->
  <tr><td style="background:#141416;padding:28px 32px 0;">
    <p style="margin:0 0 4px;font-size:11px;color:#888;letter-spacing:1.5px;text-transform:uppercase;">Hola AI Deal Alert</p>
    <span style="display:inline-block;background:rgba(212,168,71,0.15);border:1px solid rgba(212,168,71,0.4);color:#D4A847;font-size:12px;font-weight:700;letter-spacing:1px;padding:4px 12px;border-radius:100px;">{ai_grade} DEAL</span>
  </td></tr>

  <!-- Address -->
  <tr><td style="padding:20px 32px 0;">
    <h1 style="margin:0;font-size:26px;font-weight:800;color:#f0f0f0;line-height:1.2;">{address}</h1>
    <p style="margin:6px 0 0;font-size:16px;color:#888;">{city}, {state} &nbsp;·&nbsp; {source.replace('_',' ')}</p>
  </td></tr>

  <!-- Stats row -->
  <tr><td style="padding:24px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="background:#1c1c1f;border:1px solid #242428;border-radius:10px;padding:14px 8px;width:23%;">
        <div style="font-size:22px;font-weight:800;color:#D4A847;">${arv:,.0f}</div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;">ARV</div>
      </td>
      <td width="3%"></td>
      <td align="center" style="background:#1c1c1f;border:1px solid #242428;border-radius:10px;padding:14px 8px;width:23%;">
        <div style="font-size:22px;font-weight:800;color:#f0f0f0;">${mao:,.0f}</div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;">Asking</div>
      </td>
      <td width="3%"></td>
      <td align="center" style="background:#1c1c1f;border:1px solid #242428;border-radius:10px;padding:14px 8px;width:23%;">
        <div style="font-size:22px;font-weight:800;color:#22c55e;">${spread:,.0f}</div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;">Spread</div>
      </td>
      <td width="3%"></td>
      <td align="center" style="background:#1c1c1f;border:1px solid #242428;border-radius:10px;padding:14px 8px;width:23%;">
        <div style="font-size:22px;font-weight:800;color:#f0f0f0;">{auction_date or 'TBD'}</div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px;">Auction</div>
      </td>
    </tr>
    </table>
  </td></tr>

  <!-- Details -->
  <tr><td style="padding:0 32px 24px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1c1c1f;border:1px solid #242428;border-radius:10px;">
    <tr>
      <td style="padding:12px 16px;border-right:1px solid #242428;">
        <div style="font-size:12px;color:#888;">Beds / Baths</div>
        <div style="font-size:15px;font-weight:600;color:#f0f0f0;margin-top:2px;">{beds} / {baths}</div>
      </td>
      <td style="padding:12px 16px;border-right:1px solid #242428;">
        <div style="font-size:12px;color:#888;">Sq Ft</div>
        <div style="font-size:15px;font-weight:600;color:#f0f0f0;margin-top:2px;">{sqft:,}</div>
      </td>
      <td style="padding:12px 16px;">
        <div style="font-size:12px;color:#888;">Close</div>
        <div style="font-size:15px;font-weight:600;color:#f0f0f0;margin-top:2px;">14 days AS-IS</div>
      </td>
    </tr>
    </table>
  </td></tr>

  <!-- CTA -->
  <tr><td style="padding:0 32px 32px;">
    <p style="margin:0 0 16px;font-size:15px;color:#ccc;">
      Hey {first} — this one clears our underwriting threshold. Cash only, AS-IS, 14-day close.
      First to confirm gets details and assignment docs.
    </p>
    <a href="mailto:{reply_email}?subject=YES — {address}&body=I'm interested in {address}, {city} {state}. Please send details."
       style="display:inline-block;background:#D4A847;color:#0a0a0b;font-weight:700;font-size:15px;padding:14px 28px;border-radius:10px;text-decoration:none;">
      Reply YES — I'm In
    </a>
    &nbsp;
    <a href="mailto:{reply_email}?subject=PASS — {address}"
       style="display:inline-block;background:#1c1c1f;border:1px solid #242428;color:#888;font-weight:600;font-size:14px;padding:14px 20px;border-radius:10px;text-decoration:none;">
      Pass
    </a>
  </td></tr>

  <!-- Footer -->
  <tr><td style="border-top:1px solid #242428;padding:20px 32px;">
    <p style="margin:0;font-size:11px;color:#444;line-height:1.6;">
      You're receiving this because you opted into the Hola AI deal list.
      To unsubscribe, reply with UNSUBSCRIBE in the subject line.
      Not a licensed broker. All properties sold AS-IS.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return subject, html


def opt_in_confirmation(buyer_name: str, states: list[str]) -> tuple[str, str]:
    first   = buyer_name.split()[0] if buyer_name else "Investor"
    states_str = ", ".join(states)
    subject = "You're on the Hola AI deal list"
    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:32px 16px;background:#0a0a0b;font-family:Inter,Arial,sans-serif;">
<table width="560" cellpadding="0" cellspacing="0" style="background:#141416;border:1px solid #242428;border-radius:16px;padding:40px;max-width:100%;margin:0 auto;">
<tr><td>
  <div style="width:56px;height:56px;background:rgba(212,168,71,0.15);border:2px solid #D4A847;border-radius:50%;display:flex;align-items:center;justify-content:center;margin-bottom:24px;">
    <span style="font-size:24px;color:#D4A847;">✓</span>
  </div>
  <h1 style="margin:0 0 8px;font-size:28px;font-weight:800;color:#f0f0f0;">You're in, {first}.</h1>
  <p style="margin:0 0 24px;font-size:16px;color:#888;line-height:1.6;">
    You'll get deal alerts for: <strong style="color:#D4A847;">{states_str}</strong><br>
    We only send deals that pass AI underwriting — no junk.
  </p>
  <div style="background:#1c1c1f;border:1px solid rgba(212,168,71,0.25);border-radius:12px;padding:20px;margin-bottom:24px;">
    <p style="margin:0;font-size:14px;color:#ccc;line-height:1.7;">
      <strong style="color:#D4A847;">What happens next:</strong><br>
      When we find a deal matching your buy box, you'll get an email with the address, ARV, asking price, and deal grade.
      Hit <strong>Reply YES</strong> to lock in details. First to respond gets the assignment docs.
    </p>
  </div>
  <p style="margin:0;font-size:12px;color:#444;line-height:1.6;">
    To unsubscribe, reply with UNSUBSCRIBE. No spam — deals only.
  </p>
</td></tr>
</table>
</body>
</html>"""
    return subject, html


def followup_email(
    buyer_name: str,
    address: str,
    city: str,
    state: str,
    arv: float,
    mao: float,
    auction_date: str,
    day: int,
    reply_email: str,
) -> tuple[str, str]:
    first = buyer_name.split()[0] if buyer_name else "Investor"

    if day == 1:
        subject = f"Following up — {city}, {state} deal ({auction_date})"
        body_text = (
            f"Hey {first}, just following up on the {city} property I sent yesterday. "
            f"ARV ${arv:,.0f}, asking ${mao:,.0f} AS-IS. Auction is coming up — "
            f"are you in or should I move to the next buyer?"
        )
    else:
        subject = f"Last chance — {city}, {state} AS-IS deal"
        body_text = (
            f"Hey {first}, closing out my buyer list for the {city} deal today. "
            f"ARV ${arv:,.0f} / asking ${mao:,.0f} / auction {auction_date}. "
            f"Reply YES to lock in or I'll move on."
        )

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:32px 16px;background:#0a0a0b;font-family:Inter,Arial,sans-serif;">
<table width="560" cellpadding="0" cellspacing="0" style="background:#141416;border:1px solid #242428;border-radius:16px;padding:36px;max-width:100%;margin:0 auto;">
<tr><td>
  <p style="margin:0 0 4px;font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase;">Hola AI — Follow Up</p>
  <h2 style="margin:0 0 16px;font-size:22px;font-weight:700;color:#f0f0f0;">{address}, {city} {state}</h2>
  <p style="margin:0 0 24px;font-size:15px;color:#ccc;line-height:1.7;">{body_text}</p>
  <a href="mailto:{reply_email}?subject=YES — {address}&body=I'm interested. Please send details."
     style="display:inline-block;background:#D4A847;color:#0a0a0b;font-weight:700;font-size:15px;padding:14px 28px;border-radius:10px;text-decoration:none;">
    Yes, I'm In
  </a>
  &nbsp;
  <a href="mailto:{reply_email}?subject=PASS — {address}"
     style="display:inline-block;background:#1c1c1f;border:1px solid #242428;color:#888;font-size:14px;padding:14px 20px;border-radius:10px;text-decoration:none;">
    Pass
  </a>
  <p style="margin:24px 0 0;font-size:11px;color:#444;">Reply UNSUBSCRIBE to come off this list.</p>
</td></tr>
</table>
</body>
</html>"""

    return subject, html


def meeting_confirmed(
    buyer_name: str,
    meet_link: str,
    time_str: str,
    property_address: str,
) -> tuple[str, str]:
    first   = buyer_name.split()[0] if buyer_name else "Investor"
    subject = f"Call confirmed — {time_str}"
    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:32px 16px;background:#0a0a0b;font-family:Inter,Arial,sans-serif;">
<table width="560" cellpadding="0" cellspacing="0" style="background:#141416;border:1px solid #242428;border-radius:16px;padding:36px;max-width:100%;margin:0 auto;">
<tr><td>
  <h2 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#f0f0f0;">Your call is confirmed, {first}.</h2>
  <p style="margin:0 0 24px;font-size:15px;color:#888;">{property_address}</p>
  <div style="background:#1c1c1f;border:1px solid rgba(212,168,71,0.3);border-radius:12px;padding:20px;margin-bottom:24px;">
    <p style="margin:0 0 8px;font-size:13px;color:#888;">Date &amp; Time</p>
    <p style="margin:0 0 16px;font-size:18px;font-weight:700;color:#f0f0f0;">{time_str}</p>
    <a href="{meet_link}" style="display:inline-block;background:#D4A847;color:#0a0a0b;font-weight:700;font-size:14px;padding:12px 24px;border-radius:8px;text-decoration:none;">
      Join Google Meet
    </a>
  </div>
  <p style="margin:0;font-size:13px;color:#666;">Agenda: review deal details, answer questions, confirm interest. 30 minutes.</p>
</td></tr>
</table>
</body>
</html>"""
    return subject, html
