"use client";
// Onboarding as a chat conversation:
//   1. Agent greets and asks for the URL.
//   2. User pastes the URL.
//   3. Agent crawls + extracts, then narrates what it understood (profile card).
//   4. User chats corrections in natural language ("change tone to warmer",
//      "drop the ai_monetization pillar", "add SMBs to segments"). Backend
//      /onboard/revise runs each correction through the LLM.
//   5. When the user says "save it" / "looks good", we hit /onboard/confirm
//      and route to Review.

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, BACKEND_URL, type Brand, type Profile } from "@/lib/api";

type Msg =
  | { id: string; role: "agent" | "user"; text: string }
  | { id: string; role: "agent"; kind: "profile"; profile: Profile }
  | { id: string; role: "agent"; kind: "sources"; sources: any[]; accepted: Record<string, boolean> };

type Phase = "await_url" | "reading" | "reviewing" | "confirming" | "done";

const URL_RE = /(https?:\/\/[^\s]+|(?:www\.)?[a-z0-9-]+\.[a-z]{2,}[^\s]*)/i;

function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function extractUrl(text: string): string | null {
  const m = text.match(URL_RE);
  if (!m) return null;
  const raw = m[1];
  return raw.startsWith("http") ? raw : `https://${raw.replace(/^\/\//, "")}`;
}

