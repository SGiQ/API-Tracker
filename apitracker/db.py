"""Postgres storage layer for API-Tracker.

Thin wrapper over a psycopg connection pool. No ORM -- the schema is small and
the queries are explicit. All money is handled as :class:`decimal.Decimal`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import hash_key, key_last4, resolve_dsn
from .pricing import Rate
from .usage import Usage

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


class Database:
    """Owns a connection pool and exposes the operations the tracker needs."""

    def __init__(self, dsn: str | None = None, *, pool: ConnectionPool | None = None):
        if pool is not None:
            self._dsn = dsn
            self._pool = pool
        else:
            self._dsn = resolve_dsn(dsn)
            self._pool = ConnectionPool(self._dsn, min_size=1, open=True)

    @contextmanager
    def _conn(self) -> Iterator:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            yield conn

    def close(self) -> None:
        self._pool.close()

    # -- schema / setup ----------------------------------------------------

    def init_schema(self) -> None:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            conn.execute(sql)
            conn.commit()

    def load_pricing(self, rates: list[Rate], *, effective_from: datetime | None = None) -> int:
        """Insert pricing rows. Existing (provider, model, effective_from) rows are
        left untouched so reloading the seed is idempotent."""
        rows = 0
        with self._conn() as conn:
            for r in rates:
                params = {
                    "provider": r.provider,
                    "model": r.model,
                    "inp": r.input,
                    "out": r.output,
                    "cin": r.cached_input,
                    "cw": r.cache_write,
                }
                if effective_from is None:
                    cur = conn.execute(
                        """
                        INSERT INTO model_pricing
                            (provider, model, input_per_mtok, output_per_mtok,
                             cached_input_per_mtok, cache_write_per_mtok)
                        VALUES (%(provider)s, %(model)s, %(inp)s, %(out)s, %(cin)s, %(cw)s)
                        ON CONFLICT (provider, model, effective_from) DO NOTHING
                        """,
                        params,
                    )
                else:
                    params["eff"] = effective_from
                    cur = conn.execute(
                        """
                        INSERT INTO model_pricing
                            (provider, model, input_per_mtok, output_per_mtok,
                             cached_input_per_mtok, cache_write_per_mtok, effective_from)
                        VALUES (%(provider)s, %(model)s, %(inp)s, %(out)s, %(cin)s,
                                %(cw)s, %(eff)s)
                        ON CONFLICT (provider, model, effective_from) DO NOTHING
                        """,
                        params,
                    )
                rows += cur.rowcount
            conn.commit()
        return rows

    # -- apps & key mapping ------------------------------------------------

    def upsert_app(self, slug: str, name: str | None = None) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO apps (slug, name)
                VALUES (%(slug)s, %(name)s)
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                {"slug": slug, "name": name or slug},
            ).fetchone()
            conn.commit()
            return row["id"]

    def app_id_by_slug(self, slug: str) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM apps WHERE slug = %s", (slug,)
            ).fetchone()
            return row["id"] if row else None

    def map_key(self, provider: str, api_key: str, app_slug: str) -> None:
        app_id = self.app_id_by_slug(app_slug)
        if app_id is None:
            raise ValueError(f"Unknown app slug: {app_slug!r}. Create it first.")
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO provider_key_map (provider, key_hash, key_last4, app_id)
                VALUES (%(provider)s, %(hash)s, %(last4)s, %(app_id)s)
                ON CONFLICT (provider, key_hash)
                    DO UPDATE SET app_id = EXCLUDED.app_id, key_last4 = EXCLUDED.key_last4
                """,
                {
                    "provider": provider,
                    "hash": hash_key(api_key),
                    "last4": key_last4(api_key),
                    "app_id": app_id,
                },
            )
            conn.commit()

    def app_id_by_key(self, provider: str, api_key: str) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT app_id FROM provider_key_map WHERE provider = %s AND key_hash = %s",
                (provider, hash_key(api_key)),
            ).fetchone()
            return row["app_id"] if row else None

    # -- pricing lookup ----------------------------------------------------

    def current_rate(
        self, provider: str, model: str, *, at: datetime | None = None
    ) -> Optional[Rate]:
        """Most recent pricing row for (provider, model) effective at ``at``."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT provider, model, input_per_mtok, output_per_mtok,
                       cached_input_per_mtok, cache_write_per_mtok
                FROM model_pricing
                WHERE provider = %s AND model = %s
                  AND effective_from <= COALESCE(%s, now())
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (provider, model, at),
            ).fetchone()
        if row is None:
            return None
        return Rate(
            provider=row["provider"],
            model=row["model"],
            input=row["input_per_mtok"],
            output=row["output_per_mtok"],
            cached_input=row["cached_input_per_mtok"],
            cache_write=row["cache_write_per_mtok"],
        )

    # -- recording ---------------------------------------------------------

    def insert_usage_event(
        self,
        *,
        app_id: Optional[int],
        provider: str,
        model: str,
        usage: Usage,
        cost_usd: Optional[Decimal],
        request_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        occurred_at: Optional[datetime] = None,
    ) -> int:
        import json

        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO usage_events
                    (app_id, provider, model, input_tokens, output_tokens,
                     cached_input_tokens, cache_write_tokens, cost_usd, request_id,
                     metadata, occurred_at)
                VALUES (%(app_id)s, %(provider)s, %(model)s, %(in)s, %(out)s,
                        %(cin)s, %(cw)s, %(cost)s, %(req)s, %(meta)s::jsonb,
                        COALESCE(%(at)s, now()))
                RETURNING id
                """,
                {
                    "app_id": app_id,
                    "provider": provider,
                    "model": model,
                    "in": usage.input_tokens,
                    "out": usage.output_tokens,
                    "cin": usage.cached_input_tokens,
                    "cw": usage.cache_write_tokens,
                    "cost": cost_usd,
                    "req": request_id,
                    "meta": json.dumps(metadata or {}),
                    "at": occurred_at,
                },
            ).fetchone()
            conn.commit()
            return row["id"]

    # -- reporting ---------------------------------------------------------

    def report(
        self,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        group_by: str = "app-provider",
    ) -> list[dict]:
        """Aggregate usage and cost over a time window.

        ``group_by`` is one of ``app``, ``provider``, ``app-provider``, ``model``.
        """
        dims = {
            "app": ["app"],
            "provider": ["provider"],
            "app-provider": ["app", "provider"],
            "model": ["app", "provider", "model"],
        }
        if group_by not in dims:
            raise ValueError(f"group_by must be one of {sorted(dims)}")

        select_cols = {
            "app": "COALESCE(a.slug, '(unattributed)') AS app",
            "provider": "e.provider AS provider",
            "model": "e.model AS model",
        }
        cols = [select_cols[d] for d in dims[group_by]]
        group_exprs = []
        for d in dims[group_by]:
            group_exprs.append(
                "COALESCE(a.slug, '(unattributed)')" if d == "app"
                else "e.provider" if d == "provider"
                else "e.model"
            )

        where = []
        params: dict = {}
        if since is not None:
            where.append("e.occurred_at >= %(since)s")
            params["since"] = since
        if until is not None:
            where.append("e.occurred_at < %(until)s")
            params["until"] = until
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        sql = f"""
            SELECT {", ".join(cols)},
                   COUNT(*)                              AS calls,
                   SUM(e.input_tokens)                   AS input_tokens,
                   SUM(e.output_tokens)                  AS output_tokens,
                   SUM(e.cached_input_tokens)            AS cached_input_tokens,
                   SUM(e.cache_write_tokens)             AS cache_write_tokens,
                   COALESCE(SUM(e.cost_usd), 0)          AS cost_usd,
                   COUNT(*) FILTER (WHERE e.cost_usd IS NULL) AS unpriced_calls
            FROM usage_events e
            LEFT JOIN apps a ON a.id = e.app_id
            {where_sql}
            GROUP BY {", ".join(group_exprs)}
            ORDER BY cost_usd DESC
        """
        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()
