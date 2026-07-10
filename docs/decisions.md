# Decisions log

Trade-offs that are not obvious from reading the code. Each entry states the decision, the alternatives considered, the reason we chose what we chose, and what to watch for.

## 1. LangGraph over `create_agent` / plain LangChain

- **Decision.** All orchestration is LangGraph.
- **Alternatives.** LangChain's `create_agent`, LlamaIndex agents, plain function calls.
- **Reason.** Confidence-based routing (feature/uncertain/discard) + meta-HITL rule confirmation both need explicit conditional edges and interrupt points. `create_agent` is a black box; that's the wrong shape here.
- **Watch.** LangGraph state grows if we start dumping large fields into it. Keep `crawled_pages.text` clipped to ~4k chars per page.

## 2. Website ingestion for onboarding (not "fill in a form")

- **Decision.** The onboarding tab asks for one thing: a URL.
- **Alternatives.** A 20-question form; a Google Doc dump; a Notion import.
- **Reason.** The "wow" moment is *the agent understood us in 30 seconds*. That only works if we're actually reading the site, not asking the user to describe themselves. Also compliant (public marketing copy, not scraped social).
- **Watch.** Thin sites (< 800 chars extracted) → the `thin_content` flag fires and we surface an "add an About paragraph" affordance. Without that, the extraction confabulates.

## 3. Deterministic scoring, LLM only for judgement (Evaluate node)

- **Decision.** Score math is plain arithmetic. The LLM only writes a rationale, and only for items that survive to feature/uncertain.
- **Alternatives.** Ask the LLM to output a score directly; or embeddings-only.
- **Reason.** Deterministic scoring is inspectable, testable, and cheap. Discards get a canned reason string — the user rarely reads discards, so we don't need an LLM per skip.
- **Watch.** The relevance component is bag-of-words. When we outgrow it, embeddings live behind the same `_relevance` function — nothing else changes.

## 4. Learning adjusts ranking, not sourcing

- **Decision.** A confirmed rule re-weights Evaluate's `pref_boost`. It never removes sources or narrows the search.
- **Alternatives.** Auto-unfollow low-performing sources; auto-blacklist recurring topics from Ideate.
- **Reason.** The agent's job includes surprising the user. If we let learning narrow sourcing, we get a monotonically narrower feed. This is a content-rut problem for real newsletters.
- **Watch.** Under-performing sources are *flagged* in the Sources tab (an "unfollow?" prompt), never removed. Same accumulate-then-confirm discipline as rules.

## 5. Accumulate-then-confirm learning

- **Decision.** No feedback row changes the preference profile. Only stable patterns (≥ N of last M shares one reason) surface a *proposed* rule the user confirms.
- **Alternatives.** Direct rule creation on any reject; regression from a training set of feedback.
- **Reason.** Single rejects are noisy. Auto-rules from single rejects overfit fast and become the user's problem to unwind. Also: the meta-HITL confirm-step makes the learning inspectable in the Profile · Learning tab.
- **Watch.** Demo cycles are short. `LEARNING_MIN_SAMPLES=3` and `LEARNING_WINDOW=6` are the demo values; production would use higher numbers. Also: `already-said` reasons never propose a rule — dedup already handles it.

## 6. Buffer for social publishing

- **Decision.** Instagram + LinkedIn go through Buffer, not the native APIs.
- **Alternatives.** Meta Graph API for IG, LinkedIn API directly, plus a third for X/Threads/FB later.
- **Reason.** IG + LinkedIn native APIs each require app approval (weeks); Buffer wraps both under one Bearer token. `saveToDraft:true` is a second HITL gate on top of our in-app approval.
- **Watch.** Buffer's third-party OAuth is closed → per-account API keys. Fine for single-user sprint; the multi-client story is roadmap.

## 7. One approved set → many formats

- **Decision.** Write emits newsletter + IG + LinkedIn from one approved-set call.
- **Alternatives.** One graph run per channel; one prompt per channel.
- **Reason.** The same thesis must carry across channels — otherwise the newsletter and the LinkedIn post feel like different companies. One profile passed in, one thesis, three shapes.
- **Watch.** Adding X/Threads/FB later is a schema addition, not a rewrite.

## 8. `content_mix` — one number, not two modes

