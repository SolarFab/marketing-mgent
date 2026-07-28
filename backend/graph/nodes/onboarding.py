"""Onboarding subgraph — the differentiator.

PRD §4.2 flow::

    url → crawl_node → extract_node → seed_sources_node → confirm_node → persist_node

Design notes:

* Every node reads and writes only :class:`ContentState` — no shared globals.
* ``extract_node`` returns a **draft** profile. Nothing is written to the
  database until ``persist_node`` runs, which happens *after* the confirm
  HITL step. This means the user's edits in the confirm step are respected
  automatically.
* ``confirm_node`` itself is a no-op passthrough. The graph uses a
  LangGraph :func:`interrupt_before` on this node — the API surfaces the
  interrupted state to the frontend, the user submits their edits, and the
  graph resumes with the corrected state.
* ``seed_sources_node`` fails **soft**: an empty proposed list is fine and
  the user can add sources manually.
* Thin-content guard: if ``crawl_node`` returns less than
  :data:`MIN_TEXT_LENGTH` characters of extracted text, the state carries
  a ``thin_content`` flag so the confirm UI can prompt the user to paste
  an About paragraph instead of silently producing a poor profile.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ...config import settings
from ...llm import make_llm
from ...memory import db as mem
from ...prompts import load_prompt, prompt_version
from ...tools.crawl import Page, crawl_site, total_text_length
from ...tools.css_hints import extract_css_hints
from ...tools.screenshot import screenshot_homepage
from ...tools.sources import normalize_source_url, outlet_name_from_title
from ...tools.web_search import search_outlets
from ..state import ContentState

log = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 800  # below this we warn the user rather than trust the extraction


# --- Draft schemas (structured output) ---

class Identity(BaseModel):
    summary: str = Field("", description="One-sentence summary of what the business does.")
    products: list[str] = Field(default_factory=list, description="Concrete products or services named on the site.")


class Market(BaseModel):
    segments: list[str] = Field(default_factory=list, description="Customer segments the business serves.")
    geo: list[str] = Field(default_factory=list, description="Geographic markets the business serves.")
    icp: str = Field("", description="Ideal customer profile — a specific persona.")


class Positioning(BaseModel):
    value_prop: str = Field("", description="The core promise: what the business delivers and why it matters.")
    differentiators: list[str] = Field(default_factory=list, description="Specific things that make this business different from alternatives.")


class Voice(BaseModel):
    tone: list[str] = Field(default_factory=list, description="Tone descriptors as the site actually reads (e.g. 'warm', 'analytical', 'urgent').")
    vocabulary: list[str] = Field(default_factory=list, description="Characteristic words the site uses often.")
    do: list[str] = Field(default_factory=list, description="Stylistic patterns the site follows.")
    dont: list[str] = Field(default_factory=list, description="Stylistic patterns the site visibly avoids (e.g. 'hype', 'buzzwords', 'jargon').")


class ContentPillar(BaseModel):
    """A theme the business publishes about."""
    name: str = Field(..., description="Short pillar name, e.g. 'product', 'industry', 'story', 'commentary'.")
    description: str = Field(..., description="What this pillar covers — tied to concrete anchors from the site.")


class Brand(BaseModel):
    """Visual identity extracted from the site — used by the carousel/image generator.

    Colors are hex strings like '#0a0a0a'. Each color has a specific role
    so an editorial site with dual accents (like a blue CTA + red tag
    system) is captured correctly rather than being flattened to one.
    """
    primary_color: str = Field(
        default="#0a0a0a",
        description="Dominant color of the site — usually the background or main brand color. Hex.",
    )
    accent_color: str = Field(
        default="#1a3fd8",
        description="Primary CTA color — the color of the biggest buttons (subscribe, sign up), main links, headline underline. This is what a designer would call 'the brand color'. Hex.",
    )
    secondary_accent_color: str = Field(
        default="",
        description="Secondary accent used in the site's SECOND color role — often section rules, tag underlines, taglines. Empty if the site uses a single-accent palette. Hex.",
    )
    category_tag_color: str = Field(
        default="",
        description="Color used for category pill/chip tags (e.g. 'AUTONOMOUS DRIVING' style category labels). May be same as secondary_accent_color. Empty if not visible. Hex.",
    )
    background_color: str = Field(
        default="#0a0a0a",
        description="Background color for content slides. Hex.",
    )
    text_color: str = Field(
        default="#ffffff",
        description="High-contrast text color that sits on background_color. Hex.",
    )
    typography_feel: str = Field(
        default="bold sans-serif",
        description="Typography descriptor — e.g. 'bold sans-serif', 'editorial serif', 'monospace tech', 'handwritten organic'.",
    )
    mood: list[str] = Field(
        default_factory=list,
        description="3-5 short descriptors that DON'T overlap. Pick from families like: registers (editorial | urgent | hushed), palette (high-contrast | muted | warm | cool), density (dense | minimalist | spacious), texture (industrial | organic | tech | editorial | luxe).",
    )
    style_notes: str = Field(
        default="",
        description="One-sentence visual style summary suitable for prompting an image generator. Be concrete about palette, lighting, composition.",
    )
    social_handle: str = Field(
        default="",
        description="Public social handle if the site displays one, e.g. '@chinatechsignal'. Empty if not shown.",
    )
    reference_image_url: str = Field(
        default="",
        description="Backend-relative URL of the persisted homepage screenshot. Used by the image generator as a style reference. Set outside the LLM — the model should NOT populate this.",
    )
    font_families: list[str] = Field(
        default_factory=list,
        description="Actual font family names loaded on the site (from Google Fonts or CSS declarations). Set from HTML hints, not by the LLM.",
    )


class CompanyProfileDraft(BaseModel):
    """Structured output schema for the extract prompt.

    Mirrors §5.1 of the PRD. ``content_pillars`` uses a list-of-objects
    shape (rather than a dict) because smaller models handle it more
    reliably in structured-output mode; it's converted to a dict in
    :meth:`normalized` for storage.
    """
    identity: Identity = Field(default_factory=Identity, description="What the business does + its products.")
    market: Market = Field(default_factory=Market, description="Who the business sells to and where.")
    positioning: Positioning = Field(default_factory=Positioning, description="Value proposition + differentiators.")
    voice: Voice = Field(default_factory=Voice, description="How the site talks — extract from actual site copy, not generic.")
    content_pillars: list[ContentPillar] = Field(
        default_factory=list,
        description="REQUIRED. 3 to 5 themes the business should publish about. Each has a short name and a one-line description tied to what's actually on the site. NEVER return an empty list.",
        min_length=0,
    )
    content_mix: float = Field(0.5, description="Owned-vs-external ratio: 1.0 = all owned/story-driven, 0.0 = all external/curation. Inferred from what the business sells.")

    def normalized(self) -> dict[str, Any]:
        """Return a plain dict with content_mix clamped and pillars flattened.

        - ``content_mix`` is clamped to [0.0, 1.0].
        - ``content_pillars`` (list of ContentPillar) is converted to a
          ``{name: description}`` dict for storage/consumption.
        - If pillars ended up empty (smaller models sometimes still skip
          the field), fallback placeholders are derived from products +
          segments. The user can edit these in the confirm step.
        """
        d = self.model_dump()
        d["content_mix"] = max(0.0, min(1.0, float(d.get("content_mix", 0.5))))
        pillars_raw = d.get("content_pillars") or []
        pillars_flat: dict[str, str] = {}
        for p in pillars_raw:
            if isinstance(p, dict) and p.get("name"):
                pillars_flat[p["name"]] = p.get("description", "")
        if not pillars_flat:
            pillars_flat = _fallback_pillars(d)
        d["content_pillars"] = pillars_flat
        # Ensure every color field looks like a hex string; fall back to defaults otherwise
        b = d.get("brand") or {}
        for k, default in [
            ("primary_color", "#0a0a0a"),
            ("accent_color", "#ef4444"),
            ("background_color", "#0a0a0a"),
            ("text_color", "#ffffff"),
        ]:
            v = str(b.get(k) or "").strip()
            if not v.startswith("#") or not (len(v) in (4, 7)):
                b[k] = default
            else:
                b[k] = v
        d["brand"] = b
        return d


def _fallback_pillars(profile: dict[str, Any]) -> dict[str, str]:
    """Derive minimal placeholder pillars when the LLM omitted them."""
    market = profile.get("market") or {}
    identity = profile.get("identity") or {}
    segments = market.get("segments") or []
    products = identity.get("products") or []
    pillars: dict[str, str] = {}
    if products:
        pillars["product"] = f"our own products: {', '.join(products[:3])}"
    if segments:
        pillars["industry"] = f"news and analysis for {segments[0]}"
    pillars.setdefault("story", "the story behind the business")
    pillars.setdefault("commentary", "our take on what matters this week")
    return pillars


# --- Nodes ---

def crawl_node(state: ContentState) -> dict:
    """Fetch the homepage + a handful of high-signal pages.

    Populates ``crawled_pages`` in state as a list of ``{url, title, text}``.
    Sets ``thin_content`` = True when total extracted text is too short to
    yield a reliable profile — the confirm UI branches on this.
    """
    url = state.get("onboarding_url", "").strip()
    if not url:
        raise ValueError("onboarding_url is required in state")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    pages = crawl_site(url)
    payload = [{"url": p.url, "title": p.title, "text": p.text} for p in pages]
    thin = total_text_length(pages) < MIN_TEXT_LENGTH
    log.info(
        "crawl_node: url=%s pages=%d chars=%d thin=%s",
        url, len(pages), total_text_length(pages), thin,
    )
    return {
        "onboarding_url": url,
        "crawled_pages": payload,
        "messages": [
            {"role": "system", "content": f"Crawled {len(pages)} pages, thin_content={thin}"}
        ],
    }


def extract_node(state: ContentState) -> dict:
    """LLM-based Company Profile extraction from crawled text.

    Uses the prompt at ``docs/prompts/onboarding_extract_v1.md`` and
    structured output binding so the LLM must return a schema-conformant
    JSON object. The draft is placed at ``company_profile`` in state (not
    yet persisted).
    """
    pages: list[dict] = state.get("crawled_pages") or []
    if not pages:
        # Return an empty profile with a thin-content marker; confirm UI decides.
        return {"company_profile": CompanyProfileDraft().normalized()}

    joined = "\n\n".join(
        f"### {p['title']} — {p['url']}\n{p['text'][:4000]}" for p in pages
    )
    prompt = load_prompt("onboarding_extract", "v1").format(
        url=state.get("onboarding_url", ""),
        pages=joined,
    )

    llm = make_llm(temperature=0.2)
    structured = llm.with_structured_output(CompanyProfileDraft)
    try:
        draft: CompanyProfileDraft | None = structured.invoke(prompt)
        if draft is None:  # model may emit no tool call → invoke() returns None
            raise ValueError("structured output returned None")
    except Exception as e:
        log.warning("extract_node: structured output failed (%s); retrying raw JSON", e)
        try:
            raw = llm.invoke(prompt).content
            data = json.loads(raw)
            draft = CompanyProfileDraft.model_validate(data)
        except Exception:
            draft = CompanyProfileDraft()

    profile = draft.normalized()

    # Brand extraction is a hybrid pipeline (see _extract_brand):
    #   1. CSS hints from the raw homepage HTML — exact hex codes + font URLs.
    #   2. Homepage screenshot — what the visitor actually sees.
    #      Screenshot is also PERSISTED to disk so Phase 2 image generation
    #      can hand it to Nano Banana 2 as a style reference.
    #   3. Vision LLM combines both → final palette + mood + style_notes.
    # Fails soft: any step failing falls through to the text-only baseline.
    try:
        url = state.get("onboarding_url") or ""
        company_id = state.get("company_id") or settings().company_id
        profile["brand"] = _extract_brand(url, joined, profile, company_id).model_dump()
    except Exception as e:
        log.warning("extract_node: brand extraction failed (%s); using defaults", e)
        profile["brand"] = Brand().model_dump()

    log.info(
        "extract_node: mix=%.2f pillars=%d brand_mood=%s prompt=%s",
        profile["content_mix"], len(profile["content_pillars"]),
        profile["brand"].get("mood"),
        prompt_version("onboarding_extract", "v1"),
    )
    return {"company_profile": profile}


def _extract_brand(url: str, joined_pages: str, profile: dict, company_id: str) -> Brand:
    """Hybrid brand extraction: CSS hints + screenshot + vision LLM.

    Steps:

    1. Refetch the homepage HTML and mine deterministic hints
       (:mod:`backend.tools.css_hints`) — hex codes, font families,
       Google Fonts URLs.
    2. Take a rendered screenshot
       (:mod:`backend.tools.screenshot`). **Persist it** to
       ``data/brand-refs/{company_id}.png`` so Phase 2 image generation
       can hand it to Nano Banana 2 as a style reference.
    3. Send everything to a vision-capable LLM (Gemini 2.5 Flash on
       OpenRouter) with a structured-output binding on :class:`Brand`.

    If any step fails, the LLM still runs on whatever context we managed
    to gather — hints alone, or copy alone. The Brand default hex fallback
    in :meth:`CompanyProfileDraft.normalized` protects the downstream.
    """
    import base64
    from pathlib import Path
    from ...tools.crawl import _fetch_raw  # local import, avoids widening public API

    hints: dict = {}
    if url:
        try:
            raw_html = _fetch_raw(url, timeout_s=settings().crawl_timeout_s)
            if raw_html:
                hints = extract_css_hints(raw_html)
        except Exception as e:
            log.info("_extract_brand: css hints failed (%s)", e)

    # Screenshot: use once for vision + persist for Phase 2 style transfer.
    # We keep the ORIGINAL PNG on disk (used as Phase-2 reference) but send
    # a compressed JPEG to the vision LLM — the model doesn't need 191KB
    # to understand the palette, and OpenRouter has payload size caps.
    screenshot_b64: str | None = None
    reference_image_url = ""
    if url:
        png = screenshot_homepage(url)
        if png:
            # Persist the full-quality PNG for Phase 2 (Nano Banana 2 reference)
            try:
                ref_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "brand-refs"
                ref_dir.mkdir(parents=True, exist_ok=True)
                out_path = ref_dir / f"{company_id}.png"
                out_path.write_bytes(png)
                reference_image_url = f"/brand-refs/{company_id}.png"
                log.info("_extract_brand: saved reference image to %s (%d KB)", out_path, len(png) // 1024)
            except Exception as e:
                log.warning("_extract_brand: failed to persist reference image: %s", e)

            # Compress for the vision LLM (target <100KB base64)
            try:
                from io import BytesIO
                from PIL import Image  # type: ignore

                img = Image.open(BytesIO(png))
                img = img.convert("RGB")
                img.thumbnail((1024, 1024), Image.LANCZOS)
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=75, optimize=True)
                compressed = buf.getvalue()
                screenshot_b64 = base64.b64encode(compressed).decode("ascii")
                log.info("_extract_brand: compressed screenshot for vision: %d KB", len(compressed) // 1024)
            except Exception as e:
                log.warning("_extract_brand: image compression failed (%s); using raw PNG", e)
                screenshot_b64 = base64.b64encode(png).decode("ascii")

    voice = profile.get("voice") or {}
    prompt = _BRAND_PROMPT.format(
        voice=json.dumps(voice, ensure_ascii=False),
        hints=json.dumps(hints, ensure_ascii=False)[:1500] if hints else "(none extracted)",
        pages=joined_pages[:2500],
    )

    # Vision-capable model. Gemini 2.5 Flash handles both image and JSON well.
    from langchain_core.messages import HumanMessage

    # LLM extraction — falls back to a default Brand if the vision call fails,
    # so downstream still gets the persisted reference image + font families.
    result: Brand
    try:
        if screenshot_b64:
            message = HumanMessage(content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                },
            ])
            # max_tokens=3000 leaves headroom for the extended Brand schema.
            # temperature=0 keeps runs deterministic.
            llm = make_llm(model="google/gemini-2.5-flash", temperature=0.0, max_tokens=3000)
            result = llm.with_structured_output(Brand).invoke([message])
        else:
            llm = make_llm(temperature=0.0, max_tokens=3000)
            result = llm.with_structured_output(Brand).invoke(prompt)
    except Exception as e:
        log.warning("_extract_brand: LLM call failed (%s); using defaults + side-channel fields", e)
        result = Brand()

    # Inject the side-channel fields the LLM must not populate:
    # persisted screenshot URL + measured font families from HTML.
    result.reference_image_url = reference_image_url
    fonts_from_hints = list(hints.get("google_font_families") or hints.get("font_families") or [])
    if fonts_from_hints:
        result.font_families = fonts_from_hints[:5]
    return result


_BRAND_PROMPT = """You are extracting the **visual identity** of a business so an image generator can keep every generated asset on-brand. Ground everything in the screenshot — do NOT infer colors from the voice or copy.

