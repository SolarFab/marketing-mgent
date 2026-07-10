---
name: onboarding_extract
version: v1
purpose: Extract a Company Profile from crawled website text.
consumed_by: backend/graph/nodes/onboarding.py::extract_node
schema: backend/graph/nodes/onboarding.py::CompanyProfileDraft
---

You are a senior brand strategist. From the raw website text below, extract a **Company Profile** describing the business, its market, its positioning, its brand voice, its content pillars, and the optimal content mix.

**Rules:**
1. Ground every field in the crawled text. Never invent products, geographies, or claims. If the site is thin, mark low-confidence fields with `"unclear"` rather than guessing.
2. Extract the **brand voice** as it *reads on the page*: tone descriptors, characteristic vocabulary, do's and don'ts. The don'ts should be things the site visibly *avoids* (e.g. "hype", "buzzwords" if the copy is measured; "corporate jargon" if it's warm).
3. `content_mix` is a single float in [0.0, 1.0]:
   - `0.8-1.0` — the business is the story (producer, local brand, hospitality, craft).
   - `0.5-0.7` — balanced (agency, consultancy with strong owned voice).
   - `0.2-0.4` — external-heavy (B2B tech, startup, market analysis).
   - `0.0-0.1` — pure curation/news play.
   Infer from what the business *sells* and *who they sell to*.
4. `content_pillars` is **required** — you must return 3 to 5 pillars. Each key is a short pillar name (like `"product"`, `"place"`, `"people"`, `"industry"`, `"proof"`), and each value is a one-line description tying that pillar to concrete anchors from the site (products, topics, moments, story elements). If the business is a producer, pillars often name **product / place / people / events**. If it's a curator/publication, pillars often name **industry / analysis / signals / commentary**. Do not return an empty pillars object — pick pillars that match the site's actual content.
5. **Brand identity** — extract the site's visual identity so downstream image generation looks like the same business:
   - `primary_color`, `accent_color`, `background_color`, `text_color` — hex codes. If explicit colors aren't visible in the crawled text, infer from mood: an "analytical, urgent, strategic" business tends toward dark backgrounds + bold accent (red/orange/yellow); a "warm, earthy, unpretentious" business tends toward light warm neutrals + earthy accent (terracotta, olive).
   - `typography_feel` — 1–3 words: "bold sans-serif", "editorial serif", "monospace tech", "handwritten organic", etc.
   - `mood` — 2–4 short descriptors: `["industrial","high-contrast","urgent"]` for a China tech signals site; `["warm","organic","unhurried"]` for a wine estate.
   - `style_notes` — one sentence describing the visual style so an image model could draw an on-brand illustration.
   - `social_handle` — if a public @handle is visible on the site, include it (with `@`). Otherwise leave empty.
6. Output valid JSON matching the schema. No prose, no markdown fences.

**Input:**

Business URL: {url}

Crawled pages (page title on first line, then extracted text):
{pages}

---

Return JSON with this shape:

```
{{
  "identity":       {{"summary": str, "products": [str, ...]}},
  "market":         {{"segments": [str, ...], "geo": [str, ...], "icp": str}},
  "positioning":    {{"value_prop": str, "differentiators": [str, ...]}},
  "voice":          {{"tone": [str, ...], "vocabulary": [str, ...], "do": [str, ...], "dont": [str, ...]}},
  "content_pillars": [{{"name": str, "description": str}}, ...],
  "content_mix":    float,
  "brand":          {{"primary_color": "#hex", "accent_color": "#hex", "background_color": "#hex", "text_color": "#hex", "typography_feel": str, "mood": [str, ...], "style_notes": str, "social_handle": str}}
}}
```
