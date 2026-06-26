# API-Tracker

Track and **separate LLM API usage per app** so you know what to bill each one for.
Supports **Anthropic**, **OpenAI**, **Perplexity**, and **Google Gemini**. Every call
is attributed to an app, priced per model, and stored in **Postgres** for billing reports.

## How it works

```
your app ──► TrackedAnthropic / TrackedOpenAI / TrackedPerplexity ──► provider SDK
                                  │
                                  ├─ normalize token usage (input/output/cached/cache-write)
                                  ├─ attribute to an app  (explicit tag  OR  provider-key mapping)
                                  ├─ price it             (per-model rates, USD/Mtok)
                                  └─ store a usage_event in Postgres
                                                                  │
                                            apitracker report ────┘  (bill per app / provider / model)
```

* **Attribution — both methods supported.** Pass an explicit `app` tag at call time
  (wins if present), or map each provider API key to an app once and let calls be
  attributed automatically. If neither resolves, usage is still recorded as
  *unattributed* — it is never dropped.
* **Pricing is data.** Rates live in the `model_pricing` table with effective dates,
  so historical events keep the rate that was current when they happened. A call to a
  model with no rate is recorded with a `NULL` cost and surfaced as *unpriced* in
  reports — so missing pricing never loses usage.

## Install

```bash
pip install -e ".[all]"      # all provider SDKs; or [anthropic] / [openai]
```

Requires Python 3.10+ and a Postgres database. Perplexity uses the OpenAI SDK.

## Setup

API-Tracker needs only a Postgres database — there's no service to deploy. For
provisioning managed Postgres (Railway / Neon / Supabase) and the connection-pooler
gotcha, see [`DEPLOY.md`](DEPLOY.md).

```bash
export APITRACKER_DSN="postgresql://user:pass@localhost:5432/apitracker"

apitracker init-db                      # create tables
apitracker load-pricing                 # load bundled seed rates
apitracker add-app chatbot  --name "Customer Chatbot"
apitracker add-app research --name "Research Tool"

# Optional: attribute by key instead of (or in addition to) an explicit tag.
apitracker map-key openai     research --key-env OPENAI_API_KEY
apitracker map-key perplexity research --key-env PERPLEXITY_API_KEY
```

> ⚠️ **Verify non-Anthropic pricing before you bill.** Anthropic seed rates are current
> (2026-06). OpenAI and Perplexity seed rates are published list prices that drift and
> **must be checked** against the providers' pricing pages; Perplexity also charges
> per-request search fees that token counts don't capture. Edit the `model_pricing`
> table (or `apitracker/pricing.py` + reload) to keep rates accurate.

## Use in your apps

Wrap the provider client once per app; calls record automatically.

```python
import anthropic, openai
from apitracker import Tracker
from apitracker.providers import TrackedAnthropic, TrackedOpenAI, TrackedPerplexity

tracker = Tracker()  # reads $APITRACKER_DSN

# Anthropic — attributed by explicit app tag
chat = TrackedAnthropic(tracker, app="chatbot", client=anthropic.Anthropic())
chat.messages.create(model="claude-opus-4-8", max_tokens=1024,
                     messages=[{"role": "user", "content": "Hi"}])

# OpenAI — attributed by the mapped API key (no tag needed)
research = TrackedOpenAI(tracker, client=openai.OpenAI())
research.chat.completions.create(model="gpt-4o",
                                 messages=[{"role": "user", "content": "Hi"}])

# Perplexity (OpenAI-compatible)
pplx = TrackedPerplexity(tracker, app="research", api_key="pplx-...")
pplx.chat.completions.create(model="sonar",
                             messages=[{"role": "user", "content": "latest on X?"}])
```

Google Gemini works with either Gemini SDK:

```python
from apitracker.providers import TrackedGemini

# New google-genai SDK
from google import genai
gem = TrackedGemini(tracker, app="research", client=genai.Client())
gem.models.generate_content(model="gemini-2.5-flash", contents="Hi")

# Old google-generativeai SDK
import google.generativeai as genai
genai.configure(api_key="...")
gem = TrackedGemini(tracker, app="research",
                    client=genai.GenerativeModel("gemini-1.5-pro"))
gem.generate_content("Hi")
```

An app that uses several providers makes **one** `Tracker` and wraps each client with
the same `app=` tag; `report --by app-provider` then breaks the app's spend down by
provider.

The wrappers proxy the real clients unchanged — every other method/attribute passes
through, so they're drop-in replacements.

