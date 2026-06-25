"""Tracked Anthropic client.

Usage::

    import anthropic
    from apitracker import Tracker
    from apitracker.providers import TrackedAnthropic

    tracker = Tracker("postgresql://...")
    client = TrackedAnthropic(tracker, app="my-chatbot",
                              client=anthropic.Anthropic())

    msg = client.messages.create(
        model="claude-opus-4-8", max_tokens=1024,
        messages=[{"role": "user", "content": "Hi"}],
    )
    # usage for "my-chatbot" is now recorded.

Streaming: ``messages.create`` records non-streaming responses automatically.
For ``messages.stream(...)``, call ``tracker.record_anthropic(stream.get_final_message(), app=...)``
yourself after the stream completes (the final message carries the usage totals).
"""

from __future__ import annotations

from typing import Optional

from ..tracker import Tracker


class TrackedAnthropic:
    def __init__(
        self,
        tracker: Tracker,
        *,
        app: Optional[str] = None,
        api_key: Optional[str] = None,
        client=None,
        **client_kwargs,
    ):
        if client is None:
            import anthropic  # imported lazily so the dep is optional

            client = anthropic.Anthropic(**client_kwargs)
        self._client = client
        self._tracker = tracker
        self._app = app
        # If no explicit app, fall back to key-based attribution using the
        # client's own key (best-effort; SDKs expose it as .api_key).
        self._api_key = api_key or getattr(client, "api_key", None)

    @property
    def messages(self) -> "_Messages":
        return _Messages(self._client.messages, self._tracker, self._app, self._api_key)

    def __getattr__(self, name):
        return getattr(self._client, name)


class _Messages:
    def __init__(self, raw, tracker: Tracker, app, api_key):
        self._raw = raw
        self._tracker = tracker
        self._app = app
        self._api_key = api_key

    def create(self, *args, **kwargs):
        response = self._raw.create(*args, **kwargs)
        # Streaming returns an iterator/manager with no .usage yet; skip those.
        if not kwargs.get("stream") and getattr(response, "usage", None) is not None:
            self._tracker.record_anthropic(
                response, app=self._app, api_key=self._api_key,
                model=kwargs.get("model"),
            )
        return response

    def __getattr__(self, name):
        return getattr(self._raw, name)
