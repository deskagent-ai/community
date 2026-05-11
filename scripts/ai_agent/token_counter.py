# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Token Counter - Accurate token counting for knowledge management.
================================================================

Provides accurate token counting using tiktoken (if available) with
fallback to estimation. Used by KnowledgeManager for Auto-RAG decisions.

Usage:
    from ai_agent.token_counter import TokenCounter

    counter = TokenCounter()
    tokens = counter.count("Hello, world!")
    tokens = counter.count_file("path/to/file.md")
"""

from pathlib import Path
from typing import Union, Optional
import hashlib

# Import centralized token estimation
from .token_utils import estimate_tokens as _estimate_tokens_central

# Try to import tiktoken for accurate counting
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


class TokenCounter:
    """
    Token counter with caching support.

    Uses tiktoken for accurate counting if available,
    falls back to character-based estimation otherwise.

    The cl100k_base encoding is used (GPT-4, Claude approximation).
    """

    # Cache for file token counts {file_hash: token_count}
    _file_cache: dict = {}

    def __init__(self, encoding_name: str = "cl100k_base"):
        """
        Initialize token counter.

        Args:
            encoding_name: tiktoken encoding name (default: cl100k_base for GPT-4/Claude)
        """
        self.encoding_name = encoding_name
        self._encoder = None
        self.using_tiktoken = TIKTOKEN_AVAILABLE

        if TIKTOKEN_AVAILABLE:
            try:
                self._encoder = tiktoken.get_encoding(encoding_name)
            except Exception:
                self.using_tiktoken = False

    def count(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Token count (exact if tiktoken available, estimated otherwise)
        """
        if not text:
            return 0

        if self._encoder:
            return len(self._encoder.encode(text))
        else:
            # Fallback: ~3.5 chars per token (conservative for mixed content)
            return int(len(text) / 3.5)

    def count_file(self, path: Union[str, Path], use_cache: bool = True) -> int:
        """
        Count tokens in a file with optional caching.

        Args:
            path: Path to file
            use_cache: Whether to use/update cache (based on file hash)

        Returns:
            Token count for file contents
        """
        path = Path(path)
        if not path.exists():
            return 0

        # Read file content
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return 0

        if not use_cache:
            return self.count(content)

        # Check cache using content hash
        content_hash = hashlib.md5(content.encode()).hexdigest()
        cache_key = f"{path.name}:{content_hash}"

        if cache_key in self._file_cache:
            return self._file_cache[cache_key]

        # Count and cache
        tokens = self.count(content)
        self._file_cache[cache_key] = tokens

        return tokens

    def count_files(self, paths: list, use_cache: bool = True) -> dict:
        """
        Count tokens for multiple files.

        Args:
            paths: List of file paths
            use_cache: Whether to use caching

        Returns:
            Dict with {filename: tokens, "_total": total_tokens, "_details": [...]}
        """
        result = {"_total": 0, "_details": []}

        for path in paths:
            path = Path(path)
            tokens = self.count_file(path, use_cache)
            result[path.name] = tokens
            result["_total"] += tokens
            result["_details"].append({
                "file": path.name,
                "path": str(path),
                "tokens": tokens,
                "chars": len(path.read_text(encoding="utf-8")) if path.exists() else 0
            })

        return result

    def clear_cache(self):
        """Clear the file token cache."""
        self._file_cache.clear()

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "cached_files": len(self._file_cache),
            "using_tiktoken": self.using_tiktoken,
            "encoding": self.encoding_name if self.using_tiktoken else "estimation"
        }


# Module-level convenience functions

_default_counter: Optional[TokenCounter] = None


def get_counter() -> TokenCounter:
    """Get or create the default TokenCounter instance."""
    global _default_counter
    if _default_counter is None:
        _default_counter = TokenCounter()
    return _default_counter


def count_tokens(text: str) -> int:
    """
    Count tokens in text (module-level convenience function).

    Args:
        text: Text to count

    Returns:
        Token count
    """
    return get_counter().count(text)


def count_file_tokens(path: Union[str, Path]) -> int:
    """
    Count tokens in a file (module-level convenience function).

    Args:
        path: Path to file

    Returns:
        Token count
    """
    return get_counter().count_file(path)


def estimate_tokens_fast(text: str) -> int:
    """
    Fast token estimation without tiktoken (always uses ~3.5 chars/token).

    Use this when you need speed over accuracy, e.g., for quick checks.

    Note: Delegates to token_utils.estimate_tokens() which uses the same algorithm.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    return _estimate_tokens_central(text)
