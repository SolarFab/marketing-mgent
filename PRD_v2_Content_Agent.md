# PRD v2 — "Signal" · a self-marketing agent for content-constrained businesses

### Build spec — hand this to Claude Code (VS Code) and build against it top to bottom.

**Author:** Fabian Kratz (Atomity)
**Course context:** Turing College — AI Engineering, Sprint 3 Capstone ("Building with AI Agents")
**One-line pitch:** A business gives the agent its website URL; the agent learns what they sell, who they sell to, and how they talk — then sources content, drafts a newsletter + Instagram + LinkedIn posts in their voice, and gets sharper every week from their approve/reject feedback.
**Who it's for:** any business where content-creation capacity is the bottleneck — not a size category. A startup with no marketing hire, a scale-up whose one marketer is drowning, a solo producer who'd rather be in the vineyard. The constraint is the same: nobody has time to source, judge, write, and distribute content every week.

---

## 1. Problem & users

### 1.1 Problem
Businesses need a consistent marketing presence (newsletter + social) to sell, but **content-creation capacity is the bottleneck**. The weekly work — deciding what to say, sourcing what's worth saying, writing it well in a consistent brand voice, adapting it per channel — needs a skilled person with time. Where that person doesn't exist, or is stretched across ten other jobs, content becomes inconsistent, off-brand, or simply doesn't happen.

### 1.2 Target users
Segmented by **content capacity, not company size**:
- **Startups / scale-ups with no (or one overloaded) marketer** — need thought-leadership and industry commentary to build credibility, but engineering and sales eat the week.
- **Small producers and owner-operated businesses** — have a great product and a story, no marketing skill or time (wine farmer as one design archetype).
- **Secondary:** agencies / consultants (incl. Atomity) running this for a handful of such clients.

### 1.3 Two content mixes — the agent must handle both
This is a design constraint, not a nice-to-have. The right content mix depends on the business, and the onboarding profile determines it:

| | **Owned-heavy** (producer, local brand) | **External-heavy** (startup, B2B, consultancy) |
|---|---|---|
| What they post | product releases, seasonality, behind-the-scenes, events, craft | industry news commentary, trends, market takes, thought leadership |
| Where content comes from | the company's own products, calendar, story | followed sources — outlets, blogs, feeds — filtered and interpreted |
| Sourcing emphasis | idea generation from the profile | monitoring + curation of followed sources |

The Ideate node generates **both** kinds and weights them by a `content_mix` ratio derived from the profile (and user-adjustable). A wine farmer skews owned; a logistics startup skews external. Neither mode is bolted on.

### 1.4 Why this app solves it
Three moves make it work:
1. **Zero-effort onboarding.** The agent reads the company's own website and builds a rich profile — products, market, positioning, brand voice, and the right content mix — so the user doesn't fill in a long form. The "it understood my business in 30 seconds" moment is the hook.
2. **Sources the user controls.** Followed websites and feeds are explicit, visible, and editable; the agent proposes new ones for approval rather than silently deciding what to read.
3. **Supervised, self-improving loop.** The agent proposes content, the user approves/rejects with a reason, and it learns their taste over time — shrinking the human's job from "do the marketing" to "glance and approve."

