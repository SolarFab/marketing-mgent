from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import settings

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def make_llm(
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """OpenRouter-backed ChatOpenAI. `model` overrides the default from env."""
    s = settings()
    return ChatOpenAI(
        model=model or s.openrouter_model,
        api_key=s.openrouter_api_key,
        base_url=_OPENROUTER_BASE,
        temperature=temperature,
        max_tokens=max_tokens,
        default_headers={
            # OpenRouter attribution — cosmetic only
            "HTTP-Referer": "https://signal.local",
            "X-Title": "Signal Content Agent",
        },
    )
