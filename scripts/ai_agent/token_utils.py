# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Token Utilities
===============
Utility functions for token estimation, formatting, and cost calculation.

These functions are shared across all AI backend implementations to provide
consistent token handling and usage tracking.

Functions:
- estimate_tokens(text) - Estimate token count for text
- format_tokens(count) - Format token count with K suffix
- get_context_limit(model) - Get context window size for a model
- calculate_cost(...) - Calculate cost from token usage
"""

__all__ = [
    "estimate_tokens",
    "format_tokens",
    "get_context_limit",
    "calculate_cost",
]


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.

    Claude/GPT use approximately 4 characters per token on average.
    This is a rough estimate - actual tokenization varies by model.

    The estimate is conservative (3.5 chars/token) to account for
    mixed content (English ~4, German ~3.5, code varies).

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    # Conservative estimate: 3.5 chars per token for mixed content
    return int(len(text) / 3.5)


def format_tokens(tokens: int) -> str:
    """
    Format token count with K suffix for readability.

    Examples:
        500 -> "500"
        1500 -> "1.5K"
        15000 -> "15.0K"

    Args:
        tokens: Token count

    Returns:
        Formatted string like "15.2K" or "500"
    """
    if tokens >= 1000:
        return f"{tokens/1000:.1f}K"
    return str(tokens)


def get_context_limit(model: str) -> int:
    """
    Get context token limit for a model.

    Known context limits:
    - Gemini models: 1,000,000 tokens
    - Claude models: 200,000 tokens
    - Ollama/local (qwen, mistral, llama): 32,000 tokens
    - Default: 128,000 tokens

    Args:
        model: Model name/identifier (e.g., "gemini-2.5-pro", "claude-sonnet")

    Returns:
        Context limit in tokens
    """
    model_lower = model.lower() if model else ""

    # Gemini models - 1M context
    if "gemini" in model_lower:
        return 1_000_000

    # Claude models - 200K context
    if "claude" in model_lower:
        if "opus" in model_lower:
            return 200_000
        return 200_000  # Sonnet, Haiku

    # Ollama/local models (varies, default conservative)
    if any(x in model_lower for x in ["qwen", "mistral", "llama"]):
        return 32_000

    # Default for unknown models
    return 128_000


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    pricing: dict,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0
) -> float:
    """
    Calculate cost from tokens and pricing config, including cache tokens.

    Pricing is specified per 1 million tokens. Cache pricing follows
    Anthropic's model: cache reads are 90% cheaper, cache writes are 25% more.

    Args:
        input_tokens: Number of input tokens (not cached)
        output_tokens: Number of output tokens
        pricing: Dict with prices per 1M tokens:
            - "input": normal input price (e.g., $3)
            - "output": output price (e.g., $15)
            - "cache_read": cache read price (default: input * 0.1)
            - "cache_write": cache creation price (default: input * 1.25)
        cache_read_tokens: Number of tokens read from cache
        cache_creation_tokens: Number of tokens written to cache

    Returns:
        Cost in USD

    Example:
        >>> pricing = {"input": 3.0, "output": 15.0}
        >>> calculate_cost(10000, 2000, pricing)
        0.06  # (10000/1M * 3) + (2000/1M * 15)
    """
    if not pricing:
        return 0.0

    input_price = pricing.get("input", 0)  # $ per 1M tokens
    output_price = pricing.get("output", 0)  # $ per 1M tokens

    # Cache pricing defaults based on Anthropic's multipliers
    cache_read_price = pricing.get("cache_read", input_price * 0.1)  # 90% discount
    cache_write_price = pricing.get("cache_write", input_price * 1.25)  # 25% premium

    input_cost = (input_tokens / 1_000_000) * input_price if input_tokens else 0
    output_cost = (output_tokens / 1_000_000) * output_price if output_tokens else 0
    cache_read_cost = (cache_read_tokens / 1_000_000) * cache_read_price if cache_read_tokens else 0
    cache_write_cost = (cache_creation_tokens / 1_000_000) * cache_write_price if cache_creation_tokens else 0

    return input_cost + output_cost + cache_read_cost + cache_write_cost
