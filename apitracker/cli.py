"""Command-line interface for setup and billing reports.

    apitracker init-db
    apitracker load-pricing
    apitracker add-app <slug> [--name NAME]
    apitracker map-key <provider> <app-slug> [--key KEY | --key-env VAR]
    apitracker issue-key <app-slug> [--label LABEL]
    apitracker serve [--host HOST] [--port PORT]
    apitracker report [--since ISO] [--until ISO] [--by app|provider|app-provider|model]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

from .db import Database
from .pricing import SEED_PRICING
from .tracker import Tracker


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # Accept "2026-06-01" or full ISO timestamps.
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_int(n) -> str:
    return f"{int(n or 0):,}"


def _print_report(rows: list[dict]) -> None:
    if not rows:
        print("No usage in the selected window.")
        return

    dim_keys = [k for k in ("app", "provider", "model") if k in rows[0]]
    headers = dim_keys + ["calls", "in_tok", "out_tok", "cached", "cost_usd", "unpriced"]

    table = [headers]
    total_cost = Decimal(0)
    for r in rows:
        total_cost += Decimal(r["cost_usd"] or 0)
        table.append(
            [str(r[k]) for k in dim_keys]
            + [
                _fmt_int(r["calls"]),
                _fmt_int(r["input_tokens"]),
                _fmt_int(r["output_tokens"]),
                _fmt_int(r["cached_input_tokens"]),
                f"${Decimal(r['cost_usd'] or 0):,.4f}",
                _fmt_int(r["unpriced_calls"]),
            ]
        )

    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    for ri, row in enumerate(table):
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if ri == 0:
            print("  ".join("-" * widths[i] for i in range(len(headers))))
    print()
    print(f"TOTAL cost: ${total_cost:,.4f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apitracker", description=__doc__)
    parser.add_argument("--dsn", help="Postgres DSN (else $APITRACKER_DSN)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create tables")
    sub.add_parser("load-pricing", help="Load the bundled seed pricing")

    p_app = sub.add_parser("add-app", help="Create or rename an app")
    p_app.add_argument("slug")
    p_app.add_argument("--name")

    p_map = sub.add_parser("map-key", help="Map a provider API key to an app")
    p_map.add_argument("provider", choices=["anthropic", "openai", "perplexity", "gemini"])
    p_map.add_argument("app_slug")
    g = p_map.add_mutually_exclusive_group(required=True)
    g.add_argument("--key", help="The API key (will be hashed, not stored)")
    g.add_argument("--key-env", help="Env var holding the API key")

    p_key = sub.add_parser("issue-key", help="Issue an ingest API key for an app")
    p_key.add_argument("app_slug")
    p_key.add_argument("--label", help="Human label for this key (e.g. 'prod', 'railway')")

    p_serve = sub.add_parser("serve", help="Run the HTTP usage-ingestion service")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))

    p_rep = sub.add_parser("report", help="Billing report")
    p_rep.add_argument("--since")
    p_rep.add_argument("--until")
    p_rep.add_argument(
        "--by", default="app-provider",
        choices=["app", "provider", "app-provider", "model"],
    )

    args = parser.parse_args(argv)
    db = Database(args.dsn)
    try:
        if args.cmd == "init-db":
            db.init_schema()
            print("Schema created.")
        elif args.cmd == "load-pricing":
            n = db.load_pricing(SEED_PRICING)
            print(f"Loaded {n} pricing rows ({len(SEED_PRICING) - n} already present).")
        elif args.cmd == "add-app":
            db.upsert_app(args.slug, args.name)
            print(f"App {args.slug!r} ready.")
        elif args.cmd == "map-key":
            key = args.key or os.environ.get(args.key_env or "")
            if not key:
                print("error: no key provided / env var empty", file=sys.stderr)
                return 2
            db.map_key(args.provider, key, args.app_slug)
            print(f"Mapped {args.provider} key ...{key[-4:]} -> {args.app_slug}")
        elif args.cmd == "issue-key":
            key, last4 = db.issue_app_key(args.app_slug, label=args.label)
            print(
                f"Issued ingest key for {args.app_slug!r} (...{last4}).\n"
                f"Store it now -- it will not be shown again:\n\n    {key}\n"
            )
        elif args.cmd == "serve":
            import uvicorn

            from .server import create_app

            print(f"Starting API-Tracker ingest on {args.host}:{args.port}")
            uvicorn.run(create_app(Tracker(db)), host=args.host, port=args.port)
        elif args.cmd == "report":
            rows = db.report(
                since=_parse_dt(args.since),
                until=_parse_dt(args.until),
                group_by=args.by,
            )
            _print_report(rows)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
