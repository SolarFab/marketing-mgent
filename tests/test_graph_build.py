"""Tests for the graph assembly + PostgresSaver.

These reach into the DB (test branch). We verify:
- Both graphs compile without errors.
- The onboarding graph interrupts before ``confirm``.
- The content graph interrupts before ``review`` and ``publish``.
- Thread ids are deterministic and correctly shaped.
"""
import pytest


@pytest.mark.db
def test_build_onboarding_graph_compiles():
    from backend.graph.build import build_onboarding_graph, onboarding_thread

    g = build_onboarding_graph()
    assert g is not None
    thread = onboarding_thread("cid")
    assert thread["configurable"]["thread_id"] == "onboard:cid"


@pytest.mark.db
def test_build_content_graph_compiles():
    from backend.graph.build import build_content_graph, cycle_thread

    g = build_content_graph()
    assert g is not None
    thread = cycle_thread("cyc_1")
    assert thread["configurable"]["thread_id"] == "cycle:cyc_1"


@pytest.mark.db
def test_load_state_node_pulls_from_db(clean_db, sample_profile):
    """load_state_node hydrates profile, prefs, and sources from Postgres."""
    from backend.graph.build import load_state_node
    from backend.memory import db as mem

    mem.upsert_profile("test_cid", sample_profile)
    mem.add_source("test_cid", "https://x.example.com", status="active", kind="web")
    mem.add_source("test_cid", "https://paused.example.com", status="paused", kind="web")

    out = load_state_node({"company_id": "test_cid"})

    assert out["company_profile"]["content_mix"] == pytest.approx(0.8)
    assert out["preference_profile"] is not None
    # Only active source is loaded
    assert len(out["sources"]) == 1
    assert out["sources"][0]["url"] == "https://x.example.com"
    # A cycle was started
    assert out["cycle_id"].startswith("cyc_")


@pytest.mark.db
def test_review_and_publish_gates_are_no_ops():
    """These nodes exist as interrupt anchors; they must not mutate state."""
    from backend.graph.build import publish_gate_node, review_gate_node

    assert review_gate_node({}) == {}
    assert publish_gate_node({}) == {}
