"""LangGraph assembly.

Two graphs are compiled here:

* :func:`build_onboarding_graph` — crawl → extract → seed_sources →
  [interrupt] confirm → persist. Used exactly once per company at setup.
* :func:`build_content_graph` — load_state → ideate → evaluate →
  [interrupt] review → learning → write → [interrupt] publish. Run once
  per cycle.

Both graphs share a single :class:`PostgresSaver` (checkpointer) so a
paused graph can be resumed across API requests. The saver stores its
tables in the same Neon database as the app tables — no extra config.

**Thread ids**: for the content graph we use ``f"cycle:{cycle_id}"``.
For onboarding we use ``f"onboard:{company_id}"``. Every API endpoint
that resumes a graph must pass the matching thread id.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg_pool import ConnectionPool

from ..config import settings
from ..memory import db as mem
from .nodes.evaluate import evaluate_node
from .nodes.ideate import ideate_node
from .nodes.onboarding import (
    confirm_node,
    crawl_node,
    extract_node,
    persist_node,
    seed_sources_node,
)
from .state import ContentState

log = logging.getLogger(__name__)

_saver: PostgresSaver | None = None
_saver_lock = threading.Lock()

# Compiled graphs cached on first use (compilation is cheap, but re-doing
# it every request throws away the same saver-attached instance).
_onboarding_graph = None
_content_graph = None


# ---------- checkpointer ----------

def get_saver() -> PostgresSaver:
    """Return a process-wide :class:`PostgresSaver` backed by a connection pool.

    Neon suspends idle connections quickly; a single long-lived connection
    goes stale between requests. Wiring the saver to a
    :class:`psycopg_pool.ConnectionPool` means every operation checks out
    a fresh (or reused-and-healthy) connection.
    """
    global _saver
    if _saver is None:
        with _saver_lock:
            if _saver is None:
                pool = ConnectionPool(
                    conninfo=settings().database_url,
                    min_size=0,           # don't keep idle connections warm — Neon kills them
                    max_size=8,
                    max_idle=30.0,        # recycle any idle conn > 30s
                    kwargs={"autocommit": True, "prepare_threshold": 0},
                    check=ConnectionPool.check_connection,  # SELECT 1 before hand-out
                    open=True,
                )
                saver = PostgresSaver(pool)  # type: ignore[arg-type]
                saver.setup()
                _saver = saver
    return _saver


# ---------- utility nodes ----------

def load_state_node(state: ContentState) -> dict:
    """Load company_profile, preference_profile, and sources from the DB.

    Every content cycle starts with this so nodes downstream don't have to
    know how to talk to storage.
    """
    company_id = state.get("company_id") or settings().company_id
    profile = mem.get_profile(company_id) or {}
    prefs = mem.get_preferences(company_id) or {}
    sources = mem.list_sources(company_id, statuses=["active"])
    if not state.get("cycle_id"):
        cycle_id = mem.start_cycle(company_id)
    else:
        cycle_id = state["cycle_id"]
    return {
        "company_id": company_id,
        "cycle_id": cycle_id,
        "company_profile": profile,
        "preference_profile": prefs,
        "sources": sources,
    }


def review_gate_node(state: ContentState) -> dict:
    """HITL passthrough for Review.

    Graph interrupts *before* this node. When resumed, ``feedback`` and
    ``approved`` are expected to be populated by the API layer; this node
    is a no-op that lets the flow continue to Learning and Write.
    """
    return {}


def publish_gate_node(state: ContentState) -> dict:
    """HITL passthrough for Publish."""
    return {}


# ---------- graph builders ----------

def build_onboarding_graph():
    """Compile the onboarding subgraph. Interrupts before ``confirm``.

    Cached on first call.
    """
    global _onboarding_graph
    if _onboarding_graph is not None:
        return _onboarding_graph

    g = StateGraph(ContentState)
    g.add_node("crawl", crawl_node)
    g.add_node("extract", extract_node)
    g.add_node("seed_sources", seed_sources_node)
    g.add_node("confirm", confirm_node)
    g.add_node("persist", persist_node)

    g.add_edge(START, "crawl")
    g.add_edge("crawl", "extract")
    g.add_edge("extract", "seed_sources")
    g.add_edge("seed_sources", "confirm")
    g.add_edge("confirm", "persist")
    g.add_edge("persist", END)

    _onboarding_graph = g.compile(
        checkpointer=get_saver(),
        interrupt_before=["confirm"],  # user reviews profile + sources here
    )
    return _onboarding_graph


def build_content_graph():
    """Compile the per-cycle content graph.

    Interrupts before Review (user approves/rejects) and before Publish
    (user approves each channel).
    """
    global _content_graph
    if _content_graph is not None:
        return _content_graph

    # Late imports to avoid circular deps and keep test isolation clean
    from .nodes.learning import learning_node
    from .nodes.write import write_node
    from .nodes.publish import publish_node

    g = StateGraph(ContentState)
    g.add_node("load_state", load_state_node)
    g.add_node("ideate", ideate_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("review", review_gate_node)
    g.add_node("learning", learning_node)
    g.add_node("write", write_node)
    g.add_node("publish_gate", publish_gate_node)
    g.add_node("publish", publish_node)

    g.add_edge(START, "load_state")
    g.add_edge("load_state", "ideate")
    g.add_edge("ideate", "evaluate")
    g.add_edge("evaluate", "review")
    g.add_edge("review", "learning")
    g.add_edge("learning", "write")
    g.add_edge("write", "publish_gate")
    g.add_edge("publish_gate", "publish")
    g.add_edge("publish", END)

    _content_graph = g.compile(
        checkpointer=get_saver(),
        interrupt_before=["review", "publish"],
    )
    return _content_graph


# ---------- thread-id helpers ----------

def onboarding_thread(company_id: str) -> dict[str, Any]:
    """Thread config for the onboarding graph."""
    return {"configurable": {"thread_id": f"onboard:{company_id}"}}


def cycle_thread(cycle_id: str) -> dict[str, Any]:
    """Thread config for one content cycle."""
    return {"configurable": {"thread_id": f"cycle:{cycle_id}"}}
