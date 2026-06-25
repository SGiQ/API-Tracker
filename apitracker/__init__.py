"""API-Tracker: track and separate LLM API usage per app for billing.

Supports Anthropic, OpenAI, and Perplexity. Usage is attributed to an app
(by explicit tag or by provider API key), priced per model, and stored in
Postgres for billing reports.
"""

from .db import Database
from .pricing import Rate, compute_cost
from .tracker import Tracker
from .usage import Usage, from_anthropic_usage, from_openai_usage

__all__ = [
    "Tracker",
    "Database",
    "Rate",
    "compute_cost",
    "Usage",
    "from_anthropic_usage",
    "from_openai_usage",
]

__version__ = "0.1.0"
