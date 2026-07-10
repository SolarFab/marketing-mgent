"""RAGAS-based faithfulness scoring for external-item drafts.

Kept in a separate module because RAGAS pulls in its own LLM defaults
(OpenAI etc.) which can conflict with our env if not carefully set up.
The function returns None on any import or runtime failure so the eval
orchestrator can still run without it.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def ragas_faithfulness_score(*, question: str, answer: str, context: str) -> float | None:
    """Compute RAGAS faithfulness on a single (Q, A, context) triple.

    We reuse the same LLM (via LangChain wrapper) so all frameworks
    score against the same evaluator model.
    """
    try:
        from ragas import evaluate  # type: ignore
        from ragas.metrics import faithfulness  # type: ignore
        from datasets import Dataset  # type: ignore
    except Exception as e:
        log.info("ragas not available: %s", e)
        return None

    try:
        ds = Dataset.from_dict({
            "question": [question],
            "answer": [answer[:2000]],
            "contexts": [[context[:3000]]],
        })
        result = evaluate(ds, metrics=[faithfulness])
        scores: Any = result.to_pandas().iloc[0].to_dict()
        # The score column is named 'faithfulness' in current ragas
        return float(scores.get("faithfulness", 0.0))
    except Exception as e:
        log.warning("ragas evaluate failed: %s", e)
        return None
