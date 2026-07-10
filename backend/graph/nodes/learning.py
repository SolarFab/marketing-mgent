"""Learning update — the accumulate-then-confirm engine (PRD §6).

Four separations enforced here:

1. **Structured feedback, not free-text.** Every ``feedback_log`` row has a
   ``reason_code`` from a fixed vocabulary (see :data:`REASON_CODES`). The
   free-text ``note`` is stored but never used to derive rules.

2. **Accumulate, don't react.** A single reject changes nothing. We look
   at the last :data:`LEARNING_WINDOW` rejects and only propose a rule
   when a single reason accounts for at least :data:`LEARNING_MIN_SAMPLES`
   of them. Both are env-tunable so demos can trigger patterns faster.

3. **Adjust ranking, not sourcing.** The learning update writes to
   ``preference_profile`` (which feeds Evaluate's scoring), never to
   ``sources`` (which drives Ideate's sourcing). Novelty is preserved.

4. **Confirm the rule, not just the item.** A detected pattern becomes a
   ``pending_rule`` — a hypothesis for the user to confirm. Only after the
   user clicks "confirm" via the API does it move to ``confirmed_rules``.

Also: this node updates **per-source hit-rate** counters (approved wins,
surfaced already bumped in Ideate) and flags underperforming sources for
the UI to surface an "unfollow?" prompt.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from ...config import settings
from ...memory import db as mem
from ..state import ContentState

log = logging.getLogger(__name__)

REASON_CODES = (
    "off-brand",
    "wrong-product",
    "not-my-voice",
    "too-promotional",
    "already-said",
    "not-relevant-now",
    "source-not-credible",
    "too-shallow",
)


def learning_node(state: ContentState) -> dict:
    """Aggregate approve/reject feedback and update the preference profile.

    Reads:
        * ``company_id``
        * ``feedback`` — this cycle's decisions (also mirrored in feedback_log)
        * ``approved`` — the set the user greenlit for Write
        * ``preference_profile`` — the current learned state

    Side effects:
        * Bumps ``items_approved`` on the sources that contributed to
          approved external items.
        * Updates ``preference_profile.reason_histogram`` (rolling counts).
        * Appends new ``pending_rules`` when a stable pattern is detected.
    """
    s = settings()
    company_id = state.get("company_id") or s.company_id
    feedback_this_cycle = state.get("feedback") or []
    approved_this_cycle = state.get("approved") or []

    # 1. Per-source hit-rate: bump items_approved for the sources whose items
    #    made it into approved.
    for item in approved_this_cycle:
        if item.get("kind") == "external" and item.get("source_id"):
            mem.bump_source_counters(item["source_id"], approved=1)

    # 2. Reason histogram over the last LEARNING_WINDOW REJECTS.
    recent = [
        row for row in mem.recent_feedback(company_id, limit=s.learning_window * 3)
        if row.get("decision") == "reject"
    ][: s.learning_window]

    hist = Counter(r["reason_code"] for r in recent if r.get("reason_code"))

    # 3. Detect stable patterns → pending rules.
    prefs = mem.get_preferences(company_id)
    pending: list[str] = list(prefs.get("pending_rules") or [])
    confirmed: list[str] = list(prefs.get("confirmed_rules") or [])
    known = set(pending) | set(confirmed)
    new_rules: list[str] = []
    for reason, count in hist.items():
        if count < s.learning_min_samples:
            continue
        rule = _rule_from_reason(reason)
        if rule and rule not in known:
            new_rules.append(rule)
            pending.append(rule)

    # 4. Under-performing source flags (do NOT auto-unfollow — just surface).
    flagged_sources = _flag_underperformers(company_id)

    # 5. Persist prefs.
    mem.save_preferences(
        company_id,
        reason_histogram=dict(hist),
        pending_rules=pending,
    )

    log.info(
        "learning_node: company=%s approved=%d rejects_window=%d new_rules=%d flagged_sources=%d",
        company_id, len(approved_this_cycle), len(recent), len(new_rules), len(flagged_sources),
    )
    return {
        "preference_profile": mem.get_preferences(company_id),
    }


# ---------- helpers ----------

def _rule_from_reason(reason_code: str) -> str | None:
    """Map a reason code to a human-readable proposed rule.

    None means "don't propose a rule from this reason" — some reasons
    (like ``already-said``) are handled by dedup, not by learning.
    """
    if reason_code == "off-brand":
        return "downrank off-brand items"
    if reason_code == "wrong-product":
        return "downrank items about products we don't sell"
    if reason_code == "not-my-voice":
        return "reject items that miss the extracted voice"
    if reason_code == "too-promotional":
        return "downrank overtly promotional items"
    if reason_code == "not-relevant-now":
        return "downrank items whose seasonality doesn't fit this month"
    if reason_code == "source-not-credible":
        return "downrank items from unreviewed sources"
    if reason_code == "too-shallow":
        return "downrank shallow news-of-the-day items with no analysis"
    # already-said: don't propose — dedup handles it
    return None


def _flag_underperformers(company_id: str, *, min_surfaced: int = 6, threshold: float = 0.2) -> list[dict]:
    """Return sources with hit-rate ≤ threshold after enough samples.

    The UI surfaces these on the Sources tab with an "unfollow?" prompt.
    We deliberately don't unfollow programmatically — same discipline as
    the learning loop (§6.5).
    """
    sources = mem.list_sources(company_id)
    flagged: list[dict] = []
    for s in sources:
        surfaced = int(s.get("items_surfaced") or 0)
        approved = int(s.get("items_approved") or 0)
        if surfaced < min_surfaced:
            continue
        rate = approved / surfaced
        if rate <= threshold:
            flagged.append({**s, "hit_rate": rate})
    return flagged


# ---------- API-side helpers (called by /learning/confirm endpoint) ----------

def confirm_rule(company_id: str, rule: str) -> None:
    """Promote a pending rule to confirmed (called from the API)."""
    prefs = mem.get_preferences(company_id)
    pending = [r for r in (prefs.get("pending_rules") or []) if r != rule]
    confirmed = list(prefs.get("confirmed_rules") or [])
    if rule and rule not in confirmed:
        confirmed.append(rule)
    mem.save_preferences(company_id, pending_rules=pending, confirmed_rules=confirmed)


def delete_rule(company_id: str, rule: str) -> None:
    """Remove a rule from confirmed_rules (called from the API)."""
    prefs = mem.get_preferences(company_id)
    confirmed = [r for r in (prefs.get("confirmed_rules") or []) if r != rule]
    mem.save_preferences(company_id, confirmed_rules=confirmed)


def dismiss_pending_rule(company_id: str, rule: str) -> None:
    """User rejected a proposed rule — remove from pending, don't confirm."""
    prefs = mem.get_preferences(company_id)
    pending = [r for r in (prefs.get("pending_rules") or []) if r != rule]
    mem.save_preferences(company_id, pending_rules=pending)


def underperforming_sources(company_id: str, **kw) -> list[dict]:
    """Convenience wrapper for the Sources tab."""
    return _flag_underperformers(company_id, **kw)