### 1.5 Non-goals (hold the line — this is a one-week build)
- Not a market-intelligence / competitor-monitoring platform (that's the roadmap pitch, §12).
- Not an autonomous publisher — a human approval gate before anything goes out is a **feature**.
- Not an analytics product — engagement measurement needs data access these plans don't grant (§11).
- Not multi-tenant SaaS — one company per instance for the sprint.

---

## 2. Scope

### 2.1 In scope (build this)
1. **Website-ingestion onboarding** → rich Company Profile in long-term memory (identity, market, positioning, voice, content pillars, content mix) **+ seed sources**.
2. **Source management** → a first-class, user-editable list of followed websites/feeds; the agent **proposes new sources** (discovery) for approval; per-source health and hit-rate tracked.
3. **Ideate/Source node** → proposes content items in two kinds: **owned angles** (product spotlight, seasonal, behind-the-scenes, event) and **external items** (fetched from followed sources + web search). Weighted by `content_mix`. Deduplicated against history.
4. **Evaluate node** → scores each item against the profile + learned preferences; routes feature / uncertain / discard.
5. **HITL Review** → queue UI; approve/reject with a **structured reason**; feedback persisted.
6. **Learning update** → aggregates feedback into a Preference Profile; detects stable patterns; surfaces learned rules for the user to confirm (meta-HITL). Also updates **per-source hit-rate**.
7. **Write node** → from one approved content set, generates newsletter + Instagram caption + LinkedIn post, **in the company's extracted voice**; 2–3 newsletter layouts.
8. **Publish (HITL)** → per-channel approval → Buffer (draft mode) for social; newsletter render + send.
9. **Orchestrator chat** → a control rail: natural-language commands that re-run nodes, adjust the profile/sources, or explain decisions. (Keep lightweight — see §4.6.)
10. **UI** → Next.js app (five views + chat rail).
11. **Multi-model** via OpenRouter (developer setting).
12. **Evaluation report** (§10).

### 2.2 Roadmap (NOT in the sprint — this is the client pitch)
- Founder/personal voice cloning from social history · comment-worthy-post discovery (Apify; compliance-gated) · competitor content monitoring · trend & content-gap analysis · positioning recommendations · engagement analytics · multi-client workspaces · Buffer OAuth handoff for client accounts.

---

## 3. Tech stack (locked — do not substitute)

| Layer | Choice | Notes |
|---|---|---|
| Agent framework | **LangGraph** | explicit graph; conditional edges for routing |
| Backend API | **FastAPI** | exposes the graph to the frontend |
| LLM access | **OpenRouter** (OpenAI-compatible) | multi-model; `ChatOpenAI` with `base_url` override |
| Persistence | **SQLite** | `SqliteSaver` for thread state + app tables for profile/feedback/memory |
| Web search | **Tavily API** (or equivalent) | external-signal sourcing |
| RSS | **feedparser** | optional seed feeds |
| Website ingestion | **httpx + trafilatura/BeautifulSoup** | crawl + extract clean text |
| Publishing | **Buffer GraphQL API** | `createPost` with `saveToDraft: true`; covers IG + LinkedIn |
| Newsletter send | **Resend** (or Buttondown) | transactional email; instant API key |
| Frontend | **Next.js (App Router) + TypeScript** | four views + chat rail; talks to FastAPI |
| Eval | **RAGAS or DeepEval + LLM-as-Judge** | + approval-rate trend |

> **Fallback:** if the Next.js frontend endangers the deadline, ship a Streamlit UI instead — the graded artifact is the agent, so **build backend-first** (§13). The sprint task explicitly permits Streamlit or Next.js.

---

## 4. Architecture

### 4.1 Top-level graph (LangGraph)

```
  (once per producer)                         (each content cycle)
  ┌──────────────────────┐                 ┌──────────────────────┐
  │  ONBOARDING SUBGRAPH   │  ── profile ──▶ │   IDEATE / SOURCE      │
  │  url → crawl → extract │                 │  owned angles + web    │
  │  → confirm → memory    │                 └──────────┬───────────┘
  └──────────────────────┘                            │ candidates
                                             ┌──────────▼───────────┐
                                             │      EVALUATE          │ score + route
                                             └──────────┬───────────┘
                                    feature ┌───────────┼───────────┐ discard
                                            │        uncertain       │
                                            │      ┌────▼─────┐       │
                                            └────▶ │ HITL REVIEW │ ◀───┘
                                                   └────┬─────┘
                                       approved set + feedback → LEARNING UPDATE (memory)
                                                   ┌────▼─────┐
                                                   │   WRITE    │ newsletter + IG + LinkedIn (in voice)
                                                   └────┬─────┘
                                                   ┌────▼─────┐
                                                   │ PUBLISH   │ HITL → Buffer / email
                                                   └──────────┘
   ORCHESTRATOR (supervisor) sits above: interprets chat commands, re-runs any node, edits profile/config.
```

### 4.2 Onboarding subgraph (the differentiator)

`url → crawl_node → extract_node → seed_sources_node → confirm_node → persist`

- **crawl_node:** fetch the homepage + a few key pages (about, products/shop, contact). Cap at ~5 pages. Store cleaned text.
- **extract_node (LLM):** produce the structured Company Profile (§5.1) from the crawled text — including **brand voice** (tone descriptors + characteristic vocabulary + do/don't) extracted from the site's own copy, and a proposed **`content_mix`** (owned vs. external ratio) inferred from the business type.
- **seed_sources_node:** propose an initial set of followed sources for the company's space (web search for relevant outlets/blogs; detect RSS where available). The user can also paste their own URLs here.
- **confirm_node (HITL):** show the extracted profile **and proposed sources**; user edits/confirms. Required — never act on an unconfirmed profile.
- **persist:** write to `company_profile` + `sources` (memory).

> Using the company's own public website for voice extraction is clean (public marketing copy), unlike scraping a person's social posts — this is the compliant path to voice matching.

### 4.3 Nodes (content cycle)

| Node | Does | LLM? |
|---|---|---|
| **Ideate/Source** | Two branches, weighted by `content_mix`: **(a) owned** — generate angles from products/seasonality/events/story; **(b) external** — fetch recent items from active `sources` (RSS where available, else crawl) + web search for gaps. Dedup vs. `content_history`. | Yes |
| **Source Discovery** *(runs periodically, not every cycle)* | Search for outlets/blogs covering the company's space that aren't followed yet. Emit **proposals**, never auto-follow. | Yes |
| **Evaluate** | Score each item (relevance-to-profile, novelty, fit-to-pillar, seasonality, source-hit-rate) + apply learned preference weights. Route feature / uncertain / discard. | Yes (score + rationale) |
| **HITL Review** | Present ranked queue with score + rationale + origin (owned angle or which source). Capture approve/reject + reason code (+ note). | No (human) |
| **Learning Update** | Aggregate feedback into `preference_profile`; detect stable patterns; queue rule-confirmation. Update **per-source hit-rate** (approved / surfaced). | Yes (pattern summary) |
| **Write** | From approved set → newsletter (layout-selectable) + IG caption + LinkedIn post, in extracted voice. | Yes |
| **Publish** | Per-channel HITL → Buffer `createPost(saveToDraft)` for social; render + Resend for newsletter. | No + tool calls |

> **Source hit-rate is a signal, not an axe.** A source whose items are consistently rejected gets downranked and *flagged to the user* ("you've rejected 9 of 10 items from X — unfollow?"). The agent never silently drops a source the user chose — same accumulate-then-confirm discipline as §6.

### 4.4 State schema (LangGraph)

```python
class ContentState(TypedDict):
    messages: Annotated[list, add_messages]

    company_id: str
    company_profile: dict        # loaded from memory at run start (incl. content_mix)
    preference_profile: dict     # learned weights + negative filters + confirmed rules
    sources: list[dict]          # active followed sources, loaded at run start

    candidates: list[dict]       # ideate output: {id, kind, title, angle, source_id?, url?, ts}
    scored: list[dict]           # + score, rationale, route
    approved: list[dict]         # human-approved this cycle
    feedback: list[dict]         # structured approve/reject captured this cycle
    source_proposals: list[dict] # discovered sources awaiting user approval

    drafts: dict                 # {newsletter, instagram, linkedin}
    publish: dict                # per-channel: approved?, buffer_post_id?, scheduled_for?
```

### 4.5 Memory model (SQLite DDL)

```sql
CREATE TABLE company_profile (
  company_id    TEXT PRIMARY KEY,
  identity      TEXT,   -- JSON: what they do, products[]
  market        TEXT,   -- JSON: segments, geographies, ICP
  positioning   TEXT,   -- JSON: value prop, differentiators
  voice         TEXT,   -- JSON: tone[], vocabulary[], do[], dont[]
  content_pillars TEXT, -- JSON: pillar -> product/topic
  content_mix   REAL,   -- 0.0 = all external, 1.0 = all owned; e.g. wine farm 0.8, startup 0.3
  crawled_urls  TEXT,   -- JSON: pages used for extraction
  created_at    TEXT, updated_at TEXT
);

CREATE TABLE sources (                        -- followed websites/feeds; user-owned, agent-proposed
  source_id     TEXT PRIMARY KEY,
  company_id    TEXT,
  url           TEXT NOT NULL,
  name          TEXT,
  kind          TEXT,    -- 'rss' | 'web'
  status        TEXT,    -- 'active' | 'paused' | 'proposed'
  origin        TEXT,    -- 'user' | 'onboarding' | 'discovered'
  last_checked  TEXT,
  last_ok       INTEGER, -- 1/0 health flag from last fetch
  items_surfaced INTEGER DEFAULT 0,
  items_approved INTEGER DEFAULT 0,           -- hit-rate = approved / surfaced
  created_at    TEXT
);

CREATE TABLE preference_profile (
  company_id      TEXT PRIMARY KEY,
  positive_signals TEXT,  -- JSON [{signal, weight}]
  negative_filters TEXT,  -- JSON [{reason, action}]
  confirmed_rules  TEXT,  -- JSON [rule strings] (human-confirmed)
  reason_histogram TEXT,  -- JSON {reason_code: count}
  updated_at       TEXT
);

CREATE TABLE feedback_log (          -- append-only; also the eval ground truth
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id TEXT, item_id TEXT, source_id TEXT,
  decision TEXT,        -- 'approve' | 'reject'
  reason_code TEXT, note TEXT,
  cycle_id TEXT, ts TEXT
);

CREATE TABLE content_history (       -- dedup + provenance
  item_id TEXT PRIMARY KEY,
  company_id TEXT, title TEXT,
  kind TEXT,            -- 'owned' | 'external'
  source_id TEXT, url TEXT,
  status TEXT, published_channels TEXT, ts TEXT
);
-- thread/checkpoint state is owned separately by LangGraph's SqliteSaver (threads.db)
```

### 4.6 Orchestrator (keep lightweight)
A supervisor node that maps a natural-language command to a graph action. Sprint scope = a **router over a fixed action set**, not an autonomous multi-agent planner:
- "search more on <topic>" → re-run Ideate/Source with an added focus
- "why did you reject <item>?" → return the stored rationale
- "make the newsletter shorter / warmer" → re-run Write with a modifier
- "forget the <X> rule" → edit `preference_profile.confirmed_rules`
- "follow <url>" / "unfollow <source>" / "find me more sources on <topic>" → edit `sources` / run Source Discovery
- "post more about our own products" → adjust `content_mix`
- "re-onboard from <url>" → run onboarding subgraph
Anything outside the action set → a plain helpful chat reply. Do not build open-ended tool-planning for the sprint.

---

## 5. Data shapes

### 5.1 Company Profile (target of onboarding extraction)

*Owned-heavy example (wine estate):*
```json
{
  "identity":   {"summary": "...", "products": ["Riesling 2023", "Pinot Noir", "cellar tours"]},
  "market":     {"segments": ["direct-to-consumer", "regional restaurants"], "geo": ["Rheinhessen, DE"], "icp": "..."},
  "positioning":{"value_prop": "...", "differentiators": ["organic", "5th-generation family", "steep-slope"]},
  "voice":      {"tone": ["warm", "earthy", "unpretentious"], "vocabulary": ["vintage", "terroir", "hand-picked"], "do": ["tell the family story"], "dont": ["corporate jargon", "hype"]},
  "content_pillars": {"product": "wine releases", "place": "the vineyard & seasons", "people": "family & craft", "events": "tastings & tours"},
  "content_mix": 0.8
}
```

*External-heavy example (logistics startup) — same schema, different weighting:*
```json
{
  "identity":   {"summary": "...", "products": ["warehouse routing API", "fleet analytics"]},
  "market":     {"segments": ["mid-size 3PLs", "e-commerce fulfilment"], "geo": ["DACH", "EU"], "icp": "ops lead at a 50–500 person 3PL"},
  "positioning":{"value_prop": "...", "differentiators": ["no forklift retrofit", "2-week integration"]},
  "voice":      {"tone": ["direct", "technical", "no-hype"], "vocabulary": ["pick rate", "throughput", "integration"], "do": ["show numbers"], "dont": ["buzzwords", "AI-will-change-everything takes"]},
  "content_pillars": {"industry": "warehouse automation news", "proof": "customer results", "opinion": "where the market is going"},
  "content_mix": 0.3
}
```

### 5.2 Source
```json
{"source_id":"s_004","url":"https://logisticstech.com/feed","name":"LogisticsTech","kind":"rss","status":"active","origin":"discovered","last_ok":1,"items_surfaced":24,"items_approved":9}
```

### 5.3 Content candidate
```json
{"id":"c_017","kind":"owned","title":"Harvest has started","angle":"behind-the-scenes: first Riesling grapes in","source_id":null,"url":null,"pillar":"place","ts":"..."}
{"id":"c_018","kind":"external","title":"DHL forklift pilot cuts pick times 30%","angle":"what this means for mid-size 3PLs","source_id":"s_004","url":"https://...","pillar":"industry","ts":"..."}
```

---

## 6. Self-learning design (the Hard task — build it exactly like this)

Naive feedback learning overfits to noise. Enforce four separations:

1. **Structured feedback, not free-text.** On reject the user picks a reason code: `off-brand | wrong-product | not-my-voice | too-promotional | already-said | not-relevant-now | source-not-credible | too-shallow`. (The last two mostly fire on external items and are what drive source hit-rate down.) Structured reasons are what make "why not" learnable. Free-text note is optional.
2. **Accumulate, don't react.** A single reject changes nothing. `reason_histogram` aggregates across cycles; only a **stable pattern** (e.g. ≥5 of last 8 = one reason) proposes an adjustment.
3. **Adjust ranking, not sourcing.** Learned preferences change **scoring weights in Evaluate**, never the idea-generation breadth — preserves novelty and avoids a content rut.
4. **Confirm the rule, not just the item (meta-HITL).** Before acting on a detected pattern, surface it: *"You keep rejecting price-focused posts — downrank them?"* User confirms → lands in `confirmed_rules`. The agent proposes a hypothesis; it never asserts a cause. This makes learning auditable in the Profile view.
5. **Source quality is learned the same way.** Per-source hit-rate (`items_approved / items_surfaced`) feeds the Evaluate score as one weak signal, and once a source is clearly underperforming the agent *proposes* unfollowing it in the Sources view. It never removes a user-chosen source on its own.

---

## 7. Publishing (Buffer)

- Single `createPost` GraphQL mutation per channel; endpoint `https://api.buffer.com`; Bearer token from Buffer account settings (org owner).
- Use **`saveToDraft: true`** → creates a draft, not auto-published — a second safety gate on top of in-app approval. (Modes available: `addToQueue`, `customScheduled` w/ `dueAt`, or draft.)
- Covers Instagram + LinkedIn (+ X, Threads, FB) through the same call — **no native Graph-API/LinkedIn-approval work needed**.
- Rate limit ~100 req / 15 min per client (irrelevant at 1–3 posts/day, but don't hammer in test loops).
- **Product caveat (roadmap):** Buffer third-party OAuth isn't open to new devs → connecting a *client's* Buffer means a per-client API key, not a clean OAuth handoff. Fine for single-user sprint.

---

## 8. UI (Next.js) — five views + orchestrator rail

Layout: main pane with a tab bar, plus a persistent right-hand **Orchestrator chat** rail that works across all tabs.

| View | Contents |
|---|---|
| **Review** (default) | Curation queue: each candidate card shows score, rationale, pillar, and **origin** (owned angle, or which source it came from); Approve / Reject buttons + structured reason dropdown. Where HITL + feedback capture happen. |
| **Sources** | The followed-sources table: name, URL, kind (RSS/web), status, last-checked health, **items surfaced / approved (hit-rate)**. Add a source by URL. Pause/unfollow. A **"Proposed by the agent"** section lists discovered sources with a one-line reason — Follow / Dismiss. Shows the `content_mix` slider (owned ↔ external). |
| **Newsletter** | Generated draft; 2–3 layout options (Digest / Editorial / Single-story); inline edit; Approve · send. |
| **Social** | Instagram + LinkedIn drafts from the same content set; per-channel "Approve · queue to Buffer" (draft mode). |
| **Profile · Learning** | The Company Profile (editable) **and the learned Preference Profile made visible** — "the agent has learned: X" with confirm/delete per rule. Re-onboard-from-URL button. |
| **Orchestrator** (rail) | Chat control surface (see §4.6). Steers; the tabs run the structured workflow. |

The Sources view is where the agent's *reading* is made inspectable, just as Profile · Learning is where its *taste* is. Both follow the same rule: the agent proposes, the user disposes.

Onboarding is a first-run flow: paste URL → progress while crawling → confirm the extracted profile **and the proposed seed sources** → land on Review.

State: FastAPI persists via `SqliteSaver` + memory tables, so refresh/restart resumes.

---

## 9. Project structure (for Claude Code)

```
cellar/
├─ backend/
│  ├─ app.py                 # FastAPI: endpoints below
│  ├─ graph/
│  │  ├─ state.py            # ContentState TypedDict
│  │  ├─ build.py            # assemble StateGraph, compile w/ SqliteSaver
│  │  ├─ nodes/
│  │  │  ├─ onboarding.py    # crawl, extract, seed sources, confirm
│  │  │  ├─ ideate.py        # owned angles + external fetch, weighted by content_mix
│  │  │  ├─ discovery.py     # propose new sources (never auto-follow)
│  │  │  ├─ evaluate.py      # scoring + routing (deterministic score, LLM rationale)
│  │  │  ├─ learning.py      # aggregate feedback, detect patterns, source hit-rate
│  │  │  ├─ write.py         # newsletter + IG + LinkedIn in voice
│  │  │  └─ publish.py
│  │  └─ orchestrator.py     # supervisor router over fixed actions
│  ├─ tools/
│  │  ├─ web_search.py       # Tavily
│  │  ├─ crawl.py            # httpx + trafilatura
│  │  ├─ feeds.py            # feedparser; RSS detection + fetch
│  │  ├─ buffer.py           # createPost(saveToDraft)
│  │  └─ email.py            # Resend
│  ├─ memory/
│  │  ├─ db.py               # SQLite helpers over the DDL in §4.5
│  │  └─ schema.sql
│  ├─ llm.py                 # OpenRouter ChatOpenAI factory; model selectable
│  ├─ config.py              # env, model list, settings
│  └─ eval/
│     ├─ golden_set.json     # ~20 labelled candidates
│     └─ run_eval.py         # RAGAS/DeepEval + LLM-judge + approval-rate trend
├─ frontend/                 # Next.js App Router; Review / Sources / Newsletter / Social / Profile + chat rail
├─ .env.example
└─ README.md                 # setup, usage, decisions, examples (course "Documentation" req)
```

**FastAPI endpoints (minimum):**
`POST /onboard {url}` · `GET /profile` · `PUT /profile` (incl. `content_mix`) · `GET /sources` · `POST /sources {url}` · `PATCH /sources/{id}` (pause/activate) · `DELETE /sources/{id}` · `POST /sources/discover` · `POST /sources/{id}/accept` (accept a proposal) · `POST /cycle/run` · `GET /queue` · `POST /feedback {item_id, decision, reason_code, note}` · `GET /learning` · `POST /learning/confirm {rule}` · `DELETE /learning/{rule}` · `POST /write {layout}` · `GET /drafts` · `POST /publish {channel}` · `POST /chat {message}` (orchestrator).

---

## 10. Evaluation plan (Hard task)

- **Curation quality over time:** approval-rate of the "feature" route per cycle is the ground truth (from `feedback_log`). Hypothesis: precision rises cycle 1 → N as the preference profile matures. Plot it.
- **Routing precision/recall:** `eval/golden_set.json` — ~20 candidates labelled feature/discard, covering **both owned and external items** — measures the Evaluate node.
- **Source quality:** per-source hit-rate over cycles; does the agent's source ranking converge on the sources the user actually values?
- **Voice & quality:** LLM-as-Judge on generated drafts (voice match to profile, relevance, no hype/jargon per `voice.dont`), scored against a rubric; optionally RAGAS/DeepEval.
- **Optional:** LangSmith/Langfuse tracing through the graph.

---

## 11. Constraints, risks, security

- **Buffer:** third-party OAuth closed → per-account API key (sprint fine; roadmap for clients). Analytics not in Buffer's public API → engagement measurement is roadmap.
- **Instagram/LinkedIn:** handled via Buffer, so no native API approval; direct posting/analytics stay roadmap.
- **Web crawling:** respect robots, low volume, cache pages; producer's own site only for onboarding.
- **Overfitting:** mitigated by accumulate-then-confirm learning (§6).
- **Security:** developer settings (model choice, system prompts, API keys) separated from the user surface; secrets in `.env`, never in DB; at least one input guard on the orchestrator chat (reject prompt-injection / out-of-scope commands); validate all external content before it enters a prompt.
- **Error handling:** each node try/except; source/crawl failures → skip + log; Buffer/email failures → surface to user + retry, never silent.

---

## 12. Roadmap pitch (for the client conversation, not the build)
Start: "it read your website and understood your business." Then: competitor content monitoring · seasonal/trend detection tied to your products · content-gap spotting ("nobody in your space is posting about X, and you're the one who can") · positioning recommendations · engagement analytics feeding back into curation · voice cloning from your own past posts · comment-worthy-post discovery (compliance-gated) · multi-company dashboard for agencies. The sprint is the engine; this is the story that sells it.

---

## 13. Build order (sequence for Claude Code)

1. **Scaffold + memory:** repo structure, `schema.sql` (incl. `sources`), `memory/db.py`, `config.py`, `llm.py` (OpenRouter factory, model list). Prove a model call works.
2. **Onboarding subgraph:** `crawl.py` → `onboarding.py` (crawl → extract → seed sources → confirm) → persist profile + sources. This is the differentiator; get it solid first.
3. **Sources + ideation:** `feeds.py` (RSS detect/fetch) → `ideate.py` with both branches (owned angles + external fetch, weighted by `content_mix`) → dedup vs. `content_history`.
4. **Evaluate + routing:** `evaluate.py` (deterministic score + LLM rationale + feature/uncertain/discard) → wire into `graph/build.py` with `SqliteSaver`.
5. **HITL + learning:** `feedback_log` writes; `learning.py` aggregation, rule-confirmation, per-source hit-rate.
6. **Write + publish:** `write.py` (voice-matched, 3 layouts) → `buffer.py` (draft mode) + `email.py`.
7. **Source discovery:** `discovery.py` — propose new sources with reasons; accept/dismiss flow.
8. **Orchestrator:** `orchestrator.py` router over the fixed action set (§4.6).
9. **FastAPI:** expose §9 endpoints.
10. **Frontend:** Next.js five views + chat rail (or Streamlit fallback).
11. **Eval + docs:** `run_eval.py`, golden set, README.

> After each step, the app should run end-to-end at increasing capability. If time runs short: **drop step 7 first** (discovery is the most droppable feature — the Sources tab still works with user-added sources), then fall back to Streamlit at step 10. Steps 1–6 are the graded agent core and already clear the bonus bar.

---

## 14. Course requirements (embedded) + mapping

> *Turing College Sprint 3 — "Building with AI Agents". Reproduced so the spec is self-contained.*

**Task requirements:** Agent Purpose (clear purpose, why useful, target users) · Core Functionality (main features, primary tasks, user interactions) · User Interface (user-friendly, intuitive) · Technical Implementation (appropriate tools/libraries, error handling, real-world usage) · Documentation (usage docs, examples, technical decisions).

**Optional — Easy:** ChatGPT critique · agent personality · user LLM choice · expose OpenAI settings as sliders · interactive help.
**Optional — Medium:** token usage + cost display · long/short-term memory · a function tool calling an external API · user auth & personalisation · feedback loop to improve the agent · 5 tools with UI enable/disable + plugin system · multi-model support · a security guard with dev/user settings separated.
**Optional — Hard:** Agentic RAG · LLM observability (LangSmith/Langfuse) · AI evaluation report (Ragas/DeepEval) · agent that learns from feedback and adapts · integrate external data sources to enrich knowledge.

**Evaluation criteria:** problem well-defined + app addresses it · understands how agents work, agent-type differences, function-calling, code organisation, error/edge cases · uses a front-end library, relevant knowledge base, security · reflects on problems/improvements, knows when to use prompt-engineering vs RAG vs agents.
**Bonus:** for max points, implement **≥2 medium + ≥1 hard**.

### Requirement → coverage

| Requirement | Covered by |
|---|---|
| Purpose / users | §1 |
| Core functionality + interactions | §2.1, §4, §8 |
| User-friendly UI | §8 (four views + chat) |
| Tools / libraries | §3 |
| Error handling / real-world | §11 |
| Documentation | this PRD + README |
| Agent types / function calling | §4 (supervisor + routing nodes; tools per node) |
| Knowledge base | Company Profile + followed sources + content history; website ingestion |
| Security | §11 (dev/user split, input guard, secrets) |
| Prompt vs RAG vs agents reflection | §15 + README |
| **Medium ×(≥2)** | external-API tool (Buffer) ✓ · long-term memory ✓ · multi-model ✓ · feedback loop ✓ · security guard + dev/user split ✓ |
| **Hard ×(≥1)** | learns-from-feedback ✓ · evaluation report ✓ · external-data enrichment via website ingestion ✓ |

---

## 15. Key decisions (rationale log)

1. **LangGraph over create_agent** — confidence routing (feature/uncertain/discard) + meta-HITL rule-confirmation need explicit conditional edges.
2. **Website ingestion for onboarding** — turns setup into a real agent task and is the product's "wow"; also the clean, compliant route to voice matching (public marketing copy, not scraped social).
3. **Deterministic scoring, LLM judgment** — score math/dedup out of the LLM; LLM does extraction, judgment, writing. Keeps behaviour inspectable.
4. **Learning adjusts ranking, not sourcing** — preserves novelty, prevents a content rut.
5. **Accumulate-then-confirm learning** — avoids overfitting to noise; auditable in the Profile view.
6. **Buffer for publishing** — sidesteps IG/LinkedIn API approval, makes both channels in-scope, draft mode = second HITL gate.
7. **One content set → many formats** — Write emits newsletter + IG + LinkedIn from one approved set, so adding channels later is cheap.
8. **Dual content mix (owned ↔ external), set by the profile** — a producer's content is mostly their own story; a startup's is mostly industry commentary. Building only one mode would have silently excluded half the target users. `content_mix` makes the difference a data value, not a fork in the code.
9. **Sources are user-owned, agent-proposed** — the agent may discover and recommend outlets and may flag underperformers, but it never silently follows or drops a source. Same accumulate-then-confirm discipline as the learning loop, and it makes the agent's *reading* inspectable in the UI.
10. **Backend-first, Next.js on top (Streamlit fallback)** — the graded artifact is the agent; protect it against frontend time-overrun.
11. **Lightweight orchestrator** — a router over a fixed action set, not an open-ended planner, to fit the week.
12. **Scope held to one company per instance** — market-intelligence layer and multi-tenancy are the roadmap that sells, not the sprint that ships.
