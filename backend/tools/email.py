"""Resend — newsletter send.

Two entry points:

* :func:`render_newsletter_html` — turn a :class:`NewsletterDraft` dict
  into a simple, deliverable HTML string (Jinja).
* :func:`send_newsletter` — actually send via Resend, or return a mocked
  response when ``PUBLISH_MODE=preview``. Always sends to a single
  address (``RESEND_TEST_TO``) — real subscriber lists are out of scope
  by design (see project decision log).

Safety guarantee: this module never reads a subscriber list from
anywhere. The recipient is always a single, explicitly configured
address.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import resend
from jinja2 import Environment, select_autoescape
from markupsafe import Markup, escape

from ..config import settings

log = logging.getLogger(__name__)


_env = Environment(autoescape=select_autoescape(["html"]))


def _highlight_filter(text: str, term: str, color: str) -> Markup:
    """Wrap the first case-insensitive occurrence of ``term`` in body_markdown
    with a colored highlight span. Safe against HTML escaping."""
    if not term or not text:
        return Markup(escape(text))
    escaped = escape(text)
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    m = pattern.search(str(escaped))
    if not m:
        return Markup(escaped)
    before = str(escaped)[: m.start()]
    match = str(escaped)[m.start() : m.end()]
    after = str(escaped)[m.end() :]
    span = (
        f'<span style="background-color:{color};color:#0a0a0a;'
        f'padding:0 3px;border-radius:2px;font-weight:600;">{match}</span>'
    )
    return Markup(before + span + after)


_env.filters["highlight"] = _highlight_filter


# Editorial newsletter template. Palette is passed in via ``brand`` so every
# business's newsletter mirrors their own site.
_NEWSLETTER_TEMPLATE = _env.from_string(
    """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#111;line-height:1.55;">
  {% if preheader %}
  <div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:#f4f4f4;">{{ preheader }}</div>
  {% endif %}
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f4f4f4;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" style="max-width:640px;">

          {# ---------- HERO ---------- #}
          <tr>
            <td style="background:{{ brand.background_color }};color:{{ brand.text_color }};padding:22px 24px;border-radius:6px 6px 0 0;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td style="vertical-align:middle;">
                    <div style="font-size:11px;letter-spacing:0.14em;color:#8a8a8a;text-transform:uppercase;margin-bottom:6px;">{{ date }}</div>
                    <div style="font-size:22px;font-weight:800;letter-spacing:-0.01em;">
                      {% if brand_wordmark_first and brand_wordmark_rest %}
                        <span style="background-color:{{ brand.secondary_accent_color or brand.accent_color }};color:#0a0a0a;padding:0 6px;border-radius:2px;">{{ brand_wordmark_first }}</span><span style="color:{{ brand.text_color }};">{{ brand_wordmark_rest }}</span>
                      {% else %}
                        <span style="color:{{ brand.text_color }};">{{ brand_name }}</span>
                      {% endif %}
                    </div>
                  </td>
                  {% if online_url %}
                  <td align="right" style="vertical-align:middle;">
                    <a href="{{ online_url }}" style="display:inline-block;background:{{ brand.accent_color }};color:#ffffff;text-decoration:none;padding:9px 14px;border-radius:4px;font-size:13px;font-weight:600;">View online →</a>
                  </td>
                  {% endif %}
                </tr>
              </table>
            </td>
          </tr>

          {# ---------- INTRO ---------- #}
          {% if intro %}
          <tr>
            <td style="background:#ffffff;padding:22px 24px 4px;">
              <div style="font-size:12px;letter-spacing:0.14em;color:#8a8a8a;text-transform:uppercase;margin-bottom:8px;">This week's stories</div>
              <div style="font-size:15px;color:#333;">{{ intro }}</div>
            </td>
          </tr>
          {% else %}
          <tr>
            <td style="background:#ffffff;padding:22px 24px 4px;">
              <div style="font-size:12px;letter-spacing:0.14em;color:#8a8a8a;text-transform:uppercase;">This week's stories</div>
            </td>
          </tr>
          {% endif %}

          {# ---------- SECTIONS ---------- #}
          {% for s in sections %}
          <tr>
            <td style="background:#ffffff;padding:12px 24px 4px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border:1px solid #eee;border-left:3px solid {{ brand.accent_color }};border-radius:4px;">
                <tr>
                  <td style="padding:16px 18px;">
                    {% if s.category %}
                    <div style="margin-bottom:10px;">
                      <span style="display:inline-block;background:{{ brand.background_color }};color:{{ brand.text_color }};padding:4px 8px;font-size:10px;letter-spacing:0.12em;font-weight:700;text-transform:uppercase;border-radius:2px;">{{ s.category }}</span>
                    </div>
                    {% endif %}
                    {% if s.heading %}
                    <h2 style="font-size:18px;line-height:1.35;font-weight:800;margin:0 0 8px;color:#111;">{{ s.heading }}</h2>
                    {% endif %}
                    <p style="font-size:14px;color:#333;margin:0 0 10px;">
                      {{ s.body_markdown | highlight(s.highlight_term, brand.secondary_accent_color or brand.accent_color) }}
                    </p>
                    {% if s.link %}
                    <a href="{{ s.link }}" style="color:{{ brand.accent_color }};text-decoration:none;font-size:13px;font-weight:600;">Read →</a>
                    {% endif %}
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          {% endfor %}

          {# ---------- SIGNOFF ---------- #}
          {% if signoff %}
          <tr>
            <td style="background:#ffffff;padding:16px 24px 22px;">
              <div style="font-size:14px;color:#333;font-style:italic;padding-top:12px;border-top:1px solid #eee;">{{ signoff }}</div>
            </td>
          </tr>
          {% endif %}

          {# ---------- FOOTER ---------- #}
          <tr>
            <td style="background:{{ brand.background_color }};color:#999;padding:14px 24px;border-radius:0 0 6px 6px;font-size:11px;letter-spacing:0.06em;">
              {% if brand.social_handle %}{{ brand.social_handle }} · {% endif %}Sent via Signal · a draft for review
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()
)


def render_newsletter_html(draft: dict, *, brand: dict | None = None, profile: dict | None = None) -> str:
    """Render a newsletter draft to an HTML string using the brand palette.

    ``brand`` and ``profile`` are optional — when missing, sensible defaults
    are used so the template still renders (useful for tests / previews
    without a profile in the DB).
    """
    b = _brand_with_defaults(brand)
    # Split identity summary or brand_name into two segments so the wordmark
    # gets the highlight treatment ("China" in yellow, "Tech Signals" in white)
    # if there's a natural split; otherwise the whole name shows unhighlighted.
    brand_name = (profile or {}).get("identity", {}).get("summary", "")
    handle = b.get("social_handle") or ""
    if handle.startswith("@"):
        # Use the handle body as the name (e.g. @chinatechsignal → ChinaTechSignal → China Tech Signal)
        raw = handle.lstrip("@")
        # Break at capitals or the first common brand-name boundary
        readable = re.sub(r"(?<=[a-z])(?=[A-Z])|_", " ", raw).title()
    else:
        # Fall back: first word of identity summary is often the brand name
        readable = (brand_name.split(".")[0] if brand_name else "").strip() or "Signal"
        # Try a proper-noun heuristic: take up to first three title-case words
        parts = readable.split()
        readable = " ".join(parts[:3]) if parts else readable
    words = readable.split()
    wordmark_first = words[0] if len(words) >= 2 else ""
    wordmark_rest = (" " + " ".join(words[1:])) if len(words) >= 2 else ""

    return _NEWSLETTER_TEMPLATE.render(
        subject=draft.get("subject") or "",
        preheader=draft.get("preheader") or "",
        intro=draft.get("intro") or "",
        sections=draft.get("sections") or [],
        signoff=draft.get("signoff") or "",
        brand=b,
        brand_name=readable,
        brand_wordmark_first=wordmark_first,
        brand_wordmark_rest=wordmark_rest,
        date=datetime.now().strftime("%d %b %Y").upper(),
        online_url="",  # no hosted-web-version yet; leave empty so button hides
    )


def _brand_with_defaults(brand: dict | None) -> dict:
    b = dict(brand or {})
    b.setdefault("background_color", "#0a0a0a")
    b.setdefault("text_color", "#ffffff")
    b.setdefault("accent_color", "#1a3fd8")
    b.setdefault("secondary_accent_color", "#e8231a")
    b.setdefault("category_tag_color", b["background_color"])
    b.setdefault("social_handle", "")
    return b


def send_newsletter(*, draft: dict, brand: dict | None = None, profile: dict | None = None) -> dict[str, Any]:
    """Send the newsletter via Resend to ``RESEND_TEST_TO``.

    ``brand`` and ``profile`` drive the palette + wordmark. When missing,
    sensible defaults are used (matches the fallback rendering behavior).

    Returns ``{"status": "ok", "external_id": "...", "mode": "real"|"preview"}``
    or ``{"status": "error", "error": "...", "mode": "..."}``.
    """
    s = settings()
    subject = draft.get("subject") or "Weekly update"
    html = render_newsletter_html(draft, brand=brand, profile=profile)

    if s.publish_mode != "real":
        return {
            "status": "ok",
            "external_id": "preview_newsletter",
            "mode": "preview",
            "html_preview_bytes": len(html),
        }

    if not s.resend_api_key:
        return {"status": "error", "error": "RESEND_API_KEY missing", "mode": "real"}
    if not s.resend_test_to:
        return {"status": "error", "error": "RESEND_TEST_TO missing", "mode": "real"}

    resend.api_key = s.resend_api_key
    try:
        response = resend.Emails.send({
            "from": s.resend_from,
            "to": [s.resend_test_to],
            "subject": subject,
            "html": html,
        })
    except Exception as e:
        log.warning("send_newsletter: Resend failure %s", e)
        return {"status": "error", "error": str(e)[:300], "mode": "real"}

    ext_id = ""
    if isinstance(response, dict):
        ext_id = response.get("id") or ""
    return {"status": "ok", "external_id": ext_id, "mode": "real"}
