from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _alias_env(src: str, dst: str) -> None:
    v = os.getenv(src)
    if v and not os.getenv(dst):
        os.environ[dst] = v


# LangSmith SDK v0.1.x reads LANGCHAIN_*, v0.2.x reads LANGSMITH_*.
# Alias both directions so tracing works regardless of installed version.
_alias_env("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")
_alias_env("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT")
_alias_env("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
_alias_env("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT")
_alias_env("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
_alias_env("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT")
_alias_env("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING")
_alias_env("LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT")


class Settings:
    def __init__(self) -> None:
        self.database_url: str = _req("DATABASE_URL")

        self.openrouter_api_key: str = _req("OPENROUTER_API_KEY")
        self.openrouter_model: str = os.getenv(
            "OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5"
        )
        self.openrouter_models: list[str] = [
            m.strip()
            for m in os.getenv(
                "OPENROUTER_MODELS",
                "anthropic/claude-sonnet-4.5,anthropic/claude-haiku-4.5,openai/gpt-4o-mini,google/gemini-2.0-flash",
            ).split(",")
            if m.strip()
        ]

        self.tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")

        self.buffer_token: str | None = os.getenv("BUFFER_ACCESS_TOKEN")
        self.buffer_profile_ig: str | None = os.getenv("BUFFER_PROFILE_IG")
        self.buffer_profile_li: str | None = os.getenv("BUFFER_PROFILE_LI")

        self.resend_api_key: str | None = os.getenv("RESEND_API_KEY")
        self.resend_from: str = os.getenv("RESEND_FROM", "Signal <noreply@example.com>")
        self.resend_test_to: str | None = os.getenv("RESEND_TEST_TO")

        self.publish_mode: str = os.getenv("PUBLISH_MODE", "preview").lower()
        self.learning_min_samples: int = int(os.getenv("LEARNING_MIN_SAMPLES", "5"))
        self.learning_window: int = int(os.getenv("LEARNING_WINDOW", "8"))

        self.crawl_max_pages: int = int(os.getenv("CRAWL_MAX_PAGES", "6"))
        self.crawl_timeout_s: int = int(os.getenv("CRAWL_TIMEOUT_S", "15"))
        self.cycle_candidate_target: int = int(os.getenv("CYCLE_CANDIDATE_TARGET", "10"))
        self.company_id: str = os.getenv("COMPANY_ID", "demo")

        self.backend_host: str = os.getenv("BACKEND_HOST", "127.0.0.1")
        self.backend_port: int = int(os.getenv("BACKEND_PORT", "8000"))


def _req(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
