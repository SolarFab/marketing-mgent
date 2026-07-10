"""HTTP-level integration tests using FastAPI's TestClient.

These are meant to prove the endpoint contract (status codes, response
shape) end-to-end without launching a real server. Graph invocations
are patched where they'd be slow — we're testing the wiring, not the
graph again.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(clean_db):
    from backend.app import app

    with TestClient(app) as c:
        yield c


@pytest.mark.db
def test_root_returns_service_info(client):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "signal-content-agent"
    assert "company_id_default" in data


@pytest.mark.db
def test_profile_404_when_missing(client):
    r = client.get("/profile", params={"company_id": "nonexistent"})
    assert r.status_code == 404


@pytest.mark.db
def test_profile_put_and_get_roundtrip(client, sample_profile):
    r = client.put("/profile", json={"company_id": "api_cid", "profile": sample_profile})
    assert r.status_code == 200
    r = client.get("/profile", params={"company_id": "api_cid"})
    assert r.status_code == 200
    assert r.json()["content_mix"] == pytest.approx(0.8)


@pytest.mark.db
def test_sources_add_list_delete(client):
    r = client.post("/sources", json={"company_id": "api_cid", "url": "https://s.example.com", "kind": "rss"})
    assert r.status_code == 200
    src = r.json()["source"]
    sid = src["source_id"]

    r = client.get("/sources", params={"company_id": "api_cid"})
    assert any(s["source_id"] == sid for s in r.json()["sources"])

    r = client.patch(f"/sources/{sid}", json={"status": "paused"})
    assert r.status_code == 200

    r = client.delete(f"/sources/{sid}")
    assert r.status_code == 200


@pytest.mark.db
def test_learning_endpoints(client):
    from backend.memory import db as mem

    mem.save_preferences("api_cid", pending_rules=["downrank hype"], confirmed_rules=[])

    r = client.get("/learning", params={"company_id": "api_cid"})
    assert "downrank hype" in r.json()["pending_rules"]

    r = client.post("/learning/confirm", json={"company_id": "api_cid", "rule": "downrank hype"})
    assert r.status_code == 200

    r = client.get("/learning", params={"company_id": "api_cid"})
    assert "downrank hype" in r.json()["confirmed_rules"]

    r = client.delete("/learning/downrank hype", params={"company_id": "api_cid"})
    assert r.status_code == 200


@pytest.mark.db
def test_feedback_write(client):
    from backend.memory import db as mem

    r = client.post("/feedback", json={
        "company_id": "api_cid",
        "item_id": "c_1",
        "decision": "reject",
        "reason_code": "off-brand",
        "cycle_id": "cyc_1",
    })
    assert r.status_code == 200
    rows = mem.recent_feedback("api_cid")
    assert len(rows) == 1
    assert rows[0]["reason_code"] == "off-brand"


@pytest.mark.db
def test_chat_dispatches_to_orchestrator(client):
    from backend.graph.orchestrator import RouteDecision

    decision = RouteDecision(action="follow_source", url="https://xyz.example.com")
    with patch("backend.graph.orchestrator._route_message", return_value=decision):
        r = client.post("/chat", json={"company_id": "api_cid", "message": "follow xyz"})

    assert r.status_code == 200
    assert r.json()["action"] == "follow_source"


@pytest.mark.db
def test_analytics_approval_rate_shape(client):
    from backend.memory import db as mem

    mem.log_feedback("api_cid", "c_1", "approve", cycle_id="cyc_1")
    mem.log_feedback("api_cid", "c_2", "reject", reason_code="off-brand", cycle_id="cyc_1")

    r = client.get("/analytics/approval_rate", params={"company_id": "api_cid"})
    data = r.json()
    assert len(data["cycles"]) == 1
    row = data["cycles"][0]
    assert row["total"] == 2
    assert row["approved"] == 1
    assert row["rate"] == 0.5


@pytest.mark.db
def test_analytics_source_hit_rates(client):
    from backend.memory import db as mem

    s = mem.add_source("api_cid", "https://x.example.com", kind="rss")
    mem.bump_source_counters(s["source_id"], surfaced=5, approved=2)

    r = client.get("/analytics/source_hit_rates", params={"company_id": "api_cid"})
    row = r.json()["sources"][0]
    assert row["surfaced"] == 5
    assert row["approved"] == 2
    assert row["rate"] == pytest.approx(0.4)
