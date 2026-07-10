"""Evaluate node — scores candidates and routes them.

PRD §4.3 & §5.4:

    Deterministic score (math), LLM rationale.

**Score components (each 0.0-1.0):**

* ``relevance``  — cosine-ish keyword overlap between the item and the profile's
  segments / ICP / vocabulary. Deterministic.
* ``novelty``    — 1.0 if the item's title isn't in recent ``content_history``,
  otherwise a small penalty. Deterministic.
* ``pillar_fit`` — 1.0 if the item's ``pillar`` matches one in the profile's
  ``content_pillars``. Deterministic.
* ``source_hit`` — for external items, the per-source approval rate
  (``items_approved / items_surfaced``). Owned items get a neutral 0.5.
  Deterministic.
* ``pref_boost`` — sum of matches against ``preference_profile.positive_signals``
  minus matches against ``negative_filters`` and ``confirmed_rules``. Learned
  weight, deterministic given the profile.

**Final score:** weighted average, clamped to [0, 1]. Weights are in
:data:`WEIGHTS` — kept as a plain dict so eval scripts can override them for
experiments without touching this file.

**Routing:**

* ``score >= FEATURE_THRESHOLD``  → route ``feature``
* ``score >= UNCERTAIN_THRESHOLD`` → route ``uncertain`` (shown in Review with
  a nudge to double-check)
* otherwise                        → route ``discard`` (hidden by default;
  visible under a "why was this dropped" toggle in Review)

The **LLM only writes the rationale** — one call per item at most, and only
for items that survive to feature or uncertain. Discards get a canned
one-liner so we save tokens.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from ...llm import make_llm
from ...prompts import load_prompt
from ..state import ContentState

log = logging.getLogger(__name__)


WEIGHTS: dict[str, float] = {
    "relevance": 0.35,
    "novelty": 0.15,
    "pillar_fit": 0.15,
    "source_hit": 0.15,
    "pref_boost": 0.20,
}

FEATURE_THRESHOLD = 0.55
UNCERTAIN_THRESHOLD = 0.42


@dataclass
class ScoreBreakdown:
    """Per-candidate component scores + final."""
    relevance: float
    novelty: float
    pillar_fit: float
    source_hit: float
    pref_boost: float
    final: float

    def as_dict(self) -> dict[str, float]:
        return {
            "relevance": round(self.relevance, 3),
            "novelty": round(self.novelty, 3),
            "pillar_fit": round(self.pillar_fit, 3),
            "source_hit": round(self.source_hit, 3),
            "pref_boost": round(self.pref_boost, 3),
            "final": round(self.final, 3),
        }


# --- Entry point ---

def evaluate_node(state: ContentState) -> dict:
    """Score every candidate, decide a route, attach a rationale."""
    candidates: list[dict] = state.get("candidates") or []
    if not candidates:
        return {"scored": []}

    profile = state.get("company_profile") or {}
    prefs = state.get("preference_profile") or {}
    sources_by_id = {s["source_id"]: s for s in (state.get("sources") or [])}

    scored: list[dict] = []
    for c in candidates:
        breakdown = _score_candidate(c, profile=profile, prefs=prefs, sources=sources_by_id)
        route = _route(breakdown.final)
        item = {
            **c,
            "score": breakdown.as_dict(),
            "route": route,
            "rationale": _rationale(c, profile=profile, breakdown=breakdown, route=route),
        }
        scored.append(item)

    scored.sort(key=lambda i: i["score"]["final"], reverse=True)
    log.info(
        "evaluate_node: n=%d feature=%d uncertain=%d discard=%d",
        len(scored),
        sum(1 for x in scored if x["route"] == "feature"),
        sum(1 for x in scored if x["route"] == "uncertain"),
        sum(1 for x in scored if x["route"] == "discard"),
    )
    return {"scored": scored}


# --- Scoring components ---

def _score_candidate(
    c: dict, *, profile: dict, prefs: dict, sources: dict[str, dict],
) -> ScoreBreakdown:
    relevance = _relevance(c, profile)
    novelty = _novelty(c)
    pillar_fit = _pillar_fit(c, profile)
    source_hit = _source_hit(c, sources)
    pref_boost = _pref_boost(c, prefs)

    final = (
        WEIGHTS["relevance"] * relevance
        + WEIGHTS["novelty"] * novelty
        + WEIGHTS["pillar_fit"] * pillar_fit
        + WEIGHTS["source_hit"] * source_hit
        + WEIGHTS["pref_boost"] * pref_boost
    )
    return ScoreBreakdown(
        relevance=relevance,
        novelty=novelty,
        pillar_fit=pillar_fit,
        source_hit=source_hit,
        pref_boost=pref_boost,
        final=max(0.0, min(1.0, final)),
    )


def _relevance(c: dict, profile: dict) -> float:
    """Bag-of-words overlap between item text and profile signals.

    Kept intentionally simple — no embeddings, no LLM. If we later want to
    swap in embeddings, this function is the only thing to change.
    """
    market = profile.get("market") or {}
    voice = profile.get("voice") or {}
    identity = profile.get("identity") or {}
    signal_bag = set()
    for coll in (
        market.get("segments") or [],
        market.get("geo") or [],
        identity.get("products") or [],
        voice.get("vocabulary") or [],
    ):
        for s in coll:
            signal_bag |= _tokens(s)
    if market.get("icp"):
        signal_bag |= _tokens(market["icp"])

    if not signal_bag:
        return 0.5  # unknown profile: neutral

    item_bag = _tokens(c.get("title", "")) | _tokens(c.get("angle", ""))
    if not item_bag:
        return 0.0
    overlap = len(signal_bag & item_bag)
    # Normalize: number of overlap terms / expected max (5 seems fair)
    return min(1.0, overlap / 5.0)


def _novelty(c: dict) -> float:
    """Owned items are novel by default; external items were freshly fetched.

    Content_history dedup already ran in Ideate, so anything reaching here is
    novel. We keep the field as a hook for future signals (e.g. downweighting
    a topic we've covered 3 times this month).
    """
    return 1.0


def _pillar_fit(c: dict, profile: dict) -> float:
    pillar = (c.get("pillar") or "").strip().lower()
    if not pillar:
        return 0.5
    known = {p.lower() for p in (profile.get("content_pillars") or {}).keys()}
    return 1.0 if pillar in known else 0.4


def _source_hit(c: dict, sources: dict[str, dict]) -> float:
    if c.get("kind") == "owned":
        return 0.5  # neutral — not a source-driven signal
    sid = c.get("source_id")
    if not sid or sid not in sources:
        return 0.5
    src = sources[sid]
    surfaced = int(src.get("items_surfaced") or 0)
    approved = int(src.get("items_approved") or 0)
    if surfaced < 3:
        return 0.5  # too little data — don't punish new sources
    return max(0.0, min(1.0, approved / surfaced))


def _pref_boost(c: dict, prefs: dict) -> float:
    positive: list[dict] = prefs.get("positive_signals") or []
    negative: list[dict] = prefs.get("negative_filters") or []
    rules: list[str] = prefs.get("confirmed_rules") or []

    text = f"{c.get('title', '')} {c.get('angle', '')}".lower()
    boost = 0.0
    for sig in positive:
        pattern = str(sig.get("signal", "")).lower()
        if pattern and pattern in text:
            boost += float(sig.get("weight") or 0.1)

    for filt in negative:
        pattern = str(filt.get("reason", "")).lower()
        if pattern and pattern in text:
            boost -= 0.5

    for rule in rules:
        # A confirmed rule is a plain-text statement; we look for a phrase-match penalty
        r = str(rule).lower()
        if "downrank" in r or "reject" in r:
            # extract the target phrase after 'downrank ' or 'reject '
            m = re.search(r"(?:downrank|reject)\s+(.+)", r)
            if m and m.group(1).strip() in text:
                boost -= 0.4

    # Center on 0.5 so no preferences = neutral
    return max(0.0, min(1.0, 0.5 + boost))


def _route(score: float) -> str:
    if score >= FEATURE_THRESHOLD:
        return "feature"
    if score >= UNCERTAIN_THRESHOLD:
        return "uncertain"
    return "discard"


# --- Rationale (LLM, one call per non-discarded item) ---

def _rationale(c: dict, *, profile: dict, breakdown: ScoreBreakdown, route: str) -> str:
    if route == "discard":
        # Canned reason — saves tokens on items the user rarely inspects
        return _canned_discard_reason(breakdown)
    return _llm_rationale(c, profile=profile, breakdown=breakdown, route=route)


def _llm_rationale(
    c: dict, *, profile: dict, breakdown: ScoreBreakdown, route: str
) -> str:
    prompt = load_prompt("evaluate_rationale", "v1").format(
        profile=json.dumps(_compact_profile(profile), ensure_ascii=False)[:1500],
        item=json.dumps(
            {k: c.get(k) for k in ("title", "angle", "kind", "pillar", "url")},
            ensure_ascii=False,
        ),
        scores=json.dumps(breakdown.as_dict()),
        route=route,
    )
    try:
        r = make_llm(temperature=0.3).invoke(prompt)
        return str(r.content).strip()
    except Exception as e:
        log.warning("_llm_rationale: LLM call failed (%s), using canned", e)
        return _canned_reason(breakdown, route)


def _canned_discard_reason(b: ScoreBreakdown) -> str:
    parts: list[str] = []
    if b.relevance < 0.3:
        parts.append("low relevance to profile")
    if b.pillar_fit < 0.5:
        parts.append("pillar mismatch")
    if b.pref_boost < 0.4:
        parts.append("hits a learned negative signal")
    if b.source_hit < 0.3:
        parts.append("source has a low approval history")
    return ", ".join(parts) or "low overall score"


def _canned_reason(b: ScoreBreakdown, route: str) -> str:
    if route == "feature":
        return "Strong fit across relevance and pillar; source history supports featuring."
    return "Borderline — decide by hand."


def _compact_profile(profile: dict) -> dict:
    """Only include the fields the rationale prompt actually uses."""
    return {
        "identity": profile.get("identity", {}),
        "market": profile.get("market", {}),
        "voice": profile.get("voice", {}),
        "content_pillars": profile.get("content_pillars", {}),
    }


def _tokens(s: str) -> set[str]:
    """Lowercase words of length ≥ 3, no stopwords."""
    if not s:
        return set()
    return {
        w.lower()
        for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", s.lower())
        if w.lower() not in _STOP
    }


_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "you", "our", "your",
    "are", "was", "has", "have", "had", "not", "but", "how", "why", "who",
    "into", "will", "can", "over", "all", "any", "new",
}
