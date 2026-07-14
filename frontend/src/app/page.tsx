"use client";
// Review — the curation queue.
//
// Each card is one candidate. You either:
//   - Route it to one or more channels (📧 Newsletter · 📷 Instagram · 💼 LinkedIn) — a story tagged for two channels appears in both drafts.
//   - Or reject it with a structured reason (the card collapses to an "undo" bar; the agent learns from the reason over cycles).
//
// "Save & generate drafts" commits everything: rejects go to feedback_log, per-channel routing goes to Write, and drafts appear on the Newsletter / Social tabs.

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

type Channel = "newsletter" | "instagram" | "linkedin";
const CHANNELS: Channel[] = ["newsletter", "instagram", "linkedin"];

type Decision =
  | { kind: "pending" }
  | { kind: "approved"; channels: Record<Channel, boolean> }
  | { kind: "rejected"; reason: string };

const CYCLE_KEY = "signal:cycle_id";
const CHANNEL_META: Record<Channel, { label: string; emoji: string; short: string }> = {
  newsletter: { label: "Newsletter", emoji: "📧", short: "NL" },
  instagram: { label: "Instagram", emoji: "📷", short: "IG" },
  linkedin: { label: "LinkedIn", emoji: "💼", short: "LI" },
};

function ageInDays(published: string): number {
  const then = new Date(published).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.round((Date.now() - then) / (1000 * 60 * 60 * 24));
}
function formatAge(published: string): string {
  const d = ageInDays(published);
  if (d <= 0) return "today";
  if (d === 1) return "1d";
  if (d < 7) return `${d}d`;
  if (d < 30) return `${Math.round(d / 7)}w`;
  return `${Math.round(d / 30)}mo`;
}