You have three inputs:
- The site's brand voice (already extracted, provided for mood alignment only).
- Deterministic hints harvested from the site's HTML/CSS (may be empty; treat as suggestions, not truth).
- A screenshot of the homepage — this is the ground truth.

**Color extraction rules — read carefully.**

Look at the screenshot and answer these questions in order:

1. **`background_color`** — the color that fills the **top of the page, above the fold** — what a visitor sees FIRST when the page loads. If the top hero is dark and lower sections are light, the background is DARK. This will be the base color for every generated slide, so err toward the hero/masthead area, not scrolled content zones.
2. **`text_color`** — the main headline/body text color that sits on the ABOVE-THE-FOLD background above.
3. **`accent_color`** — what color is the *biggest, most salient CTA button* (e.g. "Subscribe", "Sign up", "Get started")? That is the primary accent. NOT the color of taglines. NOT the color of category tags. The **button** color.
4. **`secondary_accent_color`** — is there a *different* color used in a second role (section rules, hero taglines, underlines)? If yes, its hex. If the site is single-accent, leave empty.
5. **`category_tag_color`** — the color of category pill/chip tags (like `AUTONOMOUS DRIVING` or `FUNDING`). May match `secondary_accent_color` or be its own color. Empty if no category tags visible.
6. **`primary_color`** — the deepest brand color, often the background hue or the darkest brand element. Distinct from accent_color.

