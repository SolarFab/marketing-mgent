"""Publish node — Buffer for social + Resend for newsletter.

Reads ``publish`` from state, a dict like::

    {
      "newsletter": {"approved": true},
      "instagram":  {"approved": true},
      "linkedin":   {"approved": false},
    }

Only channels with ``approved=true`` get pushed. Everything else is
skipped. Per-channel outcomes are written back to ``state["publish"]``
and recorded in the ``publish_log`` table for the analytics dashboard.

Buffer drafts are a **second HITL gate**: even a channel that this node
successfully calls will not go live until the user hits "publish" inside
Buffer itself. That's PRD §7 by design.
"""
from __future__ import annotations

import logging
from typing import Any

from ...memory import db as mem
from ...tools.buffer import create_draft_post
from ...tools.email import send_newsletter
from ..state import ContentState

log = logging.getLogger(__name__)


def publish_node(state: ContentState) -> dict:
    """Push each approved channel; leave un-approved ones alone."""
    drafts: dict = state.get("drafts") or {}
    publish_plan: dict = state.get("publish") or {}
    company_id = state.get("company_id") or "demo"
    cycle_id = state.get("cycle_id")

    outcomes: dict[str, dict[str, Any]] = {
        "newsletter": {"skipped": True},
        "instagram": {"skipped": True},
        "linkedin": {"skipped": True},
    }

    if publish_plan.get("newsletter", {}).get("approved") and drafts.get("newsletter"):
        # Pull brand + profile so the sender's template renders in the
        # business's own palette. Falls back to defaults if profile is
        # missing (e.g. during test paths).
        profile = state.get("company_profile") or mem.get_profile(company_id) or {}
        brand = profile.get("brand") or {}
        result = send_newsletter(draft=drafts["newsletter"], brand=brand, profile=profile)
        outcomes["newsletter"] = result
        _log(company_id, cycle_id, "newsletter", result)

    if publish_plan.get("instagram", {}).get("approved") and drafts.get("instagram"):
        text = _compose_instagram(drafts["instagram"])
        result = create_draft_post(channel="instagram", text=text)
        outcomes["instagram"] = result
        _log(company_id, cycle_id, "instagram", result)

    if publish_plan.get("linkedin", {}).get("approved") and drafts.get("linkedin"):
        text = drafts["linkedin"].get("post") if isinstance(drafts["linkedin"], dict) else str(drafts["linkedin"])
        if text:
            result = create_draft_post(channel="linkedin", text=text)
            outcomes["linkedin"] = result
            _log(company_id, cycle_id, "linkedin", result)

    if cycle_id:
        mem.finish_cycle(cycle_id, status="done")

    log.info("publish_node: outcomes=%s", {k: v.get("status") for k, v in outcomes.items()})
    return {"publish": outcomes}


def _compose_instagram(ig_draft: dict) -> str:
    caption = ig_draft.get("caption") or ""
    hashtags = ig_draft.get("hashtags") or []
    tag_str = " ".join(t if t.startswith("#") else f"#{t}" for t in hashtags)
    return f"{caption}\n\n{tag_str}".strip() if tag_str else caption


def _log(company_id: str, cycle_id: str | None, channel: str, result: dict[str, Any]) -> None:
    try:
        mem.log_publish(
            company_id,
            channel,
            result.get("status", "unknown"),
            cycle_id=cycle_id,
            external_id=result.get("external_id") or "",
        )
    except Exception as e:
        log.warning("publish_log write failed: %s", e)
