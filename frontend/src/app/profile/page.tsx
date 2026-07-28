"use client";
// Profile · Learning — the "what the agent knows about you" page.
// Visual cards over the extracted profile + brand + learned rules,
// plus a raw-JSON escape hatch for power edits.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, BACKEND_URL, type Brand, type Profile } from "@/lib/api";

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [json, setJson] = useState<string>("");
  const [showJson, setShowJson] = useState(false);
  const [savingJson, setSavingJson] = useState(false);
  const [savingMix, setSavingMix] = useState(false);
  const [learning, setLearning] = useState<{
    confirmed_rules: string[];
    pending_rules: string[];
    reason_histogram: Record<string, number>;
  } | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      let learningError: string | null = null;
      const [p, l] = await Promise.all([
        api.getProfile().catch(() => null),
        api.getLearning().catch((e: any) => {
          learningError = e.message || String(e);
          return null;
        }),
      ]);
      setProfile(p);
      setJson(JSON.stringify(p, null, 2));
      setLearning(l);
      if (learningError) {
        setMsg({ tone: "warn", text: `Couldn't load learning data: ${learningError}` });
      }
    } catch (e: any) {
      setMsg({ tone: "warn", text: e.message || String(e) });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function saveJson() {
    setSavingJson(true);
    setMsg(null);
    try {
      const parsed = JSON.parse(json) as Profile;
      await api.updateProfile(parsed);
      setMsg({ tone: "ok", text: "Saved." });
      load();
    } catch (e: any) {
      setMsg({ tone: "warn", text: e.message || String(e) });
    } finally {
      setSavingJson(false);
    }
  }

  // Debounce the content-mix PUT so dragging the slider doesn't fire a
  // request per step (out-of-order responses could persist a stale value).
  const mixCommit = useRef<ReturnType<typeof setTimeout> | null>(null);

  function saveMix(next: number) {
    if (!profile) return;
    const updated = { ...profile, content_mix: next };
    setProfile(updated);
    setJson(JSON.stringify(updated, null, 2));
    if (mixCommit.current) clearTimeout(mixCommit.current);
    mixCommit.current = setTimeout(async () => {
      setSavingMix(true);
      try {
        await api.updateProfile(updated);
      } catch (e: any) {
        setMsg({ tone: "warn", text: e.message || String(e) });
      } finally {
        setSavingMix(false);
      }
    }, 400);
  }

  async function confirmRule(r: string) {
    try {
      await api.confirmRule(r);
      load();
    } catch (e: any) {
      setMsg({ tone: "warn", text: e.message || String(e) });
    }
  }
  async function dismissRule(r: string) {
    try {
      await api.dismissRule(r);
      load();
    } catch (e: any) {
      setMsg({ tone: "warn", text: e.message || String(e) });
    }
  }
  async function deleteRule(r: string) {
    try {
      await api.deleteRule(r);
      load();
    } catch (e: any) {
      setMsg({ tone: "warn", text: e.message || String(e) });
    }
  }

  if (!profile) {
    return (
      <div>
        <header className="mb-6">
          <h1 className="text-2xl font-semibold">Profile · Learning</h1>
          <p className="text-sm text-neutral-500">
            The agent's model of your brand + everything it's learned about your taste.
          </p>
        </header>
        {msg && (
          <div className={`mb-4 rounded border px-3 py-2 text-sm ${
            msg.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"
          }`}>
            {msg.text}
          </div>
        )}
        <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500">
          No profile yet. Head to the <a href="/onboard" className="text-blue-700 underline">Onboard</a> tab to set one up.
        </div>
      </div>
    );
  }

  const brand = profile.brand;

  return (
    <div className="max-w-5xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Profile · Learning</h1>
        <p className="text-sm text-neutral-500">
          The agent's model of your brand + everything it's learned about your taste. Adjust via chat on the Onboard tab or edit the raw JSON below.
        </p>
      </header>

      {msg && (
        <div className={`mb-4 rounded border px-3 py-2 text-sm ${
          msg.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"
        }`}>
          {msg.text}
        </div>
      )}

      {/* Brand hero — screenshot + palette */}
      <BrandHero brand={brand} identity={profile.identity} />

      {/* Structured profile cards */}
      <div className="grid grid-cols-2 gap-3 mt-3">
        <Card title="Who you sell to">
          {profile.market?.icp && <p className="text-sm">{profile.market.icp}</p>}
          <ChipRow label="Segments" items={profile.market?.segments} tone="sky" />
          <ChipRow label="Geography" items={profile.market?.geo} tone="neutral" />
        </Card>

        <Card title="How you're positioned">
          {profile.positioning?.value_prop && <p className="text-sm">{profile.positioning.value_prop}</p>}
          <ChipRow label="Differentiators" items={profile.positioning?.differentiators} tone="amber" />
        </Card>

        <Card title="How you talk">
          <ChipRow label="Tone" items={profile.voice?.tone} tone="emerald" />
          <ChipRow label="Vocabulary" items={profile.voice?.vocabulary} tone="neutral" />
          <ChipRow label="Do" items={profile.voice?.do} tone="emerald" />
          <ChipRow label="Don't" items={profile.voice?.dont} tone="red" />
        </Card>

        <Card title="What you publish about">
          <div className="space-y-1.5">
            {Object.entries(profile.content_pillars || {}).map(([name, desc]) => (
              <div key={name} className="text-sm">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-violet-100 text-violet-800 px-1.5 py-0.5 text-[11px] font-medium">
                    {name}
                  </span>
                </div>
                {desc && <div className="text-xs text-neutral-600 mt-0.5 ml-0.5">{desc}</div>}
              </div>
            ))}
            {Object.keys(profile.content_pillars || {}).length === 0 && (
              <p className="text-sm text-neutral-500">—</p>
            )}
          </div>
        </Card>
      </div>

      {/* Content mix — the one thing worth tweaking directly */}
      <Card title="Content mix" className="mt-3">
        <div className="text-xs text-neutral-500 mb-2">
          0 = all external / curation. 1 = all owned / your own story per cycle.
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-neutral-500 w-20">all external</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={profile.content_mix ?? 0.5}
            onChange={(e) => saveMix(parseFloat(e.target.value))}
            disabled={savingMix}
            className="flex-1"
          />
          <span className="text-[10px] text-neutral-500 w-16 text-right">all owned</span>
          <div className="text-sm tabular-nums w-12 text-right">
            {(profile.content_mix ?? 0.5).toFixed(2)}
          </div>
        </div>
      </Card>

      {/* Learned taste */}
      <div className="grid grid-cols-2 gap-3 mt-6">
        <Card title="Proposed rules" className="border-yellow-200">
          <div className="text-xs text-neutral-500 mb-2">
            Patterns the agent has noticed from your rejects. Confirm to apply, dismiss to ignore.
          </div>
          {learning?.pending_rules?.length ? (
            <div className="space-y-2">
              {learning.pending_rules.map((r) => (
                <div key={r} className="flex items-start gap-2 rounded border border-yellow-200 bg-yellow-50 p-2">
                  <div className="flex-1 text-sm">{r}</div>
                  <button
                    onClick={() => confirmRule(r)}
                    className="text-xs rounded bg-emerald-600 px-2 py-1 text-white hover:bg-emerald-500"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => dismissRule(r)}
                    className="text-xs rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
                  >
                    Dismiss
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-500">
              Nothing yet. Patterns need a few cycles of feedback to surface.
            </p>
          )}
        </Card>

        <Card title="Confirmed rules" className="border-emerald-200">
          <div className="text-xs text-neutral-500 mb-2">
            Rules you've accepted. The Evaluate node uses these to rank items.
          </div>
          {learning?.confirmed_rules?.length ? (
            <div className="space-y-2">
              {learning.confirmed_rules.map((r) => (
                <div key={r} className="flex items-start gap-2 rounded border border-emerald-200 bg-emerald-50 p-2">
                  <div className="flex-1 text-sm">{r}</div>
                  <button
                    onClick={() => deleteRule(r)}
                    className="text-xs rounded border border-red-200 px-2 py-1 text-red-700 hover:bg-red-50"
                  >
                    Forget
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-500">Nothing confirmed yet.</p>
          )}
        </Card>
      </div>

      {/* Reject reason histogram */}
      {learning?.reason_histogram && Object.keys(learning.reason_histogram).length > 0 && (
        <Card title="Reject reasons (rolling window)" className="mt-3">
          <div className="text-xs text-neutral-500 mb-2">
            Aggregated over your recent rejects. A cluster around one reason will propose a rule above.
          </div>
          <div className="space-y-1.5">
            {Object.entries(learning.reason_histogram)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => {
                const max = Math.max(...Object.values(learning.reason_histogram));
                return (
                  <div key={reason} className="flex items-center gap-3 text-sm">
                    <div className="w-40 text-neutral-600 text-xs">{reason}</div>
                    <div className="flex-1 h-2 bg-neutral-100 rounded overflow-hidden">
                      <div
                        className="h-2 bg-neutral-500 rounded"
                        style={{ width: `${(n / max) * 100}%` }}
                      />
                    </div>
                    <div className="w-8 text-right text-xs tabular-nums text-neutral-500">{n}</div>
                  </div>
                );
              })}
          </div>
        </Card>
      )}

      {/* Raw JSON escape hatch */}
      <div className="mt-6">
        <button
          type="button"
          className="text-xs text-neutral-500 hover:underline"
          onClick={() => setShowJson(!showJson)}
        >
          {showJson ? "▾" : "▸"} Advanced: view / edit raw JSON
        </button>
        {showJson && (
          <div className="mt-2 rounded-lg border border-neutral-200 bg-white p-3">
            <textarea
              value={json}
              onChange={(e) => setJson(e.target.value)}
              spellCheck={false}
              className="w-full h-96 font-mono text-xs rounded border border-neutral-300 bg-white p-3"
            />
            <div className="mt-2 flex justify-end">
              <button
                onClick={saveJson}
                disabled={savingJson}
                className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
              >
                {savingJson ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------- Brand hero ----------------

function BrandHero({
  brand,
  identity,
}: {
  brand?: Brand;
  identity?: Profile["identity"];
}) {
  const refUrl = brand?.reference_image_url
    ? `${BACKEND_URL}${brand.reference_image_url}`
    : null;

  const swatches: { label: string; hex?: string }[] = [
    { label: "Background", hex: brand?.background_color },
    { label: "Text", hex: brand?.text_color },
    { label: "Buttons", hex: brand?.accent_color },
    { label: "2nd accent", hex: brand?.secondary_accent_color || undefined },
    { label: "Tags", hex: brand?.category_tag_color || undefined },
  ].filter((s) => s.hex);

  return (
    <div className="rounded-xl overflow-hidden border border-neutral-200 bg-white">
      <div className="grid grid-cols-[1fr_1fr] gap-0">
        {/* Left: brand reference image */}
        <div className="relative bg-neutral-100 min-h-[220px]">
          {refUrl ? (
            <img
              src={refUrl}
              alt="Brand reference"
              className="w-full h-full object-cover object-top"
            />
          ) : (
            <div className="flex items-center justify-center h-full text-sm text-neutral-400">
              No reference image yet
            </div>
          )}
        </div>

        {/* Right: identity + brand summary */}
        <div className="p-5 flex flex-col gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1">
              Who you are
            </div>
            <p className="text-sm text-neutral-800">
              {identity?.summary || "—"}
            </p>
            {identity?.products && identity.products.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {identity.products.map((p) => (
                  <span
                    key={p}
                    className="text-[11px] rounded bg-amber-100 text-amber-800 px-1.5 py-0.5"
                  >
                    {p}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-neutral-200 pt-3">
            <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-2">
              Brand palette
            </div>
            <div className="flex gap-3 flex-wrap">
              {swatches.map((s) => (
                <div key={s.label} className="flex items-center gap-2">
                  <div
                    className="h-7 w-7 rounded border border-neutral-300 shrink-0"
                    style={{ backgroundColor: s.hex }}
                    title={`${s.label}: ${s.hex}`}
                  />
                  <div className="min-w-0">
                    <div className="text-[10px] text-neutral-700 font-medium">{s.label}</div>
                    <div className="text-[10px] font-mono text-neutral-500">{s.hex}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-neutral-200 pt-3">
            {brand?.typography_feel && (
              <div className="text-xs text-neutral-700">
                <span className="text-neutral-500">Typography:</span> {brand.typography_feel}
                {brand.font_families && brand.font_families.length > 0 && (
                  <span className="text-neutral-500"> · {brand.font_families.join(", ")}</span>
                )}
              </div>
            )}
            {brand?.mood && brand.mood.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {brand.mood.map((m) => (
                  <span
                    key={m}
                    className="text-[11px] rounded bg-fuchsia-100 text-fuchsia-800 px-1.5 py-0.5"
                  >
                    {m}
                  </span>
                ))}
              </div>
            )}
            {brand?.style_notes && (
              <p className="text-xs text-neutral-500 italic mt-2">{brand.style_notes}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------- Small building blocks ----------------

function Card({
  title,
  className = "",
  children,
}: {
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`rounded-lg border bg-white p-4 ${className || "border-neutral-200"}`}>
      <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-2">
        {title}
      </div>
      {children}
    </div>
  );
}

const TONE_CLASS: Record<string, string> = {
  amber: "bg-amber-100 text-amber-800",
  sky: "bg-sky-100 text-sky-800",
  neutral: "bg-neutral-100 text-neutral-700",
  emerald: "bg-emerald-100 text-emerald-800",
  red: "bg-red-100 text-red-800",
};

function ChipRow({
  label,
  items,
  tone,
}: {
  label: string;
  items?: string[];
  tone: string;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-2">
      <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1">
        {label}
      </div>
      <div className="flex flex-wrap gap-1">
        {items.map((t) => (
          <span
            key={t}
            className={`text-[11px] rounded px-1.5 py-0.5 ${TONE_CLASS[tone] || TONE_CLASS.neutral}`}
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}
