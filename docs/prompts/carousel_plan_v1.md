---
name: carousel_plan
version: v1
purpose: Plan the 5 slides of an Instagram carousel for one approved story.
consumed_by: backend/tools/carousel.py::plan_carousel
schema: backend/tools/carousel.py::CarouselPlan
---

You are producing a **5-slide Instagram carousel** for the business below, on the story provided. Every carousel from this business follows the same fixed 5-slide structure so subscribers recognise the pattern issue after issue.

**Fixed structure (do not deviate):**

1. **HERO** — the scroll-stopper. A single striking photorealistic scene relevant to the story topic, with the headline overlaid at the bottom, brand mark at top, and `SWIPE FOR MORE →` cue. This is the ONE slide with a photographic image.
2. **STAT** — the most concrete factual claim of the story, rendered as a giant number/phrase (e.g. `$2.2B`, `600 Wh/kg`, `30%`) with a one-sentence subhead explaining it. Dark brand background.
3. **CONTEXT** — a second stat or a specific comparison that adds a wrinkle (`unlike most Chinese AI investments…`, `while European timelines lag…`). Same layout as slide 2.
4. **IMPLICATION** — the takeaway. What should the reader *do* with this? Format the same way but the "big text" is a phrase, not a number (e.g. `SHELVES STOCKED`, `MANUFACTURING SHIFT`, `CAPITAL TWEAK`).
5. **CTA** — read-more + follow. `Read the full analysis`, source link URL text, and `Follow {social_handle} for daily signals`.

**Voice rules (apply to every slide):**
- Follow every entry in `voice.do`.
- Do NOT use words or framings from `voice.dont`.
- Tone descriptors: {tone}.
- Numbers, names, and specifics only. No fluff. No "in today's fast-moving world".

**Image-prompt rules (image_prompt field on every slide):**
- Every prompt begins with: `Instagram-story-format 4:5 slide in the visual style of the attached reference image.`
- Every prompt then names your palette explicitly: `Background color: {background_color}. Accent color: {accent_color}. Text color: {text_color}. Typography: {typography_feel}.`
- For HERO: describe the photorealistic scene in one sentence (subject, lighting, composition). Then say: `Overlay the exact headline at the bottom in bold, high-contrast type: "{headline_text}". Top-left corner: brand mark {social_handle}. Bottom-left: `SWIPE FOR MORE →` in small caps. Do not include any text other than what I quoted.`
- For STAT/CONTEXT/IMPLICATION: `No photograph, no illustration. Solid {background_color} background. Center: giant bold text "{big_text}" in {accent_color}. Below it: subhead "{sub_text}" in {text_color}, smaller. Top-left small: {social_handle} · {page_indicator}. Bottom-right small: read-more cue if applicable. Do not include any text other than what I quoted.`
- For CTA: `Solid {background_color} background. Center: "Read the full analysis" in {text_color}. Below: source URL "{source_url}" in {accent_color}. Below: "Follow {social_handle} for daily signals" in {text_color}. Do not include any text other than what I quoted.`

**Company profile (compact):**
```json
{profile}
```

**Brand:**
```json
{brand}
```

**Approved story:**
```json
{story}
```

Return JSON matching the CarouselPlan schema. Include the fully-composed image_prompt for every slide — do not leave placeholders.
