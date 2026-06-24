"""
Lis Pendens Scraper — Free Pre-Foreclosure Leads from County Clerk Portals

Lis pendens = "suit pending" filed when a lender begins foreclosure.
The homeowner still owns the property and is highly motivated to sell fast.
This is gold-tier wholesale inventory — 30–90 days before auction.

Supported counties (all 100% free public records):
  FL: Miami-Dade, Broward, Orange (Orlando), Hillsborough (Tampa), Palm Beach
  TX: Harris (Houston), Dallas, Bexar (San Antonio)
  GA: Fulton (Atlanta), Gwinnett
  OH: Cuyahoga (Cleveland), Franklin (Columbus)

All contacts saved with consent_given=FALSE.
Only contact sellers who respond and opt in via the inbound webhook.
"""

import asyncio
import re
from datetime import date, timedelta
from typing import Optional

from playwright.async_api import async_playwright, Page
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

LOOKBACK_DAYS = 14   # pull last 2 weeks of filings

# ── County portal configs ──────────────────────────────────────────────────────
COUNTY_PORTALS = [
    {
        "name": "Miami-Dade",
        "state": "FL",
        "type": "miamidade",
        "url":  "https://www2.miamidadeclerk.gov/ocs/Search.aspx",
    },
    {
        "name": "Broward",
        "state": "FL",
        "type": "broward",
        "url":  "https://officialrecords.browardclerk.org/",
    },
    {
        "name": "Orange",
        "state": "FL",
        "type": "orange",
        "url":  "https://or.occompt.com/recorder/web/",
    },
    {
        "name": "Hillsborough",
        "state": "FL",
        "type": "hillsborough",
        "url":  "https://pubrec.hillsclerk.com/officialrecordssearch/",
    },
    {
        "name": "Palm Beach",
        "state": "FL",
        "type": "palmbeach",
        "url":  "https://or.pbcgov.com/",
    },
]


# ── Miami-Dade scraper ─────────────────────────────────────────────────────────
async def _scrape_miamidade(page: Page, start_date: str, end_date: str) -> list[dict]:
    results = []
    try:
        await page.goto("https://www2.miamidadeclerk.gov/ocs/Search.aspx", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Set document type to LIS PENDENS
        await page.fill("#cphPage_cphPage_txtDocType", "LIS PENDENS")

        # Set date range
        date_from = await page.query_selector("#cphPage_cphPage_txtDateFrom")
        date_to   = await page.query_selector("#cphPage_cphPage_txtDateTo")
        if date_from: await date_from.fill(start_date)
        if date_to:   await date_to.fill(end_date)

        # Click search
        await page.click("#cphPage_cphPage_btnNameSearch")
        await page.wait_for_load_state("networkidle", timeout=20000)

        # Parse results table
        rows = await page.query_selector_all("table.searchResults tr:not(:first-child)")
        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) < 5:
                continue
            texts = [await c.inner_text() for c in cells]
            # Typical columns: Doc Type | Recording Date | Grantor | Grantee | Book/Page | Legal
            grantor   = texts[2].strip() if len(texts) > 2 else ""
            rec_date  = texts[1].strip() if len(texts) > 1 else ""
            book_page = texts[4].strip() if len(texts) > 4 else ""
            legal     = texts[5].strip() if len(texts) > 5 else ""

            results.append({
                "seller_name":    grantor,
                "recording_date": rec_date,
                "book_page":      book_page,
                "legal_desc":     legal,
                "county":         "Miami-Dade",
                "state":          "FL",
            })

    except Exception as e:
        print(f"[LIS_PENDENS] Miami-Dade error: {e}")

    return results


# ── Broward scraper ────────────────────────────────────────────────────────────
async def _scrape_broward(page: Page, start_date: str, end_date: str) -> list[dict]:
    results = []
    try:
        await page.goto("https://officialrecords.browardclerk.org/", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Broward uses a different form layout — search by doc type
        doc_type_input = await page.query_selector("input[name*='DocType'], input[placeholder*='Document'], #DocType")
        if doc_type_input:
            await doc_type_input.fill("LP")   # Broward code for Lis Pendens

        date_from = await page.query_selector("input[name*='DateFrom'], #DateFrom, #StartDate")
        date_to   = await page.query_selector("input[name*='DateTo'], #DateTo, #EndDate")
        if date_from: await date_from.fill(start_date)
        if date_to:   await date_to.fill(end_date)

        search_btn = await page.query_selector("input[type='submit'], button[type='submit'], #btnSearch")
        if search_btn:
            await search_btn.click()
            await page.wait_for_load_state("networkidle", timeout=20000)

        rows = await page.query_selector_all("tr.searchRow, table tbody tr")
        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) < 3:
                continue
            texts  = [await c.inner_text() for c in cells]
            grantor = texts[2].strip() if len(texts) > 2 else ""
            rec_date = texts[1].strip() if len(texts) > 1 else ""
            if not grantor:
                continue
            results.append({
                "seller_name":    grantor,
                "recording_date": rec_date,
                "book_page":      texts[4].strip() if len(texts) > 4 else "",
                "legal_desc":     texts[-1].strip() if texts else "",
                "county":         "Broward",
                "state":          "FL",
            })

    except Exception as e:
        print(f"[LIS_PENDENS] Broward error: {e}")

    return results