export default function OnboardPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("await_url");
  const [messages, setMessages] = useState<Msg[]>([
    {
      id: newId(),
      role: "agent",
      text:
        "Hi! I'm your content agent. Paste the URL of the website you want me to read — I'll figure out who you are, how you talk, and propose a starting setup. Anything odd about my read, you can tell me and I'll adjust before we save.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [proposed, setProposed] = useState<any[]>([]);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  function push(m: Msg) {
    setMessages((h) => [...h, m]);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    push({ id: newId(), role: "user", text });

    // Phase: await_url — try to pull a URL from what they typed
    if (phase === "await_url") {
      const url = extractUrl(text);
      if (!url) {
        push({
          id: newId(),
          role: "agent",
          text: "I need a URL to work with. Paste something like `https://your-site.com` and I'll do the rest.",
        });
        return;
      }
      await runOnboard(url);
      return;
    }

    // Phase: reviewing — chat-driven revision
    if (phase === "reviewing" && profile) {
      await runRevise(text);
      return;
    }
  }

  async function runOnboard(url: string) {
    setPhase("reading");
    setBusy(true);
    try {
      // Inside the try: an invalid-but-regex-matching URL would otherwise
      // throw here and leave the page stuck busy.
      const hostname = new URL(url).hostname;
      push({
        id: newId(),
        role: "agent",
        text: `Reading ${hostname}… crawling homepage + high-signal pages and extracting your voice. This takes 20–40 seconds.`,
      });
      const r = await api.onboard(url);
      const p = r.company_profile;
      const props = r.proposed_sources || [];
      const acc: Record<string, boolean> = {};
      props.forEach((s: any) => (acc[s.url] = true));
      setProfile(p);
      setProposed(props);
      setAccepted(acc);
      push({
        id: newId(),
        role: "agent",
        text: buildNarration(p, r.crawled_pages?.length ?? 0, props.length),
      });
      push({ id: newId(), role: "agent", kind: "profile", profile: p });
      if (props.length > 0) {
        push({ id: newId(), role: "agent", kind: "sources", sources: props, accepted: acc });
      }
      push({
        id: newId(),
        role: "agent",
        text:
          "Anything look off? Tell me in plain language — e.g. *drop the 'proof' pillar*, *change tone to warmer*, *add SMBs to segments*. When you're happy, say **save**.",
      });
      setPhase("reviewing");
    } catch (e: any) {
      push({
        id: newId(),
        role: "agent",
        text: `Something went wrong reading that site: ${e.message || String(e)}. Try another URL?`,
      });
      setPhase("await_url");
    } finally {
      setBusy(false);
    }
  }

  async function runRevise(userText: string) {
    if (!profile) return;
    setBusy(true);
    try {
      const data = await api.onboardRevise(profile, userText);
      const updated: Profile = data.profile;
      const changed = JSON.stringify(updated) !== JSON.stringify(profile);
      setProfile(updated);
      push({ id: newId(), role: "agent", text: data.reply || (changed ? "Updated." : "Got it.") });
      if (changed) {
        push({ id: newId(), role: "agent", kind: "profile", profile: updated });
      }
      if (data.done) {
        await runConfirm(updated);
      }
    } catch (e: any) {
      push({
        id: newId(),
        role: "agent",
        text: `Couldn't apply that: ${e.message || String(e)}. Try rephrasing?`,
      });
    } finally {
      setBusy(false);
    }
  }

  async function runConfirm(finalProfile: Profile) {
    setPhase("confirming");
    push({ id: newId(), role: "agent", text: "Saving your profile and following the sources you kept…" });
    try {
      const merged = proposed.map((s) => ({ ...s, accepted: accepted[s.url] !== false }));
      await api.onboardConfirm({
        company_profile: finalProfile,
        proposed_sources: merged,
      });
      push({
        id: newId(),
        role: "agent",
        text: "Done. Head to the **Review** tab to start your first content cycle.",
      });
      setPhase("done");
      setTimeout(() => router.push("/"), 1500);
    } catch (e: any) {
      push({ id: newId(), role: "agent", text: `Couldn't save: ${e.message || String(e)}` });
      setPhase("reviewing");
    }
  }

  return (
    <div className="max-w-3xl">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold">Onboard</h1>
        <p className="text-sm text-neutral-500">
          Chat with the agent to set up your content pipeline.
        </p>
      </div>

      <div
        ref={scrollRef}
        className="h-[65vh] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 space-y-3"
      >
        {messages.map((m) => (
          <MessageView
            key={m.id}
            m={m}
            accepted={accepted}
            setAccepted={setAccepted}
          />
        ))}
        {busy && <TypingIndicator />}
      </div>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy || phase === "reading" || phase === "confirming" || phase === "done"}
          placeholder={
            phase === "await_url"
              ? "Paste your homepage URL…"
              : phase === "reviewing"
              ? "Tell me what to change, or say 'save' when you're done"
              : "…"
          }
          className="flex-1 rounded border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-neutral-500"
        />
        <button
          type="submit"
          disabled={!input.trim() || busy}
          className="rounded bg-neutral-900 px-3 py-2 text-sm text-white disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}

// -------------------- Message view --------------------

function MessageView({
  m,
  accepted,
  setAccepted,
}: {
  m: Msg;
  accepted: Record<string, boolean>;
  setAccepted: (r: Record<string, boolean>) => void;
}) {
  if ("kind" in m && m.kind === "profile") {
    return <ProfileCard profile={m.profile} />;
  }
  if ("kind" in m && m.kind === "sources") {
    return <SourcesCard sources={m.sources} accepted={accepted} setAccepted={setAccepted} />;
  }
  const isUser = m.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
          isUser
            ? "bg-neutral-900 text-white"
            : "bg-neutral-100 text-neutral-800"
        }`}
      >
        {"text" in m ? renderInline(m.text) : ""}
      </div>
    </div>
  );
}

// Very-light markdown: **bold** and `code` and *italic*.
function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<b key={key++}>{tok.slice(2, -2)}</b>);
    else if (tok.startsWith("*")) parts.push(<i key={key++}>{tok.slice(1, -1)}</i>);
    else if (tok.startsWith("`")) parts.push(<code key={key++} className="rounded bg-neutral-200 px-1 text-xs">{tok.slice(1, -1)}</code>);
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-neutral-100 rounded-lg px-3 py-2 text-sm text-neutral-500 italic">
        thinking…
      </div>
    </div>
  );
}

// -------------------- Profile card (as chat message) --------------------

