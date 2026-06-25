import os

import pytest

from apitracker.db import Database


def test_pool_only_does_not_require_dsn(monkeypatch):
    """Passing a pre-built pool must not demand APITRACKER_DSN (used for
    transaction-pooler setups where prepared statements are disabled)."""
    monkeypatch.delenv("APITRACKER_DSN", raising=False)
    sentinel = object()
    db = Database(pool=sentinel)
    assert db._pool is sentinel


def test_no_pool_no_dsn_raises(monkeypatch):
    monkeypatch.delenv("APITRACKER_DSN", raising=False)
    with pytest.raises(ValueError):
        Database()
