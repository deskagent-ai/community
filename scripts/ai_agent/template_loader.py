# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Template Loader
===============
Loads system templates from deskagent/templates/ for AI agent prompts.

Templates are system-level definitions like:
- dialogs.md: QUESTION_NEEDED/CONFIRMATION_NEEDED format

These are always loaded (not user-overridable) and embedded
in the system prompt for all agents.
"""

from pathlib import Path
from typing import Optional

# Path is set up by ai_agent/__init__.py
from paths import get_templates_dir

__all__ = [
    "load_templates",
    "get_last_template_stats",
    "set_template_stats_skipped",
]

# Last template stats (for logging)
_last_template_stats: Optional[dict] = None


def load_templates() -> str:
    """
    Load system templates from deskagent/templates/.

    Templates are system-level definitions like:
    - dialogs.md: QUESTION_NEEDED/CONFIRMATION_NEEDED format

    These are always loaded (not user-overridable) and embedded
    in the system prompt for all agents.

    Returns:
        Concatenated template content.
    """
    global _last_template_stats

    # Lazy import to avoid circular dependency
    from .logging import log
    from .token_utils import estimate_tokens

    templates = ""
    templates_dir = get_templates_dir()
    stats = {
        "files": [],
        "total_tokens": 0,
        "total_chars": 0,
        "skipped": False
    }

    if not templates_dir.exists():
        log(f"[TemplateLoader] Templates dir not found: {templates_dir}")
        _last_template_stats = stats
        return templates

    for f in sorted(templates_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
            templates += f"\n\n{content}"
            tokens = estimate_tokens(content)
            stats["files"].append({
                "name": f.stem,
                "tokens": tokens,
                "chars": len(content)
            })
            stats["total_tokens"] += tokens
            stats["total_chars"] += len(content)
            log(f"[TemplateLoader] Loaded: {f.stem} ({tokens} tokens, {len(content)} chars)")
        except Exception as e:
            log(f"[TemplateLoader] Failed to load {f.name}: {e}")

    _last_template_stats = stats
    return templates


def get_last_template_stats() -> Optional[dict]:
    """
    Get stats from the most recent template load.

    Returns:
        Dict with template stats or None if no load happened yet.
        Contains:
        - files: List of {name, tokens, chars} for each loaded file
        - total_tokens: Total token count
        - total_chars: Total character count
        - skipped: True if templates were skipped (e.g., skip_dialogs)
    """
    return _last_template_stats


def set_template_stats_skipped():
    """
    Mark templates as skipped (for skip_dialogs agents).

    Called when an agent has skip_dialogs=True and templates
    are intentionally not loaded.
    """
    global _last_template_stats
    _last_template_stats = {
        "files": [],
        "total_tokens": 0,
        "total_chars": 0,
        "skipped": True
    }
