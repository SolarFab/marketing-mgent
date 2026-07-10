# Eval run — Onboarding extract on chinatechsignals.com

- **Date:** 2026-07-08
- **Node under test:** `backend/graph/nodes/onboarding.py::extract_node`
- **Prompt version:** `onboarding_extract@v1` (see `docs/prompts/onboarding_extract_v1.md`)
- **Model:** `anthropic/claude-haiku-4.5` via OpenRouter
- **Target site:** `https://chinatechsignals.com`
- **Pages crawled:** 6 (homepage, impressum, 4 news articles)
- **Total extracted text:** 5853 chars (`thin_content=False`)
- **Cost:** ~$0.001

## Result summary (rubric-scored by inspection)

| Field           | Verdict | Notes                                                                                            |
| --------------- | ------- | ------------------------------------------------------------------------------------------------ |
| identity        | ✅ pass  | "Daily curated intelligence on Chinese tech developments … for European audiences" — accurate    |
| market.segments | ✅ pass  | Founders, Operators, Investors, Tech strategists — matches the actual target reader              |
| market.geo      | ✅ pass  | Europe, China                                                                                    |
| positioning     | ✅ pass  | Four differentiators, all defensible from the site's own copy                                    |
| voice.tone      | ✅ pass  | analytical, urgent, strategic, matter-of-fact, competitive — matches the site's reading feel     |
| voice.dont      | ✅ pass  | "hype or sensationalism", "generic tech news", "avoid treating China as monolithic threat"       |
| content_pillars | ⚠️ v1 bug → ✅ v1.1 fix | Initial run returned `{}`; schema change to list-of-objects + Field descriptions yielded 4 pillars (funding, product_launches, strategy, sectors) |
| content_mix     | ✅ pass  | 0.25 — external-heavy, correct for a curation publication                                        |

**Overall:** the extraction understood a niche B2B intelligence publication well enough that a marketer looking at the output would say "yes, that's us."

## Bug found and fixed

**Symptom:** first run left `content_pillars` empty. The LLM (Haiku 4.5) skipped the field even though the prompt required it.

**Cause:** the field was declared as `dict[str, str]` with no `Field(description=...)`. Structured-output binding on smaller models is far more likely to skip fields without descriptions and dictionary-shaped outputs.

**Fix applied:**
1. Changed `content_pillars` to `list[ContentPillar]` (a list of objects with `name` and `description`) — smaller models handle list-of-objects far more reliably than free-form dicts.
2. Added `Field(description=...)` to every field in the schema so the JSON-schema-under-the-hood carries meaningful hints.
3. `CompanyProfileDraft.normalized()` now flattens list → `{name: description}` dict for storage.
4. Fallback logic in `_fallback_pillars` still runs if the LLM returns an empty list; user can edit in the confirm step.

**Regression coverage:** `tests/test_onboarding.py::test_extract_node_uses_structured_llm` and `::test_extract_node_fills_empty_pillars_with_fallback` — both green.

## What to test next

- Owned-heavy archetype (wine estate site) — should the same prompt yield `content_mix > 0.7`?
- Very thin site (<800 chars extracted) — does the `thin_content` flag actually surface correctly downstream?
- Multilingual site (`de`, `en`) — does the extraction stay coherent when the LLM sees two languages?

## Reproduce

```bash
python -c "
from backend.graph.nodes.onboarding import crawl_node, extract_node
state = {'onboarding_url': 'https://chinatechsignals.com'}
state.update(crawl_node(state))
state.update(extract_node(state))
import json; print(json.dumps(state['company_profile'], indent=2))
"
```
