"""Tracked Perplexity client.

Perplexity exposes an OpenAI-compatible API, so this is the :class:`TrackedOpenAI`
wrapper pointed at the Perplexity base URL and labelled with the ``perplexity``
provider (so usage prices and reports under Perplexity, not OpenAI).

Usage::

    from apitracker import Tracker
    from apitracker.providers import TrackedPerplexity

    tracker = Tracker("postgresql://...")
    client = TrackedPerplexity(tracker, app="research-bot", api_key="pplx-...")

    resp = client.chat.completions.create(
        model="sonar", messages=[{"role": "user", "content": "latest on X?"}],
    )

Note: Perplexity also bills per-request search fees that token usage does not
capture; ``cost_usd`` here reflects token costs only.
"""

from __future__ import annotations

from typing import Optional

from ..tracker import Tracker
from .openai import TrackedOpenAI

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"


class TrackedPerplexity(TrackedOpenAI):
    def __init__(
        self,
        tracker: Tracker,
        *,
        app: Optional[str] = None,
        api_key: Optional[str] = None,
        client=None,
        base_url: str = PERPLEXITY_BASE_URL,
        **client_kwargs,
    ):
        if client is None:
            import openai  # lazy

            client = openai.OpenAI(api_key=api_key, base_url=base_url, **client_kwargs)
        super().__init__(
            tracker, app=app, api_key=api_key, client=client, provider="perplexity"
        )
