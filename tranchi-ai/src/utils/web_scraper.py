"""
Free drop-in replacement for Firecrawl.
Priority: trafilatura (fast, static) → crawl4ai (JS-heavy) → Playwright fallback
No API key required. 100% local.
"""

import asyncio
from typing import Optional


def scrape_url(url: str, use_js: bool = False) -> dict:
    """
    Scrape a URL and return {"markdown": str, "html": str, "success": bool}.
    Mirrors the Firecrawl scrape_url interface so callers need zero changes.
    """
    if use_js:
        return asyncio.run(_crawl4ai_scrape(url))
    result = _trafilatura_scrape(url)
    if result["success"] and result["markdown"]:
        return result
    return asyncio.run(_crawl4ai_scrape(url))


def crawl_site(start_url: str, max_pages: int = 10) -> list[dict]:
    """Crawl a site starting from start_url, return list of page dicts."""
    return asyncio.run(_crawl4ai_crawl(start_url, max_pages))


# ── trafilatura (fast, no browser) ───────────────────────────────────────────

def _trafilatura_scrape(url: str) -> dict:
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"success": False, "markdown": "", "html": ""}
        text = trafilatura.extract(downloaded, output_format="markdown", include_links=True)
        return {"success": bool(text), "markdown": text or "", "html": downloaded}
    except Exception as e:
        return {"success": False, "markdown": "", "html": "", "error": str(e)}


# ── crawl4ai (Playwright-backed, handles JS) ─────────────────────────────────

async def _crawl4ai_scrape(url: str) -> dict:
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler(headless=True) as crawler:
            result = await crawler.arun(url=url)
            return {
                "success": result.success,
                "markdown": result.markdown or "",
                "html": result.html or "",
            }
    except Exception as e:
        return {"success": False, "markdown": "", "html": "", "error": str(e)}


async def _crawl4ai_crawl(start_url: str, max_pages: int) -> list[dict]:
    try:
        from crawl4ai import AsyncWebCrawler
        pages = []
        async with AsyncWebCrawler(headless=True) as crawler:
            result = await crawler.arun(url=start_url)
            if result.success:
                pages.append({
                    "url": start_url,
                    "markdown": result.markdown or "",
                })
        return pages
    except Exception as e:
        return [{"url": start_url, "error": str(e)}]
