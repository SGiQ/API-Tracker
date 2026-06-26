"""HTTP ingestion service -- a thin front door to :class:`apitracker.Tracker`.

Apps POST normalized usage with a per-app key (``X-App-Key``) instead of holding
the database DSN. Every request resolves the key to an app and calls
``Tracker.record()``, so all attribution, pricing, and storage logic stays in the
core library -- this module adds only auth + request shape.

Run it with::

    apitracker serve                         # uses $APITRACKER_DSN, $PORT
    uvicorn --factory apitracker.server:create_app

Install the extra first: ``pip install "api-tracker[server]"``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise ModuleNotFoundError(
        "The ingest service needs FastAPI. Install it with: pip install \"api-tracker[server]\""
    ) from exc

from .tracker import Tracker
from .usage import Usage


class UsageIn(BaseModel):
    """One LLM call's normalized usage. Token buckets are disjoint (see Usage)."""

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cached_input_tokens: int = Field(0, ge=0)
    cache_write_tokens: int = Field(0, ge=0)
    request_id: Optional[str] = None
    metadata: Optional[dict] = None
    occurred_at: Optional[datetime] = None


def create_app(tracker: Tracker | None = None) -> "FastAPI":
    """Build the FastAPI app. Pass a ``tracker`` to inject one (used in tests);
    otherwise a default ``Tracker()`` is created from ``$APITRACKER_DSN``."""
    app = FastAPI(title="API-Tracker ingest", version="1.0")
    _tracker = tracker or Tracker()

    def require_app_id(x_app_key: str = Header(..., alias="X-App-Key")) -> int:
        app_id = _tracker.db.app_id_by_app_key(x_app_key)
        if app_id is None:
            raise HTTPException(status_code=401, detail="invalid or revoked app key")
        return app_id

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/v1/usage")
    def ingest(u: UsageIn, app_id: int = Depends(require_app_id)) -> dict:
        event_id = _tracker.record(
            app_id=app_id,
            provider=u.provider,
            model=u.model,
            usage=Usage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cached_input_tokens=u.cached_input_tokens,
                cache_write_tokens=u.cache_write_tokens,
            ),
            request_id=u.request_id,
            metadata=u.metadata,
            occurred_at=u.occurred_at,
        )
        return {"id": event_id}

    return app
