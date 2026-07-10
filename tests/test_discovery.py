"""Tests for Source Discovery."""
from unittest.mock import patch

import pytest

from backend.graph.nodes import discovery


def _hit(url, title="Outlet"):
    from backend.tools.web_search import SearchResult
    return SearchResult(title=title, url=url, snippet="covers relevant topic")


def test_discovery_node_returns_empty_when_llm_yields_no_queries():
    """When the LLM-driven query generator yields nothing (thin profile,
    LLM failure), discovery bails without hitting search."""
    state = {"company_profile": {"market": {"segments": [], "geo": []}}}
    with patch("backend.graph.nodes.discovery._llm_search_queries", return_value=[]), \
         patch("backend.graph.nodes.discovery.search_outlets") as m:
        out = discovery.discovery_node(state)
    m.assert_not_called()
    assert out["source_proposals"] == []


def test_discovery_node_excludes_already_followed_hosts():
    state = {
        "company_profile": {"market": {"segments": ["wine"], "geo": ["DE"]}},
        "sources": [{"url": "https://known.example.com/feed"}],
    }
    hits = [_hit("https://known.example.com/blog"), _hit("https://new.example.com")]
    # Skip RSS probe so the test stays offline.
    with patch("backend.graph.nodes.discovery.search_outlets", return_value=hits), \
         patch("backend.tools.sources.detect_feed_url", return_value=None):
        out = discovery.discovery_node(state)
    urls = [p["url"] for p in out["source_proposals"]]
    # Normalized to root; known.example.com is already followed and filtered
    assert urls == ["https://new.example.com"]


def test_discovery_node_dedups_within_search_by_host():
    """Article URLs from the same host must collapse to one root proposal."""
    state = {"company_profile": {"market": {"segments": ["a", "b"], "geo": []}}, "sources": []}
    hits_a = [_hit("https://same.example.com/one"), _hit("https://uniq.example.com")]
    hits_b = [_hit("https://same.example.com/two")]

    call_state = {"n": 0}
    def rotating(*a, **kw):
        call_state["n"] += 1
        return hits_a if call_state["n"] == 1 else hits_b

    with patch("backend.graph.nodes.discovery.search_outlets", side_effect=rotating), \
         patch("backend.tools.sources.detect_feed_url", return_value=None):
        out = discovery.discovery_node(state)
    urls = {p["url"] for p in out["source_proposals"]}
    # Both hits from same.example.com collapse to the root; second is deduped
    assert urls == {"https://same.example.com", "https://uniq.example.com"}


@pytest.mark.db
def test_discover_and_stage_writes_proposed_rows(clean_db, sample_profile):
    from backend.memory import db as mem

    mem.upsert_profile("cid_d", sample_profile)
    hits = [_hit("https://blog.example.com", "Wine Blog")]
    with patch("backend.graph.nodes.discovery.search_outlets", return_value=hits):
        inserted = discovery.discover_and_stage("cid_d")
    assert len(inserted) == 1
    listed = mem.list_sources("cid_d", statuses=["proposed"])
    assert len(listed) == 1
    assert listed[0]["origin"] == "discovered"


@pytest.mark.db
def test_accept_promotes_proposed_to_active(clean_db):
    from backend.memory import db as mem
    s = mem.add_source("cid", "https://x.com", status="proposed", origin="discovered")
    discovery.accept_proposed(s["source_id"])
    row = mem.q1("SELECT status FROM sources WHERE source_id=%s", (s["source_id"],))
    assert row["status"] == "active"


@pytest.mark.db
def test_dismiss_removes_proposed_only(clean_db):
    from backend.memory import db as mem
    s_prop = mem.add_source("cid", "https://x.com", status="proposed", origin="discovered")
    s_user = mem.add_source("cid", "https://y.com", status="active", origin="user")

    discovery.dismiss_proposed(s_prop["source_id"])
    discovery.dismiss_proposed(s_user["source_id"])  # should NOT delete

    urls = {s["url"] for s in mem.list_sources("cid")}
    assert "https://x.com" not in urls  # proposed removed
    assert "https://y.com" in urls      # user source preserved
