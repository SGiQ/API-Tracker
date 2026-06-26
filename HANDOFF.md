# Handoff — integrating API-Tracker into the TypeScript apps

This note lets a **new Claude Code session with access to both `SGiQ/api-tracker`
and `SGiQ/nia-assistant`** pick up where we left off. Create that environment with
**both repos in scope**, then start from "Next steps" below.

## Goal

Track and separate LLM API usage **per app** (Anthropic, OpenAI, Perplexity, Google
Gemini) so each app can be billed for its own usage. One shared Postgres database;
each app tags its calls with an `app="..."` label; `report` aggregates per app /
provider / model.

## What already exists (this repo, `api-tracker`)

A complete, tested **Python** package on branch
`claude/llm-api-usage-tracking-cw1rx6` (PR #1 → `main`, not yet merged):

- `apitracker/` — `tracker.py`, `db.py` (Postgres), `pricing.py`, `usage.py`,
  `cli.py`, and `providers/` with drop-in wrappers `TrackedAnthropic`,
  `TrackedOpenAI`, `TrackedPerplexity`, `TrackedGemini`.
- `schema.sql` — Postgres DDL: `apps`, `provider_key_map`, `model_pricing`,
  `usage_events`. **This is the schema the TS integration must write to.**
- CLI: `init-db`, `load-pricing`, `add-app`, `map-key`, `report`.
- `DEPLOY.md` (managed-Postgres setup), `.claude/` SessionStart hook, tests.

### Key design rules the TS port must match (read `apitracker/usage.py` + `pricing.py`)

- **Token buckets** stored per event: `input_tokens` (full-rate), `output_tokens`,
  `cached_input_tokens` (cache read), `cache_write_tokens` (Anthropic cache create).
  The three input buckets are disjoint.
- **Normalization:**
  - Anthropic: `input_tokens` is already the uncached remainder; map
    `cache_read_input_tokens` / `cache_creation_input_tokens` directly.
  - OpenAI/Perplexity: `prompt_tokens` **includes** cached; subtract
    `prompt_tokens_details.cached_tokens` into `cached_input_tokens`.
  - Gemini: subtract `cached_content_token_count` from `prompt_token_count`; fold
    `thoughts_token_count` into output (Gemini bills thinking as output).
- **Cost** = tokens × rate / 1e6, rates in USD/Mtok from `model_pricing` (NULL rate →
  store `cost_usd = NULL`, never drop the event; surfaces as "unpriced").
- **Attribution precedence:** explicit `app` slug wins; else hash the provider key
  and look up `provider_key_map`; else unattributed. Keys are stored as SHA-256
  hash + last4, never plaintext.
- **Pricing accuracy:** Anthropic rates are current (2026-06). OpenAI/Perplexity/
  Gemini are seeded list prices flagged to VERIFY; Gemini/Perplexity have tiered /
  per-request fees not captured by flat per-model token rates.

## Infrastructure state

- **Database:** managed **Postgres on Railway** (user already provisioned it). Schema
  created + pricing loaded via the Python CLI against the Railway **public** URL.
- **DSN env var:** `APITRACKER_DSN`. ⚠️ **Which URL depends on where the app runs:**
  - App on Railway **in the same project** as Postgres → use the **internal**
    `DATABASE_URL` (`*.railway.internal`).
  - App elsewhere (Vercel, local, other host) → use the **public**
    `*.proxy.rlwy.net` URL. Append `?sslmode=require` if needed.
  - `nia-assistant` deploys to **both Railway and Vercel** (see its `railway.toml`,
    `vercel.json`) — confirm which deployment(s) need tracking and set the DSN
    accordingly per environment.

## The decision that blocked us

`nia-assistant` is a **TypeScript monorepo** (`apps/` + `packages/shared`, Prisma,
Railway + Vercel). API-Tracker is **Python**, so it can't be imported directly.
A TypeScript integration is required. Two options were on the table:

- **A (recommended): a TypeScript tracker module in `packages/shared`** that wraps the
  `@anthropic-ai/sdk` and `openai` (Perplexity = openai with Perplexity base_url)
  clients and writes to the **same Postgres** using the existing `schema.sql` tables.
  Reuses the database + pricing already set up. Fits the monorepo; every app under
  `apps/` imports it.
- **B: an HTTP ingestion API** (`POST /usage`) the TS app posts to — language-agnostic,
  but a service to deploy. Prefer only if there will be a real mix of Python + TS apps.

**User leaning / default:** A, unless they say otherwise. Confirm at the start.

## Providers nia-assistant uses

Anthropic + Perplexity + (likely) OpenAI. Other apps in the org also use **Gemini**.
The TS module should cover Anthropic, OpenAI, Perplexity at minimum; add Gemini to
match the Python feature set.

## Next steps (for the new two-repo session)

1. **Confirm approach A vs B** with the user (default A).
2. **Read `nia-assistant`** — find where LLM clients are created (search
   `anthropic`, `OpenAI`, `api.perplexity.ai`; likely in `packages/shared`) and how
   it talks to Postgres (`prisma/schema.prisma`, the Prisma client). Decide:
   write usage rows via **raw `pg`** (decoupled from their Prisma migrations, matches
   `schema.sql` 1:1) **or** add the four tables to their Prisma schema and write via
   Prisma. Raw `pg` is the lower-risk default.
3. **Build the TS tracker** in `packages/shared` mirroring `apitracker/usage.py` +
   `pricing.py` + the attribution/cost logic above. Wrappers analogous to the Python
   `providers/`.
4. **Wire `nia-assistant`** to use the wrapped clients with `app="nia-assistant"`
   (one shared tracker instance per app; reuse the DB connection, don't open one per
   call).
5. **Set `APITRACKER_DSN`** in nia-assistant's Railway/Vercel env (internal URL on
   Railway-same-project; public URL on Vercel).
6. **Test** one real call per provider, then verify with the Python CLI
   `apitracker report --by app-provider` (or a SQL query) that rows land under
   `nia-assistant`.

## Pointers

- Branch: `claude/llm-api-usage-tracking-cw1rx6`; PR #1 (open).
- Schema source of truth: `schema.sql`.
- Cost/normalization reference: `apitracker/usage.py`, `apitracker/pricing.py`,
  `apitracker/tracker.py`.
- Report SQL to mirror: `Database.report()` in `apitracker/db.py`.
- Do **not** commit any real DSN / API keys.
