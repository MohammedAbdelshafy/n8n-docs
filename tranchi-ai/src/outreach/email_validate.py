"""
Free email deliverability gate — cut bounces before they happen.

Scraped emails are the #1 bounce source: stale addresses, generic junk, and
regex artifacts (image filenames, tracking domains). This filters them with
zero cost / zero dependencies:
  1. strict syntax
  2. junk local-parts (noreply@, postmaster@, ...) and junk/placeholder domains
  3. non-email TLDs picked up by scrapers (.png/.jpg/.css ...)
  4. the domain must actually RESOLVE in DNS (dead domains = guaranteed bounce)

Not a full mailbox verify (that's a paid API), but it removes the obvious
undeliverables that wreck a sender's reputation.
"""

import re
import socket

_SYNTAX = re.compile(r"^[a-z0-9._%+\-]+@([a-z0-9\-]+\.)+[a-z]{2,}$", re.I)
_JUNK_LOCAL = ("noreply", "no-reply", "donotreply", "do-not-reply", "postmaster",
               "abuse", "mailer-daemon", "example", "test", "you@", "email@")
_JUNK_DOMAIN = {"example.com", "example.org", "test.com", "email.com", "domain.com",
                "yourdomain.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com",
                "godaddy.com", "wix.com", "squarespace.com"}
_BAD_TLD = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js",
            ".ico", ".woff", ".woff2")

_resolve_cache: dict = {}


def _domain_resolves(domain: str) -> bool:
    if domain in _resolve_cache:
        return _resolve_cache[domain]
    ok = False
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo(domain, None)   # A/AAAA lookup; dead domains raise
        ok = True
    except Exception:
        ok = False
    _resolve_cache[domain] = ok
    return ok


def is_deliverable(email: str) -> bool:
    e = (email or "").strip().lower()
    if not _SYNTAX.match(e):
        return False
    if e.endswith(_BAD_TLD):
        return False
    local, _, domain = e.partition("@")
    if any(local.startswith(j) for j in _JUNK_LOCAL):
        return False
    if domain in _JUNK_DOMAIN:
        return False
    return _domain_resolves(domain)
