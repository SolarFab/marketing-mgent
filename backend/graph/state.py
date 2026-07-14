from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ContentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]

    company_id: str
    cycle_id: str
    company_profile: dict           # incl. content_mix
    preference_profile: dict        # learned weights + negative filters + confirmed rules
    sources: list[dict]             # active followed sources, loaded at run start

    candidates: list[dict]          # {id, kind, title, angle, source_id?, url?, pillar?, ts}
    scored: list[dict]              # + score, rationale, route
    approved: list[dict]            # human-approved this cycle (union across channels)
    approved_by_channel: dict       # {newsletter: [item], instagram: [item], linkedin: [item]}
    feedback: list[dict]            # structured approve/reject captured this cycle
    source_proposals: list[dict]    # discovered sources awaiting user approval

    drafts: dict                    # {newsletter, instagram, linkedin}
    publish: dict                   # per-channel: approved?, external_id?, scheduled_for?

    # onboarding-only
    onboarding_url: str
    crawled_pages: list[dict]       # [{url, text}]
    proposed_sources: list[dict]

    # orchestrator scratch
    action: dict                    # {name, args} from router
