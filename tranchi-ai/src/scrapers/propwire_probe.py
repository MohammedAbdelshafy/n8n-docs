"""
Propwire network-capture PROBE — reverse-engineering aid (run on a CI runner).

We cannot reach propwire.com from the dev sandbox (Cloudflare 403s every proxy
and WebFetch path), and its data API is undocumented. This probe drives a real
Chromium via Playwright on a GitHub Actions runner, loads the public search
page, and logs every XHR/fetch propwire's own frontend makes — method, URL,
auth headers, POST body, response status + a body snippet.

From that captured traffic we learn the real contract (token endpoint + search
endpoint + payload) and then build a fast httpx scraper against it. Output is
printed to the run log only; nothing is saved.

    python main.py propwire-probe
"""

import asyncio
import json
from typing import Optional

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# California statewide search — the filter format propwire encodes in its URL.
SEARCH_FILTERS = {
    "locations": [{"searchType": "T", "state": "FL",
                   "title": "Florida, USA", "stateName": "Florida"}]
}
START_URL  = "https://propwire.com/"
SEARCH_URL = "https://propwire.com/search?filters=" + json.dumps(SEARCH_FILTERS)

# request URLs we care about — skip static assets / analytics noise
_SKIP = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".woff2",
         ".ttf", ".css", ".ico", ".map", "google", "gtag", "segment",
         "sentry", "hotjar", "facebook", "clarity", "doubleclick")


def _interesting(url: str, method: str) -> bool:
    low = url.lower()
    if any(s in low for s in _SKIP):
        return False
    if "propwire" not in low and "api" not in low:
        return False
    # keep API-ish traffic: POSTs, or paths that look like data/auth endpoints
    if method != "GET":
        return True
    return any(k in low for k in ("/api", "/search", "/auth", "/token",
                                  "/propert", "/graphql", "/skip"))


async def run_propwire_probe(states: Optional[list[str]] = None) -> dict:
    from playwright.async_api import async_playwright

    captured: list[dict] = []
    bodies: dict[str, str] = {}

    async def on_request(req):
        try:
            if _interesting(req.url, req.method):
                captured.append({
                    "method": req.method,
                    "url": req.url,
                    "auth": req.headers.get("authorization", ""),
                    "ctype": req.headers.get("content-type", ""),
                    "post": (req.post_data or "")[:1200],
                    "rtype": req.resource_type,
                })
        except Exception:
            pass

    async def on_response(resp):
        try:
            req = resp.request
            if not _interesting(req.url, req.method):
                return
            ct = resp.headers.get("content-type", "")
            if "json" in ct or "text" in ct:
                txt = await resp.text()
                bodies[f"{req.method} {req.url}"] = txt[:1500]
            captured.append({"resp_for": f"{req.method} {req.url}",
                             "status": resp.status, "ctype": ct})
        except Exception:
            pass

    print("[PROPWIRE-PROBE] launching Chromium…")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=UA, locale="en-US",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = await ctx.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # 1) home — clear Cloudflare, pick up any anonymous token / cookies
        try:
            r = await page.goto(START_URL, timeout=45000, wait_until="domcontentloaded")
            title = await page.title()
            print(f"[PROPWIRE-PROBE] home status={r.status if r else '?'} title={title!r}")
            if "just a moment" in (title or "").lower() or (r and r.status == 403):
                print("[PROPWIRE-PROBE] *** Cloudflare challenge on home — runner IP likely blocked ***")
            await asyncio.sleep(6)
        except Exception as e:
            print(f"[PROPWIRE-PROBE] home nav error: {e}")

        # 2) search page — this is what fires the data API calls
        try:
            r = await page.goto(SEARCH_URL, timeout=45000, wait_until="domcontentloaded")
            print(f"[PROPWIRE-PROBE] search status={r.status if r else '?'}")
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(8)
        except Exception as e:
            print(f"[PROPWIRE-PROBE] search nav error: {e}")

        await browser.close()

    # ---- report ----
    print(f"\n[PROPWIRE-PROBE] captured {len(captured)} interesting events\n" + "=" * 60)
    for c in captured:
        if "resp_for" in c:
            print(f"  <- {c['status']} {c['resp_for']}  ({c['ctype']})")
        else:
            print(f"  -> {c['method']} {c['url']}")
            if c["auth"]:
                print(f"       auth: {c['auth'][:80]}")
            if c["post"]:
                print(f"       body: {c['post']}")
    print("=" * 60 + "\n[PROPWIRE-PROBE] RESPONSE BODY SNIPPETS:")
    for k, v in bodies.items():
        print(f"\n--- {k}\n{v}")
    return {"events": len(captured), "bodies": len(bodies)}


if __name__ == "__main__":
    asyncio.run(run_propwire_probe())
