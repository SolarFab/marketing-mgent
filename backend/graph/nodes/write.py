"""Write node — one approved set → newsletter + Instagram + LinkedIn.

PRD §4.3 + §8:

* One Write call produces all three channels so the same thesis carries.
* Newsletter offers 3 layout options (``digest``, ``editorial``,
  ``single-story``) — the state may carry a preferred layout; if not, we
  pick heuristically from the size of the approved set.
* Everything is generated **in the extracted voice**. The prompts pass
  the compact profile so the LLM sees ``voice.do``/``voice.dont``.

Persistence: drafts go into the ``drafts`` table keyed by ``cycle_id``.
The API layer reads them back for the Newsletter / Social tabs.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ...llm import make_llm
from ...memory import db as mem
from ...prompts import load_prompt
from ..state import ContentState

log = logging.getLogger(__name__)


# --- Schemas ---

class NewsletterSection(BaseModel):
    heading: str = ""
    body_markdown: str = ""
    link: str = ""


class NewsletterDraft(BaseModel):
    subject: str = ""
    preheader: str = ""
    intro: str = ""
    sections: list[NewsletterSection] = Field(default_factory=list)
    signoff: str = ""
    layout: str = "digest"


class SocialDrafts(BaseModel):
    instagram: str = ""
    instagram_hashtags: list[str] = Field(default_factory=list)
    linkedin: str = ""


# --- Node ---

def write_node(state: ContentState) -> dict:
    """Generate newsletter + Instagram + LinkedIn drafts from ``approved``.

    Reads:
        * ``approved`` — the list the HITL step greenlit
        * ``company_profile`` — for voice, pillars, ICP
        * ``cycle_id`` — draft persistence key
    """
    approved = state.get("approved") or []
    if not approved:
        empty = {"newsletter": None, "instagram": None, "linkedin": None}
        return {"drafts": empty}

    profile = state.get("company_profile") or {}
    cycle_id = state.get("cycle_id") or "adhoc"
    company_id = state.get("company_id") or "demo"

    layout = _pick_layout(state, approved)

    newsletter = _write_newsletter(approved=approved, profile=profile, layout=layout)
    social = _write_social(approved=approved, profile=profile)

    drafts = {
        "newsletter": newsletter,
        "instagram": {
            "caption": social.instagram,
            "hashtags": social.instagram_hashtags,
        },
        "linkedin": {"post": social.linkedin},
    }

    try:
        mem.save_drafts(cycle_id, company_id, drafts, layout=layout)
    except Exception as e:
        log.warning("write_node: save_drafts failed: %s", e)

    log.info(
        "write_node: cycle=%s layout=%s newsletter_sections=%d",
        cycle_id, layout, len(newsletter.get("sections") or []),
    )
    return {"drafts": drafts}


# --- Helpers ---

def _pick_layout(state: ContentState, approved: list[dict]) -> str:
    """Use the explicit layout if provided, else heuristic on set size."""
    explicit = (state.get("drafts") or {}).get("layout") if isinstance(state.get("drafts"), dict) else None
    if explicit in {"digest", "editorial", "single-story"}:
        return explicit
    n = len(approved)
    if n >= 4:
        return "digest"
    if n <= 1:
        return "single-story"
    return "editorial"


def _write_newsletter(*, approved: list[dict], profile: dict, layout: str) -> dict:
    voice = profile.get("voice") or {}
    prompt = load_prompt("write_newsletter", "v1").format(
        layout=layout,
        tone=", ".join(voice.get("tone") or []),
        profile=json.dumps(_compact_profile(profile), ensure_ascii=False)[:2000],
        items=json.dumps(_compact_items(approved), ensure_ascii=False)[:4000],
    )
    llm = make_llm(temperature=0.5)
    try:
        draft: NewsletterDraft = llm.with_structured_output(NewsletterDraft).invoke(prompt)
    except Exception as e:
        log.warning("_write_newsletter: structured output failed (%s)", e)
        draft = NewsletterDraft(layout=layout)
    d = draft.model_dump()
    d["layout"] = layout  # override in case model set it
    return d


def _write_social(*, approved: list[dict], profile: dict) -> SocialDrafts:
    voice = profile.get("voice") or {}
    prompt = load_prompt("write_social", "v1").format(
        tone=", ".join(voice.get("tone") or []),
        profile=json.dumps(_compact_profile(profile), ensure_ascii=False)[:2000],
        items=json.dumps(_compact_items(approved), ensure_ascii=False)[:3000],
    )
    llm = make_llm(temperature=0.6)
    try:
        return llm.with_structured_output(SocialDrafts).invoke(prompt)
    except Exception as e:
        log.warning("_write_social: structured output failed (%s)", e)
        return SocialDrafts()


def _compact_profile(profile: dict) -> dict:
    return {
        "identity": profile.get("identity", {}),
        "market": profile.get("market", {}),
        "voice": profile.get("voice", {}),
        "content_pillars": profile.get("content_pillars", {}),
    }


def _compact_items(items: list[dict]) -> list[dict]:
    return [
        {
            "title": i.get("title"),
            "angle": i.get("angle"),
            "kind": i.get("kind"),
            "pillar": i.get("pillar"),
            "url": i.get("url"),
        }
        for i in items
    ]