**Never let voice mood override screenshot evidence.** If the voice says "urgent" but the CTA button is blue, the accent is blue. Voice is for mood descriptors, not colors.

**Other fields:**

- `typography_feel` = 1–3 words describing the actual fonts you see. Distinguish "bold sans-serif" (heavy weights, tight letter-spacing) from "editorial sans-serif" (medium weight, generous letter-spacing) from "editorial serif" from "monospace tech".
- `mood` = 3–5 descriptors that DO NOT overlap. Pick from *distinct* families:
  - Register: `editorial` | `urgent` | `hushed` | `energetic` | `authoritative`
  - Palette: `high-contrast` | `muted` | `warm` | `cool`
  - Density: `dense` | `minimalist` | `spacious`
  - Texture: `industrial` | `organic` | `tech` | `luxe` | `hand-crafted`
  Never combine `editorial` and `urgent` — those are opposites. Never combine `dense` and `minimalist`.
- `style_notes` = one concrete sentence an image generator could act on. Mention actual colors, actual lighting, actual composition style visible in the screenshot.
- `social_handle` = the @-handle only if you can literally read it on the screenshot.

**Voice (mood alignment only — DO NOT USE FOR COLORS):**
```
{voice}
```

**CSS/HTML hints (deterministic anchor for hex values when the screenshot color matches):**
```
{hints}
```

