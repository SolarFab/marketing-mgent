"""FastAPI application — HTTP surface for the Signal Content Agent.

Endpoints (mirror PRD §9):

Profile / onboarding
    POST /onboard {url}              — start onboarding, returns crawl+extract+seed
    POST /onboard/confirm            — persist the (possibly edited) profile + sources
    GET  /profile                    — current company profile
    PUT  /profile                    — edit profile (incl. content_mix)

Sources
    GET    /sources                  — list active + proposed
    POST   /sources                  — user-adds a source by URL
    PATCH  /sources/{id}             — pause/activate
    DELETE /sources/{id}             — unfollow
    POST   /sources/discover         — trigger discovery
    POST   /sources/{id}/accept      — accept a proposed source

Content cycle
    POST /cycle/run                  — start a new cycle
    GET  /queue                      — scored candidates awaiting HITL
    POST /feedback                   — approve/reject with reason
    POST /cycle/finish_review        — user finished reviewing; kick learning + write
    POST /write                      — regenerate drafts (optional layout)
    GET  /drafts                     — latest drafts for the company
    POST /publish                    — publish per-channel

Learning
    GET    /learning                 — pending + confirmed rules
    POST   /learning/confirm         — promote a pending rule
    POST   /learning/dismiss         — dismiss a pending rule
    DELETE /learning/{rule}          — remove a confirmed rule

Analytics
    GET /analytics/approval_rate     — approval rate per cycle
    GET /analytics/source_hit_rates  — per-source hit rate
    GET /analytics/reason_histogram  — reject reasons over rolling window
    GET /analytics/underperformers   — flagged sources

Orchestrator
    POST /chat {message}             — the chat rail

Every endpoint returns JSON. FastAPI auto-generates OpenAPI docs at
``/docs`` — descriptions here become the visible spec.
"""
from __future__ import annotations

import logging
import re

from typing import Any

from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .graph.build import (
    build_content_graph,
    build_onboarding_graph,
    cycle_thread,
    onboarding_thread,
)
from .graph.nodes import discovery, learning
from .graph import orchestrator as orch
from .llm import make_llm
from .memory import db as mem
from .prompts import load_prompt
from .tools import carousel as carousel_tool
from .tools import upload_materialize as upload_tool
from .tools.sources import normalize_source_url

