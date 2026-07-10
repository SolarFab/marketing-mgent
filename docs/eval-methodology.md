# Evaluation methodology

We use **five complementary evals**, each measuring a different property. They're all invoked from one orchestrator, [`backend/eval/run_eval.py`](../backend/eval/run_eval.py), which writes a timestamped Markdown + JSON report under `docs/eval-runs/`.

Why multiple frameworks? Because they're not redundant:

- Precision/recall tells you routing quality — but not whether the *drafts* the routing produces are on-brand.
- LLM-as-judge tells you brand fit — but not whether the drafts hallucinated from source articles.
- Faithfulness (DeepEval, RAGAS) catches fabrication — but doesn't tell you if the agent gets sharper over time.
- Approval-rate trend is the only ground-truth-in-the-wild — but it's noisy per cycle.

## 1. Golden-set routing precision / recall

**Measures:** the Evaluate node's routing decisions against 20 hand-labeled candidate items (10 per PRD archetype: wine estate + logistics startup). Each item has an `expected_route` in `{feature, uncertain, discard}`.

**Framework:** hand-rolled math over the deterministic score. No LLM call.

**Metric:** precision, recall, and F1 on the `feature` class.

**Source:** [`backend/eval/golden_set.json`](../backend/eval/golden_set.json).

**Why deterministic:** the Evaluate node's *routing* is math, not judgement. Testing it deterministically lets us tune thresholds against a stable ground truth. The LLM-only *rationale* is covered elsewhere.

**Reproduces:** `python -m backend.eval.run_eval` (this section runs unconditionally).

## 2. Custom LLM-judge rubric on drafts (voice match)

**Measures:** how well the generated newsletter / IG caption / LinkedIn post respects the extracted brand voice.

**Framework:** custom prompt + structured output ([`backend/eval/draft_quality.py::voice_match_score`](../backend/eval/draft_quality.py)). Judge scores four dimensions:

- `voice_match` (0–1) — tone alignment
- `voice_dont_violations` (list) — explicit hits against `voice.dont`
- `relevance` (0–1) — ICP fit
- `quality` (0–1) — general writing

**Why custom:** off-the-shelf metrics don't understand a business's `voice.dont` list. This is the eval that catches "you said no hype and the draft has hype".

**Threshold:** the judge is instructed to be strict. A `voice_match` under 0.6 is a failing draft.

## 3. DeepEval `FaithfulnessMetric` on external-branch drafts

**Measures:** did the LLM invent facts when shaping an external article into an angle?

**Framework:** DeepEval's stock `FaithfulnessMetric` ([`backend/eval/draft_quality.py::deepeval_faithfulness_score`](../backend/eval/draft_quality.py)) with the draft as `actual_output` and the source article text as `retrieval_context`.

**Why here specifically:** owned-branch drafts are grounded in the profile (which we control); external drafts are grounded in a fetched article (which we don't). This is where fabrication risk is concentrated.

**Fail-soft:** returns `None` if DeepEval isn't importable — the rest of the eval still runs.

## 4. RAGAS `faithfulness` on the same external-branch drafts

**Measures:** the same property as (3), but with a different LLM-judge implementation.

**Framework:** RAGAS's `faithfulness` metric ([`backend/eval/rag_faithfulness.py`](../backend/eval/rag_faithfulness.py)).

**Why two faithfulness scores:** they use different prompts. Where they agree, we're confident; where they disagree, that's a signal to inspect the draft by hand. Framework diversity → cheaper triage.

## 5. Approval-rate trend from `feedback_log`

**Measures:** the north star. Does the approval rate for `feature`-routed items go **up** as the preference profile matures?

**Framework:** SQL aggregation ([`backend/memory/db.py::approval_rate_by_cycle`](../backend/memory/db.py)).

**Metric:** approved / total per cycle, plotted over time.

**Why this is the ground truth:** every other eval is a proxy. This one is the user's actual behaviour. If the trend is flat or falling, the learning loop isn't working — and no rubric score can hide that.

## Report shape

Each run produces:

- `docs/eval-runs/<slug>-run.md` — human-readable
- `docs/eval-runs/<slug>-run.json` — machine-readable

The report includes:

- Golden-set precision/recall/F1 + per-item outcomes
- LLM-judge scores + rationales per draft
- Faithfulness scores (DeepEval / RAGAS) when applicable
- Approval-rate table per cycle

## Prompt reproducibility

Every prompt used by the agent is checked into [`docs/prompts/`](prompts/) with a version tag. The `backend/prompts/__init__.py` loader looks up prompts by `(name, version)` tuple — so an eval run tagged with `onboarding_extract@v1` is fully reproducible even after the prompt changes.

## What baseline vs. tuned reports show

The **baseline** eval run (`docs/eval-runs/demo-baseline-run.md`) captured an issue we found and fixed:

> Precision 1.0, Recall 0.25, F1 0.4 — the Evaluate node was routing almost everything to `uncertain`. `FEATURE_THRESHOLD` was too high given the score distribution.

After lowering the thresholds (`docs/eval-runs/demo-thresholds-lowered-run.md`):

> Precision 0.71, Recall 0.42, F1 0.53 — a real precision-recall trade-off, F1 up 33%. Uses `ev.FEATURE_THRESHOLD` and `ev.UNCERTAIN_THRESHOLD` symbolically, so the tests co-evolve with the tuning.

The lesson: **the point of the eval is that it finds regressions and miscalibrations.** Two runs in the eval-runs folder document this loop happening.
