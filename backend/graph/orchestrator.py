"""Orchestrator — the chat rail's supervisor.

PRD §4.6: a **router over a fixed action set**, not an open-ended planner.
We keep the surface deliberately small so the behaviour is predictable
and easy to test.

Flow:

1. :func:`handle_message` receives the user's chat text.
2. :func:`_route_message` calls an LLM in structured-output mode to pick
   one of the fixed actions and extract its params.
3. The matched action calls the right DB helper / node.
4. A short response is returned to the chat rail.

The chat rail is stateless from the router's POV — the caller passes a
compact ``context`` blob (recent chat history, current cycle id, etc.)
which we forward to the router prompt as advisory context.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import settings
from ..llm import make_llm
from ..memory import db as mem
from ..prompts import load_prompt
from .nodes import discovery, learning

log = logging.getLogger(__name__)


# --- Router schema ---

ActionName = Literal[
    "search_more",
    "explain_reject",
    "rewrite_newsletter",
    "forget_rule",
    "follow_source",
    "unfollow_source",
    "discover_sources",
    "set_content_mix",
    "re_onboard",
    "chat",
]


class RouteDecision(BaseModel):
    action: ActionName = Field(..., description="One of the fixed actions.")
    note: str = Field("", description="Short one-sentence justification of the choice.")

    # Action-specific params (only the relevant one should be filled)
    topic: str = ""
    item_id: str = ""
    modifier: str = ""
    rule: str = ""
    url: str = ""
    url_or_name: str = ""
    direction: str = ""   # "more_owned" | "more_external"
    delta: float = 0.0
    reply: str = ""       # for action=chat


# --- Public API ---

def handle_message(
    *,
    message: str,
    company_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route the message to an action, execute it, return a response.

    Response shape::

        {"action": "...", "note": "...", "result": {...}, "reply": "..."}
    """
    cid = company_id or settings().company_id
    profile = mem.get_profile(cid) or {}
    ctx = context or {}
    decision = _route_message(message=message, profile=profile, context=ctx)
    result = _dispatch(decision, company_id=cid)
    reply = decision.reply or result.get("reply") or _default_reply(decision, result)
    return {
        "action": decision.action,
        "note": decision.note,
        "result": result,
        "reply": reply,
    }


# --- Router ---

def _route_message(*, message: str, profile: dict, context: dict[str, Any]) -> RouteDecision:
    prompt = load_prompt("orchestrator_router", "v1").format(
        profile=json.dumps(_compact_profile(profile), ensure_ascii=False)[:1500],
        context=json.dumps(context, ensure_ascii=False)[:1500],
        message=message,
    )
    llm = make_llm(temperature=0.1)
    try:
        return llm.with_structured_output(RouteDecision).invoke(prompt)
    except Exception as e:
        log.warning("_route_message: structured output failed (%s)", e)
        return RouteDecision(action="chat", reply="Sorry — I didn't catch that. Can you rephrase?")


# --- Dispatch ---

def _dispatch(d: RouteDecision, *, company_id: str) -> dict[str, Any]:
    """Execute the action. Every branch returns a plain dict."""
    action = d.action

    if action == "chat":
        return {"kind": "chat"}

    if action == "search_more":
        # We don't actually re-run Ideate here — that's a graph invocation.
        # Instead we return an *intent* for the API layer to pick up.
        return {"kind": "intent", "intent": "run_ideate_with_focus", "topic": d.topic}

    if action == "explain_reject":
        row = mem.q1(
            "SELECT reason_code, note FROM feedback_log WHERE item_id=%s AND decision='reject' ORDER BY ts DESC LIMIT 1",
            (d.item_id,),
        )
        if row:
            return {"kind": "rationale", "item_id": d.item_id, "reason_code": row["reason_code"], "note": row.get("note")}
        return {"kind": "rationale", "item_id": d.item_id, "reason_code": None, "note": "No reject on file for that item."}

    if action == "rewrite_newsletter":
        return {"kind": "intent", "intent": "rewrite_newsletter", "modifier": d.modifier}

    if action == "forget_rule":
        learning.delete_rule(company_id, d.rule)
        return {"kind": "rule_removed", "rule": d.rule}

    if action == "follow_source":
        if not d.url:
            return {"kind": "error", "error": "no URL provided"}
        row = mem.add_source(company_id, url=d.url, status="active", origin="user")
        return {"kind": "source_followed", "source": row}

    if action == "unfollow_source":
        if not d.url_or_name:
            return {"kind": "error", "error": "no source provided"}
        rows = mem.q(
            "SELECT source_id FROM sources WHERE company_id=%s AND (url ILIKE %s OR name ILIKE %s)",
            (company_id, f"%{d.url_or_name}%", f"%{d.url_or_name}%"),
        )
        for r in rows:
            mem.delete_source(r["source_id"])
        return {"kind": "source_unfollowed", "count": len(rows)}

    if action == "discover_sources":
        proposals = discovery.discover_and_stage(company_id)
        return {"kind": "discovery_started", "proposals": len(proposals)}

    if action == "set_content_mix":
        profile = mem.get_profile(company_id) or {}
        current = float(profile.get("content_mix", 0.5))
        delta = float(d.delta) or 0.1
        if d.direction == "more_external":
            delta = -abs(delta)
        else:
            delta = abs(delta)
        new_mix = max(0.0, min(1.0, current + delta))
        profile["content_mix"] = new_mix
        mem.upsert_profile(company_id, profile)
        return {"kind": "mix_updated", "old": current, "new": new_mix}

    if action == "re_onboard":
        return {"kind": "intent", "intent": "reonboard", "url": d.url}

    return {"kind": "unknown"}


# --- Fallback reply text ---

def _default_reply(d: RouteDecision, result: dict[str, Any]) -> str:
    kind = result.get("kind")
    if kind == "source_followed":
        return f"Added {result['source']['url']} to your sources."
    if kind == "source_unfollowed":
        return f"Removed {result['count']} source(s)."
    if kind == "rule_removed":
        return f"Forgot the rule: {d.rule!r}."
    if kind == "mix_updated":
        return f"Content mix moved from {result['old']:.2f} → {result['new']:.2f}."
    if kind == "discovery_started":
        return f"Proposed {result['proposals']} new source(s) — check the Sources tab."
    if kind == "rationale":
        if result.get("reason_code"):
            return f"Rejected as {result['reason_code']!r}. Note: {result.get('note') or '—'}"
        return result.get("note") or "No history for that item."
    if kind == "intent":
        intent = result.get("intent")
        if intent == "run_ideate_with_focus":
            return f"Queued a new ideation focused on {result.get('topic')!r}."
        if intent == "rewrite_newsletter":
            return f"Queued a newsletter rewrite: {result.get('modifier')!r}."
        if intent == "reonboard":
            return f"Ready to re-onboard from {result.get('url')!r} when you confirm."
    if kind == "error":
        return f"Couldn't do that — {result.get('error')}."
    return "Ok."


def _compact_profile(profile: dict) -> dict:
    return {
        "identity": profile.get("identity", {}),
        "market": profile.get("market", {}),
        "voice": profile.get("voice", {}),
        "content_pillars": profile.get("content_pillars", {}),
    }
