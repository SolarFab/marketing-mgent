"""Tests for the Write node."""
import json
from unittest.mock import patch

import pytest

from backend.graph.nodes import write as w


def _fake_llm(responses):
    """Fake LLM that returns each preloaded JSON in sequence."""
    idx = {"n": 0}

    class Wrapped:
        def __init__(self, schema):
            self._schema = schema
        def invoke(self, prompt, **kw):
            data = responses[idx["n"]]
            idx["n"] += 1
            if hasattr(self._schema, "model_validate"):
                return self._schema.model_validate(data)
            return data

    class LLM:
        def with_structured_output(self, schema):
            return Wrapped(schema)
    return LLM()


def test_pick_layout_defaults_by_set_size():
    assert w._pick_layout({}, [1, 2, 3, 4]) == "digest"
    assert w._pick_layout({}, [1]) == "single-story"
    assert w._pick_layout({}, [1, 2]) == "editorial"


def test_pick_layout_respects_explicit():
    state = {"drafts": {"layout": "single-story"}}
    assert w._pick_layout(state, [1, 2, 3, 4]) == "single-story"


@pytest.mark.db
def test_write_node_returns_empty_when_no_approved(clean_db):
    out = w.write_node({"approved": [], "company_profile": {}, "cycle_id": "c_x"})
    assert out["drafts"]["newsletter"] is None


@pytest.mark.db
def test_write_node_generates_all_three_channels_and_persists(clean_db, sample_profile):
    from backend.memory import db as mem

    approved = [
        {"id": "c1", "title": "Harvest is starting", "angle": "first Riesling in", "kind": "owned", "pillar": "place"},
        {"id": "c2", "title": "Family history since 1897", "angle": "5th gen", "kind": "owned", "pillar": "people"},
    ]
    state = {
        "approved": approved,
        "company_profile": sample_profile,
        "company_id": "cid_write",
        "cycle_id": "cyc_write",
    }
    newsletter_json = {
        "subject": "The vintage begins",
        "preheader": "Harvest 2026",
        "intro": "This week we picked the first Riesling.",
        "sections": [
            {"heading": "Harvest", "body_markdown": "Fruit is in.", "link": ""},
        ],
        "signoff": "See you at the cellar.",
        "layout": "editorial",
    }
    social_json = {
        "instagram": "First grapes in, sun still on the slopes.",
        "instagram_hashtags": ["riesling", "harvest2026", "rheinhessen"],
        "linkedin": "Every vintage tells its own story. This week the 2026 harvest began — hand-picked, unhurried.",
    }

    with patch("backend.graph.nodes.write.make_llm", side_effect=[
        _fake_llm([newsletter_json]),
        _fake_llm([social_json]),
    ]):
        out = w.write_node(state)

    drafts = out["drafts"]
    assert drafts["newsletter"]["subject"] == "The vintage begins"
    assert drafts["instagram"]["caption"].startswith("First grapes")
    assert drafts["instagram"]["hashtags"] == ["riesling", "harvest2026", "rheinhessen"]
    assert "hand-picked" in drafts["linkedin"]["post"]

    saved = mem.get_drafts("cyc_write")
    assert saved is not None
    assert saved["newsletter"]["subject"] == "The vintage begins"
    assert saved["layout"] == "editorial"
