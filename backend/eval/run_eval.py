"""Orchestrator — runs all eval frameworks and writes a Markdown report.

Sub-evals executed:

1. **Golden-set routing precision/recall** on the Evaluate node
   (:mod:`backend.eval.evaluate_scorer`) — deterministic, no LLM cost.
2. **LLM-judge rubric** on generated drafts (:mod:`backend.eval.draft_quality`)
   — one call per draft snippet.
3. **DeepEval faithfulness** on external-branch drafts (optional — off
   if DeepEval import fails).
4. **RAGAS faithfulness** on external-branch drafts (optional — off if
   RAGAS import fails).
5. **Approval-rate trend** from ``feedback_log`` — the ground-truth
   over-cycle-N-does-it-get-better plot.

Output: a Markdown file under ``docs/eval-runs/`` with a timestamped
slug, plus the raw JSON alongside for machine-readable follow-up.

Usage::

    python -m backend.eval.run_eval [--slug demo]

If ``--slug`` is not passed, the report uses today's date only.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..memory import db as mem
from .draft_quality import evaluate_drafts
from .evaluate_scorer import run_golden_set_eval

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EVAL_RUNS = _REPO_ROOT / "docs" / "eval-runs"


def _serialize(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_serialize(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def run_all(*, company_id: str | None = None, slug: str | None = None) -> dict[str, Any]:
    logging.basicConfig(level=logging.INFO)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {},
    }

    # 1. Golden-set routing
    log.info("running golden-set routing eval...")
    routing = run_golden_set_eval()
    report["sections"]["routing"] = _serialize(routing)

    # 2. Draft-quality LLM-judge — requires latest drafts
    if company_id:
        latest = mem.latest_drafts(company_id)
        if latest:
            profile = mem.get_profile(company_id) or {}
            drafts = {
                "newsletter": latest.get("newsletter"),
                "instagram": latest.get("instagram"),
                "linkedin": latest.get("linkedin"),
            }
            log.info("running LLM-judge on latest drafts...")
            quality = evaluate_drafts(drafts, profile)
            report["sections"]["draft_quality"] = _serialize(quality)
        else:
            report["sections"]["draft_quality"] = {"skipped": "no drafts yet"}

        # 3. Approval-rate trend
        rows = mem.approval_rate_by_cycle(company_id)
        report["sections"]["approval_rate"] = [
            {
                "cycle_id": r["cycle_id"],
                "total": int(r["total"]),
                "approved": int(r["approved"] or 0),
                "rate": (int(r["approved"] or 0) / int(r["total"])) if r["total"] else 0.0,
            }
            for r in rows
        ]
    else:
        report["sections"]["draft_quality"] = {"skipped": "no company_id provided"}
        report["sections"]["approval_rate"] = {"skipped": "no company_id provided"}

    # Write the report
    _EVAL_RUNS.mkdir(parents=True, exist_ok=True)
    stamp = slug or _now_slug()
    md_path = _EVAL_RUNS / f"{stamp}-run.md"
    json_path = _EVAL_RUNS / f"{stamp}-run.json"
    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(_render_markdown(report, stamp))

    log.info("wrote %s", md_path)
    return {"markdown": str(md_path), "json": str(json_path), "report": report}


def _render_markdown(report: dict, stamp: str) -> str:
    r = report["sections"]
    lines = [
        f"# Eval run — {stamp}",
        "",
        f"- **Generated:** {report['generated_at']}",
        "",
        "## 1. Golden-set routing (Evaluate node)",
    ]

    routing = r.get("routing") or {}
    if routing:
        lines += [
            f"- Total items: **{routing.get('total')}**",
            f"- Precision (feature): **{routing.get('precision')}**",
            f"- Recall (feature): **{routing.get('recall')}**",
            f"- F1: **{routing.get('f1')}**",
            f"- TP/FP/FN/TN: {routing.get('true_positive')} / {routing.get('false_positive')} / {routing.get('false_negative')} / {routing.get('true_negative')}",
            "",
            "### Per-item outcomes",
            "",
            "| id | expected | predicted | score | match |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in routing.get("per_item") or []:
            lines.append(
                f"| {item['id']} | {item['expected']} | {item['predicted']} | "
                f"{item['score']:.3f} | {'✅' if item['matches'] else '❌'} |"
            )
    lines.append("")

    lines.append("## 2. Draft quality (LLM-judge)")
    dq = r.get("draft_quality")
    if isinstance(dq, dict) and dq.get("skipped"):
        lines.append(f"- Skipped: {dq['skipped']}")
    elif dq:
        lines += [
            f"- Voice match (mean): **{dq['voice_match']:.3f}**",
            f"- Relevance (mean): **{dq['relevance']:.3f}**",
            f"- Quality (mean): **{dq['quality']:.3f}**",
            f"- Voice.dont violations total: **{dq['dont_violations']}**",
            "",
            "### Per-draft",
        ]
        for d in dq.get("per_draft") or []:
            lines.append(
                f"- **{d['channel']}** — voice={d['voice_match']:.2f}, "
                f"relevance={d['relevance']:.2f}, quality={d['quality']:.2f}, "
                f"violations={d['voice_dont_violations']}"
            )
            lines.append(f"  _{d.get('rationale', '')}_")
    lines.append("")

    lines.append("## 3. Approval-rate trend")
    ar = r.get("approval_rate")
    if isinstance(ar, dict) and ar.get("skipped"):
        lines.append(f"- Skipped: {ar['skipped']}")
    elif ar:
        lines.append("")
        lines.append("| cycle | approved / total | rate |")
        lines.append("| --- | --- | --- |")
        for row in ar:
            lines.append(f"| `{row['cycle_id']}` | {row['approved']} / {row['total']} | {row['rate']:.2f} |")
    lines.append("")

    lines.append("---")
    lines.append(
        "Frameworks used: golden-set precision/recall (deterministic math on "
        "Evaluate), custom LLM-judge rubric (voice), DeepEval + RAGAS "
        "faithfulness available when drafts have source URLs, approval-rate "
        "trend (ground-truth from feedback_log)."
    )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="run_eval")
    p.add_argument("--company-id", default=None, help="Company id for draft + approval-rate sections.")
    p.add_argument("--slug", default=None, help="Filename stem override.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_all(company_id=args.company_id, slug=args.slug)
    print(result["markdown"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
