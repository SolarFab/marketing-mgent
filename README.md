# Signal — a self-marketing agent for content-constrained businesses

**Course context.** Turing College — AI Engineering, Sprint 3 capstone (*Building with AI Agents*).
**Author.** Fabian Kratz (Atomity).
**PRD.** [`PRD_v2_Content_Agent.md`](PRD_v2_Content_Agent.md) is the authoritative spec.

## One-line pitch

> A business hands the agent its website URL. The agent reads the site, learns *what they sell, who they sell to, and how they talk*, then sources content, drafts newsletter + Instagram + LinkedIn posts in their voice, and gets sharper every week from their approve/reject feedback.

## What's in the box

- **7 LangGraph nodes**: Crawl → Extract → Seed sources → *(HITL)* Confirm → Persist ▸ Ideate → Evaluate → *(HITL)* Review → Learning → Write → *(HITL)* Publish.
- **Onboarding subgraph** that reads a real website (crawl + trafilatura extract + LLM structured output) and builds a Company Profile with brand voice, content mix, and pillars.
- **Two-branch Ideate** — owned angles (from the profile) + external items (RSS + Tavily), weighted by a `content_mix` value the agent inferred from the site.
- **Deterministic Evaluate** — 5-component score (relevance, novelty, pillar-fit, source-hit-rate, learned-preference-boost), routed feature/uncertain/discard, LLM-only for rationale.
- **Accumulate-then-confirm learning** — structured reject reasons aggregate over a rolling window; stable patterns become *pending rules* the user promotes to *confirmed rules*. Never silently changes anything.
- **Write once, ship many** — one Write call produces newsletter (3 layouts) + IG + LinkedIn in the same voice.
- **Publish** — Buffer (draft mode) for social; Resend for newsletter; `PUBLISH_MODE=preview` mocks everything for demo.
- **Orchestrator chat rail** — supervisor router over a fixed action set (§4.6 of the PRD).
- **Multi-framework eval** — golden-set precision/recall on Evaluate, DeepEval + RAGAS faithfulness on drafts, custom LLM-judge rubric for voice match, approval-rate trend from `feedback_log`, all rolled up into a Markdown report under [`docs/eval-runs/`](docs/eval-runs/).

## Repo layout

```
project-sprint3/
├─ backend/                  Python / FastAPI / LangGraph
│  ├─ app.py                 FastAPI endpoints (§9 of the PRD)
│  ├─ graph/                 LangGraph state + build + nodes
│  ├─ tools/                 crawl · web_search · feeds · buffer · email
│  ├─ memory/                Postgres helpers + schema.sql (Neon)
│  ├─ prompts/               versioned prompt loader
│  ├─ eval/                  golden set · multi-framework eval · report writer
│  ├─ llm.py                 OpenRouter ChatOpenAI factory
│  └─ config.py              env, model list, settings
├─ frontend/                 Next.js 16 App Router + Tailwind
│  └─ src/app/               7 tabs: Review · Sources · Newsletter · Social · Profile · Analytics · Onboard
├─ docs/
│  ├─ architecture.md        graph shape, memory model, node responsibilities
│  ├─ eval-methodology.md    what we measure and why
│  ├─ decisions.md           rationale log for the sharp trade-offs
│  ├─ api-reference.md       pointer to the auto-generated /docs OpenAPI page
│  ├─ prompts/               every LLM prompt used, versioned
│  └─ eval-runs/             one Markdown + JSON file per eval invocation
├─ tests/                    pytest — 91 tests, ~1 min end-to-end
├─ .env / .env.example       API keys + config
└─ pyproject.toml            pytest config
```

## Getting started

### Prerequisites

- Python 3.12
- Node 20+ / npm
- A Neon account (free tier is plenty)
- API keys: **OpenRouter** (LLM), **Tavily** (search), **Buffer** (social), **Resend** (email), **LangSmith** (observability — optional but recommended)

### 1. Configure the environment

Copy `.env.example` to `.env` and fill it in. The DB connection string is already pinned to the Neon project used for development; if you're bringing your own Neon, replace it.

```bash
cp .env.example .env
# then edit .env
```

Key toggles you'll care about:

- `OPENROUTER_MODEL` — the default LLM. Haiku 4.5 is cheap and fast; swap to Sonnet 4.5 if your OpenRouter privacy settings allow it.
- `PUBLISH_MODE=preview` — mocks Buffer + Resend. Flip to `real` when you're ready to actually send.
- `LEARNING_MIN_SAMPLES=3` and `LEARNING_WINDOW=6` — how many reject-reason matches trigger a proposed rule. Higher = more conservative.

