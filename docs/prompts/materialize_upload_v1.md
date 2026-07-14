---
name: materialize_upload
version: v1
purpose: Turn a user-uploaded story + photo into channel-ready drafts (newsletter section, carousel plan slides 2-5, LinkedIn post, IG caption).
consumed_by: backend/tools/upload_materialize.py::materialize_from_upload
schema: backend/tools/upload_materialize.py::MaterializedUpload
---

You are helping a business publish a piece of first-hand material — a photo they took and a short story they wrote. Turn it into ready-to-review drafts across channels. Every draft must:

1. **Honor the user's story text as ground truth.** They saw the thing. Do not invent additional facts, quotes, statistics, or details they didn't include. Rearrange, tighten, and pivot for each channel — but no hallucination.
2. **Match the extracted brand voice.** Follow every `voice.do`; never use anything from `voice.dont`.
3. **Match the extracted brand palette + typography feel** for any image prompts.

## What to produce

### newsletter_section
- `category` — SHORT editorial slug in ALL CAPS (e.g. "FROM THE VINEYARD", "FIELD REPORT", "OUR TAKE"). Match the pillar the user picked (`{pillar}`) if any.
- `heading` — bold headline, 8-14 words. From their story.
- `body_markdown` — 3-5 sentences, in the extracted voice. The user's story rewritten, not extended with new facts.
- `highlight_term` — ONE word or 2-4 word phrase from body_markdown to render in accent color.

### carousel_slides — a list of 4 slides (NOT 5). Slide 0 is the user's actual photo, so skip it. You produce slides 1-4:
- **STAT** — a big text (from their story) + subhead
- **CONTEXT** — second big text or comparison + subhead
- **IMPLICATION** — takeaway phrase + subhead
- **CTA** — read-more + follow prompt

Each slide has `role`, `big_text`, `subhead`, `image_prompt`. Image prompts follow the same rules as the standard carousel prompt: solid background {background_color}, giant `big_text` in {accent_color}, subhead in {text_color}, {typography_feel}, {social_handle} top-left, brand-consistent, no invented text.

### linkedin_post
- 500-900 characters. Analytical framing of what the user observed. Ends with a specific question or genuine ask. First-person plural if the profile suggests a team; first-person singular if a solo producer.

### instagram_caption
- 120-220 characters, punchy opening in the first 90.
- 3-6 hashtags that fit the pillar and brand.

## Inputs

**Company profile (compact):**
```json
{profile}
```

**Brand palette (for image prompts):**
```json
{brand}
```

**Voice tone:** {tone}

**User pillar tag:** {pillar}

**User's title:** {title}

**User's story:**
```
{story}
```

Return JSON matching the MaterializedUpload schema.
