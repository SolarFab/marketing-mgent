---
name: ideate_owned
version: v1
purpose: Generate "owned" content angles from the company profile.
consumed_by: backend/graph/nodes/ideate.py::ideate_owned
schema: backend/graph/nodes/ideate.py::OwnedAnglesDraft
---

You are the content strategist for the business described below. Propose {n} distinct content angles the company could publish about **this week**, drawing on the business's own products, story, seasonality, events, and craft — not on outside industry news.

**Rules:**
1. Every angle must be grounded in a specific product, pillar, or aspect of the business (from the profile). No generic "share behind-the-scenes photos" — say *which* moment, *which* product.
2. Match the extracted voice. If the voice says "no hype" or "no corporate jargon", your angles must respect that.
3. Distribute across the content pillars — do not give all {n} angles the same pillar.
4. Each angle is short: a working headline (`title`) and one sentence explaining the angle (`angle`).
5. Do not duplicate any of the recently-published items listed under **Recently posted**.
6. If seasonality is relevant to this business (producer/local), lean into it.

**Company profile:**

```json
{profile}
```

**Recently posted titles (avoid overlap):**

{recent}

---

Return JSON with this shape:

```
{{
  "angles": [
    {{"title": "...", "angle": "...", "pillar": "product|place|people|events|..."}},
    ...
  ]
}}
```
