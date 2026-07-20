"""
Skip-trace via ZenRows (residential-proxy scraping API).

Free people-search sites (FastPeopleSearch etc.) hard-block datacenter IPs with
DataDome/captcha — proven (HTTP 403 from the runner). ZenRows routes the request
through residential proxies + JS rendering, which gets past that. So this is the
automated skip-trace path: given an owner name + city, fetch the people-search
page through ZenRows and pull the phone number(s).

Requires ZENROWS_API_KEY in the environment (a GitHub Actions secret — never
committed). No key => no-op (returns empty), so the pipeline still runs.

Compliance: phones here are for mailing/skip-trace of property owners you're
contacting about their own property. Calling/texting still falls under TCPA —
get consent or keep first contact to mail; honor opt-outs.
"""

import os
import re
import httpx

ZENROWS_KEY = os.getenv("ZENROWS_API_KEY", "")
_ZEN = "https://api.zenrows.com/v1/"
_PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
# strip the people-search site's own boilerplate numbers if they appear
_JUNK_PHONES = {"8005551212", "8888888888", "0000000000"}


def _digits(p: str) -> str:
    return re.sub(r"\D", "", p)


def _zenrows_get(target_url: str, js: bool = True) -> httpx.Response:
    params = {"url": target_url, "apikey": ZENROWS_KEY,
              "premium_proxy": "true", "proxy_country": "us"}
    if js:
        params["js_render"] = "true"
    return httpx.get(_ZEN, params=params, timeout=90)


def skiptrace_person(first: str, last: str, city: str, state: str = "FL") -> dict:
    """Return {'phones': [...], 'note': str} for an individual owner."""
    if not ZENROWS_KEY:
        return {"phones": [], "note": "no ZENROWS_API_KEY"}
    slug_city = re.sub(r"\s+", "-", (city or "").strip())
    target = f"https://www.fastpeoplesearch.com/name/{first}-{last}_{slug_city}-{state}".lower()
    try:
        r = _zenrows_get(target)
        if r.status_code != 200:
            return {"phones": [], "note": f"zenrows HTTP {r.status_code}"}
        seen, phones = set(), []
        for m in _PHONE_RE.findall(r.text):
            d = _digits(m)
            if len(d) == 10 and d not in _JUNK_PHONES and d not in seen:
                seen.add(d)
                phones.append(f"({d[:3]}) {d[3:6]}-{d[6:]}")
        return {"phones": phones[:3], "note": "ok" if phones else "no phone in page"}
    except Exception as e:
        return {"phones": [], "note": f"error {type(e).__name__}: {e}"}


def enabled() -> bool:
    return bool(ZENROWS_KEY)
