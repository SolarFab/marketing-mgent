"""Tests for the crawl tool.

We mock all HTTP with `respx` so tests are deterministic and offline.
"""
import httpx
import pytest
import respx

from backend.tools.crawl import (
    _discover_links,
    _extract_text,
    crawl_site,
    total_text_length,
)


HOMEPAGE_HTML = """
<html>
<head><title>Weingut Muster — Rheinhessen</title></head>
<body>
<nav><a href="/">Home</a> | <a href="/about">Our Story</a> | <a href="/wines">Wines</a> | <a href="/contact">Contact</a> | <a href="https://external.example.com/blog">External</a></nav>
<main>
<h1>Weingut Muster</h1>
<p>Five generations of Rheinhessen winemaking. Steep-slope, organic, hand-picked.</p>
<p>Our Rieslings tell the story of terroir. Visit our cellar tours in spring and summer.</p>
<p>We work with regional restaurants and sell direct to consumers across Germany.</p>
</main>
</body>
</html>
"""

ABOUT_HTML = """
<html>
<head><title>About — Weingut Muster</title></head>
<body>
<main>
<p>The Muster family has farmed this slope since 1897.</p>
<p>Every vintage is hand-harvested. We do not use industrial equipment on our steepest parcels.</p>
<p>Our vocabulary: vintage, terroir, hand-picked. Never hype, never corporate jargon.</p>
</main>
</body>
</html>
"""

WINES_HTML = """
<html><head><title>Wines — Weingut Muster</title></head><body><main>
<p>Riesling 2023: bright acidity, slate minerality.</p>
<p>Pinot Noir: elegant, cool-climate, low intervention.</p>
<p>Cellar tours available Fridays and Saturdays.</p>
</main></body></html>
"""


def test_extract_text_prefers_trafilatura():
    text = _extract_text(HOMEPAGE_HTML)
    assert "Weingut Muster" in text
    # nav shouldn't dominate — footer/nav are stripped
    assert "External" not in text or "story" in text.lower()


def test_discover_links_scores_high_signal_pages():
    links = _discover_links("https://muster.example.com", HOMEPAGE_HTML)
    # Same-origin only
    assert all("muster.example.com" in u for u in links)
    # Off-site link filtered
    assert not any("external.example.com" in u for u in links)
    # High-signal path is present
    assert any("/about" in u for u in links)
    assert any("/wines" in u for u in links)


@respx.mock
def test_crawl_site_fetches_multiple_pages():
    respx.get("https://muster.example.com").mock(
        return_value=httpx.Response(200, text=HOMEPAGE_HTML)
    )
    respx.get("https://muster.example.com/about").mock(
        return_value=httpx.Response(200, text=ABOUT_HTML)
    )
    respx.get("https://muster.example.com/wines").mock(
        return_value=httpx.Response(200, text=WINES_HTML)
    )
    respx.get("https://muster.example.com/contact").mock(
        return_value=httpx.Response(404, text="not found")
    )

    pages = crawl_site("https://muster.example.com", max_pages=4)
    urls = [p.url for p in pages]
    assert "https://muster.example.com" in urls
    assert "https://muster.example.com/about" in urls
    assert "https://muster.example.com/wines" in urls
    assert total_text_length(pages) > 200


@respx.mock
def test_crawl_site_returns_empty_when_homepage_fails():
    respx.get("https://broken.example.com").mock(
        return_value=httpx.Response(500, text="oops")
    )
    pages = crawl_site("https://broken.example.com")
    assert pages == []


@respx.mock
def test_crawl_site_respects_max_pages():
    respx.get("https://muster.example.com").mock(
        return_value=httpx.Response(200, text=HOMEPAGE_HTML)
    )
    respx.get("https://muster.example.com/about").mock(
        return_value=httpx.Response(200, text=ABOUT_HTML)
    )
    respx.get("https://muster.example.com/wines").mock(
        return_value=httpx.Response(200, text=WINES_HTML)
    )
    pages = crawl_site("https://muster.example.com", max_pages=2)
    assert len(pages) == 2
