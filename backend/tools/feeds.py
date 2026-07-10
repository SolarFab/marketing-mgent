"""RSS / feed handling.

Public API:

* :func:`detect_feed_url` — given a website URL, try to find its RSS/Atom
  feed (checks `<link rel="alternate">` and common paths like `/feed`,
  `/rss.xml`, `/atom.xml`).
* :func:`fetch_feed_items` — parse a feed URL and return recent items in a
  normalized shape.

Kept intentionally small and forgiving. Sources without a feed are still
useful — the Ideate node will fall back to Tavily web search for them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..config import settings

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "SignalContentAgent/0.1 (+https://github.com/local; feeds)",
    "Accept": "application/rss+xml, application/atom+xml, text/xml, */*",
}

_COMMON_FEED_PATHS = (
    "/feed",
    "/feed/",
    "/rss",
    "/rss.xml",
    "/atom.xml",
    "/index.xml",
    "/feed.xml",
)


@dataclass
class FeedItem:
    """One entry from a feed."""
    title: str
    url: str
    summary: str
    published: str | None  # ISO 8601 if parseable


def detect_feed_url(site_url: str, *, timeout_s: int | None = None) -> str | None:
    """Best-effort discovery of a feed URL for ``site_url``.

    Returns ``None`` if nothing feed-shaped can be found. Does not raise.
    """
    timeout_s = timeout_s or settings().crawl_timeout_s
    try:
        with httpx.Client(timeout=timeout_s, headers=_HEADERS, follow_redirects=True) as c:
            r = c.get(site_url)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        log.info("detect_feed: failed to fetch homepage %s: %s", site_url, e)
        return _probe_common_paths(site_url, timeout_s)

    # 1. <link rel="alternate" type="application/rss+xml" href="..."/>
    try:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
            typ = (link.get("type") or "").lower()
            if any(t in typ for t in ("rss", "atom", "xml")):
                href = link.get("href")
                if href:
                    return urljoin(site_url, href)
    except Exception:
        pass

    # 2. common paths
    return _probe_common_paths(site_url, timeout_s)


def fetch_feed_items(feed_url: str, *, max_items: int = 15) -> list[FeedItem]:
    """Fetch and normalize items from an RSS/Atom feed.

    Returns an empty list on any failure (never raises).
    """
    try:
        parsed = feedparser.parse(feed_url, agent=_HEADERS["User-Agent"])
    except Exception as e:
        log.info("fetch_feed: parse failed %s: %s", feed_url, e)
        return []

    items: list[FeedItem] = []
    for entry in (parsed.entries or [])[:max_items]:
        title = (getattr(entry, "title", "") or "").strip()
        url = (getattr(entry, "link", "") or "").strip()
        if not title or not url:
            continue
        summary = (getattr(entry, "summary", "") or "").strip()
        published = _entry_published(entry)
        items.append(FeedItem(title=title, url=url, summary=summary[:500], published=published))
    return items


# ---------- internals ----------

def _probe_common_paths(site_url: str, timeout_s: int) -> str | None:
    parsed = urlparse(site_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in _COMMON_FEED_PATHS:
        candidate = base + path
        try:
            with httpx.Client(timeout=timeout_s, headers=_HEADERS, follow_redirects=True) as c:
                r = c.head(candidate)
                if r.status_code >= 400:
                    continue
                ctype = r.headers.get("content-type", "").lower()
                if "xml" in ctype or "rss" in ctype or "atom" in ctype:
                    return candidate
                # some servers return HTML on HEAD; try a small GET
                r = c.get(candidate)
                if r.status_code >= 400:
                    continue
                if any(t in r.text[:400].lower() for t in ("<rss", "<feed", "<?xml")):
                    return candidate
        except Exception:
            continue
    return None


def _entry_published(entry) -> str | None:
    ts = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not ts:
        return None
    try:
        return datetime(*ts[:6], tzinfo=timezone.utc).isoformat()
    except Exception:
        return None