function ProfileCard({ profile }: { profile: Profile }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] rounded-lg border border-neutral-200 bg-white p-3 text-sm w-full">
        <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-2">
          What I understood
        </div>
        <div className="grid grid-cols-2 gap-3">
          <MiniCard title="Who you are">
            <div className="text-xs text-neutral-700">
              {profile.identity?.summary || "—"}
            </div>
            <ChipList label="Products" items={profile.identity?.products} tone="amber" />
          </MiniCard>
          <MiniCard title="Who you sell to">
            <div className="text-xs text-neutral-700">{profile.market?.icp || "—"}</div>
            <ChipList label="Segments" items={profile.market?.segments} tone="sky" />
            <ChipList label="Geography" items={profile.market?.geo} tone="neutral" />
          </MiniCard>
          <MiniCard title="How you talk">
            <ChipList label="Tone" items={profile.voice?.tone} tone="emerald" />
            <ChipList label="Do" items={profile.voice?.do} tone="emerald" />
            <ChipList label="Don't" items={profile.voice?.dont} tone="red" />
          </MiniCard>
          <MiniCard title="What you publish about">
            <div className="flex flex-wrap gap-1">
              {Object.entries(profile.content_pillars || {}).map(([name, desc]) => (
                <span
                  key={name}
                  title={desc}
                  className="text-[10px] rounded bg-violet-100 text-violet-800 px-1.5 py-0.5"
                >
                  {name}
                </span>
              ))}
            </div>
            <div className="mt-2 text-[10px] text-neutral-500">
              content mix: {(profile.content_mix ?? 0.5).toFixed(2)} (0 = all external, 1 = all owned)
            </div>
          </MiniCard>
          <div className="col-span-2">
            <BrandCard brand={profile.brand} />
          </div>
        </div>
      </div>
    </div>
  );
}

