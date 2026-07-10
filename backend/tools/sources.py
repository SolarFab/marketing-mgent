"""Source URL normalization + kind detection.

Whenever a URL becomes a followed source — via discovery, user-add, or
the onboarding seed step — we want to store *the outlet*, not one page
of it. So we:

1. Strip the URL down to its scheme+host (``https://sifted.eu/articles/xxx``
   becomes ``https://sifted.eu``).
2. Try to detect an RSS/Atom feed on that root
   (:func:`backend.tools.feeds.detect_feed_url`).
3. If a feed is found, store the *feed URL* with ``kind='rss'`` so the
   Ideate node can pull it periodically.
4. Otherwise, store the root URL with ``kind='web'`` — the Ideate node
   uses site-restricted Tavily search to pull articles from that domain.

Also filters out obviously non-outlet URLs (Instagram reels, YouTube
videos, plain PDFs) that Tavily sometimes returns as top results.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from .feeds import detect_feed_url

log = logging.getLogger(__name__)


# Domains that are obviously not "outlets" — filter them out at discovery.
# Users can still add them by hand if they really want to.
_NON_OUTLET_DOMAINS = {
    "instagram.com", "www.instagram.com",
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "tiktok.com", "www.tiktok.com",
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "twitter.com", "x.com",
    "linkedin.com", "www.linkedin.com",
    "pinterest.com", "reddit.com",
}


@dataclass
class NormalizedSource:
    """Ready-to-insert shape for the ``sources`` table."""
    url: str          # feed URL if kind==rss, else root URL
    root_url: str     # always the site root
    kind: str         # 'rss' | 'web'
    host: str         # lowercased host, no www.
    is_outlet: bool   # False for social/video/etc.


def normalize_source_url(url: str, *, probe_feed: bool = True) -> NormalizedSource:
    """Normalize an arbitrary URL into a followable outlet.

    Args:
        url: any URL — homepage, article, feed, or garbage.
        probe_feed: whether to hit the network to try RSS detection.
            Set False for pure normalization (e.g., in tests).

    Returns:
        A :class:`NormalizedSource`. ``is_outlet=False`` means the URL is
        obviously a social/video destination and shouldn't be proposed.
    """
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        # Give up — return something the caller can quickly discard.
        return NormalizedSource(url=url, root_url=url, kind="web", host="", is_outlet=False)

    host = parsed.netloc.lower()
    host_bare = host[4:] if host.startswith("www.") else host
    root = f"{parsed.scheme}://{parsed.netloc}"

    is_outlet = host not in _NON_OUTLET_DOMAINS and host_bare not in _NON_OUTLET_DOMAINS

    # If the given URL already ends with a feed-shaped path, honour that
    # even without a probe.
    lower_path = parsed.path.lower()
    if any(lower_path.endswith(s) for s in (".xml", ".rss", "/feed", "/feed/", "/rss", "/atom.xml", "/index.xml")):
        return NormalizedSource(url=url, root_url=root, kind="rss", host=host_bare, is_outlet=is_outlet)

    if not probe_feed or not is_outlet:
        return NormalizedSource(url=root, root_url=root, kind="web", host=host_bare, is_outlet=is_outlet)

    feed = detect_feed_url(root)
    if feed:
        return NormalizedSource(url=feed, root_url=root, kind="rss", host=host_bare, is_outlet=is_outlet)
    return NormalizedSource(url=root, root_url=root, kind="web", host=host_bare, is_outlet=is_outlet)


def outlet_name_from_title(title: str, host: str) -> str:
    """Turn a Tavily title into an outlet-y label.

    ``"Some Article - Sifted"`` → ``"Sifted"``
    ``"blog.example.com"``     → ``"Example"``
    """
    for sep in (" - ", " | ", " — "):
        if sep in title:
            candidate = title.split(sep)[-1].strip()
            if 2 <= len(candidate) <= 40:
                return candidate
    # Fallback: capitalize the second-level domain
    root = host.split(".")[0] if "." in host else host
    return root.capitalize() or host
