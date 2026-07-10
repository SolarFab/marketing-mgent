"""Golden-set eval for the Evaluate node's routing decisions.

Computes precision + recall + F1 for the ``feature`` route against the
labels in ``golden_set.json``.

We don't measure the LLM rationale here — that's covered by the
draft-quality eval (``draft_quality.py``). The scoring is deterministic
math; this test isolates that math against ground-truth labels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..graph.nodes.evaluate import _score_candidate, _route


_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set.json"


@dataclass
class EvaluationReport:
    total: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float
    recall: float
    f1: float
    per_item: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "true_negative": self.true_negative,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "per_item": self.per_item,
        }


def load_golden_set() -> dict:
    return json.loads(_GOLDEN_PATH.read_text())


def run_golden_set_eval() -> EvaluationReport:
    """Score every golden-set item against its profile and check the route.

    A model call is *not* made — Evaluate's scoring is deterministic math.
    Only Evaluate's routing (not its LLM rationale) is exercised.
    """
    gs = load_golden_set()
    profiles = gs["profiles"]

    per_item: list[dict[str, Any]] = []
    tp = fp = fn = tn = 0

    for item in gs["items"]:
        profile = profiles[item["profile"]]
        candidate = {
            "id": item["id"],
            "kind": item["kind"],
            "title": item["title"],
            "angle": item["angle"],
            "pillar": item.get("pillar", ""),
            "source_id": None,
        }
        breakdown = _score_candidate(candidate, profile=profile, prefs={}, sources={})
        predicted = _route(breakdown.final)
        expected = item["expected_route"]

        # For precision/recall, treat 'feature' as the positive class.
        # 'uncertain' is neutral for precision but counted as a miss for
        # 'feature' expectations to be strict.
        if expected == "feature" and predicted == "feature":
            tp += 1
        elif expected == "feature" and predicted != "feature":
            fn += 1
        elif expected != "feature" and predicted == "feature":
            fp += 1
        else:
            tn += 1

        per_item.append({
            "id": item["id"],
            "expected": expected,
            "predicted": predicted,
            "score": breakdown.final,
            "matches": expected == predicted,
        })

    total = len(gs["items"])
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return EvaluationReport(
        total=total,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        precision=precision,
        recall=recall,
        f1=f1,
        per_item=per_item,
    )
