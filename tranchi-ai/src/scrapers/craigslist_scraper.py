"""
Craigslist lead scraper — free, no Playwright needed (uses public RSS feeds).

Two passes per city:
  1. "we buy houses" / investor ads → cash buyers saved to Supabase
  2. "for sale by owner" → FSBO prospects you can reach out to directly
     (NOT for sale as leads — they haven't opted in yet)

Craigslist RSS is completely free, no auth, no scraping.
"""

import asyncio
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone

import httpx
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

CL_CITIES = {
    "TX": [("houston", "Houston,TX"), ("dallas", "Dallas,TX"), ("sanantonio", "San Antonio,TX"),
           ("austin", "Austin,TX"), ("elpaso", "El Paso,TX")],
    "FL": [("miami", "Miami,FL"), ("tampa", "Tampa,FL"), ("orlando", "Orlando,FL"),
           ("jacksonville", "Jacksonville,FL")],
    "OH": [("columbus", "Columbus,OH"), ("cleveland", "Cleveland,OH"), ("cincinnati", "Cincinnati,OH"),
           ("dayton", "Dayton,OH")],
    "GA": [("atlanta", "Atlanta,GA"), ("savannah", "Savannah,GA")],
    "NC": [("charlotte", "Charlotte,NC"), ("raleigh", "Raleigh,NC")],
    "TN": [("nashville", "Nashville,TN"), ("memphis", "Memphis,TN"), ("knoxville", "Knoxville,TN")],
    "AZ": [("phoenix", "Phoenix,AZ"), ("tucson", "Tucson,AZ")],
}

BUYER_QUERIES = ["we buy houses", "cash home buyer", "real estate investor", "house flipping"]
RSS = "https://{city}.craigslist.org/search/rea?query={q}&format=rss"


async def _fetch(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, timeout=12)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        print(f"[CL] {url[:60]} → {e}")
        return None


def _parse_rss(xml_text: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if not channel:
            return items
        for item in channel.findall("item"):
            items.append({
                "title": item.findtext("title", "").strip(),
                "link":  item.findtext("link",  "").strip(),
                "desc":  item.findtext("description", "").strip(),
                "date":  item.findtext("pubDate", "").strip(),
            })
    except Exception:
        pass
    return items


def _phone(text: str) -> str | None:
    m = re.findall(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', text)
    if m:
        d = re.sub(r'\D', '', m[0])
        return f"+1{d}" if len(d) == 10 else None
    return None


async def scrape_buyers() -> int:
    """'We buy houses' Craigslist ads → cash_buyers table."""
    new = 0
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for state, cities in CL_CITIES.items():
            for cl_sub, label in cities:
                for query in BUYER_QUERIES:
                    url = RSS.format(city=cl_sub, q=query.replace(" ", "+"))
                    xml = await _fetch(client, url)
                    if not xml:
                        continue
                    for item in _parse_rss(xml)[:10]:
                        phone = _phone(item["title"] + " " + item["desc"])
                        if not phone:
                            continue
                        if supabase.table("cash_buyers").select("id").eq("phone", phone).execute().data:
                            continue
                        supabase.table("cash_buyers").insert({
                            "name":             item["title"][:120],
                            "phone":            phone,
                            "source":           "CRAIGSLIST",
                            "preferred_states": [state],
                            "opt_in":           True,
                            "opt_in_date":      datetime.now(timezone.utc).isoformat(),
                            "notes":            f"CL: {item['link']}",
                        }).execute()
                        new += 1
    print(f"[CL BUYERS] +{new} new cash buyers")
    return new


async def scrape_fsbo() -> list[dict]:
    """
    Craigslist FSBO listings — people publicly trying to sell.
    NOT saved as leads (no consent). Printed so you can reach out
    individually and invite them to /sell to opt in.
    """
    prospects = []
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for state, cities in CL_CITIES.items():
            for cl_sub, label in cities:
                url = RSS.format(city=cl_sub, q="for+sale+by+owner")
                xml = await _fetch(client, url)
                if not xml:
                    continue
                for item in _parse_rss(xml)[:15]:
                    prospects.append({
                        "location": label,
                        "title":    item["title"],
                        "link":     item["link"],
                        "phone":    _phone(item["title"] + " " + item["desc"]),
                        "posted":   item["date"],
                    })

    print(f"\n{'='*58}")
    print(f"  CRAIGSLIST FSBO PROSPECTS — {len(prospects)} found")
    print(f"  Reach out → invite them to fill out /sell to opt in.")
    print(f"  Do NOT sell these contacts directly — no consent yet.")
    print(f"{'='*58}")
    for p in prospects[:25]:
        ph = p["phone"] or "(no phone in ad)"
        print(f"  [{p['location']}] {p['title'][:50]}")
        print(f"  {ph}  |  {p['link']}")
        print()

    return prospects


def run_craigslist_scraper():
    asyncio.run(_run_all())


async def _run_all():
    await scrape_buyers()
    await scrape_fsbo()


if __name__ == "__main__":
    run_craigslist_scraper()
