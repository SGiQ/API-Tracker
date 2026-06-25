"""Per-model pricing and pure cost computation.

Pricing is *data*, not logic: rates change over time and you want the rate that
was in effect when a call was made for accurate historical billing. The seed
below is loaded into the ``model_pricing`` table (see :mod:`apitracker.db`);
update that table (or this seed + reload) when a provider changes prices.

All rates are **USD per 1,000,000 tokens**.

Sourcing / accuracy:
* Anthropic rates are current as of 2026-06 (input/output, cache-read = 0.1x
  input, cache-write 5m = 1.25x input).
* OpenAI and Perplexity rates are seeded from publicly published list prices but
  MUST BE VERIFIED against each provider's pricing page before you bill on them
  -- they drift, and Perplexity additionally charges per-request search fees
  that token counts do not capture. Rows you don't trust can simply be edited or
  deleted in the ``model_pricing`` table. Usage for an unpriced model is still
  recorded (with a NULL cost) so nothing is ever lost; it just shows up under
  "unpriced" in reports until you add a rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .usage import Usage

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Rate:
    provider: str
    model: str
    input: Decimal           # USD / Mtok, full-rate input
    output: Decimal          # USD / Mtok, output
    cached_input: Optional[Decimal] = None   # USD / Mtok, cache read; defaults to 0.1x input
    cache_write: Optional[Decimal] = None    # USD / Mtok, cache write; defaults to input

    def cached_input_rate(self) -> Decimal:
        return self.cached_input if self.cached_input is not None else self.input * Decimal("0.1")

    def cache_write_rate(self) -> Decimal:
        return self.cache_write if self.cache_write is not None else self.input


def compute_cost(rate: Rate, usage: Usage) -> Decimal:
    """Return the USD cost of ``usage`` under ``rate`` (full precision Decimal)."""
    cost = (
        Decimal(usage.input_tokens) * rate.input
        + Decimal(usage.output_tokens) * rate.output
        + Decimal(usage.cached_input_tokens) * rate.cached_input_rate()
        + Decimal(usage.cache_write_tokens) * rate.cache_write_rate()
    ) / _MILLION
    # Money to 6 decimal places -- sub-cent precision matters at scale.
    return cost.quantize(Decimal("0.000001"))


def _d(value: str) -> Decimal:
    return Decimal(value)


# (provider, model, input, output, cached_input, cache_write)
# cached_input/cache_write left as None fall back to 0.1x / 1.0x input.
SEED_PRICING: list[Rate] = [
    # --- Anthropic (authoritative, 2026-06) -------------------------------
    Rate("anthropic", "claude-fable-5",   _d("10"), _d("50"), _d("1.0"),  _d("12.5")),
    Rate("anthropic", "claude-mythos-5",  _d("10"), _d("50"), _d("1.0"),  _d("12.5")),
    Rate("anthropic", "claude-opus-4-8",  _d("5"),  _d("25"), _d("0.5"),  _d("6.25")),
    Rate("anthropic", "claude-opus-4-7",  _d("5"),  _d("25"), _d("0.5"),  _d("6.25")),
    Rate("anthropic", "claude-opus-4-6",  _d("5"),  _d("25"), _d("0.5"),  _d("6.25")),
    Rate("anthropic", "claude-opus-4-5",  _d("5"),  _d("25"), _d("0.5"),  _d("6.25")),
    Rate("anthropic", "claude-sonnet-4-6", _d("3"), _d("15"), _d("0.3"),  _d("3.75")),
    Rate("anthropic", "claude-sonnet-4-5", _d("3"), _d("15"), _d("0.3"),  _d("3.75")),
    Rate("anthropic", "claude-haiku-4-5", _d("1"),  _d("5"),  _d("0.1"),  _d("1.25")),

    # --- OpenAI (VERIFY against https://openai.com/api/pricing) ------------
    Rate("openai", "gpt-4o",        _d("2.50"), _d("10.00"), _d("1.25")),
    Rate("openai", "gpt-4o-mini",   _d("0.15"), _d("0.60"),  _d("0.075")),
    Rate("openai", "gpt-4.1",       _d("2.00"), _d("8.00"),  _d("0.50")),
    Rate("openai", "gpt-4.1-mini",  _d("0.40"), _d("1.60"),  _d("0.10")),
    Rate("openai", "gpt-4.1-nano",  _d("0.10"), _d("0.40"),  _d("0.025")),
    Rate("openai", "o3",            _d("2.00"), _d("8.00"),  _d("0.50")),
    Rate("openai", "o4-mini",       _d("1.10"), _d("4.40"),  _d("0.275")),

    # --- Perplexity (VERIFY against https://docs.perplexity.ai/guides/pricing;
    #     token rates only -- per-request search fees are NOT captured here) -
    Rate("perplexity", "sonar",               _d("1.00"), _d("1.00")),
    Rate("perplexity", "sonar-pro",           _d("3.00"), _d("15.00")),
    Rate("perplexity", "sonar-reasoning",     _d("1.00"), _d("5.00")),
    Rate("perplexity", "sonar-reasoning-pro", _d("2.00"), _d("8.00")),
]
