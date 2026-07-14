# Prompt strategy A/B — onboarding extract

- **Generated:** 2026-07-13T10:27:50.332592+00:00
- **Site under test:** `https://chinatechsignals.com`
- **Model (held constant):** `anthropic/claude-haiku-4.5`
- **Judge model:** `openai/gpt-4o-mini` (independent from the generator so no self-grading)

## Summary

| Prompt | Judge avg | Pillars | Voice do+dont | Mix | Latency | In→Out tokens |
| --- | --- | --- | --- | --- | --- | --- |
| **v1 — rule-heavy zero-shot** | 4.80/5 | 4 | 8 | 0.25 | 14.4s | 2625 → 645 |
| **v2 — few-shot with worked examples** | 4.80/5 | 3 | 6 | 0.20 | 5.5s | 2694 → 445 |

## Per-variant detail

### v1 — rule-heavy zero-shot
_Detailed prescriptive rules, no worked examples. Production default._

- **Completeness:**
  - products: 3
  - segments: 4
  - geo: 2
  - differentiators: 4
  - voice_tone: 4
  - voice_vocabulary: 10
  - voice_do: 4
  - voice_dont: 4
  - pillars: 4
  - content_mix: 0.25
- **LLM-judge scores (1-5):**
  - identity_ok: 5
  - market_ok: 5
  - voice_ok: 5
  - pillars_ok: 5
  - mix_ok: 4
  - _The extraction accurately reflects the site's focus on Chinese tech developments for a European audience, with strong alignment in identity, market, voice, and content pillars, though the content mix could be slightly more reflective of the business archetype._

### v2 — few-shot with worked examples
_Two full worked-example profiles inline (wine estate + logistics startup)._

- **Completeness:**
  - products: 3
  - segments: 3
  - geo: 1
  - differentiators: 4
  - voice_tone: 3
  - voice_vocabulary: 5
  - voice_do: 3
  - voice_dont: 3
  - pillars: 3
  - content_mix: 0.20
- **LLM-judge scores (1-5):**
  - identity_ok: 5
  - market_ok: 5
  - voice_ok: 5
  - pillars_ok: 5
  - mix_ok: 4
  - _The extraction accurately reflects the site's focus on Chinese tech insights for a European audience, with strong alignment in identity, market, voice, and content pillars, though the content mix could be slightly more balanced._

## Takeaway

- 🥇 **Higher-scoring prompt:** v1 — rule-heavy zero-shot — avg 4.80/5
- Completeness deltas: pillars: v1=4 vs v2=3; voice_do: v1=4 vs v2=3; voice_dont: v1=4 vs v2=3

Prompt engineering has a real effect on structured-output quality even when the model is held constant. Few-shot with worked examples usually improves grounded-fields (pillars, voice specifics) at the cost of longer input tokens. Whether the ROI is worth the input-token cost is task-specific.
