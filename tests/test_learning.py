"""Tests for the Learning node — the meat of the "learns-from-feedback" bonus.

Coverage:

* Accumulate-then-confirm: one reject → no rule; enough rejects → pending
  rule; user confirms → confirmed rule; user deletes → gone.
* Per-source hit-rate: approving an external item bumps items_approved
  on the right source.
* Under-performing sources: flagged only after enough samples, and the
  agent never silently removes them.
"""
import pytest

from backend.graph.nodes import learning


COMPANY = "cid_learn"


def _log_reject(cid, reason, item_id="i", cycle_id="c1"):
    from backend.memory import db as mem

    mem.log_feedback(cid, item_id, "reject", reason_code=reason, cycle_id=cycle_id)


@pytest.mark.db
def test_one_reject_does_not_propose_a_rule(clean_db):
    from backend.memory import db as mem

    _log_reject(COMPANY, "off-brand")
    state = {"company_id": COMPANY, "feedback": [], "approved": []}
    learning.learning_node(state)

    prefs = mem.get_preferences(COMPANY)
    assert prefs.get("pending_rules") == []


@pytest.mark.db
def test_stable_pattern_proposes_pending_rule(clean_db, monkeypatch):
    """When ≥ LEARNING_MIN_SAMPLES rejects share a reason, a rule is proposed."""
    monkeypatch.setenv("LEARNING_MIN_SAMPLES", "3")
    monkeypatch.setenv("LEARNING_WINDOW", "8")
    # Reset the cached settings so the new env values take effect
    from backend.config import settings as _s
    _s.cache_clear()

    from backend.memory import db as mem

    for i in range(3):
        _log_reject(COMPANY, "off-brand", item_id=f"i{i}")

    state = {"company_id": COMPANY, "feedback": [], "approved": []}
    learning.learning_node(state)

    prefs = mem.get_preferences(COMPANY)
    pending = prefs.get("pending_rules") or []
    assert any("off-brand" in r for r in pending)


@pytest.mark.db
def test_confirm_pending_rule_moves_it(clean_db):
    from backend.memory import db as mem

    mem.save_preferences(
        COMPANY,
        pending_rules=["downrank off-brand items"],
        confirmed_rules=[],
    )
    learning.confirm_rule(COMPANY, "downrank off-brand items")

    prefs = mem.get_preferences(COMPANY)
    assert prefs["confirmed_rules"] == ["downrank off-brand items"]
    assert prefs["pending_rules"] == []


@pytest.mark.db
def test_delete_confirmed_rule(clean_db):
    from backend.memory import db as mem

    mem.save_preferences(COMPANY, confirmed_rules=["some rule"])
    learning.delete_rule(COMPANY, "some rule")

    prefs = mem.get_preferences(COMPANY)
    assert prefs["confirmed_rules"] == []


@pytest.mark.db
def test_dismiss_pending_rule(clean_db):
    from backend.memory import db as mem

    mem.save_preferences(COMPANY, pending_rules=["rule A", "rule B"])
    learning.dismiss_pending_rule(COMPANY, "rule A")

    prefs = mem.get_preferences(COMPANY)
    assert prefs["pending_rules"] == ["rule B"]


@pytest.mark.db
def test_approved_external_item_bumps_source_counters(clean_db):
    from backend.memory import db as mem

    src = mem.add_source(COMPANY, "https://x.example.com", kind="rss")
    approved = [
        {"id": "c1", "kind": "external", "source_id": src["source_id"]},
        {"id": "c2", "kind": "owned", "source_id": None},  # no bump
    ]
    state = {"company_id": COMPANY, "approved": approved, "feedback": []}
    learning.learning_node(state)

    listed = mem.list_sources(COMPANY)
    assert listed[0]["items_approved"] == 1


@pytest.mark.db
def test_underperforming_source_is_flagged_not_removed(clean_db):
    from backend.memory import db as mem

    src = mem.add_source(COMPANY, "https://bad.example.com", kind="rss")
    # Simulate 10 surfaced, 1 approved (10% hit rate)
    mem.bump_source_counters(src["source_id"], surfaced=10, approved=1)

    flagged = learning.underperforming_sources(COMPANY, min_surfaced=6, threshold=0.2)
    assert len(flagged) == 1
    assert flagged[0]["hit_rate"] == pytest.approx(0.1)

    # Source is NOT removed — the "propose, never dispose" discipline
    still_there = mem.list_sources(COMPANY)
    assert len(still_there) == 1
