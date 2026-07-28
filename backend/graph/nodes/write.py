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
    category: str = Field(
        "",
        description="Short editorial category tag in ALL CAPS — 1 to 4 words, e.g. 'AI / CONSUMER HARDWARE', 'E-COMMERCE & SUPPLY CHAIN', 'ELECTRIC VEHICLES & ENERGY'. Rendered as a dark pill above the headline.",
    )
    heading: str = ""
    body_markdown: str = ""
    highlight_term: str = Field(
        "",
        description="A single word or short phrase (2-4 words max) from body_markdown that should be highlighted in brand accent color when rendered. Pick the term that carries the story's tension or key claim — e.g. 'Chinese', '$14 billion', 'Five-Minute Charge'. Leave empty if no natural highlight.",
    )
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
    """Generate newsletter + Instagram + LinkedIn drafts, per-channel.

    Reads:
        * ``approved_by_channel`` — {newsletter: [item], instagram: [item], linkedin: [item]}
          Each channel writes from its own subset. A channel with an empty
          list gets a ``None`` draft rather than generating from other
          channels' items.
        * ``approved`` — fallback for older callers; treated as newsletter-only.
        * ``company_profile`` — for voice, pillars, ICP
        * ``cycle_id`` — draft persistence key
    """
    by_channel: dict[str, list[dict]] = state.get("approved_by_channel") or {}
    if not by_channel:
        # Back-compat: dump the flat approved list into newsletter only.
        flat = state.get("approved") or []
        by_channel = {"newsletter": list(flat)} if flat else {}

    newsletter_items = by_channel.get("newsletter") or []
    instagram_items = by_channel.get("instagram") or []
    linkedin_items = by_channel.get("linkedin") or []

    if not (newsletter_items or instagram_items or linkedin_items):
        empty = {"newsletter": None, "instagram": None, "linkedin": None}
        return {"drafts": empty}

    profile = state.get("company_profile") or {}
    cycle_id = state.get("cycle_id") or "adhoc"
    company_id = state.get("company_id") or "demo"

    # Layout heuristic still keys off the newsletter set.
    layout = _pick_layout(state, newsletter_items) if newsletter_items else "digest"

    newsletter = (
        _write_newsletter(approved=newsletter_items, profile=profile, layout=layout)
        if newsletter_items
        else None
    )

    # Social: one LLM call handles IG and LinkedIn together. If the two
    # channels have DIFFERENT sets, call twice — once with the IG set for
    # IG, once with the LinkedIn set for LinkedIn — and merge.
    ig_draft: dict | None = None
    li_draft: dict | None = None
    if instagram_items and linkedin_items and _same_ids(instagram_items, linkedin_items):
        # Same set for both — one LLM call
        social = _write_social(approved=instagram_items, profile=profile)
        ig_draft = {"caption": social.instagram, "hashtags": social.instagram_hashtags}
        li_draft = {"post": social.linkedin}
    else:
        if instagram_items:
            social_ig = _write_social(approved=instagram_items, profile=profile)
            ig_draft = {"caption": social_ig.instagram, "hashtags": social_ig.instagram_hashtags}
        if linkedin_items:
            social_li = _write_social(approved=linkedin_items, profile=profile)
            li_draft = {"post": social_li.linkedin}

    drafts = {
        "newsletter": newsletter,
        "instagram": ig_draft,
        "linkedin": li_draft,
    }

    try:
        mem.save_drafts(cycle_id, company_id, drafts, layout=layout)
    except Exception as e:
        log.warning("write_node: save_drafts failed: %s", e)

    log.info(
        "write_node: cycle=%s layout=%s | newsletter=%d IG=%d LinkedIn=%d",
        cycle_id, layout,
        len(newsletter_items), len(instagram_items), len(linkedin_items),
    )
    return {"drafts": drafts}


def _same_ids(a: list[dict], b: list[dict]) -> bool:
    return {i["id"] for i in a} == {i["id"] for i in b}


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
        draft: NewsletterDraft | None = llm.with_structured_output(NewsletterDraft).invoke(prompt)
    except Exception as e:
        log.warning("_write_newsletter: structured output failed (%s)", e)
        draft = None
    if draft is None:  # model may emit no tool call → invoke() returns None
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
        drafts: SocialDrafts | None = llm.with_structured_output(SocialDrafts).invoke(prompt)
    except Exception as e:
        log.warning("_write_social: structured output failed (%s)", e)
        drafts = None
    return drafts if drafts is not None else SocialDrafts()


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
