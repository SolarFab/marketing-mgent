"""One-shot Buffer connectivity check.

Run: python -m scripts.buffer_smoketest
Reads .env, calls create_draft_post() for IG and LinkedIn, prints the result.
Creates real drafts if PUBLISH_MODE=real. Safe to delete afterwards from
Buffer's UI.
"""
from __future__ import annotations

from backend.config import settings
from backend.tools.buffer import create_draft_post

TEST_TEXT = (
    "[SMOKETEST] If you can read this in Buffer's Drafts folder, the API "
    "connection works. Safe to delete."
)


def main() -> None:
    s = settings()
    print(f"PUBLISH_MODE       = {s.publish_mode}")
    print(f"BUFFER_ACCESS_TOKEN present? {'yes' if s.buffer_token else 'NO'}")
    print(f"BUFFER_PROFILE_IG  = {s.buffer_profile_ig!r}")
    print(f"BUFFER_PROFILE_LI  = {s.buffer_profile_li!r}")
    print("-" * 60)

    for channel in ("instagram", "linkedin"):
        print(f"→ posting draft to {channel} ...")
        result = create_draft_post(channel=channel, text=TEST_TEXT)
        print(f"  result: {result}")
        print()


if __name__ == "__main__":
    main()