### 2. Install and run the backend

```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --reload
```

The OpenAPI spec lives at [`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs).

### 3. Install and run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [`http://127.0.0.1:3000`](http://127.0.0.1:3000). First-run: go to the **Onboard** tab and paste your homepage URL.

### 4. Run the tests

```bash
pytest -q
```

The suite talks to a Neon `test` branch (isolated from your main data — see `tests/conftest.py`). ~91 tests, ~1 minute end-to-end.

### 5. Run the eval

```bash
python -m backend.eval.run_eval --slug baseline --company-id demo
```

Writes a Markdown + JSON report under `docs/eval-runs/`.

## Two content mixes, one graph

The PRD calls out a design constraint: some businesses' content is mostly their own story (a wine estate, a local brand), while others' is mostly industry commentary (a startup, a B2B tool). The Ideate node handles both, weighted by a `content_mix` float in [0, 1] the onboarding step infers from the site. This is a **data value, not a fork in the code** — same graph, different weighting.

## The learning loop, spelled out (PRD §6)

Four separations enforced in [`backend/graph/nodes/learning.py`](backend/graph/nodes/learning.py):

1. **Structured feedback, not free-text** — 8 reason codes; free-text note is stored but never drives rules.
2. **Accumulate, don't react** — one reject changes nothing. A stable pattern (≥ `LEARNING_MIN_SAMPLES` of last `LEARNING_WINDOW` rejects sharing one reason) triggers a proposed rule.
3. **Adjust ranking, not sourcing** — learned rules re-weight Evaluate's score; never touch Ideate's breadth.
4. **Confirm the rule, not just the item** — proposed rules land in `pending_rules`; the user confirms via the Profile · Learning tab; only then they hit `confirmed_rules`. The agent *proposes*, the user *disposes*.

Same discipline for sources: hit-rate is a signal, not an axe. Under-performers are flagged; the agent never silently unfollows.

## Course requirements coverage

| Requirement | Where it lives |
|---|---|
| Purpose & users | [PRD §1](PRD_v2_Content_Agent.md), README head |
| Core functionality | [`backend/graph/nodes/`](backend/graph/nodes/) + [`backend/app.py`](backend/app.py) |
| User-friendly UI | [`frontend/src/app/`](frontend/src/app/) — 7 tabs + persistent chat rail |
| Tools / libraries | [PRD §3](PRD_v2_Content_Agent.md) + [`backend/requirements.txt`](backend/requirements.txt) |
| Error handling | try/except at every node boundary; publish + graph failures surfaced to UI, never silent |
| Documentation | this README + [`docs/`](docs/) folder + every LLM prompt versioned in [`docs/prompts/`](docs/prompts/) + every eval run recorded in [`docs/eval-runs/`](docs/eval-runs/) |
| Agent types / function calling | LangGraph orchestrator supervisor + node routing + tool calls to Tavily/Buffer/Resend |
| Knowledge base | Company Profile + followed sources + content history; website ingestion is the enrichment path |
| Security | dev/user split via `PUBLISH_MODE`; secrets in `.env`; input guard on orchestrator router; test branch isolation for tests |
| Prompt vs RAG vs agents reflection | [`docs/decisions.md`](docs/decisions.md) |
| **Medium ×2+** | ✔ external-API tool (Buffer + Resend + Tavily), ✔ long-term memory (Neon), ✔ multi-model (OpenRouter), ✔ feedback loop (learning), ✔ security guard (dev/user split), ✔ token/cost visibility (LangSmith trace URLs) |
| **Hard ×1+** | ✔ learns-from-feedback ([`backend/graph/nodes/learning.py`](backend/graph/nodes/learning.py)), ✔ evaluation report (multi-framework — [`backend/eval/`](backend/eval/) + [`docs/eval-methodology.md`](docs/eval-methodology.md)), ✔ external-data enrichment (website ingestion), ✔ LLM observability (LangSmith auto-tracing) |

## Read next

- [`docs/architecture.md`](docs/architecture.md) — the graph, the state, and how HITL interrupts work.
- [`docs/eval-methodology.md`](docs/eval-methodology.md) — what each eval framework measures and why we run multiple.
- [`docs/decisions.md`](docs/decisions.md) — the trade-offs that would be easy to get wrong on a fresh read.
- [`docs/eval-runs/`](docs/eval-runs/) — the eval report history.

## License

For evaluation as coursework only. Not for redistribution.
