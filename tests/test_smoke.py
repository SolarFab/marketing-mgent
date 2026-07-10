"""Sanity tests — proves the test harness itself works.

Fast, deterministic. If any of these fail, nothing downstream will pass.
"""
import os

import pytest


def test_env_reroutes_to_test_branch():
    """conftest.py must swap DATABASE_URL for TEST_DATABASE_URL."""
    assert os.environ["DATABASE_URL"] == os.environ["TEST_DATABASE_URL"], (
        "conftest didn't reroute DATABASE_URL — tests could hit prod!"
    )


@pytest.mark.db
def test_db_connection_works():
    from backend.memory.db import q1

    row = q1("SELECT 1 AS ok")
    assert row == {"ok": 1}


@pytest.mark.db
def test_schema_has_all_tables():
    from backend.memory.db import q

    rows = q(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    tables = {r["tablename"] for r in rows}
    expected = {
        "company_profile",
        "content_history",
        "cycles",
        "drafts",
        "feedback_log",
        "preference_profile",
        "publish_log",
        "sources",
    }
    assert expected.issubset(tables), f"missing: {expected - tables}"


@pytest.mark.db
def test_profile_crud_roundtrip(clean_db, sample_profile):
    from backend.memory.db import get_profile, upsert_profile

    upsert_profile("test_co", sample_profile, crawled_urls=["https://example.com"])
    loaded = get_profile("test_co")

    assert loaded is not None
    assert loaded["content_mix"] == pytest.approx(0.8)
    assert loaded["voice"]["tone"] == ["warm", "earthy", "unpretentious"]
    assert loaded["identity"]["products"] == ["Riesling 2023", "Pinot Noir", "cellar tours"]


@pytest.mark.db
def test_source_add_and_bump(clean_db):
    from backend.memory.db import (
        add_source,
        bump_source_counters,
        list_sources,
    )

    s = add_source("test_co", "https://example.com/feed", kind="rss")
    assert s["url"] == "https://example.com/feed"

    bump_source_counters(s["source_id"], surfaced=3, approved=1)
    listed = list_sources("test_co")
    assert len(listed) == 1
    assert listed[0]["items_surfaced"] == 3
    assert listed[0]["items_approved"] == 1
