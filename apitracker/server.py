"""HTTP ingestion service + billing dashboard — a thin front door to the Tracker.

Endpoints:
  POST /v1/usage    Apps report usage with a per-app key (X-App-Key). Calls
                    Tracker.record(), so attribution/pricing/storage stay in the core.
  GET  /v1/report   Billing aggregates (JSON), protected by the dashboard key.
  GET  /            Self-contained HTML dashboard (calls /v1/report).
  GET  /healthz     Liveness probe.

Run it with::

    apitracker serve                         # uses $APITRACKER_DSN, $PORT
    uvicorn --factory apitracker.server:create_app

Install the extra first: ``pip install "api-tracker[server]"``.

The dashboard + report endpoint require ``$APITRACKER_DASHBOARD_KEY`` to be set;
without it they return 503 (so billing data is never exposed unprotected).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise ModuleNotFoundError(
        "The ingest service needs FastAPI. Install it with: pip install \"api-tracker[server]\""
    ) from exc

from .tracker import Tracker
from .usage import Usage

_GROUP_BY = ("app", "provider", "app-provider", "model", "user", "app-user")


class UsageIn(BaseModel):
    """One LLM call's normalized usage. Token buckets are disjoint (see Usage)."""

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cached_input_tokens: int = Field(0, ge=0)
    cache_write_tokens: int = Field(0, ge=0)
    request_id: Optional[str] = None
    user_id: Optional[str] = None  # the app's own user id, for per-user billing
    metadata: Optional[dict] = None
    occurred_at: Optional[datetime] = None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _normalize_row(r: dict) -> dict:
    out = {k: r[k] for k in ("app", "user", "provider", "model") if k in r}
    out.update(
        calls=int(r["calls"] or 0),
        input_tokens=int(r["input_tokens"] or 0),
        output_tokens=int(r["output_tokens"] or 0),
        cached_input_tokens=int(r["cached_input_tokens"] or 0),
        cache_write_tokens=int(r["cache_write_tokens"] or 0),
        cost_usd=float(r["cost_usd"] or 0),
        unpriced_calls=int(r["unpriced_calls"] or 0),
    )
    return out


def create_app(tracker: Tracker | None = None, dashboard_key: str | None = None) -> "FastAPI":
    """Build the FastAPI app. Pass a ``tracker`` to inject one (used in tests);
    otherwise a default ``Tracker()`` is created from ``$APITRACKER_DSN``.
    ``dashboard_key`` defaults to ``$APITRACKER_DASHBOARD_KEY``."""
    app = FastAPI(title="API-Tracker", version="1.1")
    _tracker = tracker or Tracker()
    _dash_key = dashboard_key if dashboard_key is not None else os.environ.get("APITRACKER_DASHBOARD_KEY")

    def require_app_id(x_app_key: str = Header(..., alias="X-App-Key")) -> int:
        app_id = _tracker.db.app_id_by_app_key(x_app_key)
        if app_id is None:
            raise HTTPException(status_code=401, detail="invalid or revoked app key")
        return app_id

    def require_dashboard(
        x_dashboard_key: Optional[str] = Header(None, alias="X-Dashboard-Key"),
        key: Optional[str] = Query(None),
    ) -> None:
        if not _dash_key:
            raise HTTPException(status_code=503, detail="dashboard disabled: set APITRACKER_DASHBOARD_KEY")
        if (x_dashboard_key or key) != _dash_key:
            raise HTTPException(status_code=401, detail="invalid dashboard key")

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
            user_id=u.user_id,
            metadata=u.metadata,
            occurred_at=u.occurred_at,
        )
        return {"id": event_id}

    @app.get("/v1/report")
    def report(
        by: str = "app-provider",
        since: Optional[str] = None,
        until: Optional[str] = None,
        user: Optional[str] = None,
        _: None = Depends(require_dashboard),
    ) -> dict:
        if by not in _GROUP_BY:
            raise HTTPException(status_code=400, detail=f"by must be one of {list(_GROUP_BY)}")
        rows = [
            _normalize_row(r)
            for r in _tracker.db.report(
                since=_parse_dt(since), until=_parse_dt(until), group_by=by, user=user or None
            )
        ]
        total = round(sum(r["cost_usd"] for r in rows), 6)
        return {"by": by, "rows": rows, "total_cost_usd": total}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _DASHBOARD_HTML

    return app