**Copy snippet (mood alignment only):**
```
{pages}
```

Return JSON matching the Brand schema."""


def seed_sources_node(state: ContentState) -> dict:
    """Propose an initial set of followed sources via web search.

    Draws segments + geo from the freshly-extracted profile. Failures are
    absorbed silently (Tavily rate limits etc.) — an empty list is fine.
    """
    profile = state.get("company_profile") or {}
    market = profile.get("market") or {}
    segments: list[str] = market.get("segments") or []
    geo_list: list[str] = market.get("geo") or []
    if not segments:
        # Nothing to search for — leave the proposal empty.
        return {"proposed_sources": []}

    # Same LLM-driven query approach as discovery_node — targets outlets the
    # business would actually *read*, tailored to their kind of business.
    from .discovery import _llm_search_queries

    geo = geo_list[0] if geo_list else None
    queries = _llm_search_queries(profile, n=3)

    seen: set[str] = set()
    proposals: list[dict] = []
    for query in queries:
        hits = search_outlets(topic=query, geo=geo, max_results=6)
        for h in hits:
            normalized = normalize_source_url(h.url, probe_feed=True)
            if not normalized.is_outlet or not normalized.host or normalized.host in seen:
                continue
            seen.add(normalized.host)
            proposals.append({
                "url": normalized.url,
                "root_url": normalized.root_url,
                "name": outlet_name_from_title(h.title, normalized.host),
                "kind": normalized.kind,
                "origin": "onboarding",
                "reason": (h.snippet or f"Matched: {query}")[:200],
                "matched_query": query,
            })
    log.info(
        "seed_sources_node: proposed=%d queries=%d geo=%r (rss=%d)",
        len(proposals), len(queries), geo, sum(1 for p in proposals if p["kind"] == "rss"),
    )
    return {"proposed_sources": proposals}


def confirm_node(state: ContentState) -> dict:
    """HITL passthrough. The graph interrupts *before* this node.

    The frontend re-invokes the graph with the (possibly edited) profile
    and proposed_sources; this node just forwards them so the persist step
    stores what the user actually confirmed.
    """
    return {}


def persist_node(state: ContentState) -> dict:
    """Write the confirmed profile + accepted sources to the database.

    Only sources marked ``accepted: True`` (or all, if the flag is absent
    for backwards compatibility) are inserted.
    """
    company_id = state.get("company_id") or settings().company_id
    profile = state.get("company_profile") or {}
    crawled_urls = [p["url"] for p in (state.get("crawled_pages") or [])]
    mem.upsert_profile(company_id, profile, crawled_urls=crawled_urls)

    # Ensure preference profile row exists
    mem.get_preferences(company_id)

    proposals = state.get("proposed_sources") or []
    written = 0
    for src in proposals:
        if src.get("accepted") is False:
            continue
        mem.add_source(
            company_id,
            url=src["url"],
            name=src.get("name"),
            kind=src.get("kind") or "web",
            status="active",
            origin=src.get("origin") or "onboarding",
            reason=src.get("reason"),
        )
        written += 1

    log.info("persist_node: company=%s sources_written=%d", company_id, written)
    return {
        "company_id": company_id,
        "messages": [
            {"role": "system", "content": f"Persisted profile + {written} sources for {company_id}"}
        ],
    }
