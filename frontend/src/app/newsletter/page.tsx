"use client";
// Newsletter — draft preview + 3 layout options + Approve · send.
// PRD §8.

import { useCallback, useEffect, useState } from "react";
import { api, type NewsletterDraft } from "@/lib/api";

const LAYOUTS = ["digest", "editorial", "single-story"] as const;

export default function NewsletterPage() {
  const [draft, setDraft] = useState<NewsletterDraft | null>(null);
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [publishResult, setPublishResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const savedCycle =
        typeof window !== "undefined" ? localStorage.getItem("signal:cycle_id") : null;
      const r = savedCycle
        ? await api.getDrafts(savedCycle)
        : await api.getDrafts();
      const drafts = r.drafts;
      if (drafts?.newsletter) {
        setDraft(drafts.newsletter);
        setCycleId(drafts.cycle_id || savedCycle || null);
      }
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function regenerate(layout: string) {
    if (!cycleId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.rewrite(cycleId, layout);
      setDraft(r.drafts.newsletter);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!cycleId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.publish(cycleId, "newsletter");
      setPublishResult(r.result);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Newsletter</h1>
          <p className="text-sm text-neutral-500">
            One draft. Three layouts. Human approval before send.
          </p>
        </div>
        {draft && (
          <div className="flex gap-2 items-center">
            {LAYOUTS.map((l) => (
              <button
                key={l}
                onClick={() => regenerate(l)}
                disabled={busy}
                className={`text-xs rounded px-2 py-1 border ${
                  draft.layout === l
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-300 hover:bg-neutral-100"
                } disabled:opacity-50`}
              >
                {l}
              </button>
            ))}
            <button
              onClick={publish}
              disabled={busy}
              className="ml-2 rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              Approve · send
            </button>
          </div>
        )}
      </header>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      {publishResult && (
        <div className="mb-4 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Sent — mode: <code>{publishResult.mode}</code>
          {publishResult.external_id && (
            <>
              , id: <code>{publishResult.external_id}</code>
            </>
          )}
        </div>
      )}

      {!draft && (
        <div className="text-sm text-neutral-500">
          No draft yet. Finish a review on the Review tab first.
        </div>
      )}

      {draft && (
        <article className="max-w-2xl rounded-lg border border-neutral-200 bg-white px-6 py-6 shadow-sm">
          <h2 className="text-xl font-semibold">{draft.subject}</h2>
          {draft.preheader && (
            <div className="text-xs text-neutral-500 mt-1">{draft.preheader}</div>
          )}
          {draft.intro && <p className="text-sm mt-4 italic">{draft.intro}</p>}
          <div className="mt-6 space-y-6">
            {(draft.sections || []).map((s, i) => (
              <div key={i} className="border-t border-neutral-200 pt-4">
                {s.heading && <h3 className="font-medium text-base">{s.heading}</h3>}
                <p className="text-sm mt-1 whitespace-pre-wrap">{s.body_markdown}</p>
                {s.link && (
                  <a
                    href={s.link}
                    target="_blank"
                    className="text-sm text-blue-700 mt-2 inline-block"
                  >
                    Read more →
                  </a>
                )}
              </div>
            ))}
          </div>
          {draft.signoff && (
            <div className="mt-6 text-sm italic text-neutral-700">{draft.signoff}</div>
          )}
        </article>
      )}
    </div>
  );
}
