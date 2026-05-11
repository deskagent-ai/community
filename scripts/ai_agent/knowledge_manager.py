# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Knowledge Manager - Smart knowledge loading with Auto-RAG support.
==================================================================

Central component for knowledge management in DeskAgent.
Measures token size, caches content, and provides stats for monitoring.

Phase 1+2: Token monitoring and caching (no RAG yet)
Phase 3 (future): Auto-RAG when knowledge exceeds threshold

Usage:
    from ai_agent.knowledge_manager import KnowledgeManager, get_knowledge_manager

    # Get singleton instance
    km = get_knowledge_manager()

    # Load knowledge for an agent
    content, stats = km.load_for_agent(
        pattern="deskagent",
        agent_name="support_reply"
    )

    # Get stats
    print(km.get_stats())
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, List, Dict

# Handle imports for both package and standalone execution
try:
    from .token_counter import TokenCounter, count_tokens
except ImportError:
    from token_counter import TokenCounter, count_tokens

# =============================================================================
# Path constants from paths.py (canonical source)
# =============================================================================
# Path is set up by ai_agent/__init__.py
from paths import PROJECT_DIR as _PROJECT_DIR, DESKAGENT_DIR as _DESKAGENT_DIR


def _log(msg: str):
    """Log to system.log (lazy import to avoid circular dependency)."""
    try:
        from .logging import system_log
        system_log(msg)
    except ImportError:
        print(msg)


