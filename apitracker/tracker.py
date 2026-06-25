"""Core usage-recording logic: resolve the app, price the call, store the event."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .db import Database
from .pricing import compute_cost
from .usage import Usage, from_anthropic_usage, from_gemini_usage, from_openai_usage

log = logging.getLogger("apitracker")


class Tracker:
    """Records LLM usage events, attributing each to an app and pricing it.

    Attribution precedence: an explicit ``app`` slug always wins; otherwise the
    provider ``api_key`` is hashed and looked up in the key map; if neither
    resolves, the event is stored unattributed (never dropped).
    """

    def __init__(self, db: Database | str | None = None):
        self.db = db if isinstance(db, Database) else Database(db)

    # -- attribution -------------------------------------------------------

    def _resolve_app_id(
        self, *, provider: str, app: Optional[str], api_key: Optional[str]
    ) -> Optional[int]:
        if app:
            app_id = self.db.app_id_by_slug(app)
            if app_id is None:
                # Auto-create on first sight so callers don't have to pre-register.
                app_id = self.db.upsert_app(app)
            return app_id
        if api_key:
            return self.db.app_id_by_key(provider, api_key)
        return None

    # -- generic recording -------------------------------------------------

    def record(
        self,
        *,
        provider: str,
        model: str,
        usage: Usage,
        app: Optional[str] = None,
        api_key: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        occurred_at: Optional[datetime] = None,
    ) -> int:
        """Record a normalized :class:`Usage`. Returns the event id."""
        app_id = self._resolve_app_id(provider=provider, app=app, api_key=api_key)

        rate = self.db.current_rate(provider, model, at=occurred_at)
        cost: Optional[Decimal]
        if rate is None:
            cost = None
            log.warning(
                "No pricing for %s/%s -- recording usage with NULL cost. "
                "Add a row to model_pricing to price it.",
                provider,
                model,
            )
        else:
            cost = compute_cost(rate, usage)

        return self.db.insert_usage_event(
            app_id=app_id,
            provider=provider,
            model=model,
            usage=usage,
            cost_usd=cost,
            request_id=request_id,
            metadata=metadata,
            occurred_at=occurred_at,
        )

    # -- provider-specific convenience -------------------------------------

    def record_anthropic(
        self, response, *, app: Optional[str] = None, api_key: Optional[str] = None,
        model: Optional[str] = None, metadata: Optional[dict] = None,
    ) -> int:
        """Record from an Anthropic ``Message`` (or a streamed final message)."""
        return self.record(
            provider="anthropic",
            model=model or getattr(response, "model", "unknown"),
            usage=from_anthropic_usage(getattr(response, "usage", None) or _Empty()),
            app=app,
            api_key=api_key,
            request_id=getattr(response, "id", None),
            metadata=metadata,
        )

    def record_openai(
        self, response, *, provider: str = "openai", app: Optional[str] = None,
        api_key: Optional[str] = None, model: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        """Record from an OpenAI / OpenAI-compatible (e.g. Perplexity) completion.

        Pass ``provider="perplexity"`` for Perplexity calls so they price and
        report under the right provider.
        """
        return self.record(
            provider=provider,
            model=model or getattr(response, "model", "unknown"),
            usage=from_openai_usage(getattr(response, "usage", None) or _Empty()),
            app=app,
            api_key=api_key,
            request_id=getattr(response, "id", None),
            metadata=metadata,
        )

    def record_gemini(
        self, response, *, app: Optional[str] = None, api_key: Optional[str] = None,
        model: Optional[str] = None, metadata: Optional[dict] = None,
    ) -> int:
        """Record from a Gemini ``GenerateContentResponse`` (either SDK)."""
        return self.record(
            provider="gemini",
            model=model or getattr(response, "model_version", None) or "unknown",
            usage=from_gemini_usage(getattr(response, "usage_metadata", None) or _Empty()),
            app=app,
            api_key=api_key,
            request_id=getattr(response, "response_id", None),
            metadata=metadata,
        )

    def close(self) -> None:
        self.db.close()


class _Empty:
    """Stand-in when a response carries no usage object."""
