"""
Lis Pendens Scraper — Free Pre-Foreclosure Leads from County Clerk Portals

Lis pendens = "suit pending" filed when a lender begins foreclosure.
The homeowner still owns the property and is highly motivated to sell fast —
gold-tier wholesale inventory, 30–90 days before auction.

Resilience:
  - Best-effort form fill with multiple selector fallbacks per portal.
  - LLM extraction of whatever results render (robust to layout changes).
  - Every county wrapped so one broken portal never breaks the pipeline.
  - Updated portal URLs; dead ones are skipped gracefully.

All contacts saved with consent_given=FALSE.
Only contact sellers who respond and opt in via the inbound webhook.
"""

import asyncio
import json
import re
from datetime import date, timedelta
from typing import Optional

from config import SUPABASE_URL, SUPABASE_KEY

_supabase = None

def _sb():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

LOOKBACK_DAYS = 14   # pull last 2 weeks of filings

# ── County portal configs (updated URLs) ───────────────────────────────────────
COUNTY_PORTALS = [
    {"name": "Miami-Dade",   "state": "FL", "url": "https://onlineservices.miamidadeclerk.gov/officialrecords/StandardSearch.aspx"},
    {"name": "Broward",      "state": "FL", "url": "https://officialrecords.broward.org/AcclaimWeb/search/SearchTypeDocType"},
    {"name": "Orange",       "state": "FL", "url": "https://or.occompt.com/recorder/web/"},
    {"name": "Hillsborough", "state": "FL", "url": "https://publicrec.hillsclerk.com/Public/"},
    {"name": "Palm Beach",   "state": "FL", "url": "https://erec.mypalmbeachclerk.com/"},
    {"name": "Duval",        "state": "FL", "url": "https://or.duvalclerk.com/"},
    {"name": "Harris",       "state": "TX", "url": "https://www.cclerk.hctx.net/applications/websearch/RP.aspx"},
    {"name": "Fulton",       "state": "GA", "url": "https://search.gsccca.org/RealEstate/"},
    {"name": "Franklin",     "state": "OH", "url": "https://countyclerk.franklincountyohio.gov/records-search/"},
]

DOC_TYPE_TERMS = ["LIS PENDENS", "LISPENDENS", "LP", "NOTICE OF LIS PENDENS"]


# ── LLM extraction of whatever results render ──────────────────────────────────
def _llm_extract_filings(content: str, county: str, state: str) -> list[dict]:
    from src.utils.free_llm import call_llm

    system = (
        "You extract foreclosure 'lis pendens' court filings from county clerk pages. "
        "Return ONLY a JSON array. Each item: {seller_name, recording_date, address, "
        "legal_desc, book_page}. If none found, return []."
    )
    prompt = (
        f"County: {county}, {state}. From this official-records page, extract every "
        f"LIS PENDENS / foreclosure filing. The 'seller_name' is the defendant / "
        f"grantor / property owner being foreclosed on (not the bank/plaintiff).\n\n"
        f"PAGE CONTENT:\n{content[:50_000]}"
    )
    try:
        raw = call_llm(system, prompt, max_tokens=3000).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        items = json.loads(raw)
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f"[LIS_PENDENS] {county}: LLM extract failed: {e}")
        return []