function BrandCard({ brand }: { brand?: Brand }) {
  if (!brand) return null;
  // Each swatch is labeled with what it maps to visually. If the model
  // didn't populate a role (single-accent site), the swatch is skipped.
  const swatches: { label: string; role: string; hex?: string }[] = [
    { label: "Background", role: "large surfaces", hex: brand.background_color },
    { label: "Text", role: "body copy", hex: brand.text_color },
    { label: "Buttons", role: "primary CTA", hex: brand.accent_color },
    { label: "2nd accent", role: "underlines, rules", hex: brand.secondary_accent_color || undefined },
    { label: "Tags", role: "category chips", hex: brand.category_tag_color || undefined },
  ].filter((s) => s.hex);

  const refUrl = brand.reference_image_url
    ? `${BACKEND_URL}${brand.reference_image_url}?t=${Date.now()}`
    : null;

  return (
    <div className="rounded border border-neutral-200 p-3">
      <div className="text-[9px] uppercase tracking-wider text-neutral-500 mb-2">
        Your look and feel
      </div>

      {refUrl && (
        <div className="mb-3">
          <div className="text-[10px] text-neutral-500 mb-1">
            Reference (what we&apos;ll match on every generated image):
          </div>
          <img
            src={refUrl}
            alt="Brand reference"
            className="w-full max-h-40 object-cover object-top rounded border border-neutral-200"
          />
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3">
        {swatches.map((s) => (
          <div key={s.label} className="flex items-center gap-2">
            <div
              className="h-8 w-8 rounded border border-neutral-200 shrink-0"
              style={{ backgroundColor: s.hex }}
              title={`${s.label}: ${s.hex}`}
            />
            <div className="min-w-0">
              <div className="text-[10px] font-medium text-neutral-700">{s.label}</div>
              <div className="text-[9px] text-neutral-500">{s.role}</div>
              <div className="text-[9px] font-mono text-neutral-500">{s.hex}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-1">
        {brand.typography_feel && (
          <div className="text-[10px] text-neutral-600">
            <span className="text-neutral-500">Typography:</span> {brand.typography_feel}
            {brand.font_families && brand.font_families.length > 0 && (
              <span className="text-neutral-500"> · {brand.font_families.join(", ")}</span>
            )}
          </div>
        )}
        {brand.mood && brand.mood.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {brand.mood.map((m) => (
              <span
                key={m}
                className="text-[10px] rounded bg-fuchsia-100 text-fuchsia-800 px-1.5 py-0.5"
              >
                {m}
              </span>
            ))}
          </div>
        )}
        {brand.style_notes && (
          <div className="text-[10px] text-neutral-500 italic">{brand.style_notes}</div>
        )}
        {brand.social_handle && (
          <div className="text-[10px] text-neutral-600">{brand.social_handle}</div>
        )}
      </div>
    </div>
  );
}


function MiniCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-neutral-200 p-2">
      <div className="text-[9px] uppercase tracking-wider text-neutral-500 mb-1">
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

function ChipList({
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
      <div className="text-[9px] uppercase tracking-wider text-neutral-500 mb-1">{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.map((t) => (
          <span
            key={t}
            className={`text-[10px] rounded px-1.5 py-0.5 ${TONE_CLASS[tone] || TONE_CLASS.neutral}`}
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

// -------------------- Sources card (as chat message) --------------------

function SourcesCard({
  sources,
  accepted,
  setAccepted,
}: {
  sources: any[];
  accepted: Record<string, boolean>;
  setAccepted: (r: Record<string, boolean>) => void;
}) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] w-full rounded-lg border border-neutral-200 bg-white p-3 text-sm">
        <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-2">
          Outlets I propose to follow
        </div>
        <div className="divide-y divide-neutral-100">
          {sources.map((s) => (
            <label
              key={s.url}
              className="py-2 flex items-start gap-2 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={accepted[s.url] !== false}
                onChange={(e) =>
                  setAccepted({ ...accepted, [s.url]: e.target.checked })
                }
                className="mt-1"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="text-xs font-medium truncate">{s.name || s.url}</div>
                  <span
                    className={`text-[9px] uppercase tracking-wider rounded px-1 py-0.5 ${
                      s.kind === "rss"
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-neutral-100 text-neutral-600"
                    }`}
                  >
                    {s.kind}
                  </span>
                </div>
                <div className="text-[10px] text-neutral-500 truncate">
                  {s.root_url || s.url}
                </div>
              </div>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

// -------------------- Narration builder --------------------

function buildNarration(p: Profile, nPages: number, nSources: number): string {
  const summary = p.identity?.summary?.trim() || "Got a rough read.";
  const tone = (p.voice?.tone || []).slice(0, 3).join(", ");
  const dont = (p.voice?.dont || []).slice(0, 2).join(", ");
  const pillars = Object.keys(p.content_pillars || {}).slice(0, 5).join(", ");
  const mix = p.content_mix ?? 0.5;
  const mixLabel =
    mix >= 0.7 ? "owned-heavy (your own story dominates)" :
    mix <= 0.3 ? "external-heavy (industry curation dominates)" :
                 "balanced";

  const parts: string[] = [];
  parts.push(`Read ${nPages} page${nPages === 1 ? "" : "s"}. Here's my read:`);
  parts.push(`**Who you are.** ${summary}`);
  if (tone) parts.push(`**How you talk.** ${tone}${dont ? ` — and you avoid ${dont}.` : "."}`);
  if (pillars) parts.push(`**What you publish about.** ${pillars}.`);
  parts.push(`**Content mix.** ${mix.toFixed(2)} — ${mixLabel}.`);

  const brand = p.brand;
  if (brand && (brand.mood?.length || brand.style_notes)) {
    const moodStr = (brand.mood || []).slice(0, 3).join(", ");
    parts.push(`**Look and feel.** ${moodStr}${brand.typography_feel ? ` · ${brand.typography_feel}` : ""}. I'll use this palette for anything I generate (carousels, newsletter headers) so your brand stays consistent.`);
  }

  if (nSources > 0) parts.push(`I also found ${nSources} credible outlet${nSources === 1 ? "" : "s"} that fit your space — you'll see them below.`);
  return parts.join("\n\n");
}
