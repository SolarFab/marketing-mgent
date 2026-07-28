"""Instagram carousel generation.

Two-step pipeline:

1. :func:`plan_carousel` — LLM plans exactly 5 slides for one story,
   with fixed roles (hero → stat → context → implication → cta) and a
   fully-composed image prompt per slide.
2. :func:`generate_slide_image` — hits Nano Banana 2 (Google Gemini image
   preview) via OpenRouter, passing the brand reference screenshot as a
   style-conditioning input. Returns PNG bytes.

Both functions are network operations. Failures return structured info
(rather than raising) so the calling endpoint can surface useful errors
without exposing internals.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..config import settings
from ..llm import make_llm
from ..prompts import load_prompt

log = logging.getLogger(__name__)


# ---------- schemas ----------

class Slide(BaseModel):
    """One slide in the carousel.

    Every slide has ``image_prompt`` — the ready-to-send prompt for the
    image model. The other fields are for the frontend preview and for
    the user's inline edits before generation.
    """
    role: str = Field(..., description="One of: hero | stat | context | implication | cta.")
    big_text: str = Field(
        "",
        description="The dominant text on the slide — headline for hero, stat number/phrase for stat/context/implication, CTA copy for cta.",
    )
    subhead: str = Field(
        "",
        description="Supporting sentence beneath big_text. Empty on hero and cta slides.",
    )
    image_prompt: str = Field(
        ...,
        description="Fully-composed prompt for the image model. Includes palette hex codes, layout instructions, and the exact quoted text to render.",
    )


class CarouselPlan(BaseModel):
    story_title: str = Field(..., description="Title of the source story, echoed for the user.")
    # NOTE: no min_length/max_length here. Several OpenRouter providers
    # (Bedrock, Anthropic, Azure) reject JSON-Schema minItems > 1 for
    # structured outputs. The prompt tells the LLM to return exactly 5;
    # plan_carousel() truncates or fails if it doesn't.
    slides: list[Slide] = Field(
        default_factory=list,
        description="Exactly 5 slides in fixed order: hero, stat, context, implication, cta.",
    )


# ---------- plan step ----------

def plan_carousel(*, story: dict, profile: dict) -> CarouselPlan:
    """Ask the LLM to plan the 5 slides for one story.

    ``story`` is a candidate dict (id, title, angle, url, published_date...).
    ``profile`` is the full company profile including ``brand``.
    """
    brand = profile.get("brand") or {}
    voice = profile.get("voice") or {}
    prompt = load_prompt("carousel_plan", "v1").format(
        tone=", ".join(voice.get("tone") or []),
        background_color=brand.get("background_color", "#0a0a0a"),
        accent_color=brand.get("accent_color", "#1a3fd8"),
        text_color=brand.get("text_color", "#ffffff"),
        typography_feel=brand.get("typography_feel", "bold sans-serif"),
        social_handle=brand.get("social_handle", "") or "",
        headline_text=story.get("title", ""),
        big_text="",
        sub_text="",
        page_indicator="",
        source_url=story.get("url") or story.get("verified_source_url") or "",
        profile=json.dumps(_compact_profile(profile), ensure_ascii=False, default=str)[:2500],
        brand=json.dumps(brand, ensure_ascii=False)[:1500],
        story=json.dumps(
            {
                k: story.get(k)
                for k in ("id", "title", "angle", "url", "verified_source_url", "pillar", "kind", "published_date")
                if story.get(k) is not None
            },
            ensure_ascii=False,
            default=str,
        )[:1500],
    )
    llm = make_llm(temperature=0.4, max_tokens=3000)
    plan: CarouselPlan = llm.with_structured_output(CarouselPlan).invoke(prompt)

    # Enforce the exact-5 shape post-hoc since we can't declare it on the schema.
    if len(plan.slides) > 5:
        plan.slides = plan.slides[:5]
    elif len(plan.slides) < 5:
        # Fill the missing slots with sensible defaults in the correct role order
        # so the user still gets a full grid to edit.
        default_roles = ["hero", "stat", "context", "implication", "cta"]
        present = {s.role for s in plan.slides}
        for role in default_roles:
            if len(plan.slides) >= 5:
                break
            if role not in present:
                plan.slides.append(Slide(
                    role=role,
                    big_text="",
                    subhead="",
                    image_prompt=(
                        f"Placeholder slide for {role} — LLM did not fill this role. "
                        f"Regenerate the plan or edit inline."
                    ),
                ))
    return plan


def _compact_profile(profile: dict) -> dict:
    return {
        "identity": profile.get("identity", {}),
        "market": profile.get("market", {}),
        "voice": profile.get("voice", {}),
        "content_pillars": profile.get("content_pillars", {}),
    }


# ---------- image generation ----------

# OpenRouter model IDs for Google's Nano Banana series (verified via
# `/models` endpoint 2026-07-10). "3.1-flash-image" is Nano Banana 2.
# Fallback to the 2.5 model if 3.1 isn't available on your workspace.
_IMAGE_MODEL = "google/gemini-3.1-flash-image"


def generate_slide_image(
    *,
    image_prompt: str,
    reference_image_bytes: bytes | None = None,
) -> tuple[bytes | None, str | None]:
    """Generate one slide via Nano Banana 2.

    Returns ``(png_bytes, error)`` — one of them is ``None``. The reference
    image is optional but strongly recommended for brand consistency; when
    provided it's sent as a data-URL image_url alongside the text prompt.
    """
    s = settings()

    if s.publish_mode != "real":
        # Preview mode: return a placeholder image so the UI wires end-to-end
        # without hitting the paid image endpoint. We render a small solid PNG.
        return _placeholder_png(image_prompt), None

    try:
        import openai  # type: ignore

        client = openai.OpenAI(
            api_key=s.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://signal.local",
                "X-Title": "Signal Content Agent - Carousel",
            },
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": image_prompt}]
        if reference_image_bytes:
            b64 = base64.b64encode(reference_image_bytes).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        completion = client.chat.completions.create(
            model=_IMAGE_MODEL,
            messages=[{"role": "user", "content": content}],  # type: ignore
            modalities=["image", "text"],  # type: ignore
        )

        # Response shape: choices[0].message.images[] is a list of {"type":"image_url","image_url":{"url":"data:..."}}
        msg = completion.choices[0].message
        images = getattr(msg, "images", None) or []
        for img in images:
            url_obj = img.get("image_url") if isinstance(img, dict) else None
            data_url = (url_obj or {}).get("url") if isinstance(url_obj, dict) else None
            if data_url and data_url.startswith("data:image"):
                # data URL: data:image/png;base64,....
                comma = data_url.find(",")
                if comma > 0:
                    return base64.b64decode(data_url[comma + 1:]), None
        return None, "no image in response"
    except Exception as e:
        log.warning("generate_slide_image: failed: %s", e)
        return None, str(e)[:300]


def _placeholder_png(prompt: str) -> bytes:
    """Render a small solid-color PNG as a preview-mode placeholder.

    Uses the primary color hint from the prompt if we can find one, else
    a neutral gray so the UI's slide grid still fills.
    """
    try:
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        # Try to sniff a background hex from the prompt
        import re
        m = re.search(r"Background color:\s*(#[0-9a-fA-F]{3,6})", prompt)
        bg = m.group(1) if m else "#111111"
        m2 = re.search(r"Accent color:\s*(#[0-9a-fA-F]{3,6})", prompt)
        accent = m2.group(1) if m2 else "#1a3fd8"

        # 1080x1350 shrunk to 540x675 for the preview
        img = Image.new("RGB", (540, 675), bg)
        draw = ImageDraw.Draw(img)
        # Draw an accent-color bar to hint at brand
        draw.rectangle([(0, 0), (540, 8)], fill=accent)
        try:
            font = ImageFont.load_default(size=18)
        except Exception:
            font = ImageFont.load_default()
        draw.text((20, 40), "[preview mode]", fill="#888888", font=font)
        draw.text((20, 80), "flip PUBLISH_MODE=real for real images", fill="#666666", font=font)
        # Show first ~200 chars of the prompt so the user can see what would generate
        wrapped = _wrap(prompt[:600], 46)
        y = 130
        for line in wrapped:
            draw.text((20, y), line, fill="#999999", font=font)
            y += 22
            if y > 640:
                break
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        log.warning("_placeholder_png: %s", e)
        return b""


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for w in words:
        if length + len(w) + 1 > width:
            lines.append(" ".join(current))
            current = [w]
            length = len(w)
        else:
            current.append(w)
            length += len(w) + 1
    if current:
        lines.append(" ".join(current))
    return lines


# ---------- file storage ----------

def carousel_dir(cycle_id: str, item_id: str) -> Path:
    root = Path(__file__).resolve().parent.parent.parent / "data" / "carousels"
    d = (root / cycle_id / item_id).resolve()
    if root.resolve() not in d.parents:
        raise ValueError(f"carousel path escapes storage root: {cycle_id!r}/{item_id!r}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def slide_url(cycle_id: str, item_id: str, slide_n: int) -> str:
    return f"/carousels/{cycle_id}/{item_id}/{slide_n}.png"


def save_slide(cycle_id: str, item_id: str, slide_n: int, png: bytes) -> str:
    d = carousel_dir(cycle_id, item_id)
    path = d / f"{slide_n}.png"
    path.write_bytes(png)
    return slide_url(cycle_id, item_id, slide_n)


def save_plan(cycle_id: str, item_id: str, plan: CarouselPlan) -> Path:
    d = carousel_dir(cycle_id, item_id)
    path = d / "plan.json"
    path.write_text(plan.model_dump_json(indent=2))
    return path


def load_plan(cycle_id: str, item_id: str) -> CarouselPlan | None:
    d = carousel_dir(cycle_id, item_id)
    path = d / "plan.json"
    if not path.exists():
        return None
    try:
        return CarouselPlan.model_validate_json(path.read_text())
    except Exception:
        return None