@dataclass
class KnowledgeStats:
    """Statistics about loaded knowledge."""
    files_count: int = 0
    total_tokens: int = 0
    total_chars: int = 0
    threshold_tokens: int = 30000
    exceeds_threshold: bool = False
    mode: str = "full"  # "full" or "rag" (future)
    load_time_ms: float = 0
    cache_hit: bool = False
    files: List[Dict] = field(default_factory=list)  # [{name, tokens, chars}]

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/JSON."""
        return {
            "files_count": self.files_count,
            "total_tokens": self.total_tokens,
            "total_chars": self.total_chars,
            "threshold_tokens": self.threshold_tokens,
            "exceeds_threshold": self.exceeds_threshold,
            "mode": self.mode,
            "load_time_ms": round(self.load_time_ms, 2),
            "cache_hit": self.cache_hit,
            "files": self.files
        }

    def summary(self) -> str:
        """Human-readable summary."""
        status = "OVER THRESHOLD" if self.exceeds_threshold else "OK"
        return (
            f"{self.files_count} files, {self.total_tokens:,} tokens "
            f"({self.total_tokens * 100 // self.threshold_tokens}% of {self.threshold_tokens:,} threshold) "
            f"[{status}] - {self.load_time_ms:.1f}ms"
        )

    def log_line(self) -> str:
        """Single line for system.log."""
        cache_str = "cache-hit" if self.cache_hit else "loaded"
        warn_str = " [EXCEEDS THRESHOLD]" if self.exceeds_threshold else ""
        return (
            f"Knowledge: {self.files_count} files, {self.total_tokens:,} tokens "
            f"({self.mode}, {cache_str}){warn_str}"
        )


class KnowledgeManager:
    """
    Manages knowledge loading with caching and monitoring.

    Features:
    - Token counting for all knowledge files
    - In-memory caching with TTL
    - Threshold monitoring (warns when knowledge is too large)
    - Stats collection for logging/debugging
    - Prepared for future RAG integration

    Configuration (from system.json):
        "knowledge": {
            "threshold_tokens": 30000,   # Warn/switch to RAG above this
            "cache_ttl_seconds": 300,    # Cache TTL (5 minutes)
            "auto_rag": false            # Future: auto-switch to RAG
        }
    """

    DEFAULT_THRESHOLD = 30000  # Tokens
    DEFAULT_CACHE_TTL = 300    # Seconds (5 minutes)

    def __init__(
        self,
        knowledge_dir: Path = None,
        config: dict = None
    ):
        """
        Initialize KnowledgeManager.

        Args:
            knowledge_dir: Path to knowledge directory (auto-detected if None)
            config: Optional config dict with "knowledge" settings
        """
        # Resolve knowledge directory
        if knowledge_dir is None:
            try:
                from paths import get_knowledge_dir
                knowledge_dir = get_knowledge_dir()
            except ImportError:
                # Fallback: derive from module constants
                knowledge_dir = _PROJECT_DIR / "knowledge"

        self.knowledge_dir = Path(knowledge_dir)
        self.config = config or {}

        # Settings from config
        knowledge_config = self.config.get("knowledge", {})
        self.threshold = knowledge_config.get("threshold_tokens", self.DEFAULT_THRESHOLD)
        self.cache_ttl = knowledge_config.get("cache_ttl_seconds", self.DEFAULT_CACHE_TTL)
        self.auto_rag = knowledge_config.get("auto_rag", False)

        # Token counter
        self.token_counter = TokenCounter()

        # Cache: {pattern_hash: (content, stats, timestamp)}
        self._cache: Dict[str, Tuple[str, KnowledgeStats, float]] = {}

        # Stats for last load (for quick access)
        self._last_stats: Optional[KnowledgeStats] = None

    def load_for_agent(
        self,
        pattern: str = None,
        agent_name: str = "",
        force_reload: bool = False
    ) -> Tuple[str, KnowledgeStats]:
        """
        Load knowledge for an agent with stats.

        Args:
            pattern: Knowledge pattern (regex, @path, or None for all)
            agent_name: Name of agent (for logging)
            force_reload: Bypass cache

        Returns:
            Tuple of (content, KnowledgeStats)
        """
        start_time = time.time()

        # Check cache first
        cache_key = self._get_cache_key(pattern)
        if not force_reload and cache_key in self._cache:
            content, stats, timestamp = self._cache[cache_key]
            age = time.time() - timestamp

            if age < self.cache_ttl:
                # Cache hit - update stats
                stats.cache_hit = True
                stats.load_time_ms = (time.time() - start_time) * 1000
                self._last_stats = stats
                return content, stats

        # Cache miss - load fresh
        content, stats = self._load_knowledge(pattern)

        # Update timing
        stats.load_time_ms = (time.time() - start_time) * 1000
        stats.cache_hit = False

        # Store in cache
        self._cache[cache_key] = (content, stats, time.time())
        self._last_stats = stats

        return content, stats

    def _load_knowledge(self, pattern: str = None) -> Tuple[str, KnowledgeStats]:
        """
        Internal: Load knowledge files and compute stats.

        Args:
            pattern: Knowledge pattern

        Returns:
            Tuple of (content, stats)
        """
        stats = KnowledgeStats(threshold_tokens=self.threshold)

        # Explicit empty pattern = load nothing
        if pattern == "":
            stats.mode = "disabled"
            return "", stats

        # Parse pattern into regex parts and path references
        regex_parts = []
        path_refs = []

        if pattern:
            for part in pattern.split("|"):
                part = part.strip()
                if part.startswith("@"):
                    path_refs.append(part[1:])  # Remove @ prefix
                else:
                    regex_parts.append(part)

        # Collect all files to load
        files_to_load: List[Path] = []

        # 1. Files from path references
        for path_ref in path_refs:
            ref_path = self._resolve_path_ref(path_ref)
            if ref_path and ref_path.exists():
                if ref_path.is_file():
                    files_to_load.append(ref_path)
                elif ref_path.is_dir():
                    files_to_load.extend(sorted(ref_path.glob("**/*.md")))

        # 2. Files from knowledge/ folder with regex filtering
        if self.knowledge_dir.exists():
            # Compile regex
            regex = None
            if regex_parts:
                try:
                    regex = re.compile("|".join(regex_parts), re.IGNORECASE)
                except re.error:
                    pass

            for f in sorted(self.knowledge_dir.glob("**/*.md")):
                rel_path = f.relative_to(self.knowledge_dir)
                match_string = str(rel_path.with_suffix("")).replace("\\", "/")

                # Filter by pattern
                if regex and not regex.search(match_string):
                    continue
                # Skip if only path refs specified
                if pattern and not regex_parts and path_refs:
                    continue

                files_to_load.append(f)

        # Load and measure all files
        contents = []
        for file_path in files_to_load:
            try:
                content = file_path.read_text(encoding="utf-8")
                tokens = self.token_counter.count(content)

                # Get display name
                if self.knowledge_dir.exists() and file_path.is_relative_to(self.knowledge_dir):
                    display_name = str(file_path.relative_to(self.knowledge_dir))
                else:
                    display_name = file_path.name

                stats.files.append({
                    "name": display_name,
                    "path": str(file_path),
                    "tokens": tokens,
                    "chars": len(content)
                })

                stats.files_count += 1
                stats.total_tokens += tokens
                stats.total_chars += len(content)

                # Add to content with header
                contents.append(f"\n\n### {display_name}:\n{content}")

            except Exception:
                continue

        # Check threshold
        stats.exceeds_threshold = stats.total_tokens > self.threshold

        # Determine mode
        if stats.exceeds_threshold and self.auto_rag:
            stats.mode = "rag"  # Future: trigger RAG here
        else:
            stats.mode = "full"

        return "".join(contents), stats

    def _resolve_path_ref(self, path_ref: str) -> Optional[Path]:
        """
        Resolve a @path reference to an actual path.

        Supports:
        - Regular paths: @deskagent/knowledge/docs.md
        - Plugin paths: pluginname:docs (loads from plugins/pluginname/knowledge/docs)

        Uses module-level constants _PROJECT_DIR and _DESKAGENT_DIR
        which are derived from __file__ at module load time.
        """
        # Check for plugin reference: "pluginname:path" (without @ prefix)
        # This is handled in _load_knowledge pattern parsing, not here
        # But we support it here too for explicit @plugin:path syntax
        if ":" in path_ref and not path_ref.startswith("/") and not path_ref[1] == ":":
            # Looks like plugin:path (not C:\windows path)
            plugin_name, rel_path = path_ref.split(":", 1)
            try:
                from assistant.services.plugins import get_plugins_dir
                plugin_knowledge = get_plugins_dir() / plugin_name / "knowledge"
                if rel_path:
                    plugin_path = plugin_knowledge / rel_path
                else:
                    plugin_path = plugin_knowledge
                if plugin_path.exists():
                    _log(f"[KnowledgeManager] Plugin path resolved: {path_ref} -> {plugin_path}")
                    return plugin_path
            except ImportError:
                pass  # Plugin system not available

        candidates = [
            _PROJECT_DIR / path_ref,           # <project>/deskagent/knowledge
            _DESKAGENT_DIR / path_ref,         # <project>/deskagent/deskagent/knowledge (unlikely)
            Path(path_ref)                      # Absolute path or relative to CWD
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        _log(f"[KnowledgeManager] Path not found: '{path_ref}' (tried: {_PROJECT_DIR}, {_DESKAGENT_DIR})")
        return None

    def _get_cache_key(self, pattern: str) -> str:
        """Generate cache key from pattern."""
        return hashlib.md5(str(pattern).encode()).hexdigest()

    def invalidate_cache(self, pattern: str = None):
        """
        Invalidate cache entries.

        Args:
            pattern: Specific pattern to invalidate, or None for all
        """
        if pattern is None:
            self._cache.clear()
        else:
            cache_key = self._get_cache_key(pattern)
            self._cache.pop(cache_key, None)

        # Also clear token counter cache
        self.token_counter.clear_cache()

    def get_stats(self) -> dict:
        """
        Get overall manager statistics.

        Returns:
            Dict with cache stats, settings, and last load info
        """
        return {
            "settings": {
                "threshold_tokens": self.threshold,
                "cache_ttl_seconds": self.cache_ttl,
                "auto_rag": self.auto_rag,
                "knowledge_dir": str(self.knowledge_dir)
            },
            "cache": {
                "entries": len(self._cache),
                "token_counter": self.token_counter.get_cache_stats()
            },
            "last_load": self._last_stats.to_dict() if self._last_stats else None
        }

    def get_last_stats(self) -> Optional[KnowledgeStats]:
        """Get stats from the most recent load operation."""
        return self._last_stats

    def measure_pattern(self, pattern: str = None) -> KnowledgeStats:
        """
        Measure a pattern without caching (for analysis).

        Args:
            pattern: Knowledge pattern to measure

        Returns:
            KnowledgeStats with measurements
        """
        _, stats = self._load_knowledge(pattern)
        return stats


# =============================================================================
# Singleton / Global Instance
# =============================================================================

_knowledge_manager: Optional[KnowledgeManager] = None


def get_knowledge_manager(config: dict = None, reset: bool = False) -> KnowledgeManager:
    """
    Get or create the global KnowledgeManager instance.

    Args:
        config: Optional config dict (used only on first call or reset)
        reset: Force create new instance

    Returns:
        KnowledgeManager singleton
    """
    global _knowledge_manager

    if _knowledge_manager is None or reset:
        _knowledge_manager = KnowledgeManager(config=config)

    return _knowledge_manager


def load_knowledge_with_stats(
    pattern: str = None,
    agent_name: str = ""
) -> Tuple[str, KnowledgeStats]:
    """
    Convenience function: Load knowledge and get stats.

    Args:
        pattern: Knowledge pattern
        agent_name: Agent name for logging

    Returns:
        Tuple of (content, stats)
    """
    km = get_knowledge_manager()
    return km.load_for_agent(pattern, agent_name)


def get_last_knowledge_stats() -> Optional[KnowledgeStats]:
    """Get stats from the most recent knowledge load."""
    km = get_knowledge_manager()
    return km.get_last_stats()
