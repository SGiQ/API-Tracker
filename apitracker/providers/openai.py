"""Tracked OpenAI client.

Usage::

    import openai
    from apitracker import Tracker
    from apitracker.providers import TrackedOpenAI

    tracker = Tracker("postgresql://...")
    client = TrackedOpenAI(tracker, app="my-search-app",
                           client=openai.OpenAI())

    resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "Hi"}],
    )

Streaming: pass ``stream_options={"include_usage": True}`` and record the final
chunk's ``.usage`` via ``tracker.record_openai(...)`` yourself, since usage only
arrives on the terminal chunk.
"""

from __future__ import annotations

from typing import Optional

from ..tracker import Tracker

_PROVIDER = "openai"


class TrackedOpenAI:
    def __init__(
        self,
        tracker: Tracker,
        *,
        app: Optional[str] = None,
        api_key: Optional[str] = None,
        client=None,
        provider: str = _PROVIDER,
        **client_kwargs,
    ):
        if client is None:
            import openai  # lazy

            client = openai.OpenAI(**client_kwargs)
        self._client = client
        self._tracker = tracker
        self._app = app
        self._provider = provider
        self._api_key = api_key or getattr(client, "api_key", None)

    @property
    def chat(self) -> "_Chat":
        return _Chat(self._client.chat, self._tracker, self._app, self._api_key, self._provider)

    def __getattr__(self, name):
        return getattr(self._client, name)


class _Chat:
    def __init__(self, raw, tracker, app, api_key, provider):
        self._raw = raw
        self._tracker = tracker
        self._app = app
        self._api_key = api_key
        self._provider = provider

    @property
    def completions(self) -> "_Completions":
        return _Completions(
            self._raw.completions, self._tracker, self._app, self._api_key, self._provider
        )

    def __getattr__(self, name):
        return getattr(self._raw, name)


class _Completions:
    def __init__(self, raw, tracker, app, api_key, provider):
        self._raw = raw
        self._tracker = tracker
        self._app = app
        self._api_key = api_key
        self._provider = provider

    def create(self, *args, **kwargs):
        response = self._raw.create(*args, **kwargs)
        if not kwargs.get("stream") and getattr(response, "usage", None) is not None:
            self._tracker.record_openai(
                response, provider=self._provider, app=self._app,
                api_key=self._api_key, model=kwargs.get("model"),
            )
        return response

    def __getattr__(self, name):
        return getattr(self._raw, name)
