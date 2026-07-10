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
from typing import Any

import resend
from jinja2 import Environment, select_autoescape

from ..config import settings

log = logging.getLogger(__name__)


_env = Environment(autoescape=select_autoescape(["html"]))

_NEWSLETTER_TEMPLATE = _env.from_string(
    """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{{ subject }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; max-width: 640px; margin: 0 auto; padding: 24px; color: #222; line-height: 1.55; }
  h1 { font-size: 22px; margin: 8px 0 4px; }
  .preheader { color: #777; font-size: 13px; margin-bottom: 20px; }
  .intro { font-size: 15px; margin-bottom: 24px; }
  .section { margin: 20px 0; padding-bottom: 20px; border-bottom: 1px solid #eee; }
  .section h2 { font-size: 17px; margin: 0 0 6px; }
  .section p { margin: 6px 0; }
  .section a { color: #1a5cff; text-decoration: none; }
  .signoff { margin-top: 24px; font-style: italic; color: #444; }
  .footer { margin-top: 32px; font-size: 12px; color: #888; }
</style>
</head>
<body>
<h1>{{ subject }}</h1>
{% if preheader %}<div class="preheader">{{ preheader }}</div>{% endif %}
{% if intro %}<div class="intro">{{ intro }}</div>{% endif %}
{% for s in sections %}
<div class="section">
  {% if s.heading %}<h2>{{ s.heading }}</h2>{% endif %}
  <p>{{ s.body_markdown }}</p>
  {% if s.link %}<p><a href="{{ s.link }}">Read more →</a></p>{% endif %}
</div>
{% endfor %}
{% if signoff %}<div class="signoff">{{ signoff }}</div>{% endif %}
<div class="footer">Sent by Signal · a draft for review</div>
</body>
</html>
""".strip()
)


def render_newsletter_html(draft: dict) -> str:
    """Render a newsletter draft dict to an HTML string."""
    return _NEWSLETTER_TEMPLATE.render(
        subject=draft.get("subject") or "",
        preheader=draft.get("preheader") or "",
        intro=draft.get("intro") or "",
        sections=draft.get("sections") or [],
        signoff=draft.get("signoff") or "",
    )


def send_newsletter(*, draft: dict) -> dict[str, Any]:
    """Send the newsletter via Resend to ``RESEND_TEST_TO``.

    Returns ``{"status": "ok", "external_id": "...", "mode": "real"|"preview"}``
    or ``{"status": "error", "error": "...", "mode": "..."}``.
    """
    s = settings()
    subject = draft.get("subject") or "Weekly update"
    html = render_newsletter_html(draft)

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
