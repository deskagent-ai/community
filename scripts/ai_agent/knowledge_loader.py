# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Knowledge Loader Module
=======================
Functions for loading knowledge files into AI agent context.

This module handles:
- Loading knowledge files from the knowledge/ directory
- Pattern-based filtering (regex, path references)
- Caching for performance optimization
- Statistics tracking for debugging

Public Functions:
- load_knowledge(pattern) - Load knowledge files based on pattern
- load_knowledge_cached(pattern, agent_name) - Cached version with stats
- invalidate_knowledge_cache() - Clear the cache
- get_last_knowledge_stats() - Get stats from last load
"""

import hashlib
import re
import time
from pathlib import Path
from typing import Optional

# Path is set up by ai_agent/__init__.py
from paths import PROJECT_DIR, get_knowledge_dir, DESKAGENT_DIR


# === GLOBAL STATE ===

# Knowledge cache for performance (5x faster agent starts)
# Format: {pattern_hash: (content, timestamp)}
_knowledge_cache: dict = {}
_knowledge_cache_ttl: int = 300  # 5 minutes

# Last knowledge stats (for logging and prompt_latest.txt)
_last_knowledge_stats: Optional[dict] = None


# === PUBLIC FUNCTIONS ===

__all__ = [
    "load_knowledge",
    "load_knowledge_cached",
    "invalidate_knowledge_cache",
    "get_last_knowledge_stats",
]


def load_knowledge(pattern: str = None) -> str:
    """
    Load knowledge files for context.

    Pattern syntax:
    - "company|products" - regex to match files in knowledge/ folder
    - "linkedin" - matches files in linkedin/ subfolder
    - "linkedin/style" - matches specific file in subfolder
    - "" (empty string) - load NOTHING (explicit disable)
    - "@path/to/file.md" - load specific file (relative to project root)
    - "@path/to/folder/" - load all .md files from folder
    - "company|@deskagent/systemknowledge/" - mixed (regex + path references)

    Args:
        pattern: Optional pattern string. Supports regex for knowledge/ files
                 and @path references for custom files/folders.
                 If None, all .md files from knowledge/ are loaded.
                 If empty string "", NO knowledge is loaded.

    Returns:
        Concatenated knowledge content.
    """
    from .logging import log

    # Explicit empty pattern = load nothing
    if pattern == "":
        log("[Knowledge] Knowledge disabled (empty pattern)")
        return ""

    knowledge = ""
    knowledge_dir = get_knowledge_dir()

    # Parse pattern into regex parts and path references
    regex_parts = []
    path_refs = []

    if pattern:
        for part in pattern.split("|"):
            part = part.strip()
            if part.startswith("@"):
                # Path reference (file or folder)
                path_refs.append(part[1:])  # Remove @ prefix
            else:
                regex_parts.append(part)

    # 1. Load from path references
    for path_ref in path_refs:
        # Resolve relative to project root (SHARED_DIR parent or DESKAGENT_DIR parent)
        ref_path = Path(PROJECT_DIR) / path_ref
        if not ref_path.exists():
            # Try relative to DESKAGENT_DIR parent
            ref_path = DESKAGENT_DIR.parent / path_ref
        if not ref_path.exists():
            # Try as absolute or relative to DESKAGENT_DIR itself
            ref_path = DESKAGENT_DIR / path_ref

        if ref_path.exists():
            if ref_path.is_file():
                # Single file
                try:
                    content = ref_path.read_text(encoding="utf-8")
                    knowledge += f"\n\n### {ref_path.stem}:\n{content}"
                    log(f"[Knowledge] Loaded (path): {ref_path.name} ({len(content)} chars)")
                except Exception as e:
                    log(f"[Knowledge] Failed to load {ref_path}: {e}")
            elif ref_path.is_dir():
                # Directory - load all .md files recursively
                for f in sorted(ref_path.glob("**/*.md")):
                    try:
                        content = f.read_text(encoding="utf-8")
                        # Use relative path as name for nested files
                        rel_path = f.relative_to(ref_path)
                        knowledge += f"\n\n### {rel_path}:\n{content}"
                        log(f"[Knowledge] Loaded (folder): {rel_path} ({len(content)} chars)")
                    except Exception as e:
                        log(f"[Knowledge] Failed to load {f.name}: {e}")
        else:
            log(f"[Knowledge] Path not found: {path_ref}")

    # 2. Load from knowledge/ folder with regex filtering
    if not knowledge_dir.exists():
        return knowledge

    # Compile regex from remaining parts
    regex = None
    if regex_parts:
        try:
            regex = re.compile("|".join(regex_parts), re.IGNORECASE)
        except re.error:
            log(f"[Knowledge] Invalid pattern: {regex_parts}")
            regex = None

    for f in sorted(knowledge_dir.glob("**/*.md")):
        # Get relative path for matching (supports subfolders like linkedin/style)
        rel_path = f.relative_to(knowledge_dir)
        match_string = str(rel_path.with_suffix("")).replace("\\", "/")

        # Filter by pattern if provided
        if regex and not regex.search(match_string):
            continue
        # If only path refs were specified (no regex parts), skip knowledge/ entirely
        if pattern and not regex_parts and path_refs:
            continue

        try:
            content = f.read_text(encoding="utf-8")
            knowledge += f"\n\n### {match_string}:\n{content}"
            log(f"[Knowledge] Loaded: {match_string} ({len(content)} chars)")
        except Exception as e:
            log(f"[Knowledge] Failed to load {f.name}: {e}")

    return knowledge


def load_knowledge_cached(pattern: str = None, agent_name: str = "") -> str:
    """
    Load knowledge with caching support and stats tracking.

    Uses KnowledgeManager for token counting and caching.
    Stats are stored globally and logged to system.log.

    Args:
        pattern: Knowledge pattern (same as load_knowledge)
        agent_name: Optional agent name for logging

    Returns:
        Cached or freshly loaded knowledge content.
    """
    global _last_knowledge_stats

    from .logging import log, system_log

    try:
        from .knowledge_manager import get_knowledge_manager
        km = get_knowledge_manager()
        content, stats = km.load_for_agent(pattern, agent_name)

        # Store stats globally for access by logging functions
        _last_knowledge_stats = stats.to_dict()

        # Log to system.log
        system_log(f"[Knowledge] {stats.log_line()}")

        # Detailed logging if exceeds threshold
        if stats.exceeds_threshold:
            system_log(f"[Knowledge] WARNING: {stats.total_tokens:,} tokens exceeds threshold {stats.threshold_tokens:,}!")
            system_log(f"[Knowledge] Consider using 'knowledge' filter in agent config or enabling auto_rag")

        # Log individual files if debug needed
        if stats.files:
            files_summary = ", ".join(f"{f['name']}({f['tokens']})" for f in stats.files[:5])
            if len(stats.files) > 5:
                files_summary += f" +{len(stats.files)-5} more"
            log(f"[Knowledge] Files: {files_summary}")

        return content

    except ImportError:
        # Fallback to original implementation if KnowledgeManager not available
        cache_key = hashlib.md5(str(pattern).encode()).hexdigest()

        # Check cache
        if cache_key in _knowledge_cache:
            content, timestamp = _knowledge_cache[cache_key]
            age = time.time() - timestamp
            if age < _knowledge_cache_ttl:
                log(f"[Knowledge] Cache HIT ({age:.0f}s old)")
                return content

        # Cache miss - load fresh
        log(f"[Knowledge] Cache MISS")
        content = load_knowledge(pattern)
        _knowledge_cache[cache_key] = (content, time.time())

        return content


def get_last_knowledge_stats() -> Optional[dict]:
    """
    Get stats from the most recent knowledge load.

    Returns:
        Dict with knowledge stats or None if no load happened yet.
        Contains: files_count, total_tokens, total_chars, threshold_tokens,
                  exceeds_threshold, mode, cache_hit, load_time_ms, files
    """
    return _last_knowledge_stats


def invalidate_knowledge_cache():
    """
    Clear knowledge cache.

    Call this after knowledge files have been modified to ensure
    fresh content is loaded on next access.
    """
    global _knowledge_cache

    from .logging import log

    _knowledge_cache.clear()
    log("[Knowledge] Cache invalidated")
