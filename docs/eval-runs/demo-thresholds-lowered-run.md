# Eval run — demo-thresholds-lowered

- **Generated:** 2026-07-08T11:58:33.942752+00:00

## 1. Golden-set routing (Evaluate node)
- Total items: **20**
- Precision (feature): **0.7142857142857143**
- Recall (feature): **0.4166666666666667**
- F1: **0.5263157894736842**
- TP/FP/FN/TN: 5 / 2 / 7 / 6

### Per-item outcomes

| id | expected | predicted | score | match |
| --- | --- | --- | --- | --- |
| g_wine_01 | feature | uncertain | 0.545 | ❌ |
| g_wine_02 | feature | uncertain | 0.475 | ❌ |
| g_wine_03 | discard | feature | 0.615 | ❌ |
| g_wine_04 | uncertain | uncertain | 0.525 | ✅ |
| g_wine_05 | discard | discard | 0.385 | ✅ |
| g_wine_06 | feature | uncertain | 0.475 | ❌ |
| g_wine_07 | feature | discard | 0.385 | ❌ |
| g_wine_08 | discard | uncertain | 0.475 | ❌ |
| g_wine_09 | feature | uncertain | 0.525 | ❌ |
| g_wine_10 | feature | feature | 0.615 | ✅ |
| g_logistics_01 | feature | feature | 0.755 | ✅ |
| g_logistics_02 | feature | feature | 0.685 | ✅ |
| g_logistics_03 | feature | uncertain | 0.545 | ❌ |
| g_logistics_04 | discard | uncertain | 0.475 | ❌ |
| g_logistics_05 | discard | uncertain | 0.475 | ❌ |
| g_logistics_06 | feature | uncertain | 0.545 | ❌ |
| g_logistics_07 | feature | feature | 0.685 | ✅ |
| g_logistics_08 | discard | uncertain | 0.545 | ❌ |
| g_logistics_09 | uncertain | feature | 0.615 | ❌ |
| g_logistics_10 | feature | feature | 0.615 | ✅ |

## 2. Draft quality (LLM-judge)
- Skipped: no company_id provided

## 3. Approval-rate trend
- Skipped: no company_id provided

---
Frameworks used: golden-set precision/recall (deterministic math on Evaluate), custom LLM-judge rubric (voice), DeepEval + RAGAS faithfulness available when drafts have source URLs, approval-rate trend (ground-truth from feedback_log).
