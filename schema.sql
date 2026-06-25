-- API-Tracker schema (PostgreSQL)
-- Run via `apitracker init-db` or: psql "$APITRACKER_DSN" -f schema.sql

-- Applications whose LLM usage we bill separately.
CREATE TABLE IF NOT EXISTS apps (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,         -- stable identifier passed at call time
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Maps a provider API key to an app, so usage can be attributed even when the
-- caller doesn't pass an explicit app tag. The full key is never stored: we keep
-- a SHA-256 hash for lookup and the last 4 chars for human-readable display.
CREATE TABLE IF NOT EXISTS provider_key_map (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider    TEXT NOT NULL,                -- 'anthropic' | 'openai' | 'perplexity'
    key_hash    TEXT NOT NULL,               -- sha256(api_key) hex
    key_last4   TEXT NOT NULL,
    app_id      BIGINT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, key_hash)
);

-- Per-model pricing in USD per 1,000,000 tokens, with effective dates so that
-- historical events are costed at the rate that was current when they happened.
CREATE TABLE IF NOT EXISTS model_pricing (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_per_mtok        NUMERIC(12, 4) NOT NULL,
    output_per_mtok       NUMERIC(12, 4) NOT NULL,
    cached_input_per_mtok NUMERIC(12, 4),    -- NULL -> 0.1x input at compute time
    cache_write_per_mtok  NUMERIC(12, 4),    -- NULL -> 1.0x input at compute time
    effective_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, model, effective_from)
);

-- One row per recorded LLM call.
CREATE TABLE IF NOT EXISTS usage_events (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    app_id               BIGINT REFERENCES apps(id) ON DELETE SET NULL,  -- NULL = unattributed
    provider             TEXT NOT NULL,
    model                TEXT NOT NULL,
    input_tokens         BIGINT NOT NULL DEFAULT 0,
    output_tokens        BIGINT NOT NULL DEFAULT 0,
    cached_input_tokens  BIGINT NOT NULL DEFAULT 0,
    cache_write_tokens   BIGINT NOT NULL DEFAULT 0,
    cost_usd             NUMERIC(14, 6),       -- NULL = no pricing found (unpriced)
    request_id           TEXT,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_usage_events_app_time      ON usage_events (app_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_provider_time ON usage_events (provider, occurred_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_occurred_at   ON usage_events (occurred_at);
