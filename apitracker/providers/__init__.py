"""Drop-in wrappers around the official provider SDKs that auto-record usage.

Each wrapper proxies the underlying client unchanged except that it records a
usage event after every (non-streaming) completion call. Anything not
intercepted falls through via ``__getattr__``.
"""

from .anthropic import TrackedAnthropic
from .gemini import TrackedGemini
from .openai import TrackedOpenAI
from .perplexity import TrackedPerplexity

__all__ = ["TrackedAnthropic", "TrackedOpenAI", "TrackedPerplexity", "TrackedGemini"]
