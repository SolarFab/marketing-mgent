"use client";
// Review — the default landing tab. Curation queue: score, rationale, pillar,
// origin (owned or which source), approve/reject with structured reason.
// See PRD §8.

import { useCallback, useEffect, useState } from "react";
import { api, type Candidate } from "@/lib/api";

const REASON_CODES = [
  "off-brand",
  "wrong-product",
  "not-my-voice",
  "too-promotional",
  "already-said",
  "not-relevant-now",
  "source-not-credible",
  "too-shallow",
];

const CYCLE_KEY = "signal:cycle_id";

type Decision = "approve" | "reject";

function ageInDays(published: string): number {
  const then = new Date(published).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.round((Date.now() - then) / (1000 * 60 * 60 * 24));
}

function formatAge(published: string): string {
  const d = ageInDays(published);
  if (d <= 0) return "today";
  if (d === 1) return "1d old";
  if (d < 7) return `${d}d old`;
  if (d < 30) return `${Math.round(d / 7)}w old`;
  return `${Math.round(d / 30)}mo old`;
}

export default function ReviewPage() {
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [decisions, setDecisions] = useState<Record<string, { d: Decision; r?: string }>>({});
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDiscards, setShowDiscards] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [finished, setFinished] = useState(false);

  const loadQueue = useCallback(async (cid: string) => {
    setLoading(true);
    setError(null);
    try {
      const q = await api.getQueue(cid);
      setCandidates(q.candidates || []);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(CYCLE_KEY) : null;
    if (saved) {
      setCycleId(saved);
      loadQueue(saved);
    }
  }, [loadQueue]);

  async function startNewCycle() {
    setRunning(true);
    setError(null);
    setFinished(false);
    try {
      const r = await api.runCycle();
      localStorage.setItem(CYCLE_KEY, r.cycle_id);
      setCycleId(r.cycle_id);
      setCandidates(r.candidates || []);
      setDecisions({});
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  async function decide(item_id: string, d: Decision, reason_code?: string) {
    setDecisions((s) => ({ ...s, [item_id]: { d, r: reason_code } }));
    try {
      await api.submitFeedback({
        item_id,
        decision: d,
        reason_code,
        cycle_id: cycleId ?? undefined,
        source_id:
          candidates.find((c) => c.id === item_id)?.source_id || undefined,
      });
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function finishReview() {
    if (!cycleId) return;
    setFinishing(true);
    try {
      const approved_ids = Object.entries(decisions)
        .filter(([, v]) => v.d === "approve")
        .map(([id]) => id);
      await api.finishReview(cycleId, approved_ids);
      setFinished(true);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setFinishing(false);
    }
  }

  const visible = candidates.filter(
    (c) => showDiscards || c.route !== "discard",
  );

  return (
    <div>
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Review</h1>
          <p className="text-sm text-neutral-500">
            Curation queue. Approve keeps it; reject teaches the agent why.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <label className="text-xs text-neutral-500 flex items-center gap-1">
            <input
              type="checkbox"
              checked={showDiscards}
              onChange={(e) => setShowDiscards(e.target.checked)}
            />
            show discards
          </label>
          <button
            onClick={startNewCycle}
            disabled={running}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
          >
            {running ? "Running…" : cycleId ? "Run new cycle" : "Start first cycle"}
          </button>
        </div>
      </header>

      {cycleId && (
        <div className="mb-4 text-xs text-neutral-500">
          Cycle: <code>{cycleId}</code>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      {finished && (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Review submitted. Learning + Write are running — head to Newsletter / Social to see drafts.
        </div>
      )}

      {loading && <div className="text-sm text-neutral-500">Loading queue…</div>}

      {!loading && !candidates.length && cycleId && (
        <div className="text-sm text-neutral-500">
          Queue is empty. Start a new cycle above.
        </div>
      )}

      {!cycleId && !loading && (
        <div className="text-sm text-neutral-500">
          No cycle yet. Start one when the profile + sources are ready.
        </div>
      )}

      <div className="space-y-3">
        {visible.map((c) => {
          const dec = decisions[c.id];
          return (
            <div
              key={c.id}
              className={`rounded-lg border bg-white px-4 py-3 shadow-sm ${
                dec?.d === "approve"
                  ? "border-emerald-300"
                  : dec?.d === "reject"
                  ? "border-red-200 opacity-70"
                  : "border-neutral-200"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span
                      className={`text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5 ${
                        c.kind === "owned"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-sky-100 text-sky-800"
                      }`}
                    >
                      {c.kind}
                    </span>
                    {c.pillar && (
                      <span className="text-[10px] rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-600">
                        {c.pillar}
                      </span>
                    )}
                    <span
                      className={`text-[10px] rounded px-1.5 py-0.5 ${
                        c.route === "feature"
                          ? "bg-emerald-100 text-emerald-800"
                          : c.route === "uncertain"
                          ? "bg-yellow-100 text-yellow-800"
                          : "bg-neutral-100 text-neutral-500"
                      }`}
                    >
                      {c.route} · {c.score?.final?.toFixed(2)}
                    </span>
                    {c.published_date && (
                      <span
                        className={`text-[10px] rounded px-1.5 py-0.5 ${
                          ageInDays(c.published_date) > 14
                            ? "bg-red-100 text-red-800"
                            : ageInDays(c.published_date) > 7
                            ? "bg-amber-100 text-amber-800"
                            : "bg-neutral-100 text-neutral-600"
                        }`}
                        title={c.published_date}
                      >
                        {formatAge(c.published_date)}
                      </span>
                    )}
                  </div>
                  <div className="font-medium">{c.title}</div>
                  <div className="text-sm text-neutral-600 mt-1">{c.angle}</div>
                  {c.rationale && (
                    <div className="text-xs text-neutral-500 italic mt-2">
                      {c.rationale}
                    </div>
                  )}
                  {c.url && (
                    <a
                      href={c.url}
                      target="_blank"
                      className="text-xs text-blue-700 mt-1 inline-block"
                    >
                      source →
                    </a>
                  )}
                </div>
                <div className="flex flex-col gap-2 shrink-0">
                  <button
                    onClick={() => decide(c.id, "approve")}
                    disabled={!!dec}
                    className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-500 disabled:opacity-60"
                  >
                    Approve
                  </button>
                  <select
                    onChange={(e) =>
                      e.target.value && decide(c.id, "reject", e.target.value)
                    }
                    disabled={!!dec}
                    value={dec?.d === "reject" ? dec.r || "" : ""}
                    className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs"
                  >
                    <option value="">Reject — why?</option>
                    {REASON_CODES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {visible.length > 0 && (
        <div className="mt-6 sticky bottom-0 bg-neutral-50 pt-3 pb-2 border-t border-neutral-200 flex justify-between items-center">
          <div className="text-sm text-neutral-600">
            {Object.values(decisions).filter((v) => v.d === "approve").length}{" "}
            approved · {Object.values(decisions).filter((v) => v.d === "reject").length}{" "}
            rejected · {visible.length - Object.keys(decisions).length} undecided
          </div>
          <button
            onClick={finishReview}
            disabled={!cycleId || finishing || finished}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
          >
            {finishing
              ? "Finishing…"
              : finished
              ? "Finished ✓"
              : "Finish review → generate drafts"}
          </button>
        </div>
      )}
    </div>
  );
}
