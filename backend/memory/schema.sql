-- Postgres schema for Signal Content Agent.
-- Mirrors §4.5 of the PRD; JSON columns are jsonb, timestamps are timestamptz.
-- Idempotent so you can re-run this against Neon.

CREATE TABLE IF NOT EXISTS company_profile (
  company_id       text PRIMARY KEY,
  identity         jsonb,
  market           jsonb,
  positioning      jsonb,
  voice            jsonb,
  content_pillars  jsonb,
  content_mix      real,
  brand            jsonb DEFAULT '{}'::jsonb,
  crawled_urls     jsonb,
  created_at       timestamptz DEFAULT now(),
  updated_at       timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
  source_id        text PRIMARY KEY,
  company_id       text NOT NULL,
  url              text NOT NULL,
  name             text,
  kind             text,
  status           text,
  origin           text,
  reason           text,
  last_checked     timestamptz,
  last_ok          boolean,
  items_surfaced   integer DEFAULT 0,
  items_approved   integer DEFAULT 0,
  created_at       timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_company ON sources(company_id);

CREATE TABLE IF NOT EXISTS preference_profile (
  company_id       text PRIMARY KEY,
  positive_signals jsonb DEFAULT '[]'::jsonb,
  negative_filters jsonb DEFAULT '[]'::jsonb,
  confirmed_rules  jsonb DEFAULT '[]'::jsonb,
  pending_rules    jsonb DEFAULT '[]'::jsonb,
  reason_histogram jsonb DEFAULT '{}'::jsonb,
  updated_at       timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback_log (
  id           bigserial PRIMARY KEY,
  company_id   text NOT NULL,
  item_id      text NOT NULL,
  source_id    text,
  decision     text NOT NULL,
  reason_code  text,
  note         text,
  cycle_id     text,
  ts           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_company_ts ON feedback_log(company_id, ts DESC);

CREATE TABLE IF NOT EXISTS content_history (
  item_id            text PRIMARY KEY,
  company_id         text NOT NULL,
  title              text,
  kind               text,
  source_id          text,
  url                text,
  status             text,
  published_channels jsonb DEFAULT '[]'::jsonb,
  ts                 timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_history_company_ts ON content_history(company_id, ts DESC);

CREATE TABLE IF NOT EXISTS drafts (
  cycle_id     text PRIMARY KEY,
  company_id   text NOT NULL,
  newsletter   jsonb,
  instagram    jsonb,
  linkedin     jsonb,
  layout       text,
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS publish_log (
  id            bigserial PRIMARY KEY,
  company_id    text NOT NULL,
  cycle_id      text,
  channel       text NOT NULL,
  status        text,
  external_id   text,
  scheduled_for timestamptz,
  ts            timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cycles (
  cycle_id     text PRIMARY KEY,
  company_id   text NOT NULL,
  status       text,
  started_at   timestamptz DEFAULT now(),
  finished_at  timestamptz
);