export default function ReviewPage() {
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDiscards, setShowDiscards] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Record<string, number> | null>(null);

  const loadQueue = useCallback(async (cid: string) => {
    setLoading(true);
    setError(null);
    try {
      const q = await api.getQueue(cid);
      setCandidates(q.candidates || []);
      // Pre-populate: default rejected route → rejected (but you can override).
      const init: Record<string, Decision> = {};
      (q.candidates || []).forEach((c) => {
        init[c.id] = { kind: "pending" };
      });
      setDecisions(init);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const saved =
      typeof window !== "undefined" ? localStorage.getItem(CYCLE_KEY) : null;
    if (saved) {
      setCycleId(saved);
      loadQueue(saved);
    }
  }, [loadQueue]);

  async function startNewCycle() {
    setRunning(true);
    setError(null);
    setSaved(null);
    try {
      const r = await api.runCycle();
      localStorage.setItem(CYCLE_KEY, r.cycle_id);
      setCycleId(r.cycle_id);
      setCandidates(r.candidates || []);
      const init: Record<string, Decision> = {};
      (r.candidates || []).forEach((c) => {
        init[c.id] = { kind: "pending" };
      });
      setDecisions(init);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  function toggleChannel(id: string, channel: Channel) {
    setDecisions((prev) => {
      const d = prev[id];
      const next: Record<Channel, boolean> =
        d?.kind === "approved"
          ? { ...d.channels }
          : { newsletter: false, instagram: false, linkedin: false };
      next[channel] = !next[channel];
      const anyOn = next.newsletter || next.instagram || next.linkedin;
      return {
        ...prev,
        [id]: anyOn ? { kind: "approved", channels: next } : { kind: "pending" },
      };
    });
  }

  function reject(id: string, reason: string) {
    setDecisions((prev) => ({ ...prev, [id]: { kind: "rejected", reason } }));
  }

  function undoReject(id: string) {
    setDecisions((prev) => ({ ...prev, [id]: { kind: "pending" } }));
  }

  async function saveAndGenerate() {
    if (!cycleId) return;
    setSaving(true);
    setError(null);
    try {
      // 1. Fire feedback for every rejected item (so learning gets the signal).
      const rejects = candidates.filter(
        (c) => decisions[c.id]?.kind === "rejected",
      );
      await Promise.all(
        rejects.map((c) => {
          const d = decisions[c.id];
          if (d?.kind !== "rejected") return Promise.resolve();
          return api.submitFeedback({
            item_id: c.id,
            decision: "reject",
            reason_code: d.reason,
            cycle_id: cycleId,
            source_id: c.source_id,
          });
        }),
      );

      // 2. Fire feedback for every approved item (for hit-rate / history stats).
      const approvals = candidates.filter(
        (c) => decisions[c.id]?.kind === "approved",
      );
      await Promise.all(
        approvals.map((c) =>
          api.submitFeedback({
            item_id: c.id,
            decision: "approve",
            cycle_id: cycleId,
            source_id: c.source_id,
          }),
        ),
      );

      // 3. Build per-channel routing and finish the cycle.
      const byChannel: Record<Channel, string[]> = {
        newsletter: [],
        instagram: [],
        linkedin: [],
      };
      candidates.forEach((c) => {
        const d = decisions[c.id];
        if (d?.kind !== "approved") return;
        (Object.keys(d.channels) as Channel[]).forEach((ch) => {
          if (d.channels[ch]) byChannel[ch].push(c.id);
        });
      });
      const r = await api.finishReview(cycleId, byChannel);
      setSaved(r.channel_counts || {});
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  const counts = candidates.reduce(
    (acc, c) => {
      const d = decisions[c.id];
      if (d?.kind === "approved") {
        if (d.channels.newsletter) acc.newsletter++;
        if (d.channels.instagram) acc.instagram++;
        if (d.channels.linkedin) acc.linkedin++;
      } else if (d?.kind === "rejected") {
        acc.rejected++;
      } else {
        acc.pending++;
      }
      return acc;
    },
    { newsletter: 0, instagram: 0, linkedin: 0, rejected: 0, pending: 0 },
  );

  const visible = candidates.filter(
    (c) => showDiscards || c.route !== "discard",
  );

  return (
    <div className="max-w-4xl">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Review</h1>
          <p className="text-sm text-neutral-500">
            Route each story to the channels it fits — or reject with a reason so the agent learns.
          </p>
        </div>
        <div className="flex gap-2 items-center shrink-0">
          <label className="text-xs text-neutral-500 flex items-center gap-1 select-none">
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
      {saved && (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Drafts generated · newsletter: {saved.newsletter ?? 0} · Instagram: {saved.instagram ?? 0} · LinkedIn: {saved.linkedin ?? 0}. Head to the Newsletter / Social tabs to preview.
        </div>
      )}

      {loading && <div className="text-sm text-neutral-500">Loading queue…</div>}

      {!loading && !candidates.length && !cycleId && (
        <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500">
          No cycle yet. Start one when the profile + sources are ready.
        </div>
      )}
      {!loading && !candidates.length && cycleId && (
        <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500">
          Queue is empty. Start a new cycle above.
        </div>
      )}

      <div className="space-y-2 pb-24">
        {visible.map((c) => {
          const d = decisions[c.id] || { kind: "pending" as const };
          if (d.kind === "rejected") {
            return (
              <RejectedRow
                key={c.id}
                title={c.title}
                reason={d.reason}
                onUndo={() => undoReject(c.id)}
              />
            );
          }
          return (
            <CandidateCard
              key={c.id}
              c={c}
              decision={d}
              onToggle={(ch) => toggleChannel(c.id, ch)}
              onReject={(reason) => reject(c.id, reason)}
            />
          );
        })}
      </div>

      {/* Sticky footer summary + save */}
      {candidates.length > 0 && (
        <div className="fixed bottom-0 left-[220px] right-[360px] bg-white border-t border-neutral-200 px-8 py-3 flex items-center justify-between gap-4">
          <div className="flex gap-4 items-center text-sm">
            <ChannelPill channel="newsletter" count={counts.newsletter} />
            <ChannelPill channel="instagram" count={counts.instagram} />
            <ChannelPill channel="linkedin" count={counts.linkedin} />
            <div className="text-neutral-400">·</div>
            <div className="text-xs text-neutral-500">
              {counts.rejected} rejected · {counts.pending} pending
            </div>
          </div>
          <button
            onClick={saveAndGenerate}
            disabled={saving || !cycleId}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
          >
            {saving ? "Saving & generating…" : "Save & generate drafts →"}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------- Card ----------------

function CandidateCard({
  c,
  decision,
  onToggle,
  onReject,
}: {
  c: Candidate;
  decision: Extract<Decision, { kind: "pending" } | { kind: "approved" }>;
  onToggle: (channel: Channel) => void;
  onReject: (reason: string) => void;
}) {
  const isPending = decision.kind === "pending";
  const channels = isPending
    ? { newsletter: false, instagram: false, linkedin: false }
    : decision.channels;

  return (
    <div
      className={`rounded-lg border bg-white transition ${
        isPending ? "border-neutral-200" : "border-emerald-300 shadow-sm"
      }`}
    >
      <div className="p-4">
        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span
            className={`text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5 cursor-help ${
              c.kind === "owned"
                ? "bg-amber-100 text-amber-800"
                : "bg-sky-100 text-sky-800"
            }`}
            title={
              c.kind === "owned"
                ? "OWNED — an original angle the agent generated from your profile (products, story, positioning). No outside article behind it; you write it under your own name."
                : "EXTERNAL — anchored on an outside article the agent found. Click 'source →' to read the original."
            }
          >
            {c.kind}
          </span>
          {c.pillar && (
            <span
              className="text-[10px] rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-600 cursor-help"
              title={`Content pillar — one of the themes the agent extracted from your site. This story fits the '${c.pillar}' pillar.`}
            >
              {c.pillar}
            </span>
          )}
          <span
            className={`text-[10px] rounded px-1.5 py-0.5 cursor-help ${
              c.route === "feature"
                ? "bg-emerald-100 text-emerald-800"
                : c.route === "uncertain"
                ? "bg-yellow-100 text-yellow-800"
                : "bg-neutral-100 text-neutral-500"
            }`}
            title={
              c.route === "feature"
                ? `feature — the agent recommends featuring this. Score ${c.score?.final?.toFixed(2)}/1.00. Weighted average of relevance, novelty, pillar-fit, source hit-rate, and learned preferences.`
                : c.route === "uncertain"
                ? `uncertain — borderline. Score ${c.score?.final?.toFixed(2)}/1.00. Decide by hand.`
                : `discard — the agent thinks skip this. Score ${c.score?.final?.toFixed(2)}/1.00. Hidden by default; visible because 'show discards' is on.`
            }
          >
            {c.route} · {c.score?.final?.toFixed(2)}
          </span>
          {c.published_date && (
            <span
              className={`text-[10px] rounded px-1.5 py-0.5 cursor-help ${
                ageInDays(c.published_date) > 14
                  ? "bg-red-100 text-red-800"
                  : ageInDays(c.published_date) > 7
                  ? "bg-amber-100 text-amber-800"
                  : "bg-neutral-100 text-neutral-600"
              }`}
              title={`Published ${c.published_date}. Fresher items are usually stronger newsletter picks.`}
            >
              {formatAge(c.published_date)}
            </span>
          )}
        </div>

        {/* Content */}
        <div className="font-medium">{c.title}</div>
        <div className="text-sm text-neutral-600 mt-1">{c.angle}</div>
        {c.rationale && (
          <div className="text-xs text-neutral-500 italic mt-2">{c.rationale}</div>
        )}
        {c.url && (
          <a
            href={c.url}
            target="_blank"
            className="text-xs text-blue-700 mt-2 inline-block"
          >
            source →
          </a>
        )}
        {c.kind === "owned" && c.verified_source_url && (
          <div className="mt-2 flex items-start gap-1.5">
            <span
              className="text-[10px] rounded bg-emerald-100 text-emerald-800 px-1.5 py-0.5 shrink-0 mt-0.5 cursor-help"
              title="This owned angle passed a live fact-check: the agent searched the web for its factual claim and found a corroborating article within the last 30 days. Original angle is still yours to write; the citation is a footnote."
            >
              ✓ fact-checked
            </span>
            <a
              href={c.verified_source_url}
              target="_blank"
              className="text-xs text-neutral-600 hover:text-blue-700 underline decoration-neutral-300 hover:decoration-blue-500 line-clamp-1"
            >
              {c.verified_source_title || c.verified_source_url}
            </a>
          </div>
        )}
      </div>

      {/* Action row */}
      <div className="border-t border-neutral-100 px-4 py-2 flex items-center gap-2 flex-wrap">
        <span className="text-[10px] text-neutral-500 uppercase tracking-wider mr-1">
          Route to:
        </span>
        {CHANNELS.map((ch) => {
          const on = channels[ch];
          const meta = CHANNEL_META[ch];
          return (
            <button
              key={ch}
              type="button"
              onClick={() => onToggle(ch)}
              className={`rounded-md px-2.5 py-1 text-xs border transition ${
                on
                  ? "bg-emerald-600 border-emerald-600 text-white"
                  : "bg-white border-neutral-300 text-neutral-700 hover:border-neutral-400"
              }`}
            >
              {meta.emoji} {meta.label}
            </button>
          );
        })}
        <div className="flex-1" />
        <select
          onChange={(e) => e.target.value && onReject(e.target.value)}
          value=""
          className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs"
        >
          <option value="">✕ Reject — why?</option>
          {REASON_CODES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function RejectedRow({
  title,
  reason,
  onUndo,
}: {
  title: string;
  reason: string;
  onUndo: () => void;
}) {
  return (
    <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 flex items-center gap-3 text-sm">
      <span className="text-neutral-400 text-xs">✕</span>
      <span className="text-neutral-500 line-through truncate flex-1">{title}</span>
      <span className="text-[10px] rounded bg-red-100 text-red-800 px-1.5 py-0.5">
        {reason}
      </span>
      <button
        onClick={onUndo}
        className="text-xs text-blue-700 hover:underline"
      >
        undo
      </button>
    </div>
  );
}

function ChannelPill({ channel, count }: { channel: Channel; count: number }) {
  const meta = CHANNEL_META[channel];
  const active = count > 0;
  return (
    <div
      className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${
        active
          ? "bg-emerald-100 text-emerald-800"
          : "bg-neutral-100 text-neutral-500"
      }`}
    >
      <span>{meta.emoji}</span>
      <span className="font-medium">{count}</span>
      <span>for {meta.label}</span>
    </div>
  );
}
