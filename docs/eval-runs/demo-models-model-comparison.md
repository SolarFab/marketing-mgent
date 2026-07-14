# Model comparison — onboarding extract

- **Generated:** 2026-07-13T10:18:14.910270+00:00
- **Site under test:** `https://chinatechsignals.com`
- **Judge model:** `openai/gpt-4o-mini`
- **Variants compared:** 3

## Summary

| Model | Latency | Cost (est) | Judge avg | Pillars | Voice do+dont | Mix |
| --- | --- | --- | --- | --- | --- | --- |
| **Claude Haiku 4.5** | 14.5s | $0.0059 | 4.80/5 | 5 | 9 | 0.25 |
| **Gemini 2.5 Flash** | 5.4s | $0.0008 | 4.80/5 | 5 | 8 | 0.25 |
| **GPT-4o mini** | 5.4s | $0.0006 | 4.80/5 | 4 | 6 | 0.60 |

## Per-variant detail

### Claude Haiku 4.5
- Model id: `anthropic/claude-haiku-4.5`
- Latency: 14.47s
- Estimated cost: $0.0059 (2602 in / 658 out tokens)
- **Completeness:**
  - products: 3
  - segments: 4
  - geo: 1
  - differentiators: 4
  - voice_tone: 4
  - voice_vocabulary: 10
  - voice_do: 5
  - voice_dont: 4
  - pillars: 5
  - content_mix: 0.25
- **LLM-judge scores (1-5):**
  - identity_ok: 5
  - market_ok: 5
  - voice_ok: 5
  - pillars_ok: 5
  - mix_ok: 4
  - _The extraction accurately reflects the site's focus on Chinese tech developments for a European audience, with strong alignment in identity, market, voice, and content pillars, though the content mix could be slightly more balanced._

### Gemini 2.5 Flash
- Model id: `google/gemini-2.5-flash`
- Latency: 5.40s
- Estimated cost: $0.0008 (2602 in / 635 out tokens)
- **Completeness:**
  - products: 2
  - segments: 5
  - geo: 2
  - differentiators: 3
  - voice_tone: 5
  - voice_vocabulary: 10
  - voice_do: 4
  - voice_dont: 4
  - pillars: 5
  - content_mix: 0.25
- **LLM-judge scores (1-5):**
  - identity_ok: 5
  - market_ok: 5
  - voice_ok: 5
  - pillars_ok: 5
  - mix_ok: 4
  - _The extraction accurately reflects the site's focus on Chinese tech intelligence for a European audience, with strong alignment in identity, market, voice, and content pillars, though the content mix could be slightly more aligned with a producer archetype._

### GPT-4o mini
- Model id: `openai/gpt-4o-mini`
- Latency: 5.39s
- Estimated cost: $0.0006 (2602 in / 396 out tokens)
- **Completeness:**
  - products: 3
  - segments: 3
  - geo: 2
  - differentiators: 3
  - voice_tone: 3
  - voice_vocabulary: 5
  - voice_do: 3
  - voice_dont: 3
  - pillars: 4
  - content_mix: 0.60
- **LLM-judge scores (1-5):**
  - identity_ok: 5
  - market_ok: 5
  - voice_ok: 5
  - pillars_ok: 5
  - mix_ok: 4
  - _The extraction accurately reflects the site's focus on providing insights into Chinese technology for European stakeholders, with a strong alignment in identity, market, voice, and content pillars._

## Takeaway

- 🥇 **Highest quality (LLM-judge):** Claude Haiku 4.5 — avg 4.80/5
- 💰 **Cheapest:** GPT-4o mini — $0.0006
- ⚡ **Fastest:** GPT-4o mini — 5.4s

The default model in production (Claude Haiku 4.5) was chosen based on OpenRouter privacy constraints and cost, but this table lets you make the call empirically per business.
