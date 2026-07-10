"""Extract deterministic brand hints directly from HTML/CSS.

Used as an input to the vision-LLM brand-extraction step. The LLM
anchors its final palette on the measured hex codes here, rather than
guessing from mood alone.

We don't try to *understand* the CSS — we just harvest visible signals:

- ``<meta name="theme-color">`` — the site's declared theme color.
- CSS custom properties named like ``--primary``, ``--brand-*``,
  ``--accent-*``, ``--bg-*``, ``--text-*`` — modern design systems
  expose the brand palette here.
- Most frequent hex colors in inline styles and ``<style>`` blocks.
- ``font-family`` declarations — often points at Google Fonts.

Fails soft: returns an empty dict rather than raising.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

log = logging.getLogger(__name__)

_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_CSS_VAR_RE = re.compile(
    r"--(?P<name>[a-zA-Z0-9_-]*(?:primary|brand|accent|bg|background|foreground|text|fg|surface|highlight)[a-zA-Z0-9_-]*)"
    r"\s*:\s*(?P<value>[^;{}]+)",
    re.IGNORECASE,
)
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;{}]+)", re.IGNORECASE)


def extract_css_hints(html: str) -> dict:
    """Return a dict of brand-relevant signals harvested from raw HTML."""
    if not html:
        return {}

    hints: dict = {}

    # 1. <meta name="theme-color">
    m = re.search(
        r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if m:
        hints["theme_color"] = _normalize_hex(m.group(1))

    # 2. CSS custom properties
    css_vars: dict[str, str] = {}
    for match in _CSS_VAR_RE.finditer(html):
        name = match.group("name").lower()
        value = match.group("value").strip()
        # Only keep values that look like colors
        if value.startswith("#") or value.startswith("rgb") or value.startswith("hsl"):
            css_vars[name] = value
    if css_vars:
        hints["css_vars"] = css_vars

    # 3. Most-frequent hex colors (excluding pure black/white boilerplate unless dominant)
    counts: Counter[str] = Counter()
    for match in _HEX_RE.finditer(html):
        h = _normalize_hex("#" + match.group(1))
        if h:
            counts[h] += 1
    # Drop trivial black/white unless they dominate
    trivial = {"#000000", "#ffffff", "#fff", "#000"}
    non_trivial = [(c, n) for c, n in counts.most_common(30) if c not in trivial]
    trivial_hits = [(c, n) for c, n in counts.most_common(30) if c in trivial]
    top_colors = non_trivial[:8] + trivial_hits[:2]
    if top_colors:
        hints["top_colors"] = [{"hex": c, "count": n} for c, n in top_colors]

    # 4. font-family declarations
    fonts: list[str] = []
    for match in _FONT_FAMILY_RE.finditer(html):
        fam = match.group(1).strip().strip("'\"")
        # take just the first family
        first = fam.split(",")[0].strip().strip("'\"")
        if first and first.lower() not in ("inherit", "initial", "unset") and first not in fonts:
            fonts.append(first)
    if fonts:
        hints["font_families"] = fonts[:5]

    # 5. Google Fonts / Adobe Fonts URLs — useful hints for image-gen prompts
    #    even though the image model can't load fonts, showing "Inter" or
    #    "Manrope" in the prompt biases the model's typography rendering.
    font_urls: list[str] = []
    for match in re.finditer(
        r'https?://fonts\.googleapis\.com/css2?\?[^"\'\s>]+',
        html,
    ):
        url = match.group(0)
        if url not in font_urls:
            font_urls.append(url)
    for match in re.finditer(
        r'https?://use\.typekit\.net/[^"\'\s>]+',
        html,
    ):
        url = match.group(0)
        if url not in font_urls:
            font_urls.append(url)
    if font_urls:
        hints["font_urls"] = font_urls[:3]
        # Parse Google Fonts URLs to extract family names
        google_families: list[str] = []
        for u in font_urls:
            for m in re.finditer(r"family=([^&:]+)", u):
                fam = m.group(1).replace("+", " ")
                if fam not in google_families:
                    google_families.append(fam)
        if google_families:
            hints["google_font_families"] = google_families[:5]

    return hints


def _normalize_hex(value: str) -> str:
    """Turn '#fff' into '#ffffff'; lowercase; return empty on failure."""
    v = value.strip().lower()
    if not v.startswith("#"):
        return ""
    body = v[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    if len(body) == 6 and all(c in "0123456789abcdef" for c in body):
        return "#" + body
    if len(body) == 8 and all(c in "0123456789abcdef" for c in body):
        # drop alpha channel
        return "#" + body[:6]
    return ""
