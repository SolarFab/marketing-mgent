"use client";
// Analytics — approval-rate over cycles, per-source hit-rate, top reject
// reasons, flagged underperformers. Feeds the "Hard task: evaluation" story.

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Rates = {
  cycles: {
    cycle_id: string;
    total: number;
    approved: number;
    rate: number;
    started_at: string | null;
  }[];
};

type Hits = {
  sources: {
    source_id: string;
    name?: string;
    url?: string;
    surfaced: number;
    approved: number;
    rate: number | null;
  }[];
};

export default function AnalyticsPage() {
  const [rates, setRates] = useState<Rates | null>(null);
  const [hits, setHits] = useState<Hits | null>(null);
  const [reasons, setReasons] = useState<Record<string, number>>({});
  const [flagged, setFlagged] = useState<any[]>([]);

  const load = useCallback(async () => {
    try {
      const [r, h, rr, f] = await Promise.all([
        api.approvalRate(),
        api.sourceHitRates(),
        api.reasonHistogram(),
        api.underperformers(),
      ]);
      setRates(r);
      setHits(h);
      setReasons(rr.histogram || {});
      setFlagged(f.sources || []);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <p className="text-sm text-neutral-500">
          Approval-rate is the ground-truth eval — does the agent get sharper cycle over cycle?
        </p>
      </header>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Approval rate per cycle</h2>
        {!rates?.cycles?.length ? (
          <div className="text-sm text-neutral-500">
            No cycles finished yet.
          </div>
        ) : (
          <div className="rounded border border-neutral-200 bg-white p-4">
            <div className="flex items-end gap-2 h-40">
              {rates.cycles.map((c, i) => (
                <div key={c.cycle_id} className="flex-1 flex flex-col items-center gap-1">
                  <div
                    className="w-full bg-emerald-500 rounded-t"
                    style={{ height: `${Math.max(4, c.rate * 100)}%` }}
                    title={`${c.approved}/${c.total} approved`}
                  />
                  <div className="text-[10px] text-neutral-500 tabular-nums">
                    {(c.rate * 100).toFixed(0)}%
                  </div>
                  <div className="text-[9px] text-neutral-400">c{i + 1}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Per-source hit-rate</h2>
        {!hits?.sources?.length ? (
          <div className="text-sm text-neutral-500">No sources tracked yet.</div>
        ) : (
          <div className="rounded border border-neutral-200 bg-white divide-y">
            {hits.sources.map((s) => (
              <div key={s.source_id} className="p-2 flex items-center gap-3 text-sm">
                <div className="flex-1 truncate">{s.name || s.url}</div>
                <div className="w-32 h-2 bg-neutral-100 rounded">
                  <div
                    className="h-2 bg-emerald-500 rounded"
                    style={{ width: `${(s.rate ?? 0) * 100}%` }}
                  />
                </div>
                <div className="w-24 text-right text-xs tabular-nums">
                  {s.rate === null ? "n/a" : `${(s.rate * 100).toFixed(0)}%`}{" "}
                  <span className="text-neutral-400">
                    ({s.approved}/{s.surfaced})
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {Object.keys(reasons).length > 0 && (
        <section className="mb-8">
          <h2 className="text-lg font-medium mb-2">Top reject reasons (rolling)</h2>
          <div className="rounded border border-neutral-200 bg-white p-3">
            {Object.entries(reasons)
              .sort((a, b) => b[1] - a[1])
              .map(([r, n]) => (
                <div key={r} className="flex items-center gap-2 text-sm">
                  <div className="w-40 text-neutral-600">{r}</div>
                  <div className="flex-1 h-2 bg-neutral-100 rounded">
                    <div
                      className="h-2 bg-neutral-400 rounded"
                      style={{
                        width: `${(n / Math.max(...Object.values(reasons))) * 100}%`,
                      }}
                    />
                  </div>
                  <div className="w-8 text-right text-xs tabular-nums">{n}</div>
                </div>
              ))}
          </div>
        </section>
      )}

      {flagged.length > 0 && (
        <section>
          <h2 className="text-lg font-medium mb-2">Flagged for review</h2>
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm">
            <div className="mb-2">
              These sources have a hit-rate ≤ 20% after 6+ surfacings. The agent
              won't unfollow — that's on you.
            </div>
            {flagged.map((s) => (
              <div key={s.source_id} className="flex items-center gap-2 py-1">
                <div className="flex-1 truncate">{s.name || s.url}</div>
                <div className="text-xs">
                  {(s.hit_rate * 100).toFixed(0)}% ({s.items_approved}/
                  {s.items_surfaced})
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
