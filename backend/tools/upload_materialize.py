"""Turn a user upload (photo + short story) into channel-ready drafts.

The user provides the ground truth (their photo, their words). The LLM
only reshapes for each channel — no hallucinated stats, no invented
quotes. This is the OWNED path with zero fabrication risk.

Result shape:

* ``newsletter_section`` — one editorial section, same schema the
  Write node's newsletter draft uses.
* ``carousel_slides`` — 4 slides (STAT, CONTEXT, IMPLICATION, CTA).
  The hero slide is the user's own photo verbatim; it's inserted by
  the calling code, not by the LLM.
* ``linkedin_post`` — plain string.
* ``instagram_caption`` — plain string.
* ``instagram_hashtags`` — list.
"""
from __future__ import annotations

import base64
import json
import logging
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, Field

from ..llm import make_llm
from ..prompts import load_prompt
from .carousel import Slide

log = logging.getLogger(__name__)


# ---------- schemas ----------


class MaterializedNewsletterSection(BaseModel):
    category: str = ""
    heading: str = ""
    body_markdown: str = ""
    highlight_term: str = ""


class MaterializedUpload(BaseModel):
    newsletter_section: MaterializedNewsletterSection = Field(default_factory=MaterializedNewsletterSection)
    carousel_slides: list[Slide] = Field(default_factory=list)
    linkedin_post: str = ""
    instagram_caption: str = ""
    instagram_hashtags: list[str] = Field(default_factory=list)


# ---------- entry point ----------


def materialize_from_upload(*, upload: dict, profile: dict) -> MaterializedUpload:
    """One LLM call — reshape the upload for every channel at once."""
    brand = profile.get("brand") or {}
    voice = profile.get("voice") or {}
    prompt = load_prompt("materialize_upload", "v1").format(
        profile=json.dumps(_compact_profile(profile), ensure_ascii=False, default=str)[:2500],
        brand=json.dumps(brand, ensure_ascii=False)[:1500],
        tone=", ".join(voice.get("tone") or []),
        pillar=upload.get("pillar") or "",
        title=upload.get("title") or "",
        story=upload.get("story") or "",
        background_color=brand.get("background_color", "#0a0a0a"),
        accent_color=brand.get("accent_color", "#1a3fd8"),
        text_color=brand.get("text_color", "#ffffff"),
        typography_feel=brand.get("typography_feel", "bold sans-serif"),
        social_handle=brand.get("social_handle", "") or "",
    )
    llm = make_llm(temperature=0.4, max_tokens=3000)
    result: MaterializedUpload = llm.with_structured_output(MaterializedUpload).invoke(prompt)

    # Enforce the exact-4 shape for carousel slides (Amazon Bedrock rejects
    # minItems > 1 on structured outputs, so the model may return anywhere
    # from 3-5 slides). Truncate to 4 and pad if short.
    default_roles = ["stat", "context", "implication", "cta"]
    if len(result.carousel_slides) > 4:
        result.carousel_slides = result.carousel_slides[:4]
    while len(result.carousel_slides) < 4:
        missing_role = default_roles[len(result.carousel_slides)]
        result.carousel_slides.append(Slide(
            role=missing_role,
            big_text="",
            subhead="",
            image_prompt=(
                f"Placeholder {missing_role} slide — LLM did not fill this role. "
                f"Regenerate or edit inline."
            ),
        ))
    return result


def _compact_profile(profile: dict) -> dict:
    return {
        "identity": profile.get("identity", {}),
        "market": profile.get("market", {}),
        "voice": profile.get("voice", {}),
        "content_pillars": profile.get("content_pillars", {}),
    }


# ---------- carousel-hero helper: paste user photo verbatim into slide 0 ----------