# ── Best-effort form-driven search, then LLM-extract the result page ───────────
async def _scrape_portal(context, portal: dict, start_date: str, end_date: str) -> list[dict]:
    name  = portal["name"]
    state = portal["state"]
    url   = portal["url"]
    page  = await context.new_page()

    try:
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ico}", lambda r: r.abort())
        await page.goto(url, timeout=40000, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # Best-effort: set a document-type field if present
        for sel in ["#cphPage_cphPage_txtDocType", "#DocType", "input[name*='DocType']",
                    "input[placeholder*='Document']", "input[placeholder*='Type']",
                    "select[name*='DocType']"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.fill("LIS PENDENS")
                    break
            except Exception:
                continue

        # Best-effort: set date range
        for sel in ["#cphPage_cphPage_txtDateFrom", "#DateFrom", "#StartDate",
                    "input[name*='DateFrom']", "input[name*='FromDate']"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(start_date)
                    break
            except Exception:
                continue
        for sel in ["#cphPage_cphPage_txtDateTo", "#DateTo", "#EndDate",
                    "input[name*='DateTo']", "input[name*='ToDate']"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(end_date)
                    break
            except Exception:
                continue

        # Best-effort: submit
        for sel in ["#cphPage_cphPage_btnNameSearch", "#btnSearch",
                    "input[type='submit']", "button[type='submit']",
                    "button:has-text('Search')", "a:has-text('Search')"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        await asyncio.sleep(4)
                    break
            except Exception:
                continue

        content = await page.content()
        low = content.lower()
        if any(m in low for m in ["captcha", "access denied", "just a moment", "request blocked"]):
            print(f"[LIS_PENDENS] {name}: blocked (captcha/bot wall) — skipping")
            return []

        raw = _llm_extract_filings(content, name, state)
        for r in raw:
            r["county"] = name
            r["state"]  = state
        return raw

    except Exception as e:
        print(f"[LIS_PENDENS] {name} error: {e}")
        return []
    finally:
        try:
            await page.close()
        except Exception:
            pass


# ── Address extraction from legal description ──────────────────────────────────
def _extract_address(legal_desc: str, state: str) -> tuple[str, str, str]:
    address, city, zip_code = "", "", ""
    addr_match = re.search(
        r"\d{2,6}\s+[A-Z0-9][A-Za-z0-9\s.]+?(?:ST|STREET|AVE|AVENUE|DR|DRIVE|RD|ROAD|"
        r"BLVD|WAY|LN|LANE|CT|COURT|CIR|CIRCLE|PL|PLACE|TER|TERRACE|TRL|HWY|PKWY)\b",
        legal_desc, re.IGNORECASE,
    )
    if addr_match:
        address = addr_match.group(0).strip()
    zip_match = re.search(r"\b\d{5}\b", legal_desc)
    if zip_match:
        zip_code = zip_match.group(0)
    return address, city, zip_code


# ── Save to seller_leads ───────────────────────────────────────────────────────
def _save_leads(raw_leads: list[dict]) -> int:
    saved = 0
    for lead in raw_leads:
        name = (lead.get("seller_name") or "").strip()
        if not name or len(name) < 3:
            continue

        legal = lead.get("legal_desc", "") or ""
        address = (lead.get("address") or "").strip()
        if not address:
            address, _, _ = _extract_address(legal, lead.get("state", "FL"))

        _, city, zip_code = _extract_address(legal, lead.get("state", "FL"))

        record = {
            "full_name":     name,
            "address":       address or legal[:100],
            "city":          city,
            "state":         lead.get("state", "FL"),
            "zip":           zip_code,
            "source":        "LIS_PENDENS",
            "source_detail": f"{lead.get('county', '')} County Clerk — {lead.get('recording_date', '')}",
            "lead_type":     "PRE_FORECLOSURE",
            "notes":         f"Book/Page: {lead.get('book_page', '')} | {legal[:200]}",
            "consent_given": False,
        }

        try:
            existing = (
                _sb().table("seller_leads")
                .select("id")
                .eq("full_name", record["full_name"])
                .eq("source", "LIS_PENDENS")
                .eq("source_detail", record["source_detail"])
                .execute()
            )
            if existing.data:
                continue
            result = _sb().table("seller_leads").insert(record).execute()
            if result.data:
                saved += 1
        except Exception as e:
            print(f"[LIS_PENDENS] DB save error: {e}")

    return saved


# ── Main entry ─────────────────────────────────────────────────────────────────
async def run_lis_pendens_scraper(counties: Optional[list[str]] = None) -> dict:
    from playwright.async_api import async_playwright

    end_dt    = date.today()
    start_dt  = end_dt - timedelta(days=LOOKBACK_DAYS)
    start_str = start_dt.strftime("%m/%d/%Y")
    end_str   = end_dt.strftime("%m/%d/%Y")

    portals = COUNTY_PORTALS
    if counties:
        portals = [p for p in portals if p["name"] in counties or p["state"] in counties]

    all_leads: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="en-US",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        for portal in portals:
            print(f"[LIS_PENDENS] {portal['name']}, {portal['state']} ({start_str} → {end_str})...")
            try:
                leads = await _scrape_portal(context, portal, start_str, end_str)
            except Exception as e:
                print(f"[LIS_PENDENS] {portal['name']} fatal: {e}")
                leads = []
            print(f"  → {len(leads)} lis pendens found")
            all_leads.extend(leads)
            await asyncio.sleep(2)

        await browser.close()

    saved = _save_leads(all_leads)
    print(f"[LIS_PENDENS] Total found: {len(all_leads)} | Saved to DB: {saved}")

    return {
        "total_found": len(all_leads),
        "saved":       saved,
        "counties":    [p["name"] for p in portals],
    }


if __name__ == "__main__":
    asyncio.run(run_lis_pendens_scraper())
