"""apitracker-client -- tiny Python client for the API-Tracker ingest service.

Report LLM usage over HTTP, attributed per app, with no database credentials in
your app. Mirrors the Node ``@sgiq/apitracker`` SDK.

Two ways to use it:

    # 1. Wrap a provider client once; calls record themselves.
    import openai
    from apitracker_client import track
    client = track(openai.OpenAI(api_key=...), app="checkwellcall")
    client.chat.completions.create(model="gpt-4o", messages=[...])

    # 2. Record manually (streaming, or any code path).
    from apitracker_client import record
    record(provider="openai", model="gpt-4o", input_tokens=100, output_tokens=40)

Config comes from the environment -- ``APITRACKER_URL`` and ``APITRACKER_KEY`` --
or pass ``url=`` / ``key=`` explicitly. With either missing the client is a no-op:
it never raises into, blocks, or slows your LLM calls (POSTs run on a background
thread and swallow their own errors). The *app* is resolved server-side from the
key, so the ``app=`` argument is for clarity only.

Standard library only -- no third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Optional
from urllib import request as _urlrequest

__all__ = ["record", "track", "TrackedOpenAI", "TrackedAnthropic"]

log = logging.getLogger("apitracker_client")

# A small daemon pool so POSTs never block the caller and never outlive the process.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="apitracker")


def _env(url: Optional[str], key: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    u = (url or os.environ.get("APITRACKER_URL") or "").rstrip("/")
    k = key or os.environ.get("APITRACKER_KEY")
    return (u or None, k)


def _post(url: str, key: str, body: dict, timeout: float) -> None:
    data = json.dumps(body).encode("utf-8")
    req = _urlrequest.Request(
        f"{url}/v1/usage",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "X-App-Key": key},
    )
    try:
        with _urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted URL)
            resp.read()
    except Exception as exc:  # noqa: BLE001 - tracking must never raise into the app
        log.warning("apitracker-client: failed to post usage (non-fatal): %s", exc)


def _nonneg(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def record(
    *,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    url: Optional[str] = None,
    key: Optional[str] = None,
    timeout: float = 4.0,
) -> None:
    """Report one LLM call. Fire-and-forget: returns immediately, never raises,
    and is a no-op when the tracker isn't configured."""
    u, k = _env(url, key)
    if not u or not k:
        return
    body = {
        "provider": provider,
        "model": model,
        "input_tokens": _nonneg(input_tokens),
        "output_tokens": _nonneg(output_tokens),
        "cached_input_tokens": _nonneg(cached_input_tokens),
        "cache_write_tokens": _nonneg(cache_write_tokens),
        "user_id": user_id,
        "request_id": request_id,
        "metadata": metadata or {},
    }
    try:
        _pool.submit(_post, u, k, body, timeout)
    except RuntimeError:
        # Pool already shut down (interpreter exiting) -- drop silently.
        pass


# ── Usage normalization (structural -- no SDK imports) ────────────────────────

def _attr(obj: Any, name: str, default: Any = 0) -> Any:
    return getattr(obj, name, default) if obj is not None else default


def _from_openai(response: Any) -> dict:
    u = _attr(response, "usage", None)
    prompt = _nonneg(_attr(u, "prompt_tokens", 0))
    completion = _nonneg(_attr(u, "completion_tokens", 0))
    details = _attr(u, "prompt_tokens_details", None)
    cached = min(_nonneg(_attr(details, "cached_tokens", 0)), prompt)
    return {
        "input_tokens": prompt - cached,
        "output_tokens": completion,
        "cached_input_tokens": cached,
        "model": _attr(response, "model", "unknown"),
        "request_id": _attr(response, "id", None),
    }


def _from_anthropic(response: Any) -> dict:
    u = _attr(response, "usage", None)
    return {
        "input_tokens": _nonneg(_attr(u, "input_tokens", 0)),
        "output_tokens": _nonneg(_attr(u, "output_tokens", 0)),
        "cached_input_tokens": _nonneg(_attr(u, "cache_read_input_tokens", 0)),
        "cache_write_tokens": _nonneg(_attr(u, "cache_creation_input_tokens", 0)),
        "model": _attr(response, "model", "unknown"),
        "request_id": _attr(response, "id", None),
    }


