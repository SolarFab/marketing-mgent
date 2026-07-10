"""Tests for the Ideate node — both branches, dedup, and mix weighting."""
import json
from unittest.mock import patch

import pytest

from backend.graph.nodes import ideate


def _fake_llm_returning(json_obj):
    """Build a fake LLM whose with_structured_output().invoke() returns json_obj."""
    class Wrapped:
        def __init__(self, schema):
            self._schema = schema
        def invoke(self, prompt, **kw):
            return self._schema.model_validate(json_obj)

    class LLM:
        def with_structured_output(self, schema):
            return Wrapped(schema)
    return LLM()


# --- Owned branch ---

def test_ideate_owned_dedupes_against_recent(sample_profile):
    llm = _fake_llm_returning({
        "angles": [
            {"title": "Harvest is starting", "angle": "first Riesling grapes in", "pillar": "place"},
            {"title": "Old news title", "angle": "should be filtered out", "pillar": "product"},
            {"title": "Meet the family", "angle": "5 generations", "pillar": "people"},
        ]
    })
    recent = {"old news title"}  # lowercased matches _ideate_owned filter
    with patch("backend.graph.nodes.ideate.make_llm", return_value=llm):
        out = ideate._ideate_owned(profile=sample_profile, n=5, recent=recent)
    titles = [c["title"] for c in out]
    assert "Old news title" not in titles
    assert "Harvest is starting" in titles
    assert all(c["kind"] == "owned" for c in out)
    assert all(c["source_id"] is None for c in out)


def test_ideate_owned_returns_empty_when_n_zero(sample_profile):
    """content_mix=0 should skip the owned branch cleanly."""
    with patch("backend.graph.nodes.ideate.make_llm") as m:
        out = ideate._ideate_owned(profile=sample_profile, n=0, recent=set())
    assert out == []
    m.assert_not_called()


# --- External branch ---

def test_ideate_external_shapes_articles(sample_profile_external):
    """LLM shapes real fetched items; skip=True items are dropped."""
    raw_items = [
        {"title": "DHL cuts pick times 30%", "summary": "warehouse robotics", "url": "https://a.example.com/1", "source_id": "s_a"},
        {"title": "Irrelevant celebrity gossip", "summary": "n/a", "url": "https://a.example.com/2", "source_id": "s_a"},
    ]
    llm = _fake_llm_returning({
        "angles": [
            {"article_index": 0, "skip": False, "title": "What DHL's 30% pick-time cut means", "angle": "for mid-size 3PLs", "pillar": "industry"},
            {"article_index": 1, "skip": True, "title": "", "angle": "", "pillar": ""},
        ]
    })
    with patch("backend.graph.nodes.ideate._collect_external_items", return_value=raw_items), \
         patch("backend.graph.nodes.ideate.make_llm", return_value=llm):
        candidates, source_ids = ideate._ideate_external(
            profile=sample_profile_external, sources=[], n=3, recent=set(),
        )
    assert len(candidates) == 1
    assert candidates[0]["kind"] == "external"
    assert candidates[0]["source_id"] == "s_a"
    assert candidates[0]["url"] == "https://a.example.com/1"
    assert source_ids == ["s_a"]


def test_ideate_external_returns_empty_without_raw_items(sample_profile_external):
    with patch("backend.graph.nodes.ideate._collect_external_items", return_value=[]):
        candidates, source_ids = ideate._ideate_external(
            profile=sample_profile_external, sources=[], n=3, recent=set(),
        )
    assert candidates == []
    assert source_ids == []


# --- Full node with real DB ---

@pytest.mark.db
def test_ideate_node_writes_history_and_bumps_source_counters(clean_db, sample_profile):
    """After ideate_node, each candidate is recorded in content_history and
    the source that contributed has items_surfaced++.
    """
    from backend.memory import db as mem

    # Set up a source and profile row
    mem.upsert_profile("cid", sample_profile)
    src = mem.add_source("cid", "https://rss.example.com/feed", kind="rss")

    raw_items = [
        {"title": "some article", "summary": "x", "url": "https://a/1", "source_id": src["source_id"]},
    ]
    owned_llm = _fake_llm_returning({
        "angles": [{"title": "Owned angle 1", "angle": "a", "pillar": "product"}]
    })
    ext_llm = _fake_llm_returning({
        "angles": [{"article_index": 0, "skip": False, "title": "External angle 1", "angle": "b", "pillar": "industry"}]
    })

    # Rotate LLM: first call is owned, second is external
    calls = {"n": 0}
    def rotating_llm(*a, **kw):
        calls["n"] += 1
        return owned_llm if calls["n"] == 1 else ext_llm

    state = {
        "company_id": "cid",
        "company_profile": sample_profile,
        "sources": [{**src, "status": "active"}],
    }
    with patch("backend.graph.nodes.ideate._collect_external_items", return_value=raw_items), \
         patch("backend.graph.nodes.ideate.make_llm", side_effect=rotating_llm):
        out = ideate.ideate_node(state)

    assert len(out["candidates"]) == 2
    titles = {c["title"] for c in out["candidates"]}
    assert titles == {"Owned angle 1", "External angle 1"}

    # source counters bumped once
    listed = mem.list_sources("cid")
    assert listed[0]["items_surfaced"] == 1

    # history has 2 rows
    hist = mem.q("SELECT title FROM content_history WHERE company_id='cid'")  # type: ignore
    assert {r["title"] for r in hist} == titles


# expose mem.q for the test above
from backend.memory import db as mem  # noqa: E402
