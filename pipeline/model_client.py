"""Unified LLM client supporting DeepSeek, Qwen, and OpenAI via OpenAI-compatible API.

Usage:
    >>> from pipeline.model_client import quick_chat
    >>> resp = quick_chat("What is LangGraph?")
    >>> print(resp.content)
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Token usage statistics from an LLM response."""

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class LLMResponse:
    """Wrapped LLM response containing generated content and usage stats."""

    content: str
    usage: Usage = field(default_factory=lambda: Usage(0, 0))

    def __getitem__(self, key: str) -> Any:
        if key == "content":
            return self.content
        if key == "usage":
            return self.usage
        msg = f"LLMResponse has no field {key!r}"
        raise KeyError(msg)


# ---------------------------------------------------------------------------
# Provider registry — model → (input_price_per_1k, output_price_per_1k) in USD
# ---------------------------------------------------------------------------

MODEL_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.00027, 0.00110),
    "deepseek-reasoner": (0.00055, 0.00219),
    "qwen-plus": (0.00080, 0.00200),
    "qwen-turbo": (0.00030, 0.00060),
    "gpt-4o-mini": (0.00015, 0.00060),
    "gpt-4o": (0.00250, 0.01000),
    "gpt-4.1-mini": (0.00100, 0.00400),
    "gpt-4.1-nano": (0.00010, 0.00040),
}

# Cost in RMB per 1M tokens for the default model of each provider
PROVIDER_PRICES_RMB: dict[str, tuple[float, float]] = {
    "deepseek": (1.0, 2.0),
    "qwen": (4.0, 12.0),
    "openai": (150.0, 600.0),
}

PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "openai": "gpt-4o-mini",
}

DEFAULT_PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
}

ProviderName = Literal["deepseek", "qwen", "openai"]

# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base for LLM providers.

    Subclasses must implement :meth:`chat` which sends messages to the model
    and returns a structured response.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name identifier (e.g. ``deepseek``, ``qwen``, ``openai``)."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of message dicts with ``role`` and ``content`` keys.
            model: Model identifier. Falls back to provider default when
                ``None``.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens in the response. ``None`` means the
                model's default limit.

        Returns:
            LLMResponse with generated content and usage stats.

        Raises:
            httpx.HTTPStatusError: Server returned an error status.
            httpx.RequestError: Network or connection failure.
        """


# ---------------------------------------------------------------------------
# OpenAI-compatible implementation
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """Provider that calls any OpenAI-compatible chat completion endpoint.

    Args:
        api_key: API key for authentication.
        base_url: API base URL (e.g. ``https://api.deepseek.com``).
        default_model: Model name used when none is specified in ``chat()``.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str = "deepseek-chat",
        name: str = "deepseek",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._name = name
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: Conversation history.
            model: Override the default model.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            Structured response with content and usage.

        Raises:
            httpx.HTTPStatusError: On non-2xx status.
            httpx.RequestError: On network errors.
        """
        payload: dict = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(
            "POST %s model=%s messages=%d",
            url,
            payload["model"],
            len(messages),
        )

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        usage_data = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
        )

        return LLMResponse(content=content, usage=usage)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return self._default_model


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_provider(name: str | None = None) -> LLMProvider:
    """Create an LLM provider from environment configuration.

    Environment variables:

    * ``LLM_PROVIDER`` — one of ``deepseek``, ``qwen``, ``openai``
      (default: ``deepseek``)
    * ``DEEPSEEK_API_KEY`` / ``QWEN_API_KEY`` / ``OPENAI_API_KEY``
    * ``DEEPSEEK_BASE_URL`` / ``QWEN_BASE_URL`` / ``OPENAI_BASE_URL``
      (optional, falls back to the provider's default)

    Args:
        name: Provider name override. If ``None``, reads ``LLM_PROVIDER``
            from the environment.

    Returns:
        A configured :class:`LLMProvider` instance.

    Raises:
        ValueError: Unknown provider name or missing API key.
    """
    provider_name: str = (name or os.getenv("LLM_PROVIDER") or "deepseek").lower()

    cfg = DEFAULT_PROVIDER_CONFIG.get(provider_name)
    if cfg is None:
        msg = f"Unknown provider: {provider_name!r} (choices: {', '.join(DEFAULT_PROVIDER_CONFIG)})"
        raise ValueError(msg)

    key_var = f"{provider_name.upper()}_API_KEY"
    api_key = os.getenv(key_var)
    if not api_key:
        raise ValueError(
            f"Missing API key: set {key_var} environment variable "
            f"(or LLM_PROVIDER to switch providers)"
        )

    url_var = f"{provider_name.upper()}_BASE_URL"
    base_url = os.getenv(url_var) or cfg["base_url"]
    model = cfg["model"]

    logger.info(
        "Created provider: %s base_url=%s model=%s",
        provider_name,
        base_url,
        model,
    )
    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url,
        default_model=model,
        name=provider_name,
    )


# ---------------------------------------------------------------------------
# Cost Tracker
# ---------------------------------------------------------------------------


@dataclass
class _ProviderStats:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class CostTracker:
    """Tracks LLM token usage and estimates cost across providers.

    Usage:
        >>> tracker = CostTracker()
        >>> tracker.record(Usage(100, 50), "deepseek")
        >>> tracker.record(Usage(200, 80), "deepseek")
        >>> tracker.estimated_cost("deepseek")
        0.00056
        >>> tracker.report()
    """

    def __init__(self) -> None:
        self._providers: dict[str, _ProviderStats] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, usage: Usage, provider: str) -> None:
        """Record a single LLM API call.

        Args:
            usage: Token usage from the response.
            provider: Provider name (``deepseek``, ``qwen``, ``openai``).
        """
        stats = self._providers.setdefault(provider, _ProviderStats())
        stats.calls += 1
        stats.prompt_tokens += usage.prompt_tokens
        stats.completion_tokens += usage.completion_tokens

    def estimated_cost(self, provider: str) -> float:
        """Return cumulative estimated cost in RMB for a provider.

        Args:
            provider: Provider name.

        Returns:
            Cost in RMB.
        """
        stats = self._providers.get(provider)
        if stats is None:
            return 0.0

        prices = PROVIDER_PRICES_RMB.get(provider)
        if prices is None:
            logger.warning("Unknown provider %r for cost estimate", provider)
            return 0.0

        input_price, output_price = prices
        return (stats.prompt_tokens / 1_000_000 * input_price) + (
            stats.completion_tokens / 1_000_000 * output_price
        )

    def report(self, provider: str | None = None) -> str:
        """Print and return a cost report.

        Args:
            provider: When set, report only for this provider.
                When ``None``, report for all tracked providers.

        Returns:
            Formatted report string.
        """
        providers = [provider] if provider else sorted(self._providers)
        lines: list[str] = [
            "=" * 55,
            "  LLM Cost Report",
            "=" * 55,
            f"  {'Provider':<12} {'Calls':>6} {'Prompt':>8} {'Output':>8} {'Total':>8}  {'Cost(¥)':>10}",
            "  " + "-" * 53,
        ]

        total_cost = 0.0
        total_prompt = 0
        total_completion = 0
        total_calls = 0

        for prov in providers:
            stats = self._providers.get(prov)
            if stats is None:
                continue
            cost = self.estimated_cost(prov)
            total_cost += cost
            total_calls += stats.calls
            total_prompt += stats.prompt_tokens
            total_completion += stats.completion_tokens
            lines.append(
                f"  {prov:<12} {stats.calls:>6} {stats.prompt_tokens:>8,} "
                f"{stats.completion_tokens:>8,} {stats.prompt_tokens + stats.completion_tokens:>8,} "
                f"¥{cost:>8.4f}"
            )

        lines.append("  " + "-" * 53)
        lines.append(
            f"  {'TOTAL':<12} {total_calls:>6} {total_prompt:>8,} "
            f"{total_completion:>8,} {total_prompt + total_completion:>8,} "
            f"¥{total_cost:>8.4f}"
        )
        lines.append("=" * 55)

        report = "\n".join(lines)
        logger.info("\n%s", report)
        print(f"\n{report}")
        return report


# Global singleton used by the pipeline
_tracker: CostTracker = CostTracker()


def get_tracker() -> CostTracker:
    """Return the global :class:`CostTracker` instance.

    Returns:
        The global tracker used by :func:`chat_with_retry`.
    """
    return _tracker


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


def chat_with_retry(
    messages: list[dict[str, str]],
    *,
    provider: LLMProvider | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> LLMResponse:
    """Call ``chat()`` with automatic retries on transient failures.

    Retries on :class:`httpx.HTTPStatusError` (5xx) and
    :class:`httpx.RequestError` with exponential backoff.
    Other exceptions propagate immediately.

    Args:
        messages: Conversation history.
        provider: Provider instance. Created via :func:`create_provider`
            when ``None``.
        model: Model override.
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        max_retries: Maximum number of retry attempts (default 3).
        base_delay: Initial backoff delay in seconds (doubles each retry).

    Returns:
        LLM response.

    Raises:
        httpx.HTTPStatusError: After exhausting all retries on server errors.
        httpx.RequestError: After exhausting all retries on network errors.
    """
    provider = provider or create_provider()

    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            resp = provider.chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if resp.usage.total_tokens > 0:
                _tracker.record(resp.usage, provider.name)
            return resp
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise
            last_exc = e
        except httpx.RequestError as e:
            last_exc = e
        except Exception:
            raise

        if attempt < max_retries:
            delay = base_delay * (2**attempt)
            logger.warning(
                "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                max_retries + 1,
                delay,
                last_exc,
            )
            time.sleep(delay)

    raise RuntimeError(
        f"LLM call failed after {max_retries + 1} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# Token & cost helpers
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Roughly estimate token count for a text string.

    Uses a simple heuristic: count ASCII word-boundary tokens at 1.3 tokens
    per word, and CJK characters at 1.5 tokens per character.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    ascii_chars = 0
    cjk_chars = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af":
            cjk_chars += 1
        else:
            ascii_chars += 1

    return int(ascii_chars / 3.5 + cjk_chars * 1.5) + 1


def calculate_cost(
    usage: Usage,
    model: str = "deepseek-chat",
) -> float:
    """Calculate the USD cost of a model invocation.

    Args:
        usage: Token usage statistics.
        model: Model identifier. Looked up in :data:`MODEL_PRICES`.

    Returns:
        Cost in USD.
    """
    prices = MODEL_PRICES.get(model)
    if prices is None:
        logger.warning("Unknown model %r, returning 0 cost", model)
        return 0.0

    input_price, output_price = prices
    return (usage.prompt_tokens / 1000 * input_price) + (
        usage.completion_tokens / 1000 * output_price
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = "You are a helpful AI assistant."


def quick_chat(
    prompt: str,
    *,
    system: str = _SYSTEM_PROMPT,
    model: str | None = None,
    provider: LLMProvider | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> LLMResponse:
    """One-shot chat: send a single user prompt and get a response.

    Args:
        prompt: User message content.
        system: System prompt override (default: helpful assistant).
        model: Model override.
        provider: Provider instance. Auto-created when ``None``.
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.

    Returns:
        LLM response.
    """
    provider = provider or create_provider()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    return provider.chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Convenience exports
# ---------------------------------------------------------------------------

def chat(
    prompt: str | list[dict[str, str]],
    *,
    provider: LLMProvider | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> LLMResponse:
    """Send a chat prompt with automatic retry and cost tracking.

    Accepts either a plain string (single user message) or a list of
    message dicts for multi-turn conversations.

    Args:
        prompt: Plain string user message, or list of ``{"role": ..., "content": ...}`` dicts.
        provider: Provider instance. Auto-created when ``None``.
        model: Model override.
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial backoff delay in seconds.

    Returns:
        LLM response.
    """
    messages: list[dict[str, str]]
    if isinstance(prompt, str):
        messages = [{"role": "user", "content": prompt}]
    else:
        messages = prompt

    return chat_with_retry(
        messages,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        base_delay=base_delay,
    )


tracker = get_tracker()

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        provider = create_provider()
        logger.info("Provider created: %s", type(provider).__name__)

        resp = chat_with_retry(
            [{"role": "user", "content": "Say hello in one sentence."}],
            temperature=0.3,
            max_tokens=50,
        )
        logger.info("Response: %s", resp.content)
        logger.info("Usage: %s", resp.usage)

        cost = calculate_cost(resp.usage)
        logger.info("Estimated cost: $%.6f", cost)

        quick = quick_chat("What is 2+2?")
        logger.info("Quick: %s", quick.content)

        _tracker.report()

    except Exception:
        logger.exception("Smoke test failed")
        raise
