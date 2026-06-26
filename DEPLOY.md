# Deployment

API-Tracker is a **library + CLI** that needs a **Postgres database**. That alone
is enough if your apps import the library and write to the DB directly. To track
**many apps without sharing the DSN**, also deploy the **HTTP ingestion service**
(section 4) — apps then POST usage with a per-app key instead of holding DB creds.

> A browser dashboard is still a separate service we can add later. For now: a
> database (required) plus, optionally, the ingestion service.

## 1. Provision managed Postgres

Any managed Postgres works. Common choices:

| Provider | Get the connection string | Notes |
| --- | --- | --- |
| **Railway** | New Project → *Add PostgreSQL* → service → **Variables** → `DATABASE_URL` | Persistent service; pairs well if you later add an ingestion API here too. |
| **Neon** | Project → **Connection Details** → copy the `postgresql://…` string | Serverless Postgres; string already includes `?sslmode=require`. |
| **Supabase** | Project → **Settings → Database → Connection string** | Use the **direct** connection (port `5432`) — see the pooler note below. |

## 2. Set the DSN

API-Tracker reads `APITRACKER_DSN` (or pass `dsn=` to `Tracker`/`Database`).

```bash
export APITRACKER_DSN="postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

- **SSL:** managed providers require TLS. Append `?sslmode=require` if the provider's
  string doesn't already include it. (Neon includes it; Railway/Supabase direct URLs
  may not.)
- **Secrets:** never commit the DSN. Keep it in your secret manager / platform env
  vars. `.env` is git-ignored; `.env.example` shows the shape.

## 3. Initialize the database

```bash
apitracker init-db        # create tables
apitracker load-pricing   # load seed pricing (then verify OpenAI/Perplexity rates)
```

That's it — your apps can now record usage and you can run `apitracker report`.

## 4. (Optional) Deploy the HTTP ingestion service

Run this when multiple apps should report usage without each holding the DSN.
It's a FastAPI app that fronts `Tracker.record()`; apps authenticate with a
per-app key (`X-App-Key`) issued by `apitracker issue-key`.

**Railway (same project as the Postgres — recommended):**

1. **New service → Deploy from the API-Tracker repo.** The bundled
   [`nixpacks.toml`](nixpacks.toml) installs `.[server]` and starts `apitracker serve`.
2. **Set `APITRACKER_DSN`** on the service to the Postgres' **internal** URL via a
   reference variable — `${{ Postgres.DATABASE_URL }}` — so traffic stays on
   Railway's private network and the DB is never publicly exposed.
3. Railway injects `$PORT`; the service binds it automatically.
4. **Health check path:** `/healthz`.
5. Note the service's public URL — that's the `APITRACKER_URL` your apps POST to.

**Issue a key per app** (run against the DB, e.g. locally with the public DSN, or
from a Railway shell):

```bash
apitracker add-app chatbot --name "Customer Chatbot"
apitracker issue-key chatbot --label prod     # prints the key once — store it
```

Each app then needs just two env vars: `APITRACKER_URL` and its `X-App-Key`. No
database credentials leave the tracker's own project.

> **Auth & exposure.** The ingest endpoint is public (apps call it over the
> internet), but it does nothing without a valid key, and a key can only write
> usage for its own app. Keep keys in each app's secret manager; revoke a leaked
> one by setting `revoked_at` in `app_keys`. Put it behind your platform's TLS
> (Railway terminates HTTPS for you).

## Connection pooler gotcha (Supabase / PgBouncer / Neon pooled endpoint)

API-Tracker uses a persistent `psycopg` connection pool, and psycopg3 uses **server-side
prepared statements** by default. Those are **incompatible with a transaction-mode
pooler** (Supabase's port `6543`, a bare PgBouncer in `transaction` mode, or Neon's
`-pooler` host) and will fail with errors like `prepared statement "_pg3_…" already exists`.

Two safe options:

1. **Use the direct/session connection** (Supabase port `5432`, Neon's non-pooled host).
   Recommended — API-Tracker already pools connections itself, so you don't need the
   provider's transaction pooler.
2. If you must go through a transaction-mode pooler, disable prepared statements by
   passing a pre-built pool to `Database`:

   ```python
   from psycopg_pool import ConnectionPool
   from apitracker import Database, Tracker

   pool = ConnectionPool(
       conninfo="postgresql://…:6543/…?sslmode=require",
       kwargs={"prepare_threshold": None},   # disable prepared statements
       open=True,
   )
   tracker = Tracker(Database(pool=pool))
   ```

## Backups & retention

This is billing data — enable your provider's automated backups / point-in-time
recovery, and keep history long enough to cover your billing disputes window.
`usage_events` is append-only and grows with traffic; partition or archive by
`occurred_at` if volume gets large.