- **Decision.** The two content mixes (owned-heavy producer, external-heavy startup) are a single float in [0, 1], set by the profile and user-adjustable.
- **Alternatives.** Two separate Ideate modes; two separate graphs.
- **Reason.** The difference *is* a data value. Coding it as a mode was a hidden fork — twice the surface, twice the bugs, half the users covered.
- **Watch.** The mix slider is on the Sources tab. It re-derives owned vs. external per cycle. `content_mix=0.5` doesn't mean a coin flip — it means the mix is exactly balanced across N candidates.

## 9. Sources are user-owned, agent-proposed

- **Decision.** The agent may discover, propose, and flag underperformers. It never silently follows or unfollows.
- **Alternatives.** Auto-follow discovered sources; auto-unfollow low-hit-rate ones.
- **Reason.** Making the agent's *reading* inspectable is as important as making its *taste* inspectable. Same discipline as the learning loop.
- **Watch.** The Sources tab has three sections: Followed, Proposed, and (implicitly) flagged. Users promote/dismiss proposals; the agent never grants itself an accept.

## 10. Neon Postgres, not SQLite

- **Decision.** All state (including LangGraph's `PostgresSaver`) lives in a Neon project.
- **Alternatives.** SQLite + `SqliteSaver` (as the PRD originally spec'd).
- **Reason.** Neon gives us branches (a `test` branch isolates pytest from production data), zero-setup remote persistence, and a cleaner path to any multi-tenant future.
- **Watch.** `PostgresSaver.setup()` runs once (creates checkpoint tables). Subsequent boots are fast. The test branch stays truncated between runs via `clean_db` fixture in [`tests/conftest.py`](../tests/conftest.py).

## 11. LangSmith over Langfuse for observability

- **Decision.** LangSmith, primary.
- **Alternatives.** Langfuse (originally in the spec), or roll our own.
- **Reason.** LangSmith is LangChain's own tool → **zero-config with LangGraph**: set two env vars and every node run auto-traces with per-node latency + cost. Langfuse for LangGraph requires callback wiring. Same course-credit either way; LangSmith is less code.
- **Watch.** Tracing is non-blocking — a 403 on ingest doesn't kill the run. The `config.py` env-alias handles both `LANGSMITH_*` and `LANGCHAIN_*` prefixes so SDK-version drift never bites.

## 12. Preview publish mode for demo, real mode when ready

- **Decision.** `PUBLISH_MODE=preview` by default. `real` requires an explicit env change.
- **Alternatives.** Always real; behind a UI toggle.
- **Reason.** A course capstone that accidentally hits a Resend Audience list is a career-limiting move. Preview is honest about what's happening (returns mocked responses) without pretending it sent. Real mode is one env-var flip.
- **Watch.** Even in `real` mode: Resend sends only to `RESEND_TEST_TO`; Buffer creates drafts, not scheduled posts. Two safety nets, both by design.

## 13. Streamlit was the fallback; Next.js won

- **Decision.** Next.js 16 App Router + Tailwind, kept small.
- **Alternatives.** Streamlit for speed.
- **Reason.** The user explicitly picked Next.js. The 7-tab layout with a persistent chat rail is much cleaner in Next.js. Trade-off: more boilerplate; more debug surface. Mitigated by keeping every page under 400 lines and every API call going through one `src/lib/api.ts`.
- **Watch.** No SSR fetches — every page is `"use client"` and uses `fetch` against the FastAPI backend. Faster to reason about; no server-rendered secrets risk.

## 14. Lightweight orchestrator (a router, not a planner)

- **Decision.** The chat rail routes to one of 10 fixed actions or falls back to `chat`.
- **Alternatives.** An open-ended tool-planning agent that could compose multi-step actions.
- **Reason.** Predictable behaviour is a feature for a course submission that must be demoable in 5 minutes. Also: everything the router does maps 1:1 to an API endpoint, which makes it testable.
- **Watch.** If the action set grows, add prompt examples per action rather than expanding the schema.

## 15. Documentation is a first-class deliverable

- **Decision.** Every module has docstrings. Every prompt lives in `docs/prompts/` with a version tag. Every eval run writes to `docs/eval-runs/`. `docs/` folder has architecture + methodology + decisions + api-reference.
- **Alternatives.** README-only; docstrings-only.
- **Reason.** Course rubric weighs documentation. Also: this project has enough moving parts that a fresh reader needs multiple entry points.
- **Watch.** Don't let `docs/` rot. Update `decisions.md` when a trade-off changes; add an eval-run whenever the golden set or thresholds move.
