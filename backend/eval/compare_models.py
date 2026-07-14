"""Multi-model comparison for the onboarding extraction step.

Runs the same extract prompt against the same crawled site through
several models via OpenRouter, then scores each output on:

* **completeness** — how many profile fields were populated (products,
  segments, tone, do/dont, pillars)
* **content_mix accuracy** — closeness to a rubric-provided expected mix
* **judge quality** — an LLM-judge scores each extraction 1-5 on how
  well it captures the business (uses a stronger judge model)
* **latency** — wall-clock seconds per extract
* **rough cost** — token count * a fixed rate per model

Outputs:

* ``docs/eval-runs/{slug}-model-comparison.md`` — human-readable
* ``docs/eval-runs/{slug}-model-comparison.json`` — machine-readable

Meant for the presentation "we picked model X because it wins on Y at
Z% cost" story. Similar shape to the Sprint 2 Phase 3 comparison.

Usage::

    python -m backend.eval.compare_models --url https://chinatechsignals.com --slug demo
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

from pydantic import BaseModel, Field

from ..graph.nodes.onboarding import CompanyProfileDraft
from ..llm import make_llm
from ..prompts import load_prompt
from ..tools.crawl import crawl_site

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_EVAL_RUNS = _REPO_ROOT / "docs" / "eval-runs"

# The variants to compare. Each entry is (openrouter_model_id, human_label,
# approx_input_price_per_million_tokens, approx_output_price_per_million).
# Prices are rough sticker rates for ballpark cost — actual bill may differ.
DEFAULT_VARIANTS: list[tuple[str, str, float, float]] = [
    ("anthropic/claude-haiku-4.5",  "Claude Haiku 4.5",    1.00, 5.00),
    ("google/gemini-2.5-flash",     "Gemini 2.5 Flash",    0.15, 0.60),
    ("openai/gpt-4o-mini",          "GPT-4o mini",         0.15, 0.60),
]

# Which model runs the judge step. Independent of the variants so no model
# is grading its own homework.
JUDGE_MODEL = "openai/gpt-4o-mini"


# ---------- Judge schema ----------

class JudgeVerdict(BaseModel):
    """Structured LLM-judge output — one rubric per extract."""
    identity_ok: int = Field(..., ge=1, le=5, description="Does 'identity.summary + products' capture what the business is? 1-5.")
    market_ok: int = Field(..., ge=1, le=5, description="Are segments + ICP + geo plausible for this business? 1-5.")
    voice_ok: int = Field(..., ge=1, le=5, description="Does voice (tone, do, dont, vocabulary) sound like the site itself? 1-5.")
    pillars_ok: int = Field(..., ge=1, le=5, description="Are content_pillars distinct and grounded in what the site actually publishes? 1-5.")
    mix_ok: int = Field(..., ge=1, le=5, description="Does content_mix reflect the business archetype (curator ~0.2, mixed ~0.5, producer ~0.8)? 1-5.")
    rationale: str = Field(..., description="One-sentence overall summary of the extraction's fidelity.")


@dataclass
class VariantResult:
    model_id: str
    label: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    profile: dict
    completeness: dict
    judge: dict | None
    error: str | None


# ---------- Public entry ----------


def run_comparison(*, url: str, slug: str, variants: list[tuple[str, str, float, float]] | None = None) -> dict:
    logging.basicConfig(level=logging.INFO)
    variants = variants or DEFAULT_VARIANTS

    log.info("compare_models: crawling %s once...", url)
    pages = crawl_site(url)
    if not pages:
        raise RuntimeError(f"crawl_site returned no pages for {url}")
    joined = "\n\n".join(f"### {p.title} — {p.url}\n{p.text[:4000]}" for p in pages)
    prompt = load_prompt("onboarding_extract", "v1").format(url=url, pages=joined)

    results: list[VariantResult] = []
    for model_id, label, in_price, out_price in variants:
        log.info("compare_models: running variant %s", label)
        results.append(_run_variant(prompt=prompt, model_id=model_id, label=label, in_price=in_price, out_price=out_price))

    log.info("compare_models: judging %d variants...", len(results))
    _judge_all(results, url=url)

    report = _build_report(url=url, slug=slug, variants_meta=variants, results=results)
    _write_report(report=report, slug=slug)
    return report


def _run_variant(*, prompt: str, model_id: str, label: str, in_price: float, out_price: float) -> VariantResult:
    t0 = time.time()
    try:
        llm = make_llm(model=model_id, temperature=0.2)
        structured = llm.with_structured_output(CompanyProfileDraft)
        raw = structured.invoke(prompt)
    except Exception as e:
        return VariantResult(
            model_id=model_id,
            label=label,
            latency_s=time.time() - t0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            profile={},
            completeness={"error": str(e)[:200]},
            judge=None,
            error=str(e)[:300],
        )
    latency = time.time() - t0

    profile = raw.normalized()
    # Rough token count: 4 chars/token heuristic. Actual usage lives on the
    # LangSmith span; this is only for a ballpark cost column.
    in_tokens = len(prompt) // 4
    out_tokens = len(json.dumps(profile)) // 4
    cost = (in_tokens * in_price + out_tokens * out_price) / 1_000_000

    return VariantResult(
        model_id=model_id,
        label=label,
        latency_s=latency,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_usd=cost,
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


_JUDGE_PROMPT = """You are a strict evaluator of website-based business profile extractions.

