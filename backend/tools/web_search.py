"""Web search via Tavily.

Used by two nodes:

* **Ideate/Source** — searches for recent items in the company's space to
  supplement RSS/website sourcing when the followed-source list is thin
  or the requested topic isn't covered.
* **Source Discovery** — searches for *outlets* (news sites, industry
  blogs, newsletters) that publish about the company's segments, so the
  agent can propose new sources to the user.

Two entry points:

* :func:`search_content` — returns individual articles/pages with a
  title, url, and short snippet.
* :func:`search_outlets` — returns homepage-shaped results suitable for
  proposing as followed sources.

Both return an empty list on failure (never raise). The caller decides
whether an empty search means "skip" or "warn user".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import settings

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    published_date: str | None = None  # ISO date when Tavily has it


def search_content(query: str, *, max_results: int = 8, days: int = 7) -> list[SearchResult]:
    """Search the web for recent articles matching ``query``.

    ``topic='news'`` biases toward news outlets and applies the ``days``
    recency window (Tavily quirk: the ``days`` param only works with
    news topic).
    """
    return _tavily_search(query, max_results=max_results, depth="advanced", topic="news", days=days)


def search_content_on_site(*, domain: str, query: str = "recent articles", max_results: int = 6, days: int = 14) -> list[SearchResult]:
    """Site-restricted content search — the Ideate node's fallback for non-RSS sources.

    When a followed source is a plain website (no RSS), we still want the
    agent to *actually pull items from that outlet* — not do a generic
    web search. Tavily's ``include_domains`` narrows results to the given
    domain; ``topic='news'`` + ``days`` keeps them recent.
    """
    return _tavily_search(
        query,
        max_results=max_results,
        depth="advanced",
        include_domains=[domain],
        topic="news",
        days=days,
    )


def search_outlets(topic: str, geo: str | None = None, *, max_results: int = 6) -> list[SearchResult]:
    """Search for *outlets* covering ``topic`` — used by Source Discovery.

    The query is shaped to favour homepages and about-pages of publishers
    rather than individual articles.
    """
    parts = [topic, "blog OR newsletter OR magazine OR publication"]
    if geo:
        parts.append(geo)
    query = " ".join(parts)
    return _tavily_search(query, max_results=max_results, depth="basic")


def _tavily_search(
    query: str,
    *,
    max_results: int,
    depth: str,
    include_domains: list[str] | None = None,
    topic: str | None = None,
    days: int | None = None,
) -> list[SearchResult]:
    key = settings().tavily_api_key
    if not key:
        log.warning("web_search: TAVILY_API_KEY missing, returning [] for %r", query)
        return []
    try:
        # Local import so the module remains importable in envs without tavily
        from tavily import TavilyClient  # type: ignore

        client = TavilyClient(api_key=key)
        kwargs: dict = {"query": query, "search_depth": depth, "max_results": max_results}
        if include_domains:
            kwargs["include_domains"] = include_domains
        if topic:
            kwargs["topic"] = topic
            if days is not None:
                kwargs["days"] = days
        raw = client.search(**kwargs)
    except Exception as e:
        log.warning("web_search: tavily call failed for %r: %s", query, e)
        return []

    results: list[SearchResult] = []
    for r in (raw.get("results") or []):
        url = r.get("url") or ""
        if not url:
            continue
        results.append(
            SearchResult(
                title=(r.get("title") or url)[:200],
                url=url,
                snippet=(r.get("content") or "")[:500],
                score=float(r.get("score") or 0.0),
                published_date=r.get("published_date"),
            )
        )
    return results
