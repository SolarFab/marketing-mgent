// Thin fetch wrapper around the FastAPI backend.
//
// All calls go through `req(...)` which handles JSON, error surfacing,
// and the `NEXT_PUBLIC_BACKEND_URL` base. Every module in the UI imports
// from here so a URL/prefix change is a one-file edit.

export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export const COMPANY_ID = process.env.NEXT_PUBLIC_COMPANY_ID ?? "demo";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

type Init = Omit<RequestInit, "body"> & { body?: unknown };

async function req<T>(path: string, init: Init = {}): Promise<T> {
  const url = path.startsWith("http") ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers as Record<string, string> | undefined),
    },
    body: init.body ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(
      typeof data?.detail === "string" ? data.detail : res.statusText,
      res.status,
      data,
    );
  }
  return data as T;
}

// ---------- typed endpoints ----------

export type Brand = {
  primary_color?: string;
  accent_color?: string;
  secondary_accent_color?: string;
  category_tag_color?: string;
  background_color?: string;
  text_color?: string;
  typography_feel?: string;
  mood?: string[];
  style_notes?: string;
  social_handle?: string;
  reference_image_url?: string;
  font_families?: string[];
};

export type Profile = {
  identity?: { summary?: string; products?: string[] };
  market?: { segments?: string[]; geo?: string[]; icp?: string };
  positioning?: { value_prop?: string; differentiators?: string[] };
  voice?: { tone?: string[]; vocabulary?: string[]; do?: string[]; dont?: string[] };
  content_pillars?: Record<string, string>;
  content_mix?: number;
  brand?: Brand;
};

export type Source = {
  source_id: string;
  company_id: string;
  url: string;
  name?: string;
  kind: string;
  status: string;
  origin: string;
  reason?: string;
  items_surfaced: number;
  items_approved: number;
};

export type Candidate = {
  id: string;
  kind: "owned" | "external";
  title: string;
  angle: string;
  pillar?: string;
  source_id?: string;
  url?: string;
  published_date?: string | null;
  score?: {
    relevance: number;
    novelty: number;
    pillar_fit: number;
    source_hit: number;
    pref_boost: number;
    final: number;
  };
  route?: "feature" | "uncertain" | "discard";
  rationale?: string;
};

export type NewsletterDraft = {
  subject?: string;
  preheader?: string;
  intro?: string;
  sections?: { heading?: string; body_markdown?: string; link?: string }[];
  signoff?: string;
  layout?: string;
};