# ── Client wrappers ───────────────────────────────────────────────────────────

class _LeafProxy:
    """Wraps the method container (e.g. ``completions`` or ``messages``) and
    intercepts the named methods to record usage; everything else passes through."""

    def __init__(self, target: Any, methods: Iterable[str], on_result, opts: dict):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_m", set(methods))
        object.__setattr__(self, "_on", on_result)
        object.__setattr__(self, "_opts", opts)

    def __getattr__(self, name: str):
        attr = getattr(self._t, name)
        if name in self._m and callable(attr):
            def wrapped(*args, **kwargs):
                result = attr(*args, **kwargs)
                try:
                    self._on(result, self._opts)
                except Exception as exc:  # noqa: BLE001
                    log.warning("apitracker-client: record failed (non-fatal): %s", exc)
                return result
            return wrapped
        return attr


class _PathProxy:
    """Navigates an attribute path (e.g. ``chat`` -> ``completions``) then hands
    off to a _LeafProxy that intercepts the call methods."""

    def __init__(self, target: Any, path: list[str], methods: Iterable[str], on_result, opts: dict):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_p", path)
        object.__setattr__(self, "_m", methods)
        object.__setattr__(self, "_on", on_result)
        object.__setattr__(self, "_opts", opts)

    def __getattr__(self, name: str):
        attr = getattr(self._t, name)
        if self._p and name == self._p[0]:
            rest = self._p[1:]
            if rest:
                return _PathProxy(attr, rest, self._m, self._on, self._opts)
            return _LeafProxy(attr, self._m, self._on, self._opts)
        return attr


def _record_from(normalize):
    def on_result(result, opts):
        norm = normalize(result)
        record(
            provider=opts["provider"],
            model=norm["model"],
            input_tokens=norm.get("input_tokens", 0),
            output_tokens=norm.get("output_tokens", 0),
            cached_input_tokens=norm.get("cached_input_tokens", 0),
            cache_write_tokens=norm.get("cache_write_tokens", 0),
            user_id=opts.get("user_id"),
            request_id=norm.get("request_id"),
            metadata=opts.get("metadata"),
            url=opts.get("url"),
            key=opts.get("key"),
        )
    return on_result


def TrackedOpenAI(client: Any, *, app: Optional[str] = None, provider: str = "openai", **opts) -> Any:
    """Wrap an OpenAI (or OpenAI-compatible) client so ``chat.completions.create``
    records usage. Pass ``provider="perplexity"`` for Perplexity."""
    o = {"provider": provider, "app": app, **opts}
    return _PathProxy(client, ["chat", "completions"], {"create", "parse"}, _record_from(_from_openai), o)


def TrackedAnthropic(client: Any, *, app: Optional[str] = None, **opts) -> Any:
    """Wrap an Anthropic client so ``messages.create`` / ``messages.parse`` record usage."""
    o = {"provider": "anthropic", "app": app, **opts}
    return _PathProxy(client, ["messages"], {"create", "parse"}, _record_from(_from_anthropic), o)


def track(client: Any, *, app: Optional[str] = None, **opts) -> Any:
    """Auto-detect an OpenAI or Anthropic client and wrap it. For Perplexity or
    other OpenAI-compatible endpoints, use ``TrackedOpenAI(client, provider=...)``."""
    if hasattr(client, "chat") and hasattr(getattr(client, "chat"), "completions"):
        return TrackedOpenAI(client, app=app, **opts)
    if hasattr(client, "messages"):
        return TrackedAnthropic(client, app=app, **opts)
    raise TypeError(
        "apitracker-client: could not detect provider client. "
        "Use TrackedOpenAI() or TrackedAnthropic() explicitly."
    )
