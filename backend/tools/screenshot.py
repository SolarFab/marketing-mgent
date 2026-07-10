"""Headless-browser screenshot for brand extraction.

Rendered pixels are the ground truth for what a visitor actually sees —
CSS custom properties + inline styles miss the design-system indirection
that dominates modern sites.

The screenshot goes to a vision LLM (see
:func:`backend.graph.nodes.onboarding._extract_brand`) which returns
a palette + mood + typography feel grounded in what actually rendered.

Fails soft: returns ``None`` if Playwright isn't installed or the site
fails to load. Brand extraction then falls back to CSS hints + inferred
mood only.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def screenshot_homepage(url: str, *, timeout_s: int = 20, viewport: tuple[int, int] = (1440, 900)) -> bytes | None:
    """Return PNG bytes of the homepage above-the-fold render, or None."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        log.info("screenshot: playwright not available (%s)", e)
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": viewport[0], "height": viewport[1]},
                user_agent=(
                    "SignalContentAgent/0.1 (+https://github.com/local; "
                    "brand-screenshot)"
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            # Give lazy assets a beat to render, but cap it
            page.wait_for_timeout(1500)
            png = page.screenshot(full_page=False, type="png")
            browser.close()
        return png
    except Exception as e:
        log.warning("screenshot: capture failed for %s: %s", url, e)
        return None