def paste_user_photo_as_hero(
    *,
    upload_photo_path: Path,
    cycle_id: str,
    item_id: str,
    upload_title: str,
    brand: dict,
) -> Path:
    """Copy the user's photo into the carousel-generated slides folder as slide 0.

    Also overlays the story title at the bottom in the brand palette so the
    hero has the same "swipe for more" affordance as the AI-generated version.
    """
    from .carousel import carousel_dir
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        # Pillow missing — just copy the raw photo.
        out_dir = carousel_dir(cycle_id, item_id)
        out_path = out_dir / "0.png"
        out_path.write_bytes(upload_photo_path.read_bytes())
        return out_path

    out_dir = carousel_dir(cycle_id, item_id)
    out_path = out_dir / "0.png"

    img = Image.open(upload_photo_path).convert("RGB")
    # Instagram portrait 4:5 → 1080x1350
    target = (1080, 1350)
    img = _cover_resize(img, target)

    # Overlay: bottom fade to background, title text, brand mark, swipe cue
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    bg_hex = brand.get("background_color", "#0a0a0a")
    text_hex = brand.get("text_color", "#ffffff")
    accent_hex = brand.get("secondary_accent_color") or brand.get("accent_color", "#1a3fd8")
    bg_rgb = _hex_to_rgb(bg_hex)
    text_rgb = _hex_to_rgb(text_hex)
    accent_rgb = _hex_to_rgb(accent_hex)

    # Bottom gradient overlay for legibility
    grad_h = 480
    for y in range(grad_h):
        alpha = int(220 * (y / grad_h))
        draw.line(
            [(0, img.height - grad_h + y), (img.width, img.height - grad_h + y)],
            fill=(*bg_rgb, alpha),
        )
    # Top thin ribbon in accent color
    draw.rectangle([(0, 0), (img.width, 8)], fill=(*accent_rgb, 255))

    # Text: title
    title = upload_title[:120]
    font_size = 62
    font = _load_font(font_size)
    _draw_wrapped_text(
        draw,
        title,
        (48, img.height - 320),
        max_width=img.width - 96,
        font=font,
        fill=text_rgb,
        line_spacing=8,
    )

    # Small text: swipe indicator
    small = _load_font(22)
    draw.text(
        (48, img.height - 60),
        "SWIPE FOR MORE →",
        fill=(*text_rgb, 255),
        font=small,
    )

    # Bottom-right: handle
    handle = brand.get("social_handle", "")
    if handle:
        bbox = draw.textbbox((0, 0), handle, font=small)
        w = bbox[2] - bbox[0]
        draw.text(
            (img.width - w - 48, img.height - 60),
            handle,
            fill=(*text_rgb, 255),
            font=small,
        )

    composed = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    composed.save(out_path, format="PNG", optimize=True)
    return out_path


def _cover_resize(img, target: tuple[int, int]):
    """Resize + crop to exactly cover ``target`` dimensions."""
    from PIL import Image  # type: ignore

    tw, th = target
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    dst_ratio = tw / th
    if src_ratio > dst_ratio:
        # Source is wider; crop sides
        new_h = th
        new_w = int(th * src_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        x = (new_w - tw) // 2
        return resized.crop((x, 0, x + tw, th))
    else:
        # Source is taller; crop top/bottom
        new_w = tw
        new_h = int(tw / src_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        y = (new_h - th) // 2
        return resized.crop((0, y, tw, y + th))


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (10, 10, 10)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _load_font(size: int):
    from PIL import ImageFont  # type: ignore

    for candidate in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Avenir Next.ttc",
        "/Library/Fonts/Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _draw_wrapped_text(draw, text, xy, *, max_width, font, fill, line_spacing=6):
    words = text.split()
    if not words:
        return
    lines = []
    current: list[str] = []
    for w in words:
        trial = " ".join(current + [w])
        bbox = draw.textbbox((0, 0), trial, font=font)
        width = bbox[2] - bbox[0]
        if current and width > max_width:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    x, y = xy
    for i, line in enumerate(lines):
        draw.text((x, y + i * (font.size + line_spacing)), line, fill=(*fill, 255), font=font)
