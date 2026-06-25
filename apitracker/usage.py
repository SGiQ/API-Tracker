"""Normalized token-usage representation shared across providers.

Each provider reports token usage with a different shape. We normalize all of
them into a single :class:`Usage` so cost computation and storage are uniform.

Conventions (important for correct billing):

* ``input_tokens``       -- *uncached* prompt tokens, billed at the full input rate.
* ``cached_input_tokens``-- prompt tokens served from a cache (cache *read*),
                            billed at the discounted cached-input rate.
* ``cache_write_tokens`` -- prompt tokens written to a cache (Anthropic cache
                            *creation*), billed at the cache-write premium.
* ``output_tokens``      -- generated tokens, billed at the output rate.

The three input buckets are disjoint: the total prompt size is
``input_tokens + cached_input_tokens + cache_write_tokens``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cached_input_tokens
            + self.cache_write_tokens
        )


def _int(value) -> int:
    """Coerce a possibly-None numeric attribute to a non-negative int."""
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def from_anthropic_usage(u) -> Usage:
    """Normalize an Anthropic ``response.usage`` object.

    Anthropic reports ``input_tokens`` as the *uncached remainder* already, with
    ``cache_read_input_tokens`` and ``cache_creation_input_tokens`` tracked
    separately -- so the buckets map across directly with no subtraction.
    """
    return Usage(
        input_tokens=_int(getattr(u, "input_tokens", 0)),
        output_tokens=_int(getattr(u, "output_tokens", 0)),
        cached_input_tokens=_int(getattr(u, "cache_read_input_tokens", 0)),
        cache_write_tokens=_int(getattr(u, "cache_creation_input_tokens", 0)),
    )


def from_openai_usage(u) -> Usage:
    """Normalize an OpenAI (or OpenAI-compatible, e.g. Perplexity) ``usage`` object.

    OpenAI reports ``prompt_tokens`` *inclusive* of cached tokens, with the
    cached portion under ``prompt_tokens_details.cached_tokens``. We subtract it
    out so ``input_tokens`` holds only the full-rate remainder.
    """
    prompt_tokens = _int(getattr(u, "prompt_tokens", 0))
    completion_tokens = _int(getattr(u, "completion_tokens", 0))

    cached = 0
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = _int(getattr(details, "cached_tokens", 0))
    cached = min(cached, prompt_tokens)

    return Usage(
        input_tokens=prompt_tokens - cached,
        output_tokens=completion_tokens,
        cached_input_tokens=cached,
        cache_write_tokens=0,
    )


def from_gemini_usage(u) -> Usage:
    """Normalize a Gemini ``response.usage_metadata`` object.

    Works for both the new ``google-genai`` and old ``google-generativeai`` SDKs
    (same field names). ``prompt_token_count`` is inclusive of cached tokens, so
    the cached portion (``cached_content_token_count``) is subtracted out. Thinking
    tokens (``thoughts_token_count``) are billed as output, so they're folded into
    ``output_tokens`` alongside the visible ``candidates_token_count``.
    """
    prompt = _int(getattr(u, "prompt_token_count", 0))
    candidates = _int(getattr(u, "candidates_token_count", 0))
    thoughts = _int(getattr(u, "thoughts_token_count", 0))
    cached = min(_int(getattr(u, "cached_content_token_count", 0)), prompt)

    return Usage(
        input_tokens=prompt - cached,
        output_tokens=candidates + thoughts,
        cached_input_tokens=cached,
        cache_write_tokens=0,
    )
