"""Tests for the HTTP ingestion service.

These run without a database: a fake Tracker is injected so we exercise only the
service's auth + request-shape + record-dispatch behavior. Skipped entirely when
FastAPI / its TestClient deps aren't installed (`pip install ".[dev]"`).
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # FastAPI's TestClient runs on httpx

from fastapi.testclient import TestClient  # noqa: E402

from apitracker.server import create_app  # noqa: E402


class _FakeDB:
    def __init__(self, keys: dict[str, int]):
        self._keys = keys

    def app_id_by_app_key(self, api_key: str):
        return self._keys.get(api_key)


class _FakeTracker:
    """Stands in for Tracker: records calls instead of touching Postgres."""

    def __init__(self, keys: dict[str, int]):
        self.db = _FakeDB(keys)
        self.calls: list[dict] = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return 4242


def _client(keys=None):
    tracker = _FakeTracker(keys or {"atk_valid": 7})
    return TestClient(create_app(tracker)), tracker


def test_healthz_ok():
    client, _ = _client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_missing_key_is_rejected():
    client, tracker = _client()
    resp = client.post("/v1/usage", json={"provider": "anthropic", "model": "claude-opus-4-8"})
    assert resp.status_code == 422  # required header absent
    assert tracker.calls == []


def test_invalid_key_is_unauthorized():
    client, tracker = _client()
    resp = client.post(
        "/v1/usage",
        headers={"X-App-Key": "atk_nope"},
        json={"provider": "anthropic", "model": "claude-opus-4-8"},
    )
    assert resp.status_code == 401
    assert tracker.calls == []


def test_valid_key_records_with_resolved_app_id():
    client, tracker = _client({"atk_valid": 7})
    resp = client.post(
        "/v1/usage",
        headers={"X-App-Key": "atk_valid"},
        json={
            "provider": "anthropic",
            "model": "claude-opus-4-8",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cached_input_tokens": 200,
            "cache_write_tokens": 50,
            "request_id": "req_123",
            "metadata": {"endpoint": "/chat"},
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"id": 4242}

    assert len(tracker.calls) == 1
    call = tracker.calls[0]
    assert call["app_id"] == 7  # resolved from the key, not the request body
    assert call["provider"] == "anthropic"
    assert call["model"] == "claude-opus-4-8"
    assert call["request_id"] == "req_123"
    assert call["metadata"] == {"endpoint": "/chat"}
    usage = call["usage"]
    assert (usage.input_tokens, usage.output_tokens) == (1000, 500)
    assert (usage.cached_input_tokens, usage.cache_write_tokens) == (200, 50)


def test_negative_tokens_are_rejected():
    client, tracker = _client()
    resp = client.post(
        "/v1/usage",
        headers={"X-App-Key": "atk_valid"},
        json={"provider": "anthropic", "model": "claude-opus-4-8", "input_tokens": -5},
    )
    assert resp.status_code == 422
    assert tracker.calls == []
