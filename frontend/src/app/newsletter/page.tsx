"use client";
// Newsletter — WYSIWYG preview matching the email HTML the backend renders.
// Uses the brand palette from the profile so the preview mirrors what
// lands in the inbox.

import { useCallback, useEffect, useState } from "react";
import { api, type Brand, type NewsletterDraft } from "@/lib/api";

const LAYOUTS = ["digest", "editorial", "single-story"] as const;

export default function NewsletterPage() {
  const [draft, setDraft] = useState<NewsletterDraft | null>(null);
  const [brand, setBrand] = useState<Brand | undefined>(undefined);
  const [identity, setIdentity] = useState<{ summary?: string } | undefined>(undefined);
  const [handle, setHandle] = useState<string>("");
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [publishResult, setPublishResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const savedCycle =
        typeof window !== "undefined" ? localStorage.getItem("signal:cycle_id") : null;
      const [draftsRes, profile] = await Promise.all([
        savedCycle ? api.getDrafts(savedCycle) : api.getDrafts(),
        api.getProfile().catch(() => null),
      ]);
      const drafts: any = draftsRes.drafts;
      if (drafts?.newsletter) {
        setDraft(drafts.newsletter);
        setCycleId(drafts.cycle_id || savedCycle || null);
      }
      if (profile) {
        setBrand(profile.brand);
        setIdentity(profile.identity);
        setHandle(profile.brand?.social_handle || "");
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
      const nl = (r.drafts as any)?.newsletter;
      if (nl) setDraft(nl);
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
    <div className="max-w-4xl">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Newsletter</h1>
          <p className="text-sm text-neutral-500">
            Rendered exactly as it will land in the inbox — palette drawn from your brand.
          </p>
        </div>
        {draft && (
          <div className="flex gap-2 items-center shrink-0">
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
              className="ml-1 rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
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
          {publishResult.mode === "real" ? "Sent." : "Sent (preview)."} Mode:{" "}
          <code>{publishResult.mode}</code>
          {publishResult.external_id && (
            <>
              , id: <code>{publishResult.external_id}</code>
            </>
          )}
        </div>
      )}

      {!draft && (
        <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500">
          No draft yet. Finish a review on the Review tab first — items you tagged for 📧 Newsletter will appear here.
        </div>
      )}

      {draft && (
        <NewsletterPreview draft={draft} brand={brand} identity={identity} handle={handle} />
      )}
    </div>
  );
}

// ---------- WYSIWYG preview matching backend Jinja email template ----------

function NewsletterPreview({
  draft,
  brand,
  identity,
  handle,
}: {
  draft: NewsletterDraft;
  brand?: Brand;
  identity?: { summary?: string };
  handle: string;
}) {
  const bg = brand?.background_color || "#0a0a0a";
  const fg = brand?.text_color || "#ffffff";
  const accent = brand?.accent_color || "#1a3fd8";
  const highlight = brand?.secondary_accent_color || accent;

  const brandName = derivedWordmark(handle, identity?.summary);
  const [wordmarkFirst, ...wordmarkRest] = brandName.split(" ");
  const wordmarkTail = wordmarkRest.join(" ");

  const date = new Date().toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).toUpperCase();

  return (
    <div className="rounded-xl bg-neutral-100 p-6">
      <div className="mx-auto max-w-[640px] bg-white rounded-md shadow-sm overflow-hidden">
        {/* HERO */}
        <div style={{ background: bg, color: fg, padding: "22px 24px" }}>
          <div className="flex items-center justify-between">
            <div>
              <div
                style={{
                  fontSize: "11px",
                  letterSpacing: "0.14em",
                  color: "#8a8a8a",
                  textTransform: "uppercase",
                  marginBottom: "6px",
                }}
              >
                {date}
              </div>
              <div style={{ fontSize: "22px", fontWeight: 800, letterSpacing: "-0.01em" }}>
                {wordmarkTail ? (
                  <>
                    <span
                      style={{
                        background: highlight,
                        color: "#0a0a0a",
                        padding: "0 6px",
                        borderRadius: "2px",
                      }}
                    >
                      {wordmarkFirst}
                    </span>
                    <span style={{ color: fg }}> {wordmarkTail}</span>
                  </>
                ) : (
                  <span style={{ color: fg }}>{wordmarkFirst || "Newsletter"}</span>
                )}
              </div>
            </div>
            <a
              href="#"
              onClick={(e) => e.preventDefault()}
              style={{
                background: accent,
                color: "#ffffff",
                textDecoration: "none",
                padding: "9px 14px",
                borderRadius: "4px",
                fontSize: "13px",
                fontWeight: 600,
              }}
            >
              View online →
            </a>
          </div>
        </div>

        {/* INTRO */}
        <div className="px-6 pt-5 pb-1">
          <div
            style={{
              fontSize: "12px",
              letterSpacing: "0.14em",
              color: "#8a8a8a",
              textTransform: "uppercase",
              marginBottom: "8px",
            }}
          >
            This week's stories
          </div>
          {draft.intro && <div className="text-sm text-neutral-700">{draft.intro}</div>}
        </div>

        {/* SECTIONS */}
        <div className="px-6 py-3 space-y-3">
          {(draft.sections || []).map((s, i) => (
            <article
              key={i}
              className="rounded border border-neutral-200"
              style={{ borderLeft: `3px solid ${accent}` }}
            >
              <div className="p-4">
                {s.category && (
                  <div className="mb-2">
                    <span
                      style={{
                        background: bg,
                        color: fg,
                        padding: "4px 8px",
                        fontSize: "10px",
                        letterSpacing: "0.12em",
                        fontWeight: 700,
                        textTransform: "uppercase",
                        borderRadius: "2px",
                        display: "inline-block",
                      }}
                    >
                      {s.category}
                    </span>
                  </div>
                )}
                {s.heading && (
                  <h2 className="text-lg font-extrabold text-neutral-900 leading-tight mb-2">
                    {s.heading}
                  </h2>
                )}
                {s.body_markdown && (
                  <p className="text-sm text-neutral-700 mb-2">
                    <HighlightedText
                      text={s.body_markdown}
                      term={s.highlight_term}
                      color={highlight}
                    />
                  </p>
                )}
                {s.link && (
                  <a
                    href={s.link}
                    target="_blank"
                    style={{ color: accent, fontSize: "13px", fontWeight: 600 }}
                    className="no-underline"
                  >
                    Read →
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>

        {/* SIGNOFF */}
        {draft.signoff && (
          <div className="px-6 pb-5">
            <div className="pt-3 border-t border-neutral-100 text-sm italic text-neutral-700">
              {draft.signoff}
            </div>
          </div>
        )}

        {/* FOOTER */}
        <div
          style={{ background: bg, color: "#999" }}
          className="px-6 py-3 text-[11px] tracking-wide"
        >
          {handle ? `${handle} · ` : ""}Sent via Signal · a draft for review
        </div>
      </div>
    </div>
  );
}

function HighlightedText({
  text,
  term,
  color,
}: {
  text: string;
  term?: string;
  color: string;
}) {
  if (!term) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(term.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <span
        style={{
          background: color,
          color: "#0a0a0a",
          padding: "0 3px",
          borderRadius: "2px",
          fontWeight: 600,
        }}
      >
        {text.slice(idx, idx + term.length)}
      </span>
      {text.slice(idx + term.length)}
    </>
  );
}

function derivedWordmark(handle: string, summary?: string): string {
  if (handle) {
    const raw = handle.replace(/^@/, "");
    // camel-case → spaced: ChinaTechSignal → China Tech Signal
    return raw
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }
  if (summary) {
    const first = summary.split(".")[0].trim();
    const words = first.split(/\s+/).slice(0, 3);
    return words.join(" ");
  }
  return "Newsletter";
}
