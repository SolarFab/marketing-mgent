"""Buffer GraphQL API — social publishing.

We use a single :func:`create_post` mutation per channel. All calls run
in **draft mode** (``saveToDraft: true``) so the human still confirms
before anything goes live from inside Buffer's own UI.

Config surface:

* ``BUFFER_ACCESS_TOKEN`` — Personal Key from Buffer → Settings → API.
* ``BUFFER_PROFILE_IG`` / ``BUFFER_PROFILE_LI`` — channel IDs. We accept
  either the raw ID *or* the full Buffer URL and extract the ID.

When ``PUBLISH_MODE=preview`` (the default), the API isn't called — a
mock response is returned so the frontend can render "would publish"
without needing a live account.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger(__name__)

_BUFFER_URL = "https://api.buffer.com/graphql"

_CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id } }
    ... on UnexpectedError { message }
    ... on InvalidInputError { message }
    ... on NotFoundError { message }
    ... on UnauthorizedError { message }
    ... on RestProxyError { message }
    ... on LimitReachedError { message }
  }
}
""".strip()


def extract_channel_id(value: str | None) -> str | None:
    """Accept a raw ID or a Buffer URL; return the raw channel ID."""
    if not value:
        return None
    m = re.search(r"/channels?/([a-fA-F0-9]{16,})", value)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-fA-F0-9]{16,}", value.strip()):
        return value.strip()
    return None


def create_draft_post(
    *,
    channel: str,  # 'instagram' | 'linkedin'
    text: str,
) -> dict[str, Any]:
    """Push a draft post to Buffer for the given channel.

    Returns a dict like ``{"status": "ok", "external_id": "...", "mode": "real"}``
    on success, or ``{"status": "error", "error": "...", "mode": "..."}``
    on failure. Never raises — the caller decides how to surface errors
    to the user.
    """
    s = settings()
    if s.publish_mode != "real":
        return {"status": "ok", "external_id": f"preview_{channel}", "mode": "preview"}

    token = s.buffer_token
    if not token:
        return {"status": "error", "error": "BUFFER_ACCESS_TOKEN missing", "mode": "real"}

    channel_id_raw = s.buffer_profile_ig if channel == "instagram" else s.buffer_profile_li
    channel_id = extract_channel_id(channel_id_raw)
    if not channel_id:
        return {"status": "error", "error": f"buffer channel id for {channel} missing", "mode": "real"}

    if channel == "instagram":
        return {
            "status": "error",
            "error": "Instagram drafts require an image or video asset; text-only publishing is blocked by the platform.",
            "mode": "real",
        }

    variables = {
        "input": {
            "channelId": channel_id,
            "text": text,
            "assets": [],
            "mode": "addToQueue",
            "schedulingType": "automatic",
            "saveToDraft": True,
        }
    }
    payload = {"query": _CREATE_POST_MUTATION, "variables": variables}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(_BUFFER_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("buffer.create_draft_post: HTTP failure %s", e)
        return {"status": "error", "error": str(e)[:200], "mode": "real"}

    if data.get("errors"):
        return {"status": "error", "error": str(data["errors"])[:300], "mode": "real"}

    result = (data.get("data") or {}).get("createPost") or {}
    typename = result.get("__typename", "")
    if typename == "PostActionSuccess":
        post_id = (result.get("post") or {}).get("id", "")
        return {"status": "ok", "external_id": post_id, "mode": "real"}
    if result.get("message"):
        return {"status": "error", "error": f"{typename}: {result['message']}", "mode": "real"}
    return {"status": "error", "error": f"unexpected response: {result}", "mode": "real"}
