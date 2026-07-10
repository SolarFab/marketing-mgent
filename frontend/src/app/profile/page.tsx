"use client";
// Profile · Learning — editable profile + learned rules made visible.
// "The agent has learned: X" with confirm/delete per rule. PRD §8.

import { useCallback, useEffect, useState } from "react";
import { api, type Profile } from "@/lib/api";

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [json, setJson] = useState<string>("");
  const [learning, setLearning] = useState<{
    confirmed_rules: string[];
    pending_rules: string[];
    reason_histogram: Record<string, number>;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, l] = await Promise.all([
        api.getProfile().catch(() => null),
        api.getLearning(),
      ]);
      setProfile(p);
      setJson(JSON.stringify(p, null, 2));
      setLearning(l);
    } catch (e: any) {
      setMsg(e.message || String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function saveProfile() {
    setBusy(true);
    setMsg(null);
    try {
      const parsed = JSON.parse(json) as Profile;
      await api.updateProfile(parsed);
      setMsg("Saved.");
      load();
    } catch (e: any) {
      setMsg(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRule(r: string) {
    await api.confirmRule(r);
    load();
  }
  async function dismissRule(r: string) {
    await api.dismissRule(r);
    load();
  }
  async function deleteRule(r: string) {
    await api.deleteRule(r);
    load();
  }

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Profile · Learning</h1>
        <p className="text-sm text-neutral-500">
          Voice + market + pillars, and everything the agent has learned about
          your taste.
        </p>
      </header>

      {msg && (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {msg}
        </div>
      )}

      <section className="mb-8">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-medium">Company profile</h2>
          <button
            onClick={saveProfile}
            disabled={busy}
            className="text-sm rounded bg-neutral-900 px-3 py-1 text-white hover:bg-neutral-700 disabled:opacity-50"
          >
            Save
          </button>
        </div>
        {!profile && (
          <div className="text-sm text-neutral-500">
            No profile yet. Go to the Onboard tab and paste your homepage URL.
          </div>
        )}
        {profile && (
          <textarea
            value={json}
            onChange={(e) => setJson(e.target.value)}
            spellCheck={false}
            className="w-full h-96 font-mono text-xs rounded border border-neutral-300 bg-white p-3"
          />
        )}
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Pending rules — the agent proposes</h2>
        {learning?.pending_rules?.length === 0 && (
          <div className="text-sm text-neutral-500">
            No pending rules. Keep reviewing — patterns need a few cycles of feedback.
          </div>
        )}
        <div className="space-y-2">
          {learning?.pending_rules?.map((r) => (
            <div key={r} className="flex items-center gap-2 rounded border border-yellow-200 bg-yellow-50 p-3">
              <div className="flex-1 text-sm">{r}</div>
              <button
                onClick={() => confirmRule(r)}
                className="text-xs rounded bg-emerald-600 px-2 py-1 text-white"
              >
                Confirm
              </button>
              <button
                onClick={() => dismissRule(r)}
                className="text-xs rounded border border-neutral-300 px-2 py-1"
              >
                Dismiss
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Confirmed rules</h2>
        {learning?.confirmed_rules?.length === 0 && (
          <div className="text-sm text-neutral-500">Nothing confirmed yet.</div>
        )}
        <div className="space-y-2">
          {learning?.confirmed_rules?.map((r) => (
            <div key={r} className="flex items-center gap-2 rounded border border-emerald-200 bg-emerald-50 p-3">
              <div className="flex-1 text-sm">{r}</div>
              <button
                onClick={() => deleteRule(r)}
                className="text-xs rounded border border-red-200 px-2 py-1 text-red-700"
              >
                Forget
              </button>
            </div>
          ))}
        </div>
      </section>

      {learning?.reason_histogram && Object.keys(learning.reason_histogram).length > 0 && (
        <section>
          <h2 className="text-lg font-medium mb-2">Reject reasons — rolling window</h2>
          <div className="rounded border border-neutral-200 bg-white p-3">
            {Object.entries(learning.reason_histogram).map(([reason, n]) => (
              <div key={reason} className="flex items-center gap-2 text-sm">
                <div className="w-40 text-neutral-600">{reason}</div>
                <div className="flex-1 h-2 bg-neutral-100 rounded">
                  <div
                    className="h-2 bg-neutral-400 rounded"
                    style={{
                      width: `${
                        (n /
                          Math.max(...Object.values(learning.reason_histogram))) *
                        100
                      }%`,
                    }}
                  />
                </div>
                <div className="w-8 text-right text-xs tabular-nums">{n}</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