# ── Self-contained dashboard page (no external assets) ────────────────────────
_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>API-Tracker</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f1115; color: #e6e8eb; }
  header { padding: 18px 24px; border-bottom: 1px solid #232733; display: flex;
           align-items: baseline; gap: 16px; flex-wrap: wrap; }
  h1 { font-size: 18px; margin: 0; font-weight: 600; }
  .total { margin-left: auto; font-size: 22px; font-weight: 700; color: #7dd3fc; }
  .total small { font-size: 12px; font-weight: 400; color: #8b93a1; }
  .controls { padding: 14px 24px; display: flex; gap: 12px; align-items: end; flex-wrap: wrap;
              border-bottom: 1px solid #232733; }
  label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
          color: #8b93a1; margin-bottom: 4px; }
  select, input, button { background: #1a1e27; color: #e6e8eb; border: 1px solid #2c313d;
          border-radius: 6px; padding: 7px 10px; font: inherit; }
  button { cursor: pointer; border-color: #3b82f6; }
  button:hover { background: #21262f; }
  .wrap { padding: 20px 24px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: right; padding: 8px 12px; border-bottom: 1px solid #1c2029; white-space: nowrap; }
  th { color: #8b93a1; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  td.dim, th.dim { text-align: left; }
  tr:hover td { background: #151922; }
  .cost { color: #7dd3fc; font-variant-numeric: tabular-nums; }
  .unpriced { color: #f59e0b; }
  .bars { margin: 4px 0 18px; }
  .bar-row { display: flex; align-items: center; gap: 10px; margin: 3px 0; }
  .bar-label { width: 200px; color: #c7cdd6; overflow: hidden; text-overflow: ellipsis; }
  .bar-track { flex: 1; background: #161a22; border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 16px; background: linear-gradient(90deg,#3b82f6,#7dd3fc); }
  .bar-val { width: 90px; text-align: right; color: #7dd3fc; font-variant-numeric: tabular-nums; }
  .muted { color: #8b93a1; }
</style>
</head>
<body>
<header>
  <h1>API-Tracker</h1>
  <span class="muted">LLM usage &amp; billing</span>
  <span class="total"><span id="total">—</span> <small>total</small></span>
</header>
<div class="controls">
  <div><label>Group by</label>
    <select id="by">
      <option value="app">app</option>
      <option value="app-provider" selected>app + provider</option>
      <option value="provider">provider</option>
      <option value="model">app + provider + model</option>
      <option value="app-user">app + user</option>
      <option value="user">user</option>
    </select>
  </div>
  <div><label>Since</label><input type="date" id="since" /></div>
  <div><label>Until</label><input type="date" id="until" /></div>
  <div><label>User filter</label><input type="text" id="user" placeholder="user id" size="16" /></div>
  <button id="refresh">Refresh</button>
  <button id="rekey" title="Change dashboard key">Key</button>
</div>
<div class="wrap">
  <div class="bars" id="bars"></div>
  <table><thead id="thead"></thead><tbody id="tbody"></tbody></table>
  <p class="muted" id="status"></p>
</div>
<script>
const STORE = 'apitracker_dashboard_key';
const $ = (id) => document.getElementById(id);
function getKey(force) {
  let k = force ? null : localStorage.getItem(STORE);
  if (!k) { k = prompt('Dashboard key:'); if (k) localStorage.setItem(STORE, k); }
  return k;
}
const fmtUsd = (n) => '$' + Number(n).toFixed(4);
const fmtInt = (n) => Number(n).toLocaleString();

async function load() {
  const by = $('by').value, since = $('since').value, until = $('until').value, user = $('user').value.trim();
  const p = new URLSearchParams({ by });
  if (since) p.set('since', since);
  if (until) p.set('until', until);
  if (user) p.set('user', user);
  $('status').textContent = 'Loading…';
  let res;
  try { res = await fetch('/v1/report?' + p, { headers: { 'X-Dashboard-Key': getKey() } }); }
  catch (e) { $('status').textContent = 'Network error'; return; }
  if (res.status === 401) { localStorage.removeItem(STORE); $('status').textContent = 'Invalid key — click Key to re-enter.'; return; }
  if (res.status === 503) { $('status').textContent = 'Dashboard disabled: set APITRACKER_DASHBOARD_KEY on the service.'; return; }
  if (!res.ok) { $('status').textContent = 'Error ' + res.status; return; }
  render(await res.json());
}

function render(data) {
  $('total').textContent = fmtUsd(data.total_cost_usd);
  const rows = data.rows || [];
  const dims = ['app', 'user', 'provider', 'model'].filter((d) => rows[0] && d in rows[0]);
  const cols = [...dims, 'calls', 'input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_tokens', 'cost_usd', 'unpriced_calls'];
  const labels = { input_tokens: 'in', output_tokens: 'out', cached_input_tokens: 'cached', cache_write_tokens: 'cache wr', cost_usd: 'cost', unpriced_calls: 'unpriced' };

  $('thead').innerHTML = '<tr>' + cols.map((c) =>
    '<th class="' + (dims.includes(c) ? 'dim' : '') + '">' + (labels[c] || c) + '</th>').join('') + '</tr>';

  $('tbody').innerHTML = rows.map((r) => '<tr>' + cols.map((c) => {
    if (dims.includes(c)) return '<td class="dim">' + (r[c] ?? '') + '</td>';
    if (c === 'cost_usd') return '<td class="cost">' + fmtUsd(r[c]) + '</td>';
    if (c === 'unpriced_calls') return '<td class="' + (r[c] ? 'unpriced' : 'muted') + '">' + r[c] + '</td>';
    return '<td>' + fmtInt(r[c]) + '</td>';
  }).join('') + '</tr>').join('') || '<tr><td class="muted" colspan="' + cols.length + '">No usage in range.</td></tr>';

  const max = Math.max(1, ...rows.map((r) => r.cost_usd));
  $('bars').innerHTML = rows.slice(0, 10).map((r) => {
    const label = dims.map((d) => r[d]).join(' · ');
    const pct = (r.cost_usd / max) * 100;
    return '<div class="bar-row"><div class="bar-label">' + label + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div>' +
      '<div class="bar-val">' + fmtUsd(r.cost_usd) + '</div></div>';
  }).join('');

  $('status').textContent = rows.length + ' row(s).';
}

$('refresh').onclick = load;
$('by').onchange = load;
$('rekey').onclick = () => { getKey(true); load(); };
load();
</script>
</body>
</html>"""
