"""Versioned prompt registry.

Each prompt lives in its own Markdown file under ``docs/prompts/`` so it is
easy to review in diffs and cite in eval reports. The Python side loads them
by ``(name, version)`` — evals record the exact tuple used so runs are
reproducible.

Never inline a prompt string in a node module. Always ``load_prompt(...)``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPT_ROOT = Path(__file__).resolve().parent.parent.parent / "docs" / "prompts"


@lru_cache(maxsize=64)
def load_prompt(name: str, version: str = "v1") -> str:
    """Return the prompt body (everything after the ``---`` front-matter).

    Raises ``FileNotFoundError`` if the prompt file is missing — no silent
    fallbacks.
    """
    path = _PROMPT_ROOT / f"{name}_{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    raw = path.read_text(encoding="utf-8")
    # strip yaml front-matter if present
    if raw.startswith("---"):
        _, _, rest = raw.split("---", 2)
        return rest.strip()
    return raw.strip()


def prompt_version(name: str, version: str = "v1") -> str:
    """Return a stable identifier for the prompt (name@version)."""
    return f"{name}@{version}"