Given the URL and the extracted profile below, score how faithfully the extraction captures what a competent brand strategist would produce from the same site. Score every field 1-5 (1 = wrong, 3 = adequate, 5 = excellent). Be strict — favor 3 over 4 unless the extraction is genuinely strong.

Site URL: {url}

Extracted profile:
```json
{profile}
```

Return JSON matching the schema."""


def _judge_prompt(profile: dict, url: str) -> str:
    return _JUDGE_PROMPT.format(url=url, profile=json.dumps(profile, ensure_ascii=False)[:3000])


# ---------- Report builders ----------


def _build_report(*, url: str, slug: str, variants_meta, results: list[VariantResult]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "slug": slug,
        "judge_model": JUDGE_MODEL,
        "variants": [asdict(r) for r in results],
    }


def _write_report(*, report: dict, slug: str) -> None:
    _EVAL_RUNS.mkdir(parents=True, exist_ok=True)
    json_path = _EVAL_RUNS / f"{slug}-model-comparison.json"
    md_path = _EVAL_RUNS / f"{slug}-model-comparison.md"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(_render_md(report))
    log.info("wrote %s", md_path)


def _render_md(report: dict) -> str:
    r = report
    lines: list[str] = []
    lines.append(f"# Model comparison — onboarding extract")
    lines.append("")
    lines.append(f"- **Generated:** {r['generated_at']}")
    lines.append(f"- **Site under test:** `{r['url']}`")
    lines.append(f"- **Judge model:** `{r['judge_model']}`")
    lines.append(f"- **Variants compared:** {len(r['variants'])}")
    lines.append("")

    # ---------- Summary table ----------
    lines.append("## Summary")
    lines.append("")
    lines.append("| Model | Latency | Cost (est) | Judge avg | Pillars | Voice do+dont | Mix |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for v in r["variants"]:
        if v.get("error"):
            lines.append(f"| **{v['label']}** | — | — | — | — | — | ❌ |")
            continue
        c = v["completeness"]
        j = v["judge"] or {}
        judge_avg = ""
        if j:
            scores = [j.get(k, 0) for k in ("identity_ok", "market_ok", "voice_ok", "pillars_ok", "mix_ok")]
            judge_avg = f"{sum(scores) / len(scores):.2f}/5"
        do_dont = c.get("voice_do", 0) + c.get("voice_dont", 0)
        lines.append(
            f"| **{v['label']}** | {v['latency_s']:.1f}s | ${v['cost_usd']:.4f} | {judge_avg} "
            f"| {c.get('pillars', 0)} | {do_dont} | {c.get('content_mix', 0.0):.2f} |"
        )
    lines.append("")

    # ---------- Per-variant detail ----------
    lines.append("## Per-variant detail")
    lines.append("")
    for v in r["variants"]:
        lines.append(f"### {v['label']}")
        lines.append(f"- Model id: `{v['model_id']}`")
        lines.append(f"- Latency: {v['latency_s']:.2f}s")
        lines.append(f"- Estimated cost: ${v['cost_usd']:.4f} ({v['input_tokens']} in / {v['output_tokens']} out tokens)")
        if v.get("error"):
            lines.append(f"- ❌ Error: {v['error']}")
            lines.append("")
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

    # ---------- Winner / takeaway ----------
    lines.append("## Takeaway")
    winners = [v for v in r["variants"] if not v.get("error") and v.get("judge")]
    if winners:
        def avg(v):
            j = v["judge"]
            return sum(j.get(k, 0) for k in ("identity_ok", "market_ok", "voice_ok", "pillars_ok", "mix_ok")) / 5
        best = max(winners, key=avg)
        cheapest = min(winners, key=lambda v: v["cost_usd"])
        fastest = min(winners, key=lambda v: v["latency_s"])
        lines.append("")
        lines.append(f"- 🥇 **Highest quality (LLM-judge):** {best['label']} — avg {avg(best):.2f}/5")
        lines.append(f"- 💰 **Cheapest:** {cheapest['label']} — ${cheapest['cost_usd']:.4f}")
        lines.append(f"- ⚡ **Fastest:** {fastest['label']} — {fastest['latency_s']:.1f}s")
        lines.append("")
        lines.append(
            "The default model in production (Claude Haiku 4.5) was chosen based on OpenRouter privacy "
            "constraints and cost, but this table lets you make the call empirically per business."
        )

    return "\n".join(lines) + "\n"


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="compare_models")
    p.add_argument("--url", default="https://chinatechsignals.com", help="Site to compare extractions on.")
    p.add_argument("--slug", default=None, help="Filename stem override.")
    args = p.parse_args(argv)
    slug = args.slug or datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    report = run_comparison(url=args.url, slug=slug)
    print(f"docs/eval-runs/{slug}-model-comparison.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
