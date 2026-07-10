"""Shared pytest fixtures.

Key safety guarantee: this file **rewrites** ``DATABASE_URL`` to
``TEST_DATABASE_URL`` (the Neon 'test' branch) before any backend module
imports it. Tests can therefore truncate tables freely without touching
your real data.

If ``TEST_DATABASE_URL`` is missing the whole test suite is skipped —
we never fall back to the production DB.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# --- 1. Load .env from repo root ---
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# --- 2. Reroute to the Neon test branch BEFORE any backend imports ---
_test_url = os.getenv("TEST_DATABASE_URL")
if not _test_url:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Refusing to run tests against DATABASE_URL "
        "to avoid clobbering real data. Create a Neon test branch and set "
        "TEST_DATABASE_URL in .env."
    )
os.environ["DATABASE_URL"] = _test_url

# Disable LangSmith tracing noise in tests
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

# Make the repo root importable so `import backend...` works
sys.path.insert(0, str(_ROOT))


# --- 3. Fixtures ---

@pytest.fixture
def clean_db():
    """Truncate all app tables before yielding.

    Use this on any test that touches the DB. The Neon test branch is shared
    across tests in a run, so truncation is the isolation boundary.
    """
    from backend.memory.db import x  # local import: env is now correct

    tables = [
        "publish_log",
        "drafts",
        "content_history",
        "feedback_log",
        "preference_profile",
        "sources",
        "cycles",
        "company_profile",
    ]
    for t in tables:
        x(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def sample_profile() -> dict:
    """A minimal but realistic Company Profile (owned-heavy archetype)."""
    return {
        "identity": {
            "summary": "5th-generation Rheinhessen family winery.",
            "products": ["Riesling 2023", "Pinot Noir", "cellar tours"],
        },
        "market": {
            "segments": ["direct-to-consumer", "regional restaurants"],
            "geo": ["Rheinhessen, DE"],
            "icp": "wine enthusiasts and regional restaurateurs",
        },
        "positioning": {
            "value_prop": "Steep-slope, organic, hand-picked Rheinhessen wines.",
            "differentiators": ["organic", "5th-generation family", "steep-slope"],
        },
        "voice": {
            "tone": ["warm", "earthy", "unpretentious"],
            "vocabulary": ["vintage", "terroir", "hand-picked"],
            "do": ["tell the family story"],
            "dont": ["corporate jargon", "hype"],
        },
        "content_pillars": {
            "product": "wine releases",
            "place": "vineyard & seasons",
            "people": "family & craft",
            "events": "tastings & tours",
        },
        "content_mix": 0.8,
    }


@pytest.fixture
def sample_profile_external() -> dict:
    """External-heavy archetype (logistics startup)."""
    return {
        "identity": {
            "summary": "Warehouse routing API for mid-size 3PLs.",
            "products": ["warehouse routing API", "fleet analytics"],
        },
        "market": {
            "segments": ["mid-size 3PLs", "e-commerce fulfilment"],
            "geo": ["DACH", "EU"],
            "icp": "ops lead at a 50-500 person 3PL",
        },
        "positioning": {
            "value_prop": "Route your warehouse without a forklift retrofit.",
            "differentiators": ["no forklift retrofit", "2-week integration"],
        },
        "voice": {
            "tone": ["direct", "technical", "no-hype"],
            "vocabulary": ["pick rate", "throughput", "integration"],
            "do": ["show numbers"],
            "dont": ["buzzwords", "AI-will-change-everything takes"],
        },
        "content_pillars": {
            "industry": "warehouse automation news",
            "proof": "customer results",
            "opinion": "where the market is going",
        },
        "content_mix": 0.3,
    }


@pytest.fixture
def fake_llm():
    """A stand-in LLM whose ``invoke`` returns a preloaded response.

    Usage in a test::

        def test_something(fake_llm):
            fake_llm.responses = ['{"foo": "bar"}']
            # patch make_llm to return fake_llm...

    The class mirrors just enough of ``ChatOpenAI`` for our nodes to work.
    """
    class FakeLLM:
        def __init__(self) -> None:
            self.responses: list[str] = []
            self.calls: list = []

        def invoke(self, prompt, **kw):
            self.calls.append((prompt, kw))
            if not self.responses:
                return _FakeMsg("")
            return _FakeMsg(self.responses.pop(0))

        # match ChatOpenAI.with_structured_output().invoke(...) shape too
        def with_structured_output(self, schema):
            outer = self

            class _Wrapped:
                def invoke(self_inner, prompt, **kw):
                    outer.calls.append((prompt, kw))
                    import json
                    if not outer.responses:
                        return schema() if callable(schema) else {}
                    raw = outer.responses.pop(0)
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if hasattr(schema, "model_validate"):
                        return schema.model_validate(data)
                    return data

            return _Wrapped()

    class _FakeMsg:
        def __init__(self, content: str) -> None:
            self.content = content

    return FakeLLM()
