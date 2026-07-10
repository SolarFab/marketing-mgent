"""Website crawling for the onboarding subgraph.

Public entry point: :func:`crawl_site` — given a homepage URL, returns a
small list of ``{url, title, text}`` dicts covering the homepage and a
handful of high-signal pages (about, products, contact, ...).

Design choices:

- **Same-origin only.** We never follow off-site links during onboarding —
  the company's own site is the source of truth for identity and voice.
- **Heuristic page selection**, not a full crawler. The PRD caps at ~5
  pages; we discover candidate pages by scanning the homepage anchor text
  for high-signal keywords (about, product, service, story, team, ...).
- **Extraction via trafilatura**, which is designed to strip nav/footer
  boilerplate. Falls back to BeautifulSoup's text if trafilatura returns
  nothing useful.
- **Low volume, respectful.** We hit at most :data:`CRAWL_MAX_PAGES` pages
  in one call, with a per-request timeout.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from ..config import settings

log = logging.getLogger(__name__)


# Keyword hints (lowercased anchor text or path fragments) that identify
# pages worth including in the profile extraction.
_PAGE_HINTS = (
    "about", "story", "our story", "who we are",
    "product", "products", "shop", "wines", "services", "solution",
    "team", "people", "founder", "history", "craft",
    "how it works", "why us", "our approach",
    "contact", "impressum",  # useful for geography inference
)

_HEADERS = {
    "User-Agent": (
        "SignalContentAgent/0.1 (+https://github.com/local; onboarding-crawl)"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


@dataclass
class Page:
    """One crawled page."""
    url: str
    title: str
    text: str


def crawl_site(url: str, *, max_pages: int | None = None, timeout_s: int | None = None) -> list[Page]:
    """Fetch homepage + up to ``max_pages - 1`` other high-signal same-origin pages.

    Never raises for individual page failures; returns whatever was fetched
    successfully. If the homepage itself fails the return list is empty.

    Args:
        url: A homepage URL, e.g. ``https://example.com``.
        max_pages: Cap on total pages returned (default from settings).
        timeout_s: Per-request timeout (default from settings).

    Returns:
        A list of :class:`Page`. Homepage first, then discovered pages.
    """
    s = settings()
    max_pages = max_pages or s.crawl_max_pages
    timeout_s = timeout_s or s.crawl_timeout_s

    homepage = _fetch_page(url, timeout_s)
    if homepage is None:
        log.warning("crawl: homepage fetch failed for %s", url)
        return []

    pages: list[Page] = [homepage]

    # Discover candidate URLs by scanning anchor tags on the homepage HTML.
    # We need the *raw* HTML for this; refetch just the HTML for parsing.
    raw = _fetch_raw(url, timeout_s)
    if raw:
        candidates = _discover_links(url, raw)
        for cand in candidates:
            if len(pages) >= max_pages:
                break
            if any(p.url == cand for p in pages):
                continue
            p = _fetch_page(cand, timeout_s)
            if p and p.text.strip():
                pages.append(p)

    return pages


def total_text_length(pages: list[Page]) -> int:
    """Sum of extracted text across pages — used for thin-content detection."""
    return sum(len(p.text) for p in pages)


# ---------- internals ----------

def _fetch_raw(url: str, timeout_s: int) -> str | None:
    try:
        with httpx.Client(timeout=timeout_s, headers=_HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text
    except Exception as e:
        log.info("crawl: raw fetch failed %s: %s", url, e)
        return None


def _fetch_page(url: str, timeout_s: int) -> Page | None:
    raw = _fetch_raw(url, timeout_s)
    if not raw:
        return None
    text = _extract_text(raw)
    title = _extract_title(raw) or url
    if not text.strip():
        return None
    return Page(url=url, title=title, text=text)


def _extract_text(html: str) -> str:
    try:
        extracted = trafilatura.extract(
            html, include_comments=False, include_tables=False, no_fallback=False
        )
        if extracted and len(extracted) > 200:
            return extracted
    except Exception:
        pass
    # Fallback: strip tags and collapse whitespace
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def _extract_title(html: str) -> str | None:
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
    except Exception:
        pass
    return None


def _discover_links(homepage_url: str, homepage_html: str) -> list[str]:
    """Return same-origin URLs whose anchor text or path looks high-signal."""
    origin = urlparse(homepage_url)
    if not origin.netloc:
        return []
    origin_host = origin.netloc.lower()

    try:
        soup = BeautifulSoup(homepage_html, "html.parser")
    except Exception:
        return []

    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(homepage_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc.lower() != origin_host:
            continue
        # Clean fragment
        absolute = absolute.split("#", 1)[0]
        if absolute in seen or absolute == homepage_url:
            continue
        seen.add(absolute)

        anchor_text = (a.get_text() or "").strip().lower()
        path = parsed.path.lower()
        score = _hint_score(anchor_text) + _hint_score(path)
        if score > 0:
            scored.append((score, absolute))

    # Higher-scoring first, break ties by shorter path (usually top-level pages)
    scored.sort(key=lambda t: (-t[0], len(urlparse(t[1]).path)))
    return [u for _, u in scored]


def _hint_score(text: str) -> int:
    if not text:
        return 0
    return sum(1 for hint in _PAGE_HINTS if hint in text)
