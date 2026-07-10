"use client";
// Social — Instagram + LinkedIn drafts from the same content set. Per-channel
// approve → queue to Buffer (draft mode). PRD §8.

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function SocialPage() {
  const [drafts, setDrafts] = useState<any>(null);
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const saved =
        typeof window !== "undefined" ? localStorage.getItem("signal:cycle_id") : null;
      const r = saved ? await api.getDrafts(saved) : await api.getDrafts();
      const d = r.drafts;
      if (d) {
        setDrafts(d);
        setCycleId(d.cycle_id || saved || null);
      }
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function publish(channel: "instagram" | "linkedin") {
    if (!cycleId) return;
    setBusy(channel);
    setError(null);
    try {
      const r = await api.publish(cycleId, channel);
      setResults((s) => ({ ...s, [channel]: r.result }));
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Social</h1>
        <p className="text-sm text-neutral-500">
          Instagram + LinkedIn from the same content set. Buffer draft mode is a
          second safety gate.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      {!drafts && (
        <div className="text-sm text-neutral-500">
          No drafts yet. Finish a review on the Review tab first.
        </div>
      )}

      {drafts?.instagram && (
        <section className="mb-6 rounded-lg border border-neutral-200 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <div>
              <h2 className="font-medium">Instagram</h2>
              <div className="text-xs text-neutral-500">
                Punchy first 90 chars. 3–6 hashtags.
              </div>
            </div>
            <button
              onClick={() => publish("instagram")}
              disabled={busy === "instagram"}
              className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              Approve · queue to Buffer
            </button>
          </div>
          <p className="text-sm whitespace-pre-wrap">
            {drafts.instagram.caption}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {(drafts.instagram.hashtags || []).map((h: string) => (
              <span
                key={h}
                className="text-[11px] rounded bg-sky-100 px-1.5 py-0.5 text-sky-700"
              >
                #{h.replace(/^#/, "")}
              </span>
            ))}
          </div>
          {results.instagram && (
            <div className="mt-3 text-xs text-emerald-700">
              Queued — mode: {results.instagram.mode}
            </div>
          )}
        </section>
      )}

      {drafts?.linkedin && (
        <section className="rounded-lg border border-neutral-200 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <div>
              <h2 className="font-medium">LinkedIn</h2>
              <div className="text-xs text-neutral-500">
                Claim or number in the first line. Ends on a question or a specific ask.
              </div>
            </div>
            <button
              onClick={() => publish("linkedin")}
              disabled={busy === "linkedin"}
              className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              Approve · queue to Buffer
            </button>
          </div>
          <p className="text-sm whitespace-pre-wrap">{drafts.linkedin.post}</p>
          {results.linkedin && (
            <div className="mt-3 text-xs text-emerald-700">
              Queued — mode: {results.linkedin.mode}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
