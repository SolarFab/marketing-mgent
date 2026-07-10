"""Voice-match and quality eval for generated drafts.

Two complementary approaches:

* **Custom LLM-judge rubric** (:func:`voice_match_score`) — a small,
  targeted judge that scores draft text against ``voice.do`` /
  ``voice.dont`` explicitly. Transparent and cheap.
* **DeepEval** (:func:`deepeval_faithfulness_score`) — an off-the-shelf
  faithfulness metric applied to external-item drafts (does the drafted
  angle stay grounded in the source article?).

RAGAS is covered in :mod:`rag_faithfulness` because its dependencies
sometimes conflict with older Python; kept isolated so the rest of eval
still runs if RAGAS import blows up.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from ..llm import make_llm

log = logging.getLogger(__name__)


class RubricScore(BaseModel):
    """LLM-judge structured verdict for one draft."""
    voice_match: float = Field(..., ge=0.0, le=1.0, description="How well the draft matches the extracted voice.")
    voice_dont_violations: list[str] = Field(default_factory=list, description="Any voice.dont items the draft violates.")
    relevance: float = Field(..., ge=0.0, le=1.0, description="Relevance to the ICP.")
    quality: float = Field(..., ge=0.0, le=1.0, description="General writing quality.")
    rationale: str = Field(..., description="Two-sentence rationale.")


@dataclass
class QualityReport:
    voice_match: float
    dont_violations: int
    relevance: float
    quality: float
    per_draft: list[dict[str, Any]]


_JUDGE_PROMPT = """You are a strict brand-quality judge. Given a company's brand voice profile and a draft (newsletter, IG caption, or LinkedIn post), score how well the draft respects the voice, ICP, and general writing standards.

**Rules:**
1. `voice_match` scores 0-1 on how well the draft's tone matches the extracted voice.
2. `voice_dont_violations` lists any items from `voice.dont` the draft actually violates (empty list is fine).
3. `relevance` scores 0-1 on how well the draft speaks to the ICP.
4. `quality` scores 0-1 on writing quality (no filler, no vague claims).
5. `rationale` — two sentences.

Do not inflate scores. Be strict.

**Voice profile:**
```json
{voice}
```

**Market:**
```json
{market}
```

**Draft:**
```
{draft}
```

Return JSON.
"""


def voice_match_score(*, draft_text: str, profile: dict) -> RubricScore:
    """One rubric-based judge call on a single draft snippet."""
    voice = profile.get("voice") or {}
    market = profile.get("market") or {}
    prompt = _JUDGE_PROMPT.format(
        voice=json.dumps(voice, ensure_ascii=False),
        market=json.dumps(market, ensure_ascii=False),
        draft=draft_text[:3000],
    )
    llm = make_llm(temperature=0.0)
    return llm.with_structured_output(RubricScore).invoke(prompt)


def evaluate_drafts(drafts: dict, profile: dict) -> QualityReport:
    """Judge each channel's draft and roll up a QualityReport."""
    per: list[dict[str, Any]] = []

    def _add(channel: str, text: str) -> None:
        if not text:
            return
        try:
            score = voice_match_score(draft_text=text, profile=profile)
        except Exception as e:
            log.warning("evaluate_drafts: judge failed on %s: %s", channel, e)
            return
        per.append({
            "channel": channel,
            "voice_match": score.voice_match,
            "voice_dont_violations": score.voice_dont_violations,
            "relevance": score.relevance,
            "quality": score.quality,
            "rationale": score.rationale,
        })

    nl = drafts.get("newsletter") or {}
    if nl:
        # concatenate a snippet from the newsletter
        parts = [nl.get("subject"), nl.get("intro")]
        for s in (nl.get("sections") or [])[:3]:
            parts.append(s.get("body_markdown"))
        _add("newsletter", "\n\n".join(p for p in parts if p))

    ig = drafts.get("instagram") or {}
    if ig:
        _add("instagram", ig.get("caption") or "")

    li = drafts.get("linkedin") or {}
    if li:
        _add("linkedin", li.get("post") or "")

    if not per:
        return QualityReport(0.0, 0, 0.0, 0.0, [])

    return QualityReport(
        voice_match=sum(p["voice_match"] for p in per) / len(per),
        dont_violations=sum(len(p["voice_dont_violations"]) for p in per),
        relevance=sum(p["relevance"] for p in per) / len(per),
        quality=sum(p["quality"] for p in per) / len(per),
        per_draft=per,
    )


# ---------- DeepEval bridge ----------

def deepeval_faithfulness_score(*, draft_text: str, source_text: str) -> float | None:
    """Run DeepEval's FaithfulnessMetric on a draft vs. its source article.

    Returns a score in [0, 1] or None if DeepEval isn't installed / fails.
    Used on external-branch drafts to catch fabrication.
    """
    try:
        from deepeval.metrics import FaithfulnessMetric  # type: ignore
        from deepeval.test_case import LLMTestCase  # type: ignore
    except Exception as e:
        log.info("deepeval not available: %s", e)
        return None

    try:
        tc = LLMTestCase(
            input="Summarize this article for the target audience.",
            actual_output=draft_text[:2000],
            retrieval_context=[source_text[:3000]],
        )
        metric = FaithfulnessMetric(threshold=0.7)
        metric.measure(tc)
        return float(metric.score)
    except Exception as e:
        log.warning("deepeval faithfulness failed: %s", e)
        return None