# ── Generic table scraper (works for most FL county clerk portals) ─────────────
async def _scrape_generic(page: Page, portal: dict, start_date: str, end_date: str) -> list[dict]:
    results = []
    county = portal["name"]
    state  = portal["state"]
    try:
        await page.goto(portal["url"], timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        # Try to fill doc type field
        for sel in ["#DocType", "input[name*='DocType']", "input[placeholder*='Type']"]:
            el = await page.query_selector(sel)
            if el:
                await el.fill("LIS PENDENS")
                break

        # Fill date range
        for sel in ["#DateFrom", "#StartDate", "input[name*='DateFrom']"]:
            el = await page.query_selector(sel)
            if el:
                await el.fill(start_date)
                break
        for sel in ["#DateTo", "#EndDate", "input[name*='DateTo']"]:
            el = await page.query_selector(sel)
            if el:
                await el.fill(end_date)
                break

        # Submit
        for sel in ["#btnSearch", "input[type='submit']", "button[type='submit']"]:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_load_state("networkidle", timeout=20000)
                break

        rows = await page.query_selector_all("table tbody tr, tr.resultRow")
        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) < 3:
                continue
            texts = [await c.inner_text() for c in cells]
            grantor = ""
            rec_date = ""
            for i, t in enumerate(texts):
                t = t.strip()
                if re.match(r"\d{1,2}/\d{1,2}/\d{4}", t) and not rec_date:
                    rec_date = t
                elif len(t) > 5 and not grantor and i > 0:
                    grantor = t

            if grantor:
                results.append({
                    "seller_name":    grantor,
                    "recording_date": rec_date,
                    "book_page":      "",
                    "legal_desc":     texts[-1].strip() if texts else "",
                    "county":         county,
                    "state":          state,
                })

    except Exception as e:
        print(f"[LIS_PENDENS] {county} error: {e}")

    return results


# ── Address extraction from legal description ──────────────────────────────────
def _extract_address(legal_desc: str, seller_name: str) -> tuple[str, str, str, str]:
    """Best-effort address extraction from clerk record text."""
    address, city, state_code, zip_code = "", "", "FL", ""

    # Common patterns in FL legal descriptions
    addr_match = re.search(r"\d{3,5}\s+[A-Z][A-Za-z\s]+(?:ST|AVE|DR|RD|BLVD|WAY|LN|CT|CIR|PL)\b", legal_desc, re.IGNORECASE)
    if addr_match:
        address = addr_match.group(0).strip()

    zip_match = re.search(r"\b3[0-9]{4}\b", legal_desc)
    if zip_match:
        zip_code = zip_match.group(0)

    return address, city, state_code, zip_code


# ── Save to seller_leads ───────────────────────────────────────────────────────
def _save_leads(raw_leads: list[dict]) -> int:
    saved = 0
    for lead in raw_leads:
        if not lead.get("seller_name"):
            continue

        address, city, state_code, zip_code = _extract_address(
            lead.get("legal_desc", ""), lead.get("seller_name", "")
        )

        record = {
            "full_name":       lead["seller_name"],
            "address":         address or lead.get("legal_desc", "")[:100],
            "city":            city,
            "state":           lead.get("state", state_code),
            "zip":             zip_code,
            "source":          "LIS_PENDENS",
            "source_detail":   f"{lead.get('county', '')} County Clerk — {lead.get('recording_date', '')}",
            "lead_type":       "PRE_FORECLOSURE",
            "notes":           f"Book/Page: {lead.get('book_page', '')} | {lead.get('legal_desc', '')[:200]}",
            "consent_given":   False,
        }

        # Dedupe by seller name + source
        existing = (
            supabase.table("seller_leads")
            .select("id")
            .eq("full_name", record["full_name"])
            .eq("source", "LIS_PENDENS")
            .eq("source_detail", record["source_detail"])
            .execute()
        )
        if existing.data:
            continue

        try:
            result = supabase.table("seller_leads").insert(record).execute()
            if result.data:
                saved += 1
        except Exception as e:
            print(f"[LIS_PENDENS] DB save error: {e}")

    return saved


# ── Main entry ─────────────────────────────────────────────────────────────────
async def run_lis_pendens_scraper(counties: Optional[list[str]] = None) -> dict:
    end_dt   = date.today()
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    start_str = start_dt.strftime("%m/%d/%Y")
    end_str   = end_dt.strftime("%m/%d/%Y")

    portals = COUNTY_PORTALS
    if counties:
        portals = [p for p in portals if p["name"] in counties or p["state"] in counties]

    all_leads: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )

        for portal in portals:
            print(f"[LIS_PENDENS] Scraping {portal['name']}, {portal['state']} ({start_str} → {end_str})...")
            page = await context.new_page()

            if portal["type"] == "miamidade":
                leads = await _scrape_miamidade(page, start_str, end_str)
            elif portal["type"] == "broward":
                leads = await _scrape_broward(page, start_str, end_str)
            else:
                leads = await _scrape_generic(page, portal, start_str, end_str)

            print(f"  → {len(leads)} lis pendens found")
            all_leads.extend(leads)
            await page.close()

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
