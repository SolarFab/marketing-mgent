"""Prompt-strategy A/B for the onboarding extract prompt.

Runs the SAME model against the SAME crawled site with two prompt
versions and scores each with the same LLM judge. This is the "does
prompt engineering actually change the output" experiment.

Currently compares:

* **v1** — rule-heavy zero-shot (production default).
* **v2** — few-shot with two worked-example profiles (wine estate +
  logistics startup).

Same completeness metrics + judge as :mod:`backend.eval.compare_models`
so the outputs line up visually in the eval-runs folder.

Usage::

    python -m backend.eval.compare_prompts --url https://chinatechsignals.com --slug demo
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from ..graph.nodes.onboarding import CompanyProfileDraft
from ..llm import make_llm
from ..prompts import load_prompt
from ..tools.crawl import crawl_site
from .compare_models import JudgeVerdict, JUDGE_MODEL, _judge_prompt

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EVAL_RUNS = _REPO_ROOT / "docs" / "eval-runs"

# The prompt versions to compare. Each entry is (version, human_label,
# short_description_for_report).
DEFAULT_VARIANTS: list[tuple[str, str, str]] = [
    ("v1", "v1 — rule-heavy zero-shot", "Detailed prescriptive rules, no worked examples. Production default."),
    ("v2", "v2 — few-shot with worked examples", "Two full worked-example profiles inline (wine estate + logistics startup)."),
]

# Same model runs both variants so the LLM stays constant and only the
# prompt changes. Default matches production so the comparison is realistic.
FIXED_MODEL = "anthropic/claude-haiku-4.5"


@dataclass
class VariantResult:
    version: str
    label: str
    description: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    profile: dict
    completeness: dict
    judge: dict | None
    error: str | None


def run_comparison(*, url: str, slug: str, variants: list[tuple[str, str, str]] | None = None) -> dict:
    logging.basicConfig(level=logging.INFO)
    variants = variants or DEFAULT_VARIANTS

    log.info("compare_prompts: crawling %s once...", url)
    pages = crawl_site(url)
    if not pages:
        raise RuntimeError(f"crawl_site returned no pages for {url}")
    joined = "\n\n".join(f"### {p.title} — {p.url}\n{p.text[:4000]}" for p in pages)

    results: list[VariantResult] = []
    for version, label, description in variants:
        log.info("compare_prompts: running %s", label)
        results.append(_run_variant(version=version, label=label, description=description, url=url, joined=joined))

    log.info("compare_prompts: judging with %s...", JUDGE_MODEL)
    _judge_all(results, url=url)

    report = _build_report(url=url, slug=slug, results=results)
    _write_report(report=report, slug=slug)
    return report


def _run_variant(*, version: str, label: str, description: str, url: str, joined: str) -> VariantResult:
    try:
        prompt = load_prompt("onboarding_extract", version).format(url=url, pages=joined)
    except FileNotFoundError:
        return VariantResult(
            version=version, label=label, description=description,
            latency_s=0.0, input_tokens=0, output_tokens=0,
            profile={}, completeness={}, judge=None,
            error=f"prompt file for version {version} not found",
        )

    t0 = time.time()
    try:
        llm = make_llm(model=FIXED_MODEL, temperature=0.2)
        raw = llm.with_structured_output(CompanyProfileDraft).invoke(prompt)
    except Exception as e:
        return VariantResult(
            version=version, label=label, description=description,
            latency_s=time.time() - t0,
            input_tokens=len(prompt) // 4, output_tokens=0,
            profile={}, completeness={}, judge=None,
            error=str(e)[:300],
        )
    latency = time.time() - t0

    profile = raw.normalized()
    return VariantResult(
        version=version,
        label=label,
        description=description,
        latency_s=latency,
        input_tokens=len(prompt) // 4,
        output_tokens=len(json.dumps(profile)) // 4,
        profile=profile,
        completeness=_completeness_metrics(profile),
        judge=None,
        error=None,
    )


def _completeness_metrics(profile: dict) -> dict:
    identity = profile.get("identity") or {}
    market = profile.get("market") or {}
    voice = profile.get("voice") or {}
    positioning = profile.get("positioning") or {}
    pillars = profile.get("content_pillars") or {}
    return {
        "products": len(identity.get("products") or []),
        "segments": len(market.get("segments") or []),
        "geo": len(market.get("geo") or []),
        "differentiators": len(positioning.get("differentiators") or []),
        "voice_tone": len(voice.get("tone") or []),
        "voice_vocabulary": len(voice.get("vocabulary") or []),
        "voice_do": len(voice.get("do") or []),
        "voice_dont": len(voice.get("dont") or []),
        "pillars": len(pillars),
        "content_mix": float(profile.get("content_mix", 0.0)),
    }


def _judge_all(results: list[VariantResult], *, url: str) -> None:
    judge_llm = make_llm(model=JUDGE_MODEL, temperature=0.0, max_tokens=800)
    for r in results:
        if not r.profile:
            continue
        try:
            verdict: JudgeVerdict = judge_llm.with_structured_output(JudgeVerdict).invoke(_judge_prompt(r.profile, url))
            r.judge = verdict.model_dump()
        except Exception as e:
            log.warning("judge failed for %s: %s", r.label, e)


def _build_report(*, url: str, slug: str, results: list[VariantResult]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "slug": slug,
        "model": FIXED_MODEL,
        "judge_model": JUDGE_MODEL,
        "variants": [asdict(r) for r in results],
    }


def _write_report(*, report: dict, slug: str) -> None:
    _EVAL_RUNS.mkdir(parents=True, exist_ok=True)
    json_path = _EVAL_RUNS / f"{slug}-prompt-comparison.json"
    md_path = _EVAL_RUNS / f"{slug}-prompt-comparison.md"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(_render_md(report))
    log.info("wrote %s", md_path)


def _render_md(report: dict) -> str:
    r = report
    lines: list[str] = []
    lines.append("# Prompt strategy A/B — onboarding extract")
    lines.append("")
    lines.append(f"- **Generated:** {r['generated_at']}")
    lines.append(f"- **Site under test:** `{r['url']}`")
    lines.append(f"- **Model (held constant):** `{r['model']}`")
    lines.append(f"- **Judge model:** `{r['judge_model']}` (independent from the generator so no self-grading)")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Prompt | Judge avg | Pillars | Voice do+dont | Mix | Latency | In→Out tokens |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for v in r["variants"]:
        if v.get("error"):
            lines.append(f"| **{v['label']}** | ❌ {v['error']} | | | | | |")
            continue
        c = v["completeness"]
        j = v["judge"] or {}
        judge_avg = ""
        if j:
            scores = [j.get(k, 0) for k in ("identity_ok", "market_ok", "voice_ok", "pillars_ok", "mix_ok")]
            judge_avg = f"{sum(scores) / len(scores):.2f}/5"
        do_dont = c.get("voice_do", 0) + c.get("voice_dont", 0)
        lines.append(
            f"| **{v['label']}** | {judge_avg} | {c.get('pillars', 0)} | {do_dont} | {c.get('content_mix', 0.0):.2f} | {v['latency_s']:.1f}s | {v['input_tokens']} → {v['output_tokens']} |"
        )
    lines.append("")

    lines.append("## Per-variant detail")
    for v in r["variants"]:
        lines.append("")
        lines.append(f"### {v['label']}")
        lines.append(f"_{v['description']}_")
        lines.append("")
        if v.get("error"):
            lines.append(f"- ❌ Error: {v['error']}")
            continue
        c = v["completeness"]
        lines.append("- **Completeness:**")
        for k in ("products", "segments", "geo", "differentiators", "voice_tone", "voice_vocabulary", "voice_do", "voice_dont", "pillars"):
            lines.append(f"  - {k}: {c.get(k, 0)}")
        lines.append(f"  - content_mix: {c.get('content_mix', 0.0):.2f}")
        j = v.get("judge") or {}
        if j:
            lines.append("- **LLM-judge scores (1-5):**")
            for k in ("identity_ok", "market_ok", "voice_ok", "pillars_ok", "mix_ok"):
                lines.append(f"  - {k}: {j.get(k, '?')}")
            lines.append(f"  - _{j.get('rationale', '')}_")

    lines.append("")
    lines.append("## Takeaway")
    winners = [v for v in r["variants"] if not v.get("error") and v.get("judge")]
    if len(winners) >= 2:
        def avg(v):
            j = v["judge"]
            return sum(j.get(k, 0) for k in ("identity_ok", "market_ok", "voice_ok", "pillars_ok", "mix_ok")) / 5
        best = max(winners, key=avg)
        lines.append("")
        lines.append(f"- 🥇 **Higher-scoring prompt:** {best['label']} — avg {avg(best):.2f}/5")
        deltas = []
        for k in ("pillars", "voice_do", "voice_dont"):
            a = winners[0]["completeness"].get(k, 0)
            b = winners[1]["completeness"].get(k, 0)
            if a != b:
                deltas.append(f"{k}: {winners[0]['label'].split(' — ')[0]}={a} vs {winners[1]['label'].split(' — ')[0]}={b}")
        if deltas:
            lines.append("- Completeness deltas: " + "; ".join(deltas))
        lines.append("")
        lines.append(
            "Prompt engineering has a real effect on structured-output quality even when the model is held constant. "
            "Few-shot with worked examples usually improves grounded-fields (pillars, voice specifics) at the cost of "
            "longer input tokens. Whether the ROI is worth the input-token cost is task-specific."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="compare_prompts")
    p.add_argument("--url", default="https://chinatechsignals.com")
    p.add_argument("--slug", default=None)
    args = p.parse_args(argv)
    slug = args.slug or datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    report = run_comparison(url=args.url, slug=slug)
    print(f"docs/eval-runs/{slug}-prompt-comparison.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
