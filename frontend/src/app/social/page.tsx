"use client";
// Social — carousel builder + LinkedIn draft.
//
// Two panes:
//   1. Instagram carousel builder — pick a story tagged 📷 Instagram in
//      the current cycle, plan 5 slides, generate images (Nano Banana 2),
//      preview, and queue to Buffer.
//   2. LinkedIn — the drafted post from Write, with Approve · queue button.
//
// Both use the brand palette from your onboarding.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Brand, type Candidate } from "@/lib/api";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8765";

type SlidePlan = {
  role: string;
  big_text: string;
  subhead: string;
  image_prompt: string;
};

type Outcome = {
  index: number;
  url: string | null;
  role: string;
  error?: string;
};

export default function SocialPage() {
  const [drafts, setDrafts] = useState<any>(null);
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [brand, setBrand] = useState<Brand | undefined>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const [pubResults, setPubResults] = useState<Record<string, any>>({});
  const [error, setError] = useState<string | null>(null);

  // Carousel state per-item (id → plan + outcomes)
  const [selectedStory, setSelectedStory] = useState<Candidate | null>(null);
  const [plan, setPlan] = useState<SlidePlan[] | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [planning, setPlanning] = useState(false);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    try {
      const saved =
        typeof window !== "undefined"
          ? localStorage.getItem("signal:cycle_id")
          : null;
      const [draftsRes, profile, queue] = await Promise.all([
        saved ? api.getDrafts(saved) : api.getDrafts(),
        api.getProfile().catch(() => null),
        saved ? api.getQueue(saved).catch(() => ({ candidates: [] })) : { candidates: [] as Candidate[] },
      ]);
      const d: any = draftsRes.drafts;
      if (d) {
        setDrafts(d);
        setCycleId(d.cycle_id || saved || null);
      }
      if (profile) setBrand(profile.brand);
      setCandidates((queue.candidates as Candidate[]) || []);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function planCarousel(story: Candidate) {
    if (!cycleId) return;
    setSelectedStory(story);
    setPlan(null);
    setOutcomes([]);
    setPlanning(true);
    setError(null);
    try {
      const r = await api.carouselPlan(cycleId, story.id);
      setPlan(r.slides as SlidePlan[]);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setPlanning(false);
    }
  }

  async function generateAll() {
    if (!cycleId || !selectedStory || !plan) return;
    setGenerating(true);
    setError(null);
    try {
      const r = await api.carouselGenerate(cycleId, selectedStory.id, { slides: plan });
      setOutcomes(r.outcomes);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function regenerateSlide(index: number) {
    if (!cycleId || !selectedStory || !plan) return;
    setGenerating(true);
    setError(null);
    try {
      const r = await api.carouselGenerate(cycleId, selectedStory.id, {
        slides: plan,
        only_slide: index,
      });
      setOutcomes((prev) => {
        const map = new Map(prev.map((o) => [o.index, o]));
        r.outcomes.forEach((o) => map.set(o.index, o));
        return Array.from(map.values()).sort((a, b) => a.index - b.index);
      });
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function publishLinkedIn() {
    if (!cycleId) return;
    setBusy("linkedin");
    setError(null);
    try {
      const r = await api.publish(cycleId, "linkedin");
      setPubResults((s) => ({ ...s, linkedin: r.result }));
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function publishInstagramCaption() {
    // Simple IG text post via Buffer (no carousel yet). Retained for parity.
    if (!cycleId) return;
    setBusy("instagram");
    setError(null);
    try {
      const r = await api.publish(cycleId, "instagram");
      setPubResults((s) => ({ ...s, instagram: r.result }));
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  const igStories = useMemo(() => {
    // Any candidate that made it into approved-for-IG this cycle appears
    // in drafts.instagram... but we don't currently persist per-channel
    // approvals to state after finish_review. Fall back to any FEATURE
    // candidate so the picker isn't empty on first visit.
    if (!candidates.length) return [];
    return candidates.filter((c) => c.route === "feature").slice(0, 8);
  }, [candidates]);

  return (
    <div className="max-w-5xl">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">Social</h1>
        <p className="text-sm text-neutral-500">
          Build one Instagram carousel per story, plus your LinkedIn take. Both use your brand palette.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* ========= Instagram Carousel ========= */}
      <section className="mb-8 rounded-lg border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-5 py-3">
          <h2 className="font-semibold">Instagram carousel</h2>
          <p className="text-xs text-neutral-500">
            Nano Banana 2 · style-conditioned on your homepage screenshot · 5 slides.
          </p>
        </div>

        {!selectedStory ? (
          <div className="p-5">
            <div className="text-sm text-neutral-600 mb-3">
              Pick a story to build a carousel for. (Right now shows all feature-recommended items — I'll wire per-channel approval next.)
            </div>
            <div className="grid gap-2">
              {igStories.map((c) => (
                <button
                  key={c.id}
                  onClick={() => planCarousel(c)}
                  className="text-left rounded border border-neutral-200 p-3 hover:bg-neutral-50"
                >
                  <div className="flex items-center gap-2 mb-1 text-[10px]">
                    <span
                      className={`uppercase tracking-wider rounded px-1.5 py-0.5 ${
                        c.kind === "owned"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-sky-100 text-sky-800"
                      }`}
                    >
                      {c.kind}
                    </span>
                    {c.pillar && (
                      <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-600">
                        {c.pillar}
                      </span>
                    )}
                  </div>
                  <div className="font-medium text-sm">{c.title}</div>
                  <div className="text-xs text-neutral-500 mt-0.5">{c.angle}</div>
                </button>
              ))}
              {igStories.length === 0 && (
                <div className="text-sm text-neutral-500">
                  No stories available. Run a cycle on the Review tab and tag stories for Instagram first.
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="p-5">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-neutral-500">
                  Selected story
                </div>
                <div className="font-medium">{selectedStory.title}</div>
              </div>
              <button
                onClick={() => {
                  setSelectedStory(null);
                  setPlan(null);
                  setOutcomes([]);
                }}
                className="text-xs rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-100"
              >
                ← back
              </button>
            </div>

            {planning && (
              <div className="text-sm text-neutral-500">
                Planning slides… (LLM plans exactly 5: hero → stat → context → implication → CTA)
              </div>
            )}

            {plan && !planning && (
              <>
                <SlidePlanReview
                  plan={plan}
                  setPlan={setPlan}
                  outcomes={outcomes}
                  onRegenerate={regenerateSlide}
                  brand={brand}
                  generating={generating}
                />

                <div className="mt-4 flex items-center justify-between">
                  <div className="text-xs text-neutral-500">
                    {outcomes.length === 0
                      ? "Preview mode returns placeholder PNGs — flip PUBLISH_MODE=real for actual Nano Banana 2 renders."
                      : `${outcomes.filter((o) => o.url).length}/${plan.length} slides generated.`}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={generateAll}
                      disabled={generating}
                      className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
                    >
                      {generating
                        ? "Generating…"
                        : outcomes.length
                        ? "Regenerate all"
                        : "Generate images"}
                    </button>
                    <button
                      onClick={publishInstagramCaption}
                      disabled={busy === "instagram" || outcomes.filter((o) => o.url).length < 5}
                      className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
                      title="Buffer's IG carousel API needs publicly-reachable image URLs. Localhost URLs won't work until you deploy or tunnel via ngrok."
                    >
                      Approve · queue to Buffer
                    </button>
                  </div>
                </div>
                {pubResults.instagram && (
                  <div className="mt-3 text-xs text-emerald-700">
                    Queued — mode: {pubResults.instagram.mode}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </section>

      {/* ========= LinkedIn ========= */}
      {drafts?.linkedin && (
        <section className="rounded-lg border border-neutral-200 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <div>
              <h2 className="font-medium">LinkedIn</h2>
              <div className="text-xs text-neutral-500">
                Claim or number in the first line. Ends on a specific ask.
              </div>
            </div>
            <button
              onClick={publishLinkedIn}
              disabled={busy === "linkedin"}
              className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              Approve · queue to Buffer
            </button>
          </div>
          <p className="text-sm whitespace-pre-wrap">{drafts.linkedin.post}</p>
          {pubResults.linkedin && (
            <div className="mt-3 text-xs text-emerald-700">
              Queued — mode: {pubResults.linkedin.mode}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------- SlidePlanReview ----------------

function SlidePlanReview({
  plan,
  setPlan,
  outcomes,
  onRegenerate,
  brand,
  generating,
}: {
  plan: SlidePlan[];
  setPlan: (s: SlidePlan[]) => void;
  outcomes: Outcome[];
  onRegenerate: (index: number) => void;
  brand?: Brand;
  generating: boolean;
}) {
  const outcomeByIdx = new Map(outcomes.map((o) => [o.index, o]));

  function updateSlide(i: number, patch: Partial<SlidePlan>) {
    const next = plan.map((s, idx) => (idx === i ? { ...s, ...patch } : s));
    setPlan(next);
  }

  return (
    <div className="grid grid-cols-5 gap-3">
      {plan.map((s, i) => {
        const outcome = outcomeByIdx.get(i);
        const url = outcome?.url;
        return (
          <div
            key={i}
            className="rounded border border-neutral-200 overflow-hidden bg-neutral-50"
          >
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-neutral-500 bg-white border-b border-neutral-200 flex items-center justify-between">
              <span>
                {i + 1} · {s.role}
              </span>
              {outcome?.error && (
                <span
                  className="text-red-600 text-[10px] cursor-help"
                  title={outcome.error}
                >
                  err
                </span>
              )}
            </div>
            <div className="relative aspect-[4/5] bg-neutral-200">
              {url ? (
                <img
                  src={`${BACKEND}${url}?t=${Date.now()}`}
                  alt={s.role}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center p-2 text-center">
                  <div
                    className="w-full h-full rounded"
                    style={{ background: brand?.background_color || "#0a0a0a" }}
                  />
                </div>
              )}
              {url && !generating && (
                <button
                  onClick={() => onRegenerate(i)}
                  className="absolute inset-0 flex items-center justify-center bg-black/60 text-white text-xs opacity-0 hover:opacity-100 transition"
                  title="Regenerate just this slide"
                >
                  regenerate
                </button>
              )}
            </div>
            <div className="p-2 space-y-1">
              <input
                value={s.big_text}
                onChange={(e) => updateSlide(i, { big_text: e.target.value })}
                placeholder="Big text"
                className="w-full text-xs font-semibold border-b border-transparent focus:border-neutral-300 outline-none bg-transparent"
              />
              <input
                value={s.subhead}
                onChange={(e) => updateSlide(i, { subhead: e.target.value })}
                placeholder="Subhead"
                className="w-full text-[10px] text-neutral-600 border-b border-transparent focus:border-neutral-300 outline-none bg-transparent"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