### Streaming

Streaming responses carry usage only on the final message/chunk, so record it explicitly:

```python
# Anthropic
with chat.messages.stream(model="claude-opus-4-8", max_tokens=1024, messages=[...]) as s:
    for text in s.text_stream: ...
    tracker.record_anthropic(s.get_final_message(), app="chatbot")

# OpenAI / Perplexity: request usage on the stream, then record the final chunk
resp = research.chat.completions.create(model="gpt-4o", messages=[...],
                                        stream=True, stream_options={"include_usage": True})
final = None
for chunk in resp:
    if chunk.usage: final = chunk
if final: tracker.record_openai(final, app="research")
```

### Without the wrappers

Any code path can record directly:

```python
from apitracker import Usage
tracker.record(provider="anthropic", model="claude-opus-4-8",
               usage=Usage(input_tokens=1000, output_tokens=500),
               app="chatbot", metadata={"endpoint": "/summarize"})
```

## HTTP ingestion service — track many apps without sharing the DSN

When several apps report usage, you don't want to hand each one the database DSN
and a copy of the pricing logic. Run the bundled ingestion service instead: apps
POST usage with a per-app key and never touch Postgres. The service is a thin
front door — it just calls `Tracker.record()`, so attribution and pricing stay
in one place.

```bash
pip install -e ".[server]"

apitracker add-app chatbot --name "Customer Chatbot"
apitracker issue-key chatbot --label prod    # prints the key ONCE — store it
apitracker serve                             # listens on $PORT (default 8000)
```

Apps then fire a single request per call (fire-and-forget; never block the LLM path):

```bash
curl -X POST "$APITRACKER_URL/v1/usage" \
  -H "X-App-Key: atk_…" -H "content-type: application/json" \
  -d '{"provider":"anthropic","model":"claude-opus-4-8",
       "input_tokens":1000,"output_tokens":500,
       "cached_input_tokens":0,"cache_write_tokens":0,
       "request_id":"req_123","user_id":"u_123","metadata":{"endpoint":"/chat"}}'
# → {"id": 91}
```

`user_id` is optional — the app's own user identifier (store the stable id, not
PII). It enables per-user reporting: `report --by app-user` / `--by user`, the
`?user=` filter, and the dashboard's "app + user" / "user" groupings.

The app is resolved from the **key**, not the request body, so a leaked key can
only ever write usage for its own app. Keys are stored as a SHA-256 hash (plus
last 4); revoke one by setting `revoked_at` in `app_keys`. `GET /healthz` returns
`{"ok": true}` for platform health checks. See [`DEPLOY.md`](DEPLOY.md) to host it.

### Dashboard

The same service serves a browser **dashboard** at `GET /` (and JSON at
`GET /v1/report?by=app-provider&since=…&until=…`) — a billing table + spend-by-app
bars over the same data the CLI `report` shows. Both are gated by
`APITRACKER_DASHBOARD_KEY`; set it to enable them (unset → 503, ingestion still works).
The key is entered in the browser (stored in `localStorage`) or passed as `?key=`.

## Billing reports

```bash
apitracker report --by app                       # total per app
apitracker report --by app-provider              # per app + provider (default)
apitracker report --by model --since 2026-06-01 --until 2026-07-01
```

```
app       provider    model            calls  in_tok  out_tok  cached  cost_usd  unpriced
chatbot   anthropic   claude-opus-4-8  1      1,000   500      2,000   $0.0191   0
research  openai      gpt-4o           1      600     200      400     $0.0040   0
research  perplexity  sonar            1      500     300      0       $0.0008   0

TOTAL cost: $0.0239
```

For custom queries, `usage_events` is a plain table — join to `apps` and aggregate
however your billing system needs.

## Data model

| Table              | Purpose                                                        |
| ------------------ | ------------------------------------------------------------- |
| `apps`             | Apps you bill separately (`slug`, `name`).                     |
| `provider_key_map` | Provider API key → app (key stored as SHA-256 hash + last 4). |
| `app_keys`         | Per-app ingest keys for the HTTP service (SHA-256 hash + last 4). |
| `model_pricing`    | USD/Mtok rates per model, with effective dates.                |
| `usage_events`     | One row per recorded call: tokens, cost, app, provider, model. |

Full DDL in [`schema.sql`](schema.sql).

## Development

```bash
pip install -e ".[dev]"
pytest          # pure-logic tests (pricing + usage normalization), no DB needed
```
