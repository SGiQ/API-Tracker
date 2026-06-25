# Deployment

API-Tracker is a **library + CLI**, not a web service — there's nothing to deploy
to Vercel/Railway as an app. The only thing it needs hosted is a **Postgres
database**. Provision one with a managed provider and point `APITRACKER_DSN` at it.

> If you later want apps to report usage over HTTP (a central ingestion API) or a
> browser dashboard, those are separate services we can add. For now, a database
> is all that's required.

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
