"use client";
// My Content — drop your own photo + a short story, and the agent
// materializes it into a newsletter section, a carousel (with your photo
// as the hero slide), a LinkedIn post, and an Instagram caption.
//
// The user's photo is the ground truth: the LLM only reshapes their
// story for each channel — no fabricated facts.

import { useCallback, useEffect, useState } from "react";
import { api, BACKEND_URL, type Brand } from "@/lib/api";

type Upload = {
  upload_id: string;
  title: string | null;
  story: string;
  pillar: string | null;
  photo_url: string;
  created_at: string;
  materialized?: any;
};

type MaterializeResult = {
  newsletter_section: any;
  carousel_slides: {
    role: string;
    big_text: string;
    subhead: string;
    image_prompt: string;
  }[];
  linkedin_post: string;
  instagram_caption: string;
  instagram_hashtags: string[];
  hero_slide_url: string | null;
  generated_slides: { index: number; url: string | null; role: string; error?: string }[];
};

export default function MyContentPage() {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [brand, setBrand] = useState<Brand | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [story, setStory] = useState("");
  const [pillar, setPillar] = useState("");
  const [uploading, setUploading] = useState(false);

  const [openUpload, setOpenUpload] = useState<Upload | null>(null);
  const [materializing, setMaterializing] = useState(false);
  const [buildImages, setBuildImages] = useState(false);
  const [result, setResult] = useState<MaterializeResult | null>(null);
  // Cache-buster for generated images — refreshed only when a materialize
  // run produces new images, so re-renders don't refetch every image.
  const [imgBuster, setImgBuster] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const [r, p] = await Promise.all([
        api.listUploads(),
        api.getProfile().catch(() => null),
      ]);
      setUploads(r.uploads as Upload[]);
      setBrand(p?.brand);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function onPickFile(next: File | null) {
    setFile(next);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(next ? URL.createObjectURL(next) : null);
  }

  async function submitUpload() {
    if (!file || !story.trim()) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadContent(file, {
        story: story.trim(),
        title: title.trim() || undefined,
        pillar: pillar.trim() || undefined,
      });
      setFile(null);
      setPreviewUrl(null);
      setTitle("");
      setStory("");
      setPillar("");
      load();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setUploading(false);
    }
  }

  async function removeUpload(u: Upload) {
    if (!confirm(`Delete "${u.title || u.story.slice(0, 40)}"?`)) return;
    try {
      await api.deleteUpload(u.upload_id);
      if (openUpload?.upload_id === u.upload_id) {
        setOpenUpload(null);
        setResult(null);
      }
      load();
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }

  async function materialize(u: Upload) {
    setOpenUpload(u);
    setMaterializing(true);
    setResult(null);
    setError(null);
    try {
      const r = await api.materializeUpload(u.upload_id, buildImages);
      setResult(r);
      setImgBuster(Date.now());
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setMaterializing(false);
    }
  }

  return (
    <div className="max-w-5xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">My Content</h1>
        <p className="text-sm text-neutral-500">
          Drop your own photo and a short story. The agent turns it into a newsletter section, an Instagram carousel with your photo as the hero, a LinkedIn post, and an IG caption — all in your voice, no invented facts.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* ---------- Upload form ---------- */}
      <section className="rounded-lg border border-neutral-200 bg-white p-4 mb-6">
        <div className="grid grid-cols-[240px_1fr] gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1">
              Photo
            </div>
            <label className="block cursor-pointer">
              <div
                className={`aspect-[4/5] w-full rounded border-2 border-dashed ${
                  previewUrl ? "border-emerald-400" : "border-neutral-300"
                } bg-neutral-50 flex items-center justify-center overflow-hidden`}
              >
                {previewUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={previewUrl} alt="preview" className="w-full h-full object-cover" />
                ) : (
                  <div className="text-xs text-neutral-500 px-2 text-center">
                    Drop a photo or click to pick
                  </div>
                )}
              </div>
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => onPickFile(e.target.files?.[0] || null)}
              />
            </label>
          </div>
          <div className="space-y-2">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Working title (optional) — e.g. 'First Riesling of 2026'"
              className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
            />
            <textarea
              value={story}
              onChange={(e) => setStory(e.target.value)}
              placeholder="Tell us in your own words what happened. Real numbers, real names. The agent won't add facts you didn't include."
              rows={6}
              className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
            />
            <input
              value={pillar}
              onChange={(e) => setPillar(e.target.value)}
              placeholder="Pillar (optional) — e.g. 'place', 'people', 'events'"
              className="w-full rounded border border-neutral-300 px-3 py-2 text-sm"
            />
            <div className="flex justify-end">
              <button
                onClick={submitUpload}
                disabled={!file || !story.trim() || uploading}
                className="rounded bg-neutral-900 px-3 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
              >
                {uploading ? "Uploading…" : "Save upload"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- Uploads list ---------- */}
      <section className="mb-6">
        <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-2">
          Your uploads
        </div>
        {uploads.length === 0 ? (
          <div className="rounded-lg border border-neutral-200 bg-white p-6 text-sm text-neutral-500">
            Nothing uploaded yet. Drop your first photo above.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {uploads.map((u) => (
              <div
                key={u.upload_id}
                className={`rounded-lg border bg-white overflow-hidden ${
                  openUpload?.upload_id === u.upload_id
                    ? "border-emerald-300 shadow-sm"
                    : "border-neutral-200"
                }`}
              >
                <div className="flex gap-3 p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${BACKEND_URL}${u.photo_url}`}
                    alt=""
                    className="h-24 w-24 object-cover rounded shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    {u.title && <div className="font-medium text-sm truncate">{u.title}</div>}
                    <div className="text-xs text-neutral-600 line-clamp-3">{u.story}</div>
                    {u.pillar && (
                      <span className="inline-block mt-1 text-[10px] rounded bg-violet-100 text-violet-800 px-1.5 py-0.5">
                        {u.pillar}
                      </span>
                    )}
                  </div>
                </div>
                <div className="border-t border-neutral-100 px-3 py-2 flex items-center justify-end gap-2">
                  <button
                    onClick={() => removeUpload(u)}
                    className="text-xs rounded border border-red-200 px-2 py-1 text-red-700 hover:bg-red-50"
                  >
                    Delete
                  </button>
                  <button
                    onClick={() => materialize(u)}
                    disabled={materializing}
                    className="text-xs rounded bg-neutral-900 px-2.5 py-1 text-white hover:bg-neutral-700 disabled:opacity-50"
                  >
                    {materializing && openUpload?.upload_id === u.upload_id
                      ? "Working…"
                      : "Materialize"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ---------- Materialize output ---------- */}
      {openUpload && (
        <section className="rounded-lg border border-neutral-200 bg-white p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="font-semibold">Drafts for &quot;{openUpload.title || openUpload.story.slice(0, 40)}&quot;</h2>
              <p className="text-xs text-neutral-500">
                Only reshapes your story — no fabricated facts. Preview all channels below.
              </p>
            </div>
            <label className="flex items-center gap-2 text-xs text-neutral-600">
              <input
                type="checkbox"
                checked={buildImages}
                onChange={(e) => setBuildImages(e.target.checked)}
              />
              Also generate the 4 AI carousel slides (costs image credits)
            </label>
          </div>

          {materializing && (
            <div className="text-sm text-neutral-500">
              Reshaping your story for each channel…
            </div>
          )}

          {result && (
            <div className="space-y-6">
              {/* Newsletter section */}
              <ChannelCard title="Newsletter section">
                <NewsletterPreview section={result.newsletter_section} brand={brand} />
              </ChannelCard>

              {/* Carousel */}
              <ChannelCard title="Instagram carousel">
                <CarouselStrip
                  heroUrl={result.hero_slide_url}
                  slides={result.carousel_slides}
                  generated={result.generated_slides}
                  brand={brand}
                  imgBuster={imgBuster}
                />
              </ChannelCard>

              {/* LinkedIn */}
              <ChannelCard title="LinkedIn post">
                <p className="text-sm whitespace-pre-wrap">{result.linkedin_post}</p>
              </ChannelCard>

              {/* Instagram caption */}
              <ChannelCard title="Instagram caption">
                <p className="text-sm whitespace-pre-wrap">{result.instagram_caption}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {result.instagram_hashtags.map((h) => (
                    <span
                      key={h}
                      className="text-[11px] rounded bg-sky-100 text-sky-800 px-1.5 py-0.5"
                    >
                      #{h.replace(/^#/, "")}
                    </span>
                  ))}
                </div>
              </ChannelCard>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------- Building blocks ----------

function ChannelCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-neutral-200 p-3">
      <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-2">
        {title}
      </div>
      {children}
    </div>
  );
}

function NewsletterPreview({
  section,
  brand,
}: {
  section: any;
  brand?: Brand;
}) {
  const bg = brand?.background_color || "#0a0a0a";
  const fg = brand?.text_color || "#ffffff";
  const accent = brand?.accent_color || "#1a3fd8";
  const highlight = brand?.secondary_accent_color || accent;
  return (
    <article
      className="rounded border border-neutral-200"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="p-4">
        {section.category && (
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
            {section.category}
          </span>
        )}
        {section.heading && (
          <h2 className="text-lg font-extrabold text-neutral-900 leading-tight mt-2 mb-1">
            {section.heading}
          </h2>
        )}
        {section.body_markdown && (
          <p className="text-sm text-neutral-700">
            <Highlighted text={section.body_markdown} term={section.highlight_term} color={highlight} />
          </p>
        )}
      </div>
    </article>
  );
}

function Highlighted({
  text,
  term,
  color,
}: {
  text?: string;
  term?: string;
  color: string;
}) {
  if (!text || !term) return <>{text}</>;
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

function CarouselStrip({
  heroUrl,
  slides,
  generated,
  brand,
  imgBuster,
}: {
  heroUrl: string | null;
  slides: { role: string; big_text: string; subhead: string; image_prompt: string }[];
  generated: { index: number; url: string | null; role: string; error?: string }[];
  brand?: Brand;
  imgBuster: number;
}) {
  const generatedByIdx = new Map(generated.map((g) => [g.index, g]));

  return (
    <div className="grid grid-cols-5 gap-2">
      {/* Slide 0: the user's photo */}
      <div className="rounded border border-neutral-200 overflow-hidden bg-neutral-50">
        <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-neutral-500 bg-white border-b border-neutral-200">
          1 · hero (your photo)
        </div>
        <div className="aspect-[4/5] bg-neutral-200">
          {heroUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`${BACKEND_URL}${heroUrl}?t=${imgBuster}`}
              alt="hero"
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-xs text-neutral-500">
              hero missing
            </div>
          )}
        </div>
      </div>

      {/* Slides 1-4: AI-generated */}
      {slides.map((s, i) => {
        const g = generatedByIdx.get(i + 1);
        return (
          <div key={i} className="rounded border border-neutral-200 overflow-hidden bg-neutral-50">
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-neutral-500 bg-white border-b border-neutral-200">
              {i + 2} · {s.role}
            </div>
            <div
              className="aspect-[4/5]"
              style={{ background: brand?.background_color || "#111" }}
            >
              {g?.url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`${BACKEND_URL}${g.url}?t=${imgBuster}`}
                  alt={s.role}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full p-2 flex flex-col justify-center text-center">
                  <div className="text-xs font-bold" style={{ color: brand?.accent_color || "#1a3fd8" }}>
                    {s.big_text}
                  </div>
                  <div className="text-[10px] mt-1" style={{ color: brand?.text_color || "#fff" }}>
                    {s.subhead}
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
