"use client";
// Sources — active + proposed sources, per-source hit-rate, content-mix slider.
// The agent proposes, the user disposes. PRD §8.

import { useCallback, useEffect, useState } from "react";
import { api, type Source, type Profile } from "@/lib/api";

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [addUrl, setAddUrl] = useState("");
  const [addKind, setAddKind] = useState<"rss" | "web">("web");
  const [busy, setBusy] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([
        api.listSources(),
        api.getProfile().catch(() => null),
      ]);
      setSources(s.sources || []);
      setProfile(p);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function addSource() {
    if (!addUrl.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.addSource(addUrl.trim(), addKind);
      setAddUrl("");
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function discover() {
    setDiscovering(true);
    setError(null);
    try {
      await api.discoverSources();
      await load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setDiscovering(false);
    }
  }

  async function toggle(s: Source) {
    await api.patchSource(s.source_id, s.status === "active" ? "paused" : "active");
    load();
  }

  async function unfollow(s: Source) {
    if (!confirm(`Unfollow ${s.url}?`)) return;
    await api.deleteSource(s.source_id);
    load();
  }

  async function accept(s: Source) {
    await api.acceptSource(s.source_id);
    load();
  }

  async function updateMix(next: number) {
    if (!profile) return;
    const updated: Profile = { ...profile, content_mix: next };
    setProfile(updated);
    await api.updateProfile(updated);
  }

  const active = sources.filter((s) => s.status !== "proposed");
  const proposed = sources.filter((s) => s.status === "proposed");

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Sources</h1>
        <p className="text-sm text-neutral-500">
          What the agent reads. Add, pause, or unfollow anything.
        </p>
      </header>

      {profile && (
        <div className="mb-6 rounded-lg border border-neutral-200 bg-white px-4 py-3">
          <div className="text-sm font-medium">Content mix</div>
          <div className="text-xs text-neutral-500 mb-2">
            0 = all external, 1 = all owned. Higher means more of *your* story per cycle.
          </div>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={profile.content_mix ?? 0.5}
              onChange={(e) => updateMix(parseFloat(e.target.value))}
              className="flex-1"
            />
            <div className="w-12 text-right text-sm tabular-nums">
              {(profile.content_mix ?? 0.5).toFixed(2)}
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="mb-6 rounded-lg border border-neutral-200 bg-white px-4 py-3">
        <div className="text-sm font-medium mb-2">Add a source</div>
        <div className="flex gap-2">
          <input
            value={addUrl}
            onChange={(e) => setAddUrl(e.target.value)}
            placeholder="https://example.com or feed URL"
            className="flex-1 rounded border border-neutral-300 px-3 py-2 text-sm"
          />
          <select
            value={addKind}
            onChange={(e) => setAddKind(e.target.value as "rss" | "web")}
            className="rounded border border-neutral-300 px-2 text-sm"
          >
            <option value="web">web</option>
            <option value="rss">rss</option>
          </select>
          <button
            onClick={addSource}
            disabled={busy}
            className="rounded bg-neutral-900 px-3 text-sm text-white disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-medium">Followed</h2>
          <button
            onClick={discover}
            disabled={discovering}
            className="text-xs rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100 disabled:opacity-50"
          >
            {discovering ? "Discovering…" : "Discover more"}
          </button>
        </div>
        <div className="rounded-lg border border-neutral-200 bg-white divide-y">
          {active.length === 0 && (
            <div className="p-3 text-sm text-neutral-500">No followed sources yet.</div>
          )}
          {active.map((s) => (
            <div key={s.source_id} className="p-3 flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{s.name || s.url}</div>
                <div className="text-xs text-neutral-500 truncate">{s.url}</div>
                <div className="text-[11px] text-neutral-500 mt-1">
                  {s.kind} · {s.origin} ·{" "}
                  <span
                    className={
                      s.status === "active" ? "text-emerald-700" : "text-amber-700"
                    }
                  >
                    {s.status}
                  </span>
                  {" · "}
                  hit-rate:{" "}
                  {s.items_surfaced
                    ? `${((s.items_approved / s.items_surfaced) * 100).toFixed(0)}% (${
                        s.items_approved
                      }/${s.items_surfaced})`
                    : "n/a"}
                </div>
              </div>
              <button
                onClick={() => toggle(s)}
                className="text-xs rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
              >
                {s.status === "active" ? "pause" : "activate"}
              </button>
              <button
                onClick={() => unfollow(s)}
                className="text-xs rounded border border-red-200 px-2 py-1 text-red-700 hover:bg-red-50"
              >
                unfollow
              </button>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium mb-2">Proposed by the agent</h2>
        <div className="rounded-lg border border-neutral-200 bg-white divide-y">
          {proposed.length === 0 && (
            <div className="p-3 text-sm text-neutral-500">
              Nothing proposed yet. Hit "Discover more" above.
            </div>
          )}
          {proposed.map((s) => (
            <div key={s.source_id} className="p-3 flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{s.name || s.url}</div>
                <div className="text-xs text-neutral-500 truncate">{s.url}</div>
                {s.reason && (
                  <div className="text-[11px] text-neutral-500 italic mt-1">
                    {s.reason}
                  </div>
                )}
              </div>
              <button
                onClick={() => accept(s)}
                className="text-xs rounded bg-emerald-600 px-3 py-1 text-white hover:bg-emerald-500"
              >
                Follow
              </button>
              <button
                onClick={() => unfollow(s)}
                className="text-xs rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
              >
                Dismiss
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
