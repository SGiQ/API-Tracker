"""Configuration helpers."""

from __future__ import annotations

import hashlib
import os

DSN_ENV_VAR = "APITRACKER_DSN"


def resolve_dsn(dsn: str | None = None) -> str:
    """Return the Postgres DSN, falling back to the ``APITRACKER_DSN`` env var."""
    dsn = dsn or os.environ.get(DSN_ENV_VAR)
    if not dsn:
        raise ValueError(
            f"No Postgres DSN provided. Pass dsn=... or set ${DSN_ENV_VAR}, e.g. "
            "postgresql://user:pass@localhost:5432/apitracker"
        )
    return dsn


def hash_key(api_key: str) -> str:
    """SHA-256 hex digest used to look up a key without storing it."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def key_last4(api_key: str) -> str:
    return api_key[-4:] if len(api_key) >= 4 else api_key
