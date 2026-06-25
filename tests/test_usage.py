from types import SimpleNamespace

from apitracker.usage import (
    Usage,
    from_anthropic_usage,
    from_gemini_usage,
    from_openai_usage,
)


def test_anthropic_usage_maps_buckets_directly():
    u = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=200,
        cache_creation_input_tokens=30,
    )
    assert from_anthropic_usage(u) == Usage(
        input_tokens=100, output_tokens=50,
        cached_input_tokens=200, cache_write_tokens=30,
    )


def test_anthropic_missing_cache_fields_default_zero():
    u = SimpleNamespace(input_tokens=10, output_tokens=5)
    assert from_anthropic_usage(u) == Usage(input_tokens=10, output_tokens=5)


def test_openai_subtracts_cached_from_prompt():
    u = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
    )
    # input_tokens is the full-rate remainder: 1000 - 400 = 600
    assert from_openai_usage(u) == Usage(
        input_tokens=600, output_tokens=200, cached_input_tokens=400,
    )


def test_openai_without_cache_details():
    u = SimpleNamespace(prompt_tokens=300, completion_tokens=100)
    assert from_openai_usage(u) == Usage(input_tokens=300, output_tokens=100)


def test_none_values_coerced_to_zero():
    u = SimpleNamespace(prompt_tokens=None, completion_tokens=None)
    assert from_openai_usage(u) == Usage()


def test_gemini_folds_thoughts_into_output_and_subtracts_cache():
    u = SimpleNamespace(
        prompt_token_count=1000,
        candidates_token_count=200,
        thoughts_token_count=50,        # thinking tokens billed as output
        cached_content_token_count=400,
    )
    assert from_gemini_usage(u) == Usage(
        input_tokens=600, output_tokens=250, cached_input_tokens=400,
    )


def test_gemini_minimal_fields():
    u = SimpleNamespace(prompt_token_count=120, candidates_token_count=30)
    assert from_gemini_usage(u) == Usage(input_tokens=120, output_tokens=30)