app = FastAPI(
    title="Signal Content Agent",
    description="A self-marketing agent for content-constrained businesses. PRD v2.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve persisted brand reference screenshots so the frontend can preview them
# and the Phase 2 image generator can pass their URLs to Nano Banana 2 as
# style-reference inputs.
_BRAND_REFS_DIR = Path(__file__).resolve().parent.parent / "data" / "brand-refs"
_BRAND_REFS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/brand-refs", StaticFiles(directory=str(_BRAND_REFS_DIR)), name="brand-refs")

# Serve generated carousel slides so the frontend can preview them and
# the Buffer publisher can (eventually) hand the URL to Buffer's API.
_CAROUSELS_DIR = Path(__file__).resolve().parent.parent / "data" / "carousels"
_CAROUSELS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/carousels", StaticFiles(directory=str(_CAROUSELS_DIR)), name="carousels")

# User-uploaded photos land under data/user-uploads/{company_id}/{upload_id}.{ext}
# and are served here so the frontend can preview them and the carousel step
# can reference them by URL.
_USER_UPLOADS_DIR = Path(__file__).resolve().parent.parent / "data" / "user-uploads"
_USER_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/user-uploads", StaticFiles(directory=str(_USER_UPLOADS_DIR)), name="user-uploads")


# ---------- helpers ----------

log = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_id(value: str, label: str = "id") -> str:
    """Reject ids that could escape their storage directory (path traversal)."""
    if not _SAFE_ID_RE.match(value) or ".." in value:
        raise HTTPException(status_code=400, detail=f"invalid {label}: {value!r}")
    return value


def _company_id(body_id: str | None = None) -> str:
    """Single-tenant: fall back to env default when not supplied."""
    return body_id or settings().company_id


# ---------- request/response models ----------

class OnboardRequest(BaseModel):
    url: str = Field(..., description="Homepage URL to onboard from.")
    company_id: str | None = Field(None, description="Override the default company id.")


class OnboardConfirmRequest(BaseModel):
    company_id: str | None = None
    company_profile: dict = Field(..., description="The (possibly edited) profile to persist.")
    proposed_sources: list[dict] = Field(default_factory=list, description="Sources to seed. Set 'accepted': false on any to skip.")


class OnboardReviseRequest(BaseModel):
    current_profile: dict = Field(..., description="The profile the LLM already extracted.")
    message: str = Field(..., description="The user's chat message — a natural-language edit or question.")


class ProfileUpdate(BaseModel):
    company_id: str | None = None
    profile: dict


class SourceAdd(BaseModel):
    company_id: str | None = None
    url: str
    kind: str = "web"
    name: str | None = None


class SourcePatch(BaseModel):
    status: str  # 'active' | 'paused'


class FeedbackIn(BaseModel):
    company_id: str | None = None
    item_id: str
    decision: str  # 'approve' | 'reject'
    reason_code: str | None = None
    note: str | None = None
    source_id: str | None = None
    cycle_id: str | None = None


class WriteRequest(BaseModel):
    company_id: str | None = None
    cycle_id: str
    layout: str | None = None  # 'digest' | 'editorial' | 'single-story'


class PublishRequest(BaseModel):
    company_id: str | None = None
    cycle_id: str
    channel: str  # 'newsletter' | 'instagram' | 'linkedin'


class ChatIn(BaseModel):
    company_id: str | None = None
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


# ---------- root ----------

@app.get("/", summary="Service health")
def root() -> dict:
    return {
        "name": "signal-content-agent",
        "version": "0.1.0",
        "company_id_default": settings().company_id,
        "publish_mode": settings().publish_mode,
    }


# ---------- onboarding ----------

@app.post("/onboard", summary="Start onboarding from a URL")
def onboard(req: OnboardRequest) -> dict:
    """Crawl the site, extract a Company Profile draft, seed source proposals.

    The graph interrupts before ``confirm`` so the client can render the
    draft for the user to edit. Call :func:`onboard_confirm` to persist.
    """
    cid = _company_id(req.company_id)
    graph = build_onboarding_graph()
    cfg = onboarding_thread(cid)
    initial = {"company_id": cid, "onboarding_url": req.url}
    # Runs crawl → extract → seed_sources, then interrupts before confirm.
    graph.invoke(initial, cfg)
    snapshot = graph.get_state(cfg)
    values = snapshot.values or {}
    return {
        "company_id": cid,
        "company_profile": values.get("company_profile"),
        "proposed_sources": values.get("proposed_sources") or [],
        "crawled_pages": [
            {"url": p["url"], "title": p["title"]} for p in (values.get("crawled_pages") or [])
        ],
        "thread_id": cfg["configurable"]["thread_id"],
    }


@app.post("/onboard/revise", summary="Chat-driven profile revision (before confirm)")
def revise_profile(req: OnboardReviseRequest) -> dict:
    """LLM revises the profile based on the user's natural-language edit.

    Returns:
        * ``profile``  — the possibly-updated profile.
        * ``reply``    — the agent's chat reply (1-2 sentences).
        * ``done``     — true when the user said "save / looks good / etc.".
    """
    import json as _json

    from pydantic import BaseModel as _BaseModel, Field as _Field

    class ReviseResult(_BaseModel):
        profile: dict = _Field(default_factory=dict)
        reply: str = _Field(default="")
        done: bool = _Field(default=False)

    prompt = load_prompt("onboarding_revise", "v1").format(
        profile=_json.dumps(req.current_profile, ensure_ascii=False, default=str)[:5000],
        message=req.message,
    )
    llm = make_llm(temperature=0.2)
    try:
        result: ReviseResult = llm.with_structured_output(ReviseResult).invoke(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"revise failed: {e}")

    # If the LLM returned an empty profile (e.g. ambiguous message), preserve the current one.
    profile_out = result.profile or req.current_profile
    return {"profile": profile_out, "reply": result.reply, "done": result.done}


@app.post("/onboard/confirm", summary="Confirm and persist onboarding")
def onboard_confirm(req: OnboardConfirmRequest) -> dict:
    """Resume the onboarding graph with the user's confirmed data."""
    cid = _company_id(req.company_id)
    graph = build_onboarding_graph()
    cfg = onboarding_thread(cid)

    graph.update_state(
        cfg,
        {
            "company_id": cid,
            "company_profile": req.company_profile,
            "proposed_sources": req.proposed_sources,
        },
        as_node="confirm",
    )
    graph.invoke(None, cfg)  # resume
    return {"status": "ok", "company_id": cid}


# ---------- profile ----------

@app.get("/profile", summary="Get the current company profile")
def get_profile(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    profile = mem.get_profile(cid)
    if not profile:
        raise HTTPException(status_code=404, detail=f"no profile for company_id={cid}")
    return profile


@app.put("/profile", summary="Update the company profile")
def update_profile(req: ProfileUpdate) -> dict:
    cid = _company_id(req.company_id)
    mem.upsert_profile(cid, req.profile)
    return {"status": "ok", "profile": mem.get_profile(cid)}


# ---------- sources ----------

@app.get("/sources", summary="List sources")
def list_sources(company_id: str | None = None, status: str | None = None) -> dict:
    cid = _company_id(company_id)
    statuses = [status] if status else None
    return {"sources": mem.list_sources(cid, statuses=statuses)}


@app.post("/sources", summary="Add a source by URL")
def add_source(req: SourceAdd) -> dict:
    """Add a followed source. Any URL is normalized to its outlet:

    - Article URL → root domain
    - Root domain → auto-detect RSS, use feed URL if found
    - Feed URL → used directly

    Client-supplied ``kind`` is a hint; RSS detection can override it.
    """
    cid = _company_id(req.company_id)
    normalized = normalize_source_url(req.url, probe_feed=True)
    kind = normalized.kind if normalized.is_outlet else (req.kind or "web")
    row = mem.add_source(
        cid,
        url=normalized.url,
        kind=kind,
        name=req.name or (normalized.host or None),
        status="active",
        origin="user",
    )
    return {"source": row, "normalized": {"root_url": normalized.root_url, "detected_kind": kind}}


@app.patch("/sources/{source_id}", summary="Pause or activate a source")
def patch_source(source_id: str, req: SourcePatch) -> dict:
    if req.status not in {"active", "paused"}:
        raise HTTPException(status_code=400, detail="status must be 'active' or 'paused'")
    mem.update_source(source_id, status=req.status)
    return {"status": "ok"}


@app.delete("/sources/{source_id}", summary="Unfollow a source")
def delete_source(source_id: str) -> dict:
    mem.delete_source(source_id)
    return {"status": "ok"}


@app.post("/sources/discover", summary="Run source discovery")
def run_discovery(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    inserted = discovery.discover_and_stage(cid)
    return {"proposed": len(inserted), "sources": inserted}


@app.post("/sources/{source_id}/accept", summary="Promote a proposed source to active")
def accept_source(source_id: str) -> dict:
    discovery.accept_proposed(source_id)
    return {"status": "ok"}


# ---------- content cycle ----------

@app.post("/cycle/run", summary="Start a new content cycle")
def run_cycle(company_id: str | None = None) -> dict:
    """Runs load_state → ideate → evaluate, then interrupts before review.

    Returns the ``cycle_id`` + the scored queue. The frontend posts
    feedback for each item, then hits ``/cycle/finish_review`` to
    trigger Learning + Write.
    """
    cid = _company_id(company_id)
    graph = build_content_graph()

    # Start a fresh cycle_id up front so we control the thread key.
    cycle_id = mem.start_cycle(cid)
    cfg = cycle_thread(cycle_id)

    graph.invoke({"company_id": cid, "cycle_id": cycle_id}, cfg)
    snapshot = graph.get_state(cfg)
    values = snapshot.values or {}
    return {
        "cycle_id": cycle_id,
        "candidates": values.get("scored") or [],
    }


@app.get("/queue", summary="Get the current scored queue for a cycle")
def get_queue(cycle_id: str) -> dict:
    cfg = cycle_thread(cycle_id)
    graph = build_content_graph()
    snapshot = graph.get_state(cfg)
    values = snapshot.values or {}
    return {"cycle_id": cycle_id, "candidates": values.get("scored") or []}


@app.post("/feedback", summary="Record approve/reject on one item")
def submit_feedback(req: FeedbackIn) -> dict:
    cid = _company_id(req.company_id)
    mem.log_feedback(
        cid,
        item_id=req.item_id,
        decision=req.decision,
        source_id=req.source_id,
        reason_code=req.reason_code,
        note=req.note,
        cycle_id=req.cycle_id,
    )
    return {"status": "ok"}


class FinishReviewRequest(BaseModel):
    """Per-channel routing: each channel gets its own list of item_ids.

    The union of the three lists is what the user approved overall; the
    per-channel breakdown drives which items each Write branch sees. A
    story tagged for both newsletter and LinkedIn appears in both.
    """
    cycle_id: str
    company_id: str | None = None
    # Backwards-compat: if the client sends approved_ids, treat as newsletter-only.
    approved_ids: list[str] = Field(default_factory=list)
    approved_by_channel: dict[str, list[str]] = Field(default_factory=dict)


@app.post("/cycle/finish_review", summary="Resume the cycle after review")
def finish_review(req: FinishReviewRequest) -> dict:
    """After the user finishes review, resume the graph so Learning +
    Write can run.

    Payload shape: ``approved_by_channel = {"newsletter": [ids], "instagram": [ids], "linkedin": [ids]}``.
    Each channel's Write draft is generated from only its own subset.
    Falls back to ``approved_ids`` (flat) for older clients — those get
    treated as newsletter-only.
    """
    cid = _company_id(req.company_id)
    graph = build_content_graph()
    cfg = cycle_thread(req.cycle_id)

    snapshot = graph.get_state(cfg)
    scored = (snapshot.values or {}).get("scored") or []
    by_id = {c["id"]: c for c in scored}

    per_channel: dict[str, list[dict]] = {}
    if req.approved_by_channel:
        for channel, ids in req.approved_by_channel.items():
            per_channel[channel] = [by_id[i] for i in ids if i in by_id]
    elif req.approved_ids:
        per_channel = {"newsletter": [by_id[i] for i in req.approved_ids if i in by_id]}

    # Union across channels — used for source-hit-rate + history stats
    approved_union: list[dict] = []
    seen: set[str] = set()
    for items in per_channel.values():
        for c in items:
            if c["id"] not in seen:
                seen.add(c["id"])
                approved_union.append(c)

    # Fresh feedback for the learning window
    feedback = mem.recent_feedback(cid, limit=settings().learning_window)

    graph.update_state(
        cfg,
        {
            "approved": approved_union,
            "approved_by_channel": per_channel,
            "feedback": feedback,
        },
        as_node="review",
    )
    graph.invoke(None, cfg)  # continue until publish interrupt
    values = graph.get_state(cfg).values or {}
    return {
        "cycle_id": req.cycle_id,
        "drafts": values.get("drafts"),
        "channel_counts": {ch: len(items) for ch, items in per_channel.items()},
    }


@app.get("/drafts", summary="Latest generated drafts for a company")
def get_drafts(company_id: str | None = None, cycle_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    if cycle_id:
        return {"drafts": mem.get_drafts(cycle_id)}
    return {"drafts": mem.latest_drafts(cid)}


@app.post("/write", summary="Regenerate drafts with an optional layout")
def rewrite(req: WriteRequest) -> dict:
    """Regenerate drafts for the given cycle (used by 'rewrite newsletter' orchestrator action)."""
    from .graph.nodes.write import write_node

    cid = _company_id(req.company_id)
    cfg = cycle_thread(req.cycle_id)
    graph = build_content_graph()

    snapshot = graph.get_state(cfg)
    values = snapshot.values or {}
    approved = values.get("approved") or []
    profile = values.get("company_profile") or mem.get_profile(cid)

    state = {
        "cycle_id": req.cycle_id,
        "company_id": cid,
        "company_profile": profile,
        "approved": approved,
        "drafts": {"layout": req.layout} if req.layout else {},
    }
    result = write_node(state)
    return {"drafts": result["drafts"]}


@app.post("/publish", summary="Publish one channel from a cycle's drafts")
def publish(req: PublishRequest) -> dict:
    from .graph.nodes.publish import publish_node

    cid = _company_id(req.company_id)
    drafts_row = mem.get_drafts(req.cycle_id)
    if not drafts_row:
        raise HTTPException(status_code=404, detail=f"no drafts for cycle_id={req.cycle_id}")

    state = {
        "company_id": cid,
        "cycle_id": req.cycle_id,
        "company_profile": mem.get_profile(cid) or {},
        "drafts": {
            "newsletter": drafts_row.get("newsletter"),
            "instagram": drafts_row.get("instagram"),
            "linkedin": drafts_row.get("linkedin"),
        },
        "publish": {req.channel: {"approved": True}},
    }
    result = publish_node(state)
    channel_result = result.get("publish", {}).get(req.channel, {})
    return {"channel": req.channel, "result": channel_result}


# ---------- learning ----------

@app.get("/learning", summary="Get pending + confirmed rules and reason histogram")
def get_learning(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    prefs = mem.get_preferences(cid)
    return {
        "confirmed_rules": prefs.get("confirmed_rules") or [],
        "pending_rules": prefs.get("pending_rules") or [],
        "reason_histogram": prefs.get("reason_histogram") or {},
    }


class RuleRequest(BaseModel):
    rule: str
    company_id: str | None = None


@app.post("/learning/confirm", summary="Confirm a pending rule")
def confirm_learning(req: RuleRequest) -> dict:
    cid = _company_id(req.company_id)
    learning.confirm_rule(cid, req.rule)
    return {"status": "ok"}


@app.post("/learning/dismiss", summary="Dismiss a pending rule")
def dismiss_learning(req: RuleRequest) -> dict:
    cid = _company_id(req.company_id)
    learning.dismiss_pending_rule(cid, req.rule)
    return {"status": "ok"}


@app.delete("/learning/{rule}", summary="Remove a confirmed rule")
def delete_learning(rule: str, company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    learning.delete_rule(cid, rule)
    return {"status": "ok"}


# ---------- analytics ----------

@app.get("/analytics/approval_rate", summary="Approval rate per cycle")
def approval_rate(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    rows = mem.approval_rate_by_cycle(cid)
    return {
        "cycles": [
            {
                "cycle_id": r["cycle_id"],
                "total": int(r["total"]),
                "approved": int(r["approved"] or 0),
                "rate": (int(r["approved"] or 0) / int(r["total"])) if r["total"] else 0.0,
                "started_at": (r["started_at"].isoformat() if r["started_at"] else None),
            }
            for r in rows
        ]
    }


@app.get("/analytics/source_hit_rates", summary="Per-source hit rate")
def source_hit_rates(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    sources = mem.list_sources(cid)
    result = []
    for s in sources:
        surfaced = int(s.get("items_surfaced") or 0)
        approved = int(s.get("items_approved") or 0)
        result.append({
            "source_id": s["source_id"],
            "name": s.get("name"),
            "url": s.get("url"),
            "surfaced": surfaced,
            "approved": approved,
            "rate": approved / surfaced if surfaced else None,
        })
    return {"sources": result}


@app.get("/analytics/reason_histogram", summary="Reject reasons over the learning window")
def reason_histogram(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    prefs = mem.get_preferences(cid)
    return {"histogram": prefs.get("reason_histogram") or {}}


@app.get("/analytics/underperformers", summary="Sources flagged for review")
def underperformers(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    return {"sources": learning.underperforming_sources(cid)}


# ---------- user uploads (My Content) ----------


@app.post("/uploads", summary="Upload a photo + story to draft channel content from")
async def upload_content(
    file: UploadFile = File(...),
    story: str = Form(...),
    title: str | None = Form(None),
    pillar: str | None = Form(None),
    company_id: str | None = Form(None),
) -> dict:
    """Persist the photo and metadata. Returns the row; frontend then calls
    ``/uploads/{id}/materialize`` to turn it into channel drafts.
    """
    cid = _safe_id(_company_id(company_id), "company_id")
    # Derive extension from the upload's content type or filename
    ext = "png"
    filename = (file.filename or "").lower()
    if filename.endswith((".jpg", ".jpeg")):
        ext = "jpg"
    elif filename.endswith(".webp"):
        ext = "webp"
    upload_dir = _USER_UPLOADS_DIR / cid
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Persist first so we get a stable id, then rename the file
    row = mem.add_upload(
        cid,
        title=title,
        story=story,
        pillar=pillar,
        photo_path="",  # placeholder; updated after file save
        photo_url="",
    )
    uid = row["upload_id"]
    saved_path = upload_dir / f"{uid}.{ext}"
    body = await file.read()
    saved_path.write_bytes(body)
    photo_url = f"/user-uploads/{cid}/{uid}.{ext}"
    mem.x(
        "UPDATE user_uploads SET photo_path=%s, photo_url=%s WHERE upload_id=%s",
        (str(saved_path), photo_url, uid),
    )
    return mem.get_upload(uid) or {}


@app.get("/uploads", summary="List user-uploaded content for the company")
def list_uploads(company_id: str | None = None) -> dict:
    cid = _company_id(company_id)
    return {"uploads": mem.list_uploads(cid)}


@app.delete("/uploads/{upload_id}", summary="Delete an upload + its file")
def delete_upload(upload_id: str) -> dict:
    row = mem.get_upload(upload_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"upload {upload_id} not found")
    photo_path = row.get("photo_path")
    if photo_path:
        try:
            Path(photo_path).unlink(missing_ok=True)
        except Exception:
            pass
    mem.delete_upload(upload_id)
    return {"status": "ok"}


class MaterializeRequest(BaseModel):
    company_id: str | None = None
    build_carousel_images: bool = Field(
        False,
        description="If true, actually generates the 4 AI-produced carousel slides via Nano Banana 2. Costs image credits. Slide 0 (user's photo) is always built.",
    )


@app.post("/uploads/{upload_id}/materialize", summary="Turn upload into newsletter/carousel/LinkedIn/IG drafts")
def materialize_upload_endpoint(upload_id: str, req: MaterializeRequest) -> dict:
    """One LLM call produces all four channel drafts. The carousel's hero
    slide is the user's own photo (with an overlay); the other 4 slides can
    optionally be rendered via Nano Banana 2 when ``build_carousel_images``
    is true.
    """
    row = mem.get_upload(upload_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"upload {upload_id} not found")
    cid = _company_id(req.company_id or row.get("company_id"))
    profile = mem.get_profile(cid) or {}
    if not profile:
        raise HTTPException(status_code=404, detail=f"no profile for company_id={cid}")

    try:
        materialized = upload_tool.materialize_from_upload(upload=row, profile=profile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"materialize failed: {e}")

    payload: dict[str, Any] = {
        "newsletter_section": materialized.newsletter_section.model_dump(),
        "linkedin_post": materialized.linkedin_post,
        "instagram_caption": materialized.instagram_caption,
        "instagram_hashtags": materialized.instagram_hashtags,
        "carousel_slides": [s.model_dump() for s in materialized.carousel_slides],
        "hero_slide_url": None,
        "generated_slides": [],
    }

    # Slide 0 — the user's photo, always built (cheap, deterministic)
    cycle_id = "upload"  # namespace for upload-based carousels
    photo_path = Path(row["photo_path"])
    if photo_path.exists():
        try:
            upload_tool.paste_user_photo_as_hero(
                upload_photo_path=photo_path,
                cycle_id=cycle_id,
                item_id=upload_id,
                upload_title=row.get("title") or materialized.newsletter_section.heading,
                brand=profile.get("brand") or {},
            )
            payload["hero_slide_url"] = carousel_tool.slide_url(cycle_id, upload_id, 0)
        except Exception as e:
            log.warning("materialize: hero build failed: %s", e)

    # Slides 1-4 — Nano Banana 2, only if the caller opted in
    if req.build_carousel_images:
        ref_bytes: bytes | None = None
        ref_path = _BRAND_REFS_DIR / f"{cid}.png"
        if ref_path.exists():
            ref_bytes = ref_path.read_bytes()
        for i, slide in enumerate(materialized.carousel_slides, start=1):
            png, err = carousel_tool.generate_slide_image(
                image_prompt=slide.image_prompt,
                reference_image_bytes=ref_bytes,
            )
            if png:
                url = carousel_tool.save_slide(cycle_id, upload_id, i, png)
                payload["generated_slides"].append({"index": i, "url": url, "role": slide.role})
            else:
                payload["generated_slides"].append({"index": i, "url": None, "role": slide.role, "error": err})

    mem.save_upload_materialized(upload_id, payload)
    return payload


# ---------- carousel ----------

class CarouselPlanRequest(BaseModel):
    cycle_id: str
    item_id: str
    company_id: str | None = None


class CarouselGenerateRequest(BaseModel):
    cycle_id: str
    item_id: str
    company_id: str | None = None
    slides: list[dict] = Field(default_factory=list, description="Optional edited plan slides; if empty, uses saved plan.")
    only_slide: int | None = Field(None, description="If set, regenerate only this slide index (0-4).")


@app.post("/carousel/plan", summary="Plan a 5-slide Instagram carousel for one approved story")
def carousel_plan(req: CarouselPlanRequest) -> dict:
    """Ask the LLM to plan the carousel. Persists the plan on disk so the
    frontend can edit inline and the /generate step can pick it up.
    """
    _safe_id(req.cycle_id, "cycle_id")
    _safe_id(req.item_id, "item_id")
    cid = _company_id(req.company_id)
    profile = mem.get_profile(cid) or {}
    if not profile:
        raise HTTPException(status_code=404, detail=f"no profile for company_id={cid}")

    # Find the story in the cycle's scored queue
    from .graph.build import build_content_graph, cycle_thread

    graph = build_content_graph()
    cfg = cycle_thread(req.cycle_id)
    snapshot = graph.get_state(cfg)
    scored = (snapshot.values or {}).get("scored") or []
    story = next((c for c in scored if c["id"] == req.item_id), None)
    if not story:
        raise HTTPException(status_code=404, detail=f"item {req.item_id} not in cycle {req.cycle_id}")

    try:
        plan = carousel_tool.plan_carousel(story=story, profile=profile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"plan failed: {e}")

    carousel_tool.save_plan(req.cycle_id, req.item_id, plan)
    return {
        "cycle_id": req.cycle_id,
        "item_id": req.item_id,
        "story_title": plan.story_title,
        "slides": [s.model_dump() for s in plan.slides],
    }


@app.post("/carousel/generate", summary="Generate images for a planned carousel")
def carousel_generate(req: CarouselGenerateRequest) -> dict:
    """Runs the image model for each slide (or one, if ``only_slide`` set).

    Returns URLs of the persisted PNGs relative to the backend
    (e.g. ``/carousels/{cycle}/{item}/0.png``).
    """
    _safe_id(req.cycle_id, "cycle_id")
    _safe_id(req.item_id, "item_id")
    cid = _safe_id(_company_id(req.company_id), "company_id")
    profile = mem.get_profile(cid) or {}

    # Merge: prefer client-supplied edited slides, else load persisted plan
    if req.slides:
        try:
            plan = carousel_tool.CarouselPlan(story_title="(edited)", slides=[carousel_tool.Slide(**s) for s in req.slides])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid slides payload: {e}")
    else:
        plan = carousel_tool.load_plan(req.cycle_id, req.item_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="no plan on disk; call /carousel/plan first")

    # Load the brand reference bytes to condition every image
    ref_bytes: bytes | None = None
    ref_path = _BRAND_REFS_DIR / f"{cid}.png"
    if ref_path.exists():
        ref_bytes = ref_path.read_bytes()

    indices = [req.only_slide] if req.only_slide is not None else list(range(len(plan.slides)))
    outcomes: list[dict] = []
    for i in indices:
        if i < 0 or i >= len(plan.slides):
            continue
        slide = plan.slides[i]
        png, err = carousel_tool.generate_slide_image(
            image_prompt=slide.image_prompt,
            reference_image_bytes=ref_bytes,
        )
        if png:
            url = carousel_tool.save_slide(req.cycle_id, req.item_id, i, png)
            outcomes.append({"index": i, "url": url, "role": slide.role})
        else:
            outcomes.append({"index": i, "url": None, "role": slide.role, "error": err})

    return {
        "cycle_id": req.cycle_id,
        "item_id": req.item_id,
        "outcomes": outcomes,
    }


# ---------- orchestrator ----------

@app.post("/chat", summary="Chat rail — natural-language command")
def chat(req: ChatIn) -> dict:
    cid = _company_id(req.company_id)
    return orch.handle_message(message=req.message, company_id=cid, context=req.context)
