from decimal import Decimal

from apitracker.pricing import Rate, compute_cost
from apitracker.usage import Usage


def test_basic_input_output_cost():
    rate = Rate("anthropic", "claude-opus-4-8", Decimal("5"), Decimal("25"))
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    # 1M in @ $5 + 1M out @ $25 = $30
    assert compute_cost(rate, usage) == Decimal("30.000000")


def test_cached_input_defaults_to_tenth():
    # cached_input rate omitted -> 0.1x input.
    rate = Rate("anthropic", "x", Decimal("10"), Decimal("0"))
    usage = Usage(cached_input_tokens=1_000_000)
    assert compute_cost(rate, usage) == Decimal("1.000000")


def test_cache_write_defaults_to_input():
    rate = Rate("anthropic", "x", Decimal("10"), Decimal("0"))
    usage = Usage(cache_write_tokens=1_000_000)
    assert compute_cost(rate, usage) == Decimal("10.000000")


def test_explicit_cache_rates_used():
    rate = Rate(
        "anthropic", "claude-opus-4-8",
        Decimal("5"), Decimal("25"),
        cached_input=Decimal("0.5"), cache_write=Decimal("6.25"),
    )
    usage = Usage(
        input_tokens=1_000_000, output_tokens=1_000_000,
        cached_input_tokens=1_000_000, cache_write_tokens=1_000_000,
    )
    # 5 + 25 + 0.5 + 6.25 = 36.75
    assert compute_cost(rate, usage) == Decimal("36.750000")


def test_small_token_counts_keep_subcent_precision():
    rate = Rate("openai", "gpt-4o-mini", Decimal("0.15"), Decimal("0.60"))
    usage = Usage(input_tokens=1000, output_tokens=500)
    # (1000*0.15 + 500*0.60) / 1e6 = (150 + 300)/1e6 = 0.00045
    assert compute_cost(rate, usage) == Decimal("0.000450")
