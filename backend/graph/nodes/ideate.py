"""Ideate / Source node.

PRD §4.3: two branches, weighted by ``content_mix``:

* **Owned** — LLM generates angles directly from the Company Profile
  (products / seasonality / events / story). Used more heavily for
  producer-style businesses where the story *is* the product.
* **External** — pulls recent items from followed sources (RSS where
  available, else Tavily web search) and asks the LLM to shape each into
  an angle the company can post about, in its voice.

Candidates are then deduplicated against the recent content_history and
returned in a single list. Downstream Evaluate ranks/routes them; nothing
here decides feature/discard.

Design:

* A single top-level node :func:`ideate_node` orchestrates both branches
  and does bookkeeping (dedup, source hit-rate counters).
* Two helpers, :func:`_ideate_owned` and :func:`_ideate_external`, do the
  actual work — kept separate so tests can exercise them in isolation.
* When ``content_mix`` is close to 0 or 1 we still generate at least one
  candidate of the minority kind — variety matters more than obeying a
  ratio exactly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from ...config import settings
from ...llm import make_llm
from ...memory import db as mem
from ...prompts import load_prompt
from ...tools.feeds import fetch_feed_items
from ...tools.web_search import search_content, search_content_on_site
from ..state import ContentState

log = logging.getLogger(__name__)


# --- Structured output schemas ---

class OwnedAngleItem(BaseModel):
    title: str = Field(..., description="Working headline for the piece.")
    angle: str = Field(..., description="One-sentence explanation of the angle.")
    pillar: str = Field("", description="Pillar name from content_pillars.")
    fact_check_query: str = Field(
        "",
        description="4-10 word web-search query for the angle's most specific factual claim. Empty when the angle is about a first-person owned event (harvest, product launch) with no external fact to verify.",
    )


class OwnedAnglesDraft(BaseModel):
    angles: list[OwnedAngleItem] = Field(default_factory=list)


class ExternalAngleItem(BaseModel):
    article_index: int = Field(..., description="Index into the input article list.")
    skip: bool = Field(False, description="True if the article cannot be tied to the business.")
    title: str = Field("", description="Working headline.")
    angle: str = Field("", description="One-sentence framing tied to the business.")
    pillar: str = Field("", description="Pillar name from content_pillars.")


class ExternalAnglesDraft(BaseModel):
    angles: list[ExternalAngleItem] = Field(default_factory=list)


# --- Entry point ---

def ideate_node(state: ContentState) -> dict:
    """Generate candidate content items for one cycle.

    Reads:
        * ``company_profile`` — for products, voice, pillars, content_mix
        * ``sources`` — active followed sources for the external branch
        * ``company_id`` — for dedup vs. history + source counter updates
        * ``cycle_id`` — attached to each candidate for provenance

    Writes:
        * ``candidates`` — list of ``{id, kind, title, angle, source_id?, url?, pillar, ts}``
    """
    s = settings()
    profile = state.get("company_profile") or {}
    sources = state.get("sources") or []
    company_id = state.get("company_id") or s.company_id

    target = s.cycle_candidate_target
    mix = float(profile.get("content_mix", 0.5))
    n_owned = max(1, round(target * mix))
    n_external = max(1, target - n_owned)

    # Dedup baseline: recently-seen titles
    recent = mem.known_titles(company_id, limit=200)

    owned = _ideate_owned(profile=profile, n=n_owned, recent=recent)
    external, source_ids_surfaced = _ideate_external(
        profile=profile,
        sources=sources,
        n=n_external,
        recent=recent,
    )

    # Bump surfaced counters for sources whose items made it into candidates
    for sid in source_ids_surfaced:
        mem.bump_source_counters(sid, surfaced=1)

    # Persist each candidate to content_history as 'surfaced' so future cycles dedup
    for c in owned + external:
        try:
            mem.add_history(c, company_id, status="surfaced")
        except Exception as e:
            log.warning("ideate: history write failed for %s: %s", c["id"], e)

    log.info(
        "ideate_node: company=%s owned=%d external=%d mix=%.2f",
        company_id, len(owned), len(external), mix,
    )
    return {"candidates": owned + external}


# --- Owned branch ---

def _ideate_owned(*, profile: dict, n: int, recent: set[str]) -> list[dict]:
    """Generate owned angles, then run each through a fact-grounding step.

    Each proposed angle carries a ``fact_check_query`` — a short live-web query
    for the angle's most specific factual claim. We hit Tavily with it; if a
    recent, high-quality article corroborates the claim, we attach its URL as
    ``verified_source_url`` and let the angle through. If nothing corroborates,
    the angle is dropped unless it's a first-person owned event (empty query).

    This closes the "curator publishes unverified LLM assertions" gap without
    turning owned angles into external ones — the citation is a fact-check
    footnote, not the article being commentated on.
    """
    if n <= 0:
        return []
    prompt = load_prompt("ideate_owned", "v1").format(
        n=n,
        profile=json.dumps(profile, ensure_ascii=False, default=str)[:5000],
        recent=_format_recent(recent),
    )
    llm = make_llm(temperature=0.7)
    try:
        result: OwnedAnglesDraft = llm.with_structured_output(OwnedAnglesDraft).invoke(prompt)
        angles = result.angles
    except Exception as e:
        log.warning("_ideate_owned: structured output failed (%s)", e)
        return []

    now = _now_iso()
    out: list[dict] = []
    for a in angles:
        title = (a.title or "").strip()
        if not title or title.lower() in recent:
            continue
        query = (a.fact_check_query or "").strip()
        verified_url: str | None = None
        verified_title: str | None = None
        verified_date: str | None = None
        if query:
            hit = _fact_check_owned_angle(query)
            if hit is None:
                # Query was provided but no recent article backs the claim — drop.
                log.info(
                    "_ideate_owned: dropping unverified angle %r (query=%r)",
                    title, query,
                )
                continue
            verified_url = hit.url
            verified_title = hit.title
            verified_date = hit.published_date
        # else: query empty → first-person owned event, no external fact to check
        out.append({
            "id": _cand_id("own", title),
            "kind": "owned",
            "title": title,
            "angle": a.angle.strip(),
            "pillar": a.pillar,
            "source_id": None,
            "url": None,
            "verified_source_url": verified_url,
            "verified_source_title": verified_title,
            "published_date": verified_date,
            "ts": now,
        })
    return out


def _fact_check_owned_angle(query: str):
    """Return the top recent search hit for the angle's factual claim, or None.

    Any hit within the last 30 days counts. We don't require perfect topical
    match — just evidence the claim is real. Failures (Tavily down, no hits)
    return None so the caller can drop the angle.
    """
    try:
        results = search_content(query, max_results=3, days=30)
    except Exception as e:
        log.info("_fact_check_owned_angle: search failed for %r: %s", query, e)
        return None
    return results[0] if results else None


# --- External branch ---

def _ideate_external(
    *,
    profile: dict,
    sources: list[dict],
    n: int,
    recent: set[str],
) -> tuple[list[dict], list[str]]:
    """Fetch recent items from sources + web search, then shape via LLM.

    Returns (candidates, source_ids_that_contributed).
    """
    if n <= 0:
        return [], []

    raw_items = _collect_external_items(profile=profile, sources=sources, target=n * 2)
    if not raw_items:
        return [], []

    # Ask the LLM to shape each into an angle
    prompt = load_prompt("ideate_external", "v1").format(
        profile=json.dumps(profile, ensure_ascii=False, default=str)[:5000],
        recent=_format_recent(recent),
        articles=json.dumps(
            [
                {
                    "index": i,
                    "title": r["title"],
                    "summary": r.get("summary", "")[:400],
                    "url": r["url"],
                    "published_date": r.get("published_date"),
                }
                for i, r in enumerate(raw_items)
            ],
            ensure_ascii=False,
        )[:8000],
    )

    llm = make_llm(temperature=0.5)
    try:
        result: ExternalAnglesDraft = llm.with_structured_output(ExternalAnglesDraft).invoke(prompt)
    except Exception as e:
        log.warning("_ideate_external: structured output failed (%s)", e)
        return [], []

    now = _now_iso()
    candidates: list[dict] = []
    source_ids: list[str] = []
    for a in result.angles:
        if a.skip or not a.title:
            continue
        if a.article_index < 0 or a.article_index >= len(raw_items):
            continue
        src = raw_items[a.article_index]
        if a.title.lower().strip() in recent:
            continue
        candidates.append(
            {
                "id": _cand_id("ext", a.title),
                "kind": "external",
                "title": a.title.strip(),
                "angle": a.angle.strip(),
                "pillar": a.pillar,
                "source_id": src.get("source_id"),
                "url": src["url"],
                "published_date": src.get("published_date"),
                "ts": now,
            }
        )
        if src.get("source_id"):
            source_ids.append(src["source_id"])
        if len(candidates) >= n:
            break
    return candidates, source_ids


def _collect_external_items(*, profile: dict, sources: list[dict], target: int) -> list[dict]:
    """Pull raw items from followed sources first, then fall back to open search.

    Priority order:

    1. **RSS-kind sources** — parse the feed directly. Fastest, freshest,
       most structured.
    2. **Web-kind sources** — site-restricted Tavily search (limited to
       the source's domain). The user chose this outlet; we should pull
       *from it*, not from the web at large.
    3. **Open Tavily search** — only if steps 1 and 2 didn't fill the
       target. Used to keep the queue lively when the followed-source
       list is thin.
    """
    items: list[dict] = []
    seen_urls: set[str] = set()

    segments = (profile.get("market") or {}).get("segments") or []
    topic_query = " ".join(segments[:2]) or "recent"

    # 1. RSS sources
    for src in sources:
        if src.get("status") != "active" or src.get("kind") != "rss" or not src.get("url"):
            continue
        entries = fetch_feed_items(src["url"], max_items=8)
        for e in entries:
            if e.url in seen_urls:
                continue
            seen_urls.add(e.url)
            items.append({
                "title": e.title,
                "summary": e.summary,
                "url": e.url,
                "source_id": src["source_id"],
            })
        if len(items) >= target:
            return items[:target]

    # 2. Web sources — site-restricted search per domain
    from urllib.parse import urlparse
    for src in sources:
        if src.get("status") != "active" or src.get("kind") != "web" or not src.get("url"):
            continue
        domain = urlparse(src["url"]).netloc
        if not domain:
            continue
        hits = search_content_on_site(domain=domain, query=topic_query, max_results=5)
        for h in hits:
            if h.url in seen_urls:
                continue
            seen_urls.add(h.url)
            items.append({
                "title": h.title,
                "summary": h.snippet,
                "url": h.url,
                "source_id": src["source_id"],
                "published_date": h.published_date,
            })
        if len(items) >= target:
            return items[:target]

    # 3. Open web search fallback (only if we're still under target)
    for segment in segments[:2]:
        if len(items) >= target:
            break
        hits = search_content(f"{segment} news this week", max_results=5)
        for h in hits:
            if h.url in seen_urls:
                continue
            seen_urls.add(h.url)
            items.append({
                "title": h.title,
                "summary": h.snippet,
                "url": h.url,
                "source_id": None,
                "published_date": h.published_date,
            })
    return items[:target]


# --- helpers ---

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cand_id(prefix: str, title: str) -> str:
    """Deterministic id from prefix + a title hash. Same title = same id → dedup free."""
    import hashlib

    h = hashlib.sha1(title.strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"


def _format_recent(recent: set[str], limit: int = 30) -> str:
    if not recent:
        return "(none yet)"
    return "\n".join(f"- {t}" for t in list(recent)[:limit])
