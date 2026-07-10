# Architecture

Signal is a single-tenant LangGraph agent with two compiled graphs and one supervisor.

## The two graphs

### 1. Onboarding subgraph (one-shot, per company)

```
url → crawl_node → extract_node → seed_sources_node → [HITL] confirm_node → persist_node
```

- **crawl_node** ([`backend/tools/crawl.py`](../backend/tools/crawl.py)) — httpx + trafilatura. Same-origin only, capped at ~6 pages, favouring high-signal paths (about, products, contact).
- **extract_node** — one LLM call with structured output (Pydantic schema in [`onboarding.py`](../backend/graph/nodes/onboarding.py)). Prompt: [`docs/prompts/onboarding_extract_v1.md`](prompts/onboarding_extract_v1.md).
- **seed_sources_node** — Tavily search on segments + geo. Fails soft (empty list is fine).
- **confirm_node** — no-op; graph interrupts *before* it (`interrupt_before=["confirm"]`). The API surfaces the interrupted state to the frontend, the user edits, then `/onboard/confirm` resumes.
- **persist_node** — writes to `company_profile` + `sources`.

### 2. Content cycle graph (per week / per run)

```
load_state → ideate → evaluate → [HITL] review → learning → write → [HITL] publish
```

- **load_state_node** — hydrates `company_profile`, `preference_profile`, `sources` from Postgres, starts a new `cycle_id`.
- **ideate_node** — two branches:
  - *Owned* — LLM angles from profile + pillars.
  - *External* — RSS pull from active sources; Tavily fallback for gaps; LLM shapes each into an angle.
  - Weighted by `content_mix`. Deduplicated against `content_history`.
- **evaluate_node** — deterministic 5-component score + LLM rationale (rationale only for non-discards to save tokens).
- **review_node** — no-op; graph interrupts here. Frontend collects approve/reject with structured reason codes; POST `/cycle/finish_review` resumes.
- **learning_node** — reason-code histogram over rolling window; new patterns become `pending_rules`; per-source hit-rate counter bumped.
- **write_node** — one LLM call for newsletter (chosen layout), one for social. Everything voice-matched from the same profile.
- **publish_node** — Buffer draft for each approved social channel; Resend for the newsletter. `PUBLISH_MODE=preview` mocks both.

Both graphs share a `PostgresSaver` checkpointer on the same Neon database — a paused graph survives across API requests.

## Supervisor: the orchestrator chat rail

Not a general-purpose planner. A **router over a fixed action set** ([`backend/graph/orchestrator.py`](../backend/graph/orchestrator.py)):

- `search_more` · `explain_reject` · `rewrite_newsletter` · `forget_rule` · `follow_source` · `unfollow_source` · `discover_sources` · `set_content_mix` · `re_onboard` · `chat`

One LLM call to classify + extract params; a dispatch table calls the right DB helper or returns an intent for the API layer.

## State schema

[`backend/graph/state.py::ContentState`](../backend/graph/state.py) — a TypedDict shared by both graphs. Only the fields relevant to the current node are populated at any time; empty defaults are fine.

## Memory model

[`backend/memory/schema.sql`](../backend/memory/schema.sql) is the source of truth:

| Table | Purpose |
| --- | --- |
| `company_profile` | The extracted identity/market/positioning/voice/pillars/mix. One row per company. |
| `sources` | Followed + proposed feeds/sites. Per-source hit-rate counters live here. |
| `preference_profile` | Learned positive signals, negative filters, `pending_rules`, `confirmed_rules`, `reason_histogram`. |
| `feedback_log` | Append-only. Every approve/reject with a structured `reason_code`. Also the eval ground truth. |
| `content_history` | Every candidate we've surfaced. Dedup + provenance. |
| `drafts` | Latest newsletter/IG/LinkedIn drafts per cycle. |
| `publish_log` | Every publish attempt — analytics reads from here. |
| `cycles` | One row per cycle. Started/finished timestamps. |

Plus LangGraph's own `checkpoints` / `checkpoint_writes` created by `PostgresSaver.setup()`.

## HITL interrupts

Both graphs are compiled with `interrupt_before=[...]`:

- Onboarding: interrupts before `confirm`.
- Content cycle: interrupts before `review` and before `publish`.

The API layer is responsible for reading the interrupted state, giving the user something to edit/approve, `graph.update_state(...)` with their input, and `graph.invoke(None, cfg)` to resume.

## LLM factory

[`backend/llm.py::make_llm`](../backend/llm.py) — a `ChatOpenAI` pointed at OpenRouter. Every node calls this rather than importing a specific model client, so swapping models is a single `.env` change.

## Observability

`LANGSMITH_TRACING=true` in `.env` and langchain-openai auto-traces every LLM call to a LangSmith project named `signal-content-agent`. No callback wiring in code. The `config.py` module aliases `LANGSMITH_*` ↔ `LANGCHAIN_*` env vars so the SDK-version drift never bites.

## What isn't here (and why)

- **Multi-tenancy** — every table has a `company_id`, but the sprint uses one. Multi-tenant workspaces are the roadmap pitch (PRD §12), not the sprint.
- **Autonomous publishing** — every send has a human approval gate, plus Buffer's draft mode as a second safety net. Explicit non-goal (PRD §1.5).
- **Analytics of engagement** — Buffer's public API doesn't expose it. Roadmap (PRD §11).
- **Voice cloning from your own social history** — clean/compliant onboarding uses your public marketing copy; social-scraping is roadmap (PRD §12).
