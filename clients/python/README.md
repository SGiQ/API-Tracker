# apitracker-client (Python)

Tiny Python client for the [API-Tracker](../../README.md) ingest service. Report
LLM usage over HTTP, attributed per app, with **no database credentials** in your
app. The Python counterpart to the Node `@sgiq/apitracker` SDK.

Standard-library only (no third-party deps).

## Install

```bash
pip install "apitracker-client @ git+https://github.com/SGiQ/API-Tracker.git@py-client-v0.1.0#subdirectory=clients/python"
```

(Pin the `@<tag>` for reproducible installs.)

## Configure

```bash
export APITRACKER_URL=https://your-ingest-service.up.railway.app
export APITRACKER_KEY=atk_…        # issue with: apitracker issue-key <app>
```

With either unset the client is a **no-op** — safe to leave wired in any env.

## Use

```python
import openai
from apitracker_client import track

client = track(openai.OpenAI(api_key=...), app="checkwellcall")
client.chat.completions.create(model="gpt-4o", messages=[...])   # recorded
```

`track()` auto-detects OpenAI and Anthropic clients. For Perplexity (OpenAI-compatible)
use `TrackedOpenAI(client, provider="perplexity")`.

Recording is fire-and-forget (runs on a background thread, swallows its own errors)
and never blocks or breaks the LLM call. The app is resolved server-side from the
key, so `app=` is for clarity only.

### Manual / streaming

```python
from apitracker_client import record

record(provider="openai", model="gpt-4o",
       input_tokens=100, output_tokens=40, user_id="patient_123")
```

## API

- `track(client, app=...)` — auto-detect OpenAI/Anthropic and wrap.
- `TrackedOpenAI(client, app=..., provider=...)` / `TrackedAnthropic(client, app=...)`.
- `record(provider=, model=, input_tokens=, output_tokens=, cached_input_tokens=, cache_write_tokens=, user_id=, request_id=, metadata=)`.
