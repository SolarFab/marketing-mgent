"""Tests for the orchestrator router + action dispatch.

The router (LLM classification) is patched with fixed :class:`RouteDecision`
outputs; we test each dispatch branch's side effects.
"""
from unittest.mock import patch

import pytest

from backend.graph import orchestrator as orch
from backend.graph.orchestrator import RouteDecision


@pytest.mark.db
def test_follow_source_creates_row(clean_db):
    from backend.memory import db as mem

    decision = RouteDecision(action="follow_source", url="https://newoutlet.example.com")
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        resp = orch.handle_message(message="follow https://newoutlet.example.com", company_id="cid")

    assert resp["action"] == "follow_source"
    urls = {s["url"] for s in mem.list_sources("cid")}
    assert "https://newoutlet.example.com" in urls


@pytest.mark.db
def test_unfollow_source_removes_matches(clean_db):
    from backend.memory import db as mem

    mem.add_source("cid", "https://a.example.com", name="Alpha", status="active", origin="user")
    mem.add_source("cid", "https://b.example.com", name="Beta", status="active", origin="user")

    decision = RouteDecision(action="unfollow_source", url_or_name="alpha")
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        resp = orch.handle_message(message="unfollow alpha", company_id="cid")

    urls = {s["url"] for s in mem.list_sources("cid")}
    assert "https://a.example.com" not in urls
    assert "https://b.example.com" in urls
    assert resp["result"]["count"] == 1


@pytest.mark.db
def test_forget_rule_removes_from_confirmed(clean_db):
    from backend.memory import db as mem

    mem.save_preferences("cid", confirmed_rules=["downrank hype", "reject too-shallow"])

    decision = RouteDecision(action="forget_rule", rule="downrank hype")
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        orch.handle_message(message="forget the hype rule", company_id="cid")

    prefs = mem.get_preferences("cid")
    assert "downrank hype" not in prefs["confirmed_rules"]
    assert "reject too-shallow" in prefs["confirmed_rules"]


@pytest.mark.db
def test_set_content_mix_more_owned_moves_up(clean_db, sample_profile):
    from backend.memory import db as mem

    mem.upsert_profile("cid", sample_profile)  # mix = 0.8

    decision = RouteDecision(action="set_content_mix", direction="more_owned", delta=0.1)
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        resp = orch.handle_message(message="post more about us", company_id="cid")

    assert resp["result"]["new"] == pytest.approx(0.9)


@pytest.mark.db
def test_set_content_mix_more_external_moves_down(clean_db, sample_profile):
    from backend.memory import db as mem

    mem.upsert_profile("cid", sample_profile)  # 0.8

    decision = RouteDecision(action="set_content_mix", direction="more_external", delta=0.2)
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        resp = orch.handle_message(message="lean into industry news", company_id="cid")

    assert resp["result"]["new"] == pytest.approx(0.6)


@pytest.mark.db
def test_explain_reject_returns_last_reason(clean_db):
    from backend.memory import db as mem

    mem.log_feedback("cid", "c_123", "reject", reason_code="off-brand", note="too corporate")

    decision = RouteDecision(action="explain_reject", item_id="c_123")
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        resp = orch.handle_message(message="why did you reject c_123?", company_id="cid")

    assert resp["result"]["reason_code"] == "off-brand"
    assert resp["result"]["note"] == "too corporate"


@pytest.mark.db
def test_chat_action_returns_reply(clean_db):
    """When the router picks 'chat', the reply is passed through."""
    decision = RouteDecision(action="chat", reply="Hey! Ask me to follow a source or search a topic.")
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        resp = orch.handle_message(message="hi", company_id="cid")
    assert resp["reply"].startswith("Hey!")
