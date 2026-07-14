from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Process-wide pooler for the app tables.

    Neon suspends idle connections aggressively; ``check_connection`` runs
    a cheap ``SELECT 1`` on checkout so a dead-but-still-pooled connection
    is discarded before the caller notices.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings().database_url,
            min_size=0,
            max_size=8,
            max_idle=30.0,
            kwargs={"autocommit": True},
            check=ConnectionPool.check_connection,
        )
    return _pool


@contextmanager
def conn():
    with get_pool().connection() as c:
        yield c


def q(sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with conn() as c:
        with c.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            return list(cur.fetchall())


def q1(sql: str, params: tuple[Any, ...] = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: tuple[Any, ...] = ()) -> None:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- company profile ----------

def get_profile(company_id: str) -> dict | None:
    return q1("SELECT * FROM company_profile WHERE company_id=%s", (company_id,))


def upsert_profile(company_id: str, profile: dict, crawled_urls: list[str] | None = None) -> None:
    x(
        """
        INSERT INTO company_profile
          (company_id, identity, market, positioning, voice, content_pillars, content_mix, brand, crawled_urls, updated_at)
        VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb, now())
        ON CONFLICT (company_id) DO UPDATE SET
          identity        = EXCLUDED.identity,
          market          = EXCLUDED.market,
          positioning     = EXCLUDED.positioning,
          voice           = EXCLUDED.voice,
          content_pillars = EXCLUDED.content_pillars,
          content_mix     = EXCLUDED.content_mix,
          brand           = EXCLUDED.brand,
          crawled_urls    = COALESCE(EXCLUDED.crawled_urls, company_profile.crawled_urls),
          updated_at      = now()
        """,
        (
            company_id,
            json.dumps(profile.get("identity") or {}),
            json.dumps(profile.get("market") or {}),
            json.dumps(profile.get("positioning") or {}),
            json.dumps(profile.get("voice") or {}),
            json.dumps(profile.get("content_pillars") or {}),
            float(profile.get("content_mix", 0.5)),
            json.dumps(profile.get("brand") or {}),
            json.dumps(crawled_urls) if crawled_urls is not None else None,
        ),
    )


# ---------- sources ----------

def list_sources(company_id: str, statuses: Iterable[str] | None = None) -> list[dict]:
    if statuses:
        return q(
            "SELECT * FROM sources WHERE company_id=%s AND status = ANY(%s) ORDER BY created_at DESC",
            (company_id, list(statuses)),
        )
    return q(
        "SELECT * FROM sources WHERE company_id=%s ORDER BY created_at DESC",
        (company_id,),
    )


def add_source(
    company_id: str,
    url: str,
    *,
    name: str | None = None,
    kind: str = "web",
    status: str = "active",
    origin: str = "user",
    reason: str | None = None,
) -> dict:
    sid = new_id("s")
    x(
        """
        INSERT INTO sources (source_id, company_id, url, name, kind, status, origin, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (sid, company_id, url, name, kind, status, origin, reason),
    )
    return q1("SELECT * FROM sources WHERE source_id=%s", (sid,)) or {}


def update_source(source_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=%s" for k in fields)
    x(f"UPDATE sources SET {cols} WHERE source_id=%s", (*fields.values(), source_id))


def delete_source(source_id: str) -> None:
    x("DELETE FROM sources WHERE source_id=%s", (source_id,))


def bump_source_counters(source_id: str, *, surfaced: int = 0, approved: int = 0) -> None:
    x(
        """
        UPDATE sources
        SET items_surfaced = items_surfaced + %s,
            items_approved = items_approved + %s
        WHERE source_id=%s
        """,
        (surfaced, approved, source_id),
    )


# ---------- preference profile ----------

def get_preferences(company_id: str) -> dict:
    row = q1("SELECT * FROM preference_profile WHERE company_id=%s", (company_id,))
    if row is None:
        x(
            "INSERT INTO preference_profile (company_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (company_id,),
        )
        row = q1("SELECT * FROM preference_profile WHERE company_id=%s", (company_id,))
    return row or {}


def save_preferences(company_id: str, **fields: Any) -> None:
    """UPSERT the preference_profile row.

    Ensures a row exists (defaults from the DDL) then applies the given
    fields. Callers can pass any subset of columns.
    """
    if not fields:
        return
    # Ensure the row exists so the UPDATE isn't a no-op.
    x(
        "INSERT INTO preference_profile (company_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (company_id,),
    )
    keys = list(fields.keys())
    vals: list[Any] = []
    for k in keys:
        v = fields[k]
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    set_clause = ", ".join(
        f"{k}=%s::jsonb" if isinstance(fields[k], (dict, list)) else f"{k}=%s"
        for k in keys
    )
    x(
        f"UPDATE preference_profile SET {set_clause}, updated_at=now() WHERE company_id=%s",
        (*vals, company_id),
    )


# ---------- feedback ----------

def log_feedback(
    company_id: str,
    item_id: str,
    decision: str,
    *,
    source_id: str | None = None,
    reason_code: str | None = None,
    note: str | None = None,
    cycle_id: str | None = None,
) -> None:
    x(
        """
        INSERT INTO feedback_log (company_id, item_id, source_id, decision, reason_code, note, cycle_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (company_id, item_id, source_id, decision, reason_code, note, cycle_id),
    )


def recent_feedback(company_id: str, limit: int = 50) -> list[dict]:
    return q(
        "SELECT * FROM feedback_log WHERE company_id=%s ORDER BY ts DESC LIMIT %s",
        (company_id, limit),
    )


def approval_rate_by_cycle(company_id: str) -> list[dict]:
    return q(
        """
        SELECT cycle_id,
               COUNT(*)                                     AS total,
               SUM(CASE WHEN decision='approve' THEN 1 ELSE 0 END) AS approved,
               MIN(ts) AS started_at
        FROM feedback_log
        WHERE company_id=%s AND cycle_id IS NOT NULL
        GROUP BY cycle_id
        ORDER BY started_at ASC
        """,
        (company_id,),
    )


# ---------- content history ----------

def add_history(item: dict, company_id: str, status: str = "surfaced") -> None:
    x(
        """
        INSERT INTO content_history (item_id, company_id, title, kind, source_id, url, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (item_id) DO UPDATE SET status = EXCLUDED.status
        """,
        (
            item["id"],
            company_id,
            item.get("title"),
            item.get("kind"),
            item.get("source_id"),
            item.get("url"),
            status,
        ),
    )


def known_titles(company_id: str, limit: int = 200) -> set[str]:
    rows = q(
        "SELECT title FROM content_history WHERE company_id=%s ORDER BY ts DESC LIMIT %s",
        (company_id, limit),
    )
    return {r["title"].lower().strip() for r in rows if r.get("title")}


# ---------- cycles ----------

def start_cycle(company_id: str) -> str:
    cid = new_id("cyc")
    x("INSERT INTO cycles (cycle_id, company_id, status) VALUES (%s, %s, 'running')", (cid, company_id))
    return cid


def finish_cycle(cycle_id: str, status: str = "done") -> None:
    x(
        "UPDATE cycles SET status=%s, finished_at=now() WHERE cycle_id=%s",
        (status, cycle_id),
    )


# ---------- drafts ----------

def save_drafts(cycle_id: str, company_id: str, drafts: dict, layout: str | None = None) -> None:
    x(
        """
        INSERT INTO drafts (cycle_id, company_id, newsletter, instagram, linkedin, layout, updated_at)
        VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, now())
        ON CONFLICT (cycle_id) DO UPDATE SET
          newsletter = EXCLUDED.newsletter,
          instagram  = EXCLUDED.instagram,
          linkedin   = EXCLUDED.linkedin,
          layout     = COALESCE(EXCLUDED.layout, drafts.layout),
          updated_at = now()
        """,
        (
            cycle_id,
            company_id,
            json.dumps(drafts.get("newsletter")),
            json.dumps(drafts.get("instagram")),
            json.dumps(drafts.get("linkedin")),
            layout,
        ),
    )


def get_drafts(cycle_id: str) -> dict | None:
    return q1("SELECT * FROM drafts WHERE cycle_id=%s", (cycle_id,))


def latest_drafts(company_id: str) -> dict | None:
    return q1(
        "SELECT * FROM drafts WHERE company_id=%s ORDER BY updated_at DESC LIMIT 1",
        (company_id,),
    )


# ---------- publish log ----------

# ---------- user uploads ----------

def add_upload(
    company_id: str,
    *,
    title: str | None,
    story: str,
    pillar: str | None,
    photo_path: str,
    photo_url: str,
) -> dict:
    uid = new_id("u")
    x(
        """
        INSERT INTO user_uploads (upload_id, company_id, title, story, pillar, photo_path, photo_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (uid, company_id, title, story, pillar, photo_path, photo_url),
    )
    return q1("SELECT * FROM user_uploads WHERE upload_id=%s", (uid,)) or {}


def list_uploads(company_id: str) -> list[dict]:
    return q(
        "SELECT * FROM user_uploads WHERE company_id=%s ORDER BY created_at DESC",
        (company_id,),
    )


def get_upload(upload_id: str) -> dict | None:
    return q1("SELECT * FROM user_uploads WHERE upload_id=%s", (upload_id,))


def delete_upload(upload_id: str) -> None:
    x("DELETE FROM user_uploads WHERE upload_id=%s", (upload_id,))


def save_upload_materialized(upload_id: str, materialized: dict) -> None:
    """Persist the drafts (newsletter section / carousel plan / posts) so the
    Materialize preview survives page reloads."""
    x(
        "UPDATE user_uploads SET materialized = %s::jsonb WHERE upload_id=%s",
        (json.dumps(materialized), upload_id),
    )


def log_publish(
    company_id: str,
    channel: str,
    status: str,
    *,
    cycle_id: str | None = None,
    external_id: str | None = None,
    scheduled_for: str | None = None,
) -> None:
    x(
        """
        INSERT INTO publish_log (company_id, cycle_id, channel, status, external_id, scheduled_for)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (company_id, cycle_id, channel, status, external_id, scheduled_for),
    )
