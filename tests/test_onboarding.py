"""Tests for the onboarding subgraph nodes.

We don't hit the real LLM or the real Tavily API here — those are covered
by an optional live test at :mod:`test_onboarding_live` (skipped by default).
"""
import json
from unittest.mock import patch

import pytest

from backend.graph.nodes import onboarding as ob


# --- extract_node ---

def test_extract_node_with_thin_pages_returns_empty_profile():
    """No crawled pages → empty defaults, doesn't crash."""
    state = {"onboarding_url": "https://example.com", "crawled_pages": []}
    out = ob.extract_node(state)
    assert "company_profile" in out
    assert out["company_profile"]["content_mix"] == 0.5  # default


def test_extract_node_uses_structured_llm(fake_llm):
    """The node should call the LLM, clamp content_mix, flatten pillars."""
    fake_llm.responses = [
        json.dumps({
            "identity": {"summary": "wine", "products": ["Riesling"]},
            "market": {"segments": ["DTC"], "geo": ["DE"], "icp": "wine drinkers"},
            "positioning": {"value_prop": "steep-slope", "differentiators": ["organic"]},
            "voice": {"tone": ["warm"], "vocabulary": ["terroir"], "do": [], "dont": ["hype"]},
            "content_pillars": [
                {"name": "product", "description": "wine releases"},
                {"name": "place", "description": "the vineyard"},
                {"name": "people", "description": "family & craft"},
            ],
            "content_mix": 1.7,  # deliberately out of range
        })
    ]
    state = {
        "onboarding_url": "https://example.com",
        "crawled_pages": [{"url": "https://example.com", "title": "T", "text": "Some copy here"}],
    }
    with patch("backend.graph.nodes.onboarding.make_llm", return_value=fake_llm):
        out = ob.extract_node(state)

    profile = out["company_profile"]
    assert profile["content_mix"] == 1.0  # clamped
    assert profile["voice"]["dont"] == ["hype"]
    assert profile["identity"]["products"] == ["Riesling"]
    # pillars: flattened from list-of-dicts to name→description mapping
    assert profile["content_pillars"] == {
        "product": "wine releases",
        "place": "the vineyard",
        "people": "family & craft",
    }


def test_extract_node_fills_empty_pillars_with_fallback(fake_llm):
    """When the LLM returns no pillars, fallback synthesizes 2-4 sane defaults."""
    fake_llm.responses = [
        json.dumps({
            "identity": {"summary": "x", "products": ["ProductA"]},
            "market": {"segments": ["SegA"], "geo": [], "icp": ""},
            "positioning": {"value_prop": "", "differentiators": []},
            "voice": {"tone": [], "vocabulary": [], "do": [], "dont": []},
            "content_pillars": [],
            "content_mix": 0.5,
        })
    ]
    state = {
        "onboarding_url": "https://example.com",
        "crawled_pages": [{"url": "https://example.com", "title": "T", "text": "x" * 300}],
    }
    with patch("backend.graph.nodes.onboarding.make_llm", return_value=fake_llm):
        out = ob.extract_node(state)
    pillars = out["company_profile"]["content_pillars"]
    assert len(pillars) >= 2
    assert "product" in pillars  # comes from ProductA
    assert "industry" in pillars  # comes from SegA


def test_extract_node_falls_back_to_raw_json_on_structured_failure(fake_llm):
    """If structured_output raises, node retries with raw JSON parsing."""
    class RaisingWrapped:
        def invoke(self, prompt, **kw):
            raise ValueError("boom")

    class LLMThatRaisesStructured:
        def with_structured_output(self, schema):
            return RaisingWrapped()

        def invoke(self, prompt, **kw):
            class M:
                content = json.dumps({"identity": {"summary": "fallback", "products": []}, "content_mix": 0.3})
            return M()

    with patch("backend.graph.nodes.onboarding.make_llm", return_value=LLMThatRaisesStructured()):
        state = {
            "onboarding_url": "https://example.com",
            "crawled_pages": [{"url": "https://example.com", "title": "T", "text": "x" * 300}],
        }
        out = ob.extract_node(state)
    assert out["company_profile"]["identity"]["summary"] == "fallback"


# --- seed_sources_node ---

def test_seed_sources_returns_empty_when_no_segments():
    state = {"company_profile": {"market": {"segments": [], "geo": []}}}
    out = ob.seed_sources_node(state)
    assert out["proposed_sources"] == []


def test_seed_sources_queries_search_and_shapes_results():
    from backend.tools.web_search import SearchResult

    fake_hits = [
        SearchResult(title="Wine Weekly", url="https://wineweekly.example.com", snippet="best wine news"),
        SearchResult(title="Rheinhessen Blog", url="https://rhblog.example.com", snippet="regional coverage"),
    ]
    state = {
        "company_profile": {
            "market": {"segments": ["direct-to-consumer wine"], "geo": ["Rheinhessen"]}
        }
    }
    with patch("backend.graph.nodes.onboarding.search_outlets", return_value=fake_hits):
        out = ob.seed_sources_node(state)

    proposals = out["proposed_sources"]
    assert len(proposals) == 2
    assert proposals[0]["url"] == "https://wineweekly.example.com"
    assert proposals[0]["origin"] == "onboarding"
    assert proposals[0]["kind"] == "web"


# --- persist_node ---

@pytest.mark.db
def test_persist_node_writes_profile_and_sources(clean_db, sample_profile):
    from backend.memory.db import get_profile, list_sources

    state = {
        "company_id": "test_persist",
        "company_profile": sample_profile,
        "crawled_pages": [{"url": "https://x.example.com", "title": "T", "text": "..."}],
        "proposed_sources": [
            {"url": "https://a.example.com", "name": "A", "kind": "rss", "origin": "onboarding"},
            {"url": "https://b.example.com", "name": "B", "kind": "web", "accepted": False},
            {"url": "https://c.example.com", "name": "C", "kind": "web", "accepted": True},
        ],
    }

    out = ob.persist_node(state)
    assert out["company_id"] == "test_persist"

    loaded = get_profile("test_persist")
    assert loaded is not None
    assert loaded["content_mix"] == pytest.approx(0.8)

    sources = list_sources("test_persist")
    urls = {s["url"] for s in sources}
    # b was rejected (accepted=False), a and c accepted (or defaulted)
    assert "https://a.example.com" in urls
    assert "https://c.example.com" in urls
    assert "https://b.example.com" not in urls


# --- crawl_node ---

def test_crawl_node_raises_without_url():
    with pytest.raises(ValueError, match="onboarding_url"):
        ob.crawl_node({})


def test_crawl_node_normalizes_url_scheme():
    """Bare-domain input should be prefixed with https:// before crawling."""
    with patch("backend.graph.nodes.onboarding.crawl_site", return_value=[]) as mock:
        ob.crawl_node({"onboarding_url": "example.com"})
    called_url = mock.call_args[0][0]
    assert called_url == "https://example.com"
