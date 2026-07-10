"""Tests for the Publish node + Buffer / Resend tools."""
from unittest.mock import patch

import httpx
import pytest
import respx

from backend.graph.nodes import publish as pub
from backend.tools import buffer, email


# --- Buffer channel ID parsing ---

def test_extract_channel_id_from_bare_id():
    assert buffer.extract_channel_id("69c15a0daf47dacb6947e7e2") == "69c15a0daf47dacb6947e7e2"


def test_extract_channel_id_from_url():
    url = "https://publish.buffer.com/channels/69c15a0daf47dacb6947e7e2/schedule"
    assert buffer.extract_channel_id(url) == "69c15a0daf47dacb6947e7e2"


def test_extract_channel_id_none_for_garbage():
    assert buffer.extract_channel_id("not-an-id") is None
    assert buffer.extract_channel_id(None) is None


# --- Buffer preview mode ---

def test_buffer_preview_mode_returns_mock(monkeypatch):
    monkeypatch.setenv("PUBLISH_MODE", "preview")
    from backend.config import settings as _s
    _s.cache_clear()
    result = buffer.create_draft_post(channel="linkedin", text="hi")
    assert result["mode"] == "preview"
    assert result["status"] == "ok"


# --- Email preview mode ---

def test_email_preview_mode_returns_mock(monkeypatch):
    monkeypatch.setenv("PUBLISH_MODE", "preview")
    from backend.config import settings as _s
    _s.cache_clear()
    result = email.send_newsletter(draft={"subject": "s", "intro": "hi", "sections": [], "signoff": ""})
    assert result["mode"] == "preview"
    assert result["status"] == "ok"


# --- Email HTML render ---

def test_render_newsletter_html_includes_all_parts():
    draft = {
        "subject": "The vintage begins",
        "preheader": "Harvest 2026",
        "intro": "This week we picked the first Riesling.",
        "sections": [{"heading": "Harvest", "body_markdown": "Fruit is in.", "link": "https://example.com/read"}],
        "signoff": "See you at the cellar.",
    }
    html = email.render_newsletter_html(draft)
    assert "The vintage begins" in html
    assert "Harvest 2026" in html
    assert "Fruit is in." in html
    assert "https://example.com/read" in html


# --- Publish node ---

@pytest.mark.db
def test_publish_node_only_pushes_approved_channels(clean_db, monkeypatch):
    """Only channels with approved=True should trigger calls."""
    monkeypatch.setenv("PUBLISH_MODE", "preview")
    from backend.config import settings as _s
    _s.cache_clear()

    state = {
        "company_id": "cid",
        "cycle_id": None,
        "drafts": {
            "newsletter": {"subject": "s", "intro": "i", "sections": []},
            "instagram": {"caption": "hello", "hashtags": ["a"]},
            "linkedin": {"post": "a linkedin post"},
        },
        "publish": {
            "newsletter": {"approved": True},
            "instagram": {"approved": False},
            "linkedin": {"approved": True},
        },
    }
    with patch("backend.graph.nodes.publish.send_newsletter") as send_nl, \
         patch("backend.graph.nodes.publish.create_draft_post") as buf:
        send_nl.return_value = {"status": "ok", "external_id": "nl1", "mode": "preview"}
        buf.return_value = {"status": "ok", "external_id": "b1", "mode": "preview"}
        out = pub.publish_node(state)

    send_nl.assert_called_once()
    buf.assert_called_once_with(channel="linkedin", text="a linkedin post")
    assert out["publish"]["newsletter"]["status"] == "ok"
    assert out["publish"]["linkedin"]["status"] == "ok"
    assert out["publish"]["instagram"]["skipped"] is True


@pytest.mark.db
def test_publish_node_logs_to_publish_log(clean_db, monkeypatch):
    monkeypatch.setenv("PUBLISH_MODE", "preview")
    from backend.config import settings as _s
    _s.cache_clear()
    from backend.memory import db as mem

    state = {
        "company_id": "cid",
        "cycle_id": "cyc_log",
        "drafts": {"newsletter": {"subject": "s", "intro": "i", "sections": []}},
        "publish": {"newsletter": {"approved": True}},
    }
    with patch("backend.graph.nodes.publish.send_newsletter") as send_nl:
        send_nl.return_value = {"status": "ok", "external_id": "nl1", "mode": "preview"}
        pub.publish_node(state)

    rows = mem.q("SELECT channel, status, external_id FROM publish_log WHERE company_id='cid'")  # noqa
    assert len(rows) == 1
    assert rows[0]["channel"] == "newsletter"
    assert rows[0]["status"] == "ok"