export const api = {
  root: () => req<{ name: string; version: string; publish_mode: string }>("/"),

  // onboarding
  onboard: (url: string, company_id?: string) =>
    req<{
      company_id: string;
      company_profile: Profile;
      proposed_sources: (Source & { accepted?: boolean })[];
      crawled_pages: { url: string; title: string }[];
    }>("/onboard", { method: "POST", body: { url, company_id: company_id ?? COMPANY_ID } }),

  onboardConfirm: (payload: {
    company_id?: string;
    company_profile: Profile;
    proposed_sources: unknown[];
  }) =>
    req<{ status: string; company_id: string }>("/onboard/confirm", {
      method: "POST",
      body: { ...payload, company_id: payload.company_id ?? COMPANY_ID },
    }),

  onboardRevise: (current_profile: Profile, message: string) =>
    req<{ profile: Profile; reply: string; done: boolean }>("/onboard/revise", {
      method: "POST",
      body: { current_profile, message },
    }),

  // profile
  getProfile: () =>
    req<Profile>(`/profile?company_id=${encodeURIComponent(COMPANY_ID)}`),
  updateProfile: (profile: Profile) =>
    req<{ status: string; profile: Profile }>("/profile", {
      method: "PUT",
      body: { company_id: COMPANY_ID, profile },
    }),

  // sources
  listSources: () =>
    req<{ sources: Source[] }>(`/sources?company_id=${encodeURIComponent(COMPANY_ID)}`),
  addSource: (url: string, kind = "web", name?: string) =>
    req<{ source: Source }>("/sources", {
      method: "POST",
      body: { company_id: COMPANY_ID, url, kind, name },
    }),
  patchSource: (source_id: string, status: "active" | "paused") =>
    req<{ status: string }>(`/sources/${source_id}`, {
      method: "PATCH",
      body: { status },
    }),
  deleteSource: (source_id: string) =>
    req<{ status: string }>(`/sources/${source_id}`, { method: "DELETE" }),
  discoverSources: () =>
    req<{ proposed: number; sources: Source[] }>("/sources/discover", {
      method: "POST",
      body: { company_id: COMPANY_ID },
    }),
  acceptSource: (source_id: string) =>
    req<{ status: string }>(`/sources/${source_id}/accept`, { method: "POST" }),

  // cycle
  runCycle: () =>
    req<{ cycle_id: string; candidates: Candidate[] }>("/cycle/run", {
      method: "POST",
      body: { company_id: COMPANY_ID },
    }),
  getQueue: (cycle_id: string) =>
    req<{ cycle_id: string; candidates: Candidate[] }>(
      `/queue?cycle_id=${encodeURIComponent(cycle_id)}`,
    ),
  submitFeedback: (payload: {
    item_id: string;
    decision: "approve" | "reject";
    reason_code?: string;
    note?: string;
    source_id?: string;
    cycle_id?: string;
  }) =>
    req<{ status: string }>("/feedback", {
      method: "POST",
      body: { ...payload, company_id: COMPANY_ID },
    }),
  finishReview: (cycle_id: string, approved_ids: string[]) =>
    req<{ cycle_id: string; drafts: unknown }>("/cycle/finish_review", {
      method: "POST",
      body: { cycle_id, approved_ids, company_id: COMPANY_ID },
    }),

  // drafts / publish
  getDrafts: (cycle_id?: string) => {
    const q = cycle_id
      ? `cycle_id=${encodeURIComponent(cycle_id)}`
      : `company_id=${encodeURIComponent(COMPANY_ID)}`;
    return req<{ drafts: any }>(`/drafts?${q}`);
  },
  rewrite: (cycle_id: string, layout?: string) =>
    req<{ drafts: any }>("/write", {
      method: "POST",
      body: { company_id: COMPANY_ID, cycle_id, layout },
    }),
  publish: (cycle_id: string, channel: "newsletter" | "instagram" | "linkedin") =>
    req<{ channel: string; result: any }>("/publish", {
      method: "POST",
      body: { company_id: COMPANY_ID, cycle_id, channel },
    }),

  // learning
  getLearning: () =>
    req<{
      confirmed_rules: string[];
      pending_rules: string[];
      reason_histogram: Record<string, number>;
    }>(`/learning?company_id=${encodeURIComponent(COMPANY_ID)}`),
  confirmRule: (rule: string) =>
    req<{ status: string }>("/learning/confirm", {
      method: "POST",
      body: { company_id: COMPANY_ID, rule },
    }),
  dismissRule: (rule: string) =>
    req<{ status: string }>("/learning/dismiss", {
      method: "POST",
      body: { company_id: COMPANY_ID, rule },
    }),
  deleteRule: (rule: string) =>
    req<{ status: string }>(
      `/learning/${encodeURIComponent(rule)}?company_id=${encodeURIComponent(COMPANY_ID)}`,
      { method: "DELETE" },
    ),

  // analytics
  approvalRate: () =>
    req<{ cycles: { cycle_id: string; total: number; approved: number; rate: number; started_at: string | null }[] }>(
      `/analytics/approval_rate?company_id=${encodeURIComponent(COMPANY_ID)}`,
    ),
  sourceHitRates: () =>
    req<{ sources: { source_id: string; name?: string; url?: string; surfaced: number; approved: number; rate: number | null }[] }>(
      `/analytics/source_hit_rates?company_id=${encodeURIComponent(COMPANY_ID)}`,
    ),
  reasonHistogram: () =>
    req<{ histogram: Record<string, number> }>(
      `/analytics/reason_histogram?company_id=${encodeURIComponent(COMPANY_ID)}`,
    ),
  underperformers: () =>
    req<{ sources: (Source & { hit_rate: number })[] }>(
      `/analytics/underperformers?company_id=${encodeURIComponent(COMPANY_ID)}`,
    ),

  // chat
  chat: (message: string, context: Record<string, unknown> = {}) =>
    req<{
      action: string;
      note: string;
      result: any;
      reply: string;
    }>("/chat", { method: "POST", body: { company_id: COMPANY_ID, message, context } }),
};
