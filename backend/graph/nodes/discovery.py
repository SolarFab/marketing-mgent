"""Source Discovery — proposes new followed sources.

PRD §4.3 + §6.5: **the agent proposes; the user disposes.** Discovered
sources are inserted with ``status='proposed'``; they never affect
Ideate until the user promotes them to ``active`` via the Sources tab.

Two entry points:

* :func:`discovery_node` — LangGraph-shaped node that reads state and
  writes ``source_proposals``. Not part of the content cycle by default
  (per PRD §4.3 it runs "periodically, not every cycle"); the API layer
  triggers it on demand.
* :func:`discover_and_stage` — plain-function wrapper the API calls,
  which also stages the proposals into the DB so the Sources tab can
  render them.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ...config import settings
from ...llm import make_llm
from ...memory import db as mem
from ...prompts import load_prompt
from ...tools.sources import normalize_source_url, outlet_name_from_title
from ...tools.web_search import search_outlets
from ..state import ContentState

log = logging.getLogger(__name__)


class SearchQueries(BaseModel):
    """Structured output for the discovery-query LLM step."""
    queries: list[str] = Field(default_factory=list, description="Search-engine-ready queries targeting outlets, not articles.")


def _llm_search_queries(profile: dict, *, n: int = 4) -> list[str]:
    """Ask the LLM for outlet-targeted search queries based on the profile.

    Falls back to a bag of profile-derived strings if the LLM call fails.
    """
    try:
        prompt = load_prompt("discovery_queries", "v1").format(
            n=n,
            profile=json.dumps(_compact_profile(profile), ensure_ascii=False)[:2500],
        )
        result: SearchQueries = make_llm(temperature=0.4).with_structured_output(SearchQueries).invoke(prompt)
        queries = [q.strip() for q in (result.queries or []) if q and q.strip()]
        if queries:
            return queries[:n]
    except Exception as e:
        log.warning("_llm_search_queries: LLM step failed (%s); using fallback", e)

    # Fallback: mine pillars + segments for topics
    pillars = list((profile.get("content_pillars") or {}).keys())[:3]
    segments = (profile.get("market") or {}).get("segments") or []
    seeds = [p.replace("_", " ") for p in pillars] + list(segments[:2])
    return [f"{s} news publication" for s in seeds][:n] or ["industry news publication"]


def _compact_profile(profile: dict) -> dict:
    return {
        "identity": profile.get("identity", {}),
        "market": profile.get("market", {}),
        "content_pillars": profile.get("content_pillars", {}),
        "content_mix": profile.get("content_mix"),
    }


def discovery_node(state: ContentState) -> dict:
    """Search for outlets covering the company's segments; return proposals.

    Every proposal is normalized to a **root domain + auto-detected RSS**
    via :func:`normalize_source_url`. Social/video destinations are
    filtered out. Dedup is at the host level, so we never propose two
    URLs from the same outlet in one run.

    Does not touch the DB — the API-layer wrapper handles staging so
    tests can exercise this node without a DB write.
    """
    profile = state.get("company_profile") or {}
    market = profile.get("market") or {}
    geo_list = market.get("geo") or []
    already_followed_hosts = _hosts([s.get("url") for s in (state.get("sources") or [])])
    already_followed_hosts |= _hosts(
        [s.get("root_url") if isinstance(s, dict) else None for s in (state.get("sources") or [])]
    )

    # LLM generates outlet-focused search queries based on the profile.
    # This is what fixes the "wrong audience" problem: for a curation publication,
    # queries target *what they read* (e.g. Chinese tech outlets), not
    # *who reads them* (e.g. European founders).
    queries = _llm_search_queries(profile, n=4)
    geo = geo_list[0] if geo_list else None

    proposals: list[dict] = []
    seen: set[str] = set(already_followed_hosts)
    skipped_articles = 0
    skipped_social = 0
    for query in queries:
        hits = search_outlets(topic=query, geo=geo, max_results=6)
        for h in hits:
            normalized = normalize_source_url(h.url, probe_feed=True)
            if not normalized.is_outlet:
                skipped_social += 1
                continue
            if not normalized.host or normalized.host in seen:
                skipped_articles += 1
                continue
            seen.add(normalized.host)
            proposals.append({
                "url": normalized.url,           # feed URL if kind==rss, else root
                "root_url": normalized.root_url, # always the site root — shown in UI
                "name": outlet_name_from_title(h.title, normalized.host),
                "kind": normalized.kind,
                "origin": "discovered",
                "reason": (h.snippet or f"Matched: {query}")[:200],
                "matched_query": query,
            })

    log.info(
        "discovery_node: queries=%d proposals=%d already_followed=%d skipped_articles=%d skipped_social=%d",
        len(queries), len(proposals), len(already_followed_hosts), skipped_articles, skipped_social,
    )
    return {"source_proposals": proposals}


def discover_and_stage(company_id: str) -> list[dict]:
    """Public entry: run discovery for ``company_id`` and stage proposals.

    Inserts each proposal into ``sources`` with ``status='proposed'`` so
    the Sources tab can render "Proposed by the agent". Returns the
    inserted rows.
    """
    profile = mem.get_profile(company_id) or {}
    if not profile:
        return []
    followed = mem.list_sources(company_id)
    state: ContentState = {
        "company_profile": profile,
        "sources": followed,
    }
    proposals = discovery_node(state)["source_proposals"]

    inserted: list[dict] = []
    for p in proposals:
        try:
            row = mem.add_source(
                company_id,
                url=p["url"],
                name=p.get("name"),
                kind=p.get("kind") or "web",
                status="proposed",
                origin="discovered",
                reason=p.get("reason"),
            )
            inserted.append(row)
        except Exception as e:
            log.warning("discover_and_stage: insert failed for %s: %s", p.get("url"), e)
    return inserted


def accept_proposed(source_id: str) -> None:
    """Promote a proposed source to active."""
    mem.update_source(source_id, status="active")


def dismiss_proposed(source_id: str) -> None:
    """Discard a proposed source. Only 'proposed' rows are removable this
    way — user-added or onboarded sources need the explicit unfollow flow.
    """
    row = mem.q1("SELECT status FROM sources WHERE source_id=%s", (source_id,))
    if row and row.get("status") == "proposed":
        mem.delete_source(source_id)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _hosts(urls: list[str | None]) -> set[str]:
    return {_host(u) for u in urls if u}
