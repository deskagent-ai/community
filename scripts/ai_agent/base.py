# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Agent Base - Shared utilities
================================
Common classes and functions for all AI agent implementations.

This module serves as the main entry point for shared utilities.
All functions are re-exported from dedicated modules for backwards compatibility.
"""

__all__ = [
    # Logging (from .logging)
    "log",
    "set_logger",
    "set_console_logging",
    "start_log_buffer",
    "stop_log_buffer",
    "init_system_log",
    "system_log",
    "anon_message_log",
    "log_tool_call",
    # Token utilities (from .token_utils)
    "estimate_tokens",
    "format_tokens",
    "get_context_limit",
    "calculate_cost",
    # Metrics (from .metrics)
    "AgentMetrics",
    # Agent logging (from .agent_logging)
    "AgentResponse",
    "write_prompt_log",
    "write_agent_log",
    "log_task_summary",
    # Event publishing (from .event_publishing)
    "set_current_task_id",
    "get_current_task_id",
    "publish_tool_event",
    "publish_context_event",
    # MCP discovery (from .mcp_discovery)
    "WINDOWS_ONLY_MCP",
    "discover_mcp_servers",
    # Knowledge loading (from .knowledge_loader)
    "load_knowledge",
    "invalidate_knowledge_cache",
    "get_last_knowledge_stats",
    # Template loading (from .template_loader)
    "load_templates",
    "get_last_template_stats",
    "set_template_stats_skipped",
    # Response parsing (from .response_parser)
    "clean_tool_markers",
    "extract_json",
    # Prompt building (from .prompt_builder)
    "DEFAULT_SYSTEM_PROMPT",
    "build_system_prompt",
    "build_system_prompt_parts",
    # Config resolution (from .config_resolver)
    "resolve_all_placeholders",
    "resolve_config_placeholders",
    "_resolve_path_placeholders",
    "CONFIG_REDACTED_PATTERNS",
    # Dev context (from .dev_context)
    "reset_dev_context",
    "set_dev_anonymization",
    "capture_dev_context",
    "add_dev_tool_result",
    "update_dev_iteration",
    "get_dev_context",
    # Backend config (from .backend_config)
    "get_agent_config",
    "is_backend_available",
    "get_default_backend",
    # Cache management
    "clear_all_caches",
]

# Import logging functions from dedicated module (avoids circular imports)
# These are re-exported for backwards compatibility
from .logging import (
    log,
    set_logger,
    set_console_logging,
    start_log_buffer,
    stop_log_buffer,
    init_system_log,
    system_log,
    anon_message_log,
    log_tool_call
)

# Import token utilities from dedicated module
# Re-exported for backwards compatibility
from .token_utils import (
    estimate_tokens,
    format_tokens,
    get_context_limit,
    calculate_cost,
)

# Import AgentMetrics from dedicated module
# Re-exported for backwards compatibility
from .metrics import AgentMetrics

# Import agent logging utilities from dedicated module
# Re-exported for backwards compatibility
from .agent_logging import (
    AgentResponse,
    write_prompt_log,
    write_agent_log,
    log_task_summary,
)

# Event publishing functions - moved to event_publishing.py
# Re-exported for backwards compatibility
from .event_publishing import (
    set_current_task_id,
    get_current_task_id,
    publish_tool_event,
    publish_context_event,
)


# === MCP SERVER DISCOVERY ===
# Moved to mcp_discovery.py - re-export for backwards compatibility
from .mcp_discovery import WINDOWS_ONLY_MCP, discover_mcp_servers

# Knowledge loading - moved to knowledge_loader.py
# Re-export for backwards compatibility
from .knowledge_loader import (
    load_knowledge,
    invalidate_knowledge_cache,
    get_last_knowledge_stats
)

# Last template stats - now managed by template_loader module
# Re-exported for backwards compatibility
from .template_loader import load_templates, get_last_template_stats, set_template_stats_skipped


# === TEXT CLEANING ===
# Generic utilities for cleaning AI responses - moved to response_parser.py
# Re-exported for backwards compatibility
from .response_parser import clean_tool_markers, extract_json


# Prompt builder functions - moved to prompt_builder.py
# Re-export for backwards compatibility
from .prompt_builder import (
    DEFAULT_SYSTEM_PROMPT,
    build_system_prompt,
    build_system_prompt_parts,
)


# =============================================================================
# CONFIG Placeholder System - moved to config_resolver.py
# =============================================================================
# Re-export for backwards compatibility
from .config_resolver import (
    resolve_all_placeholders,
    resolve_config_placeholders,
    _resolve_path_placeholders,
    CONFIG_REDACTED_PATTERNS,
)


# === DEVELOPER CONTEXT CAPTURE ===
# Re-exported from dev_context module for backwards compatibility
from .dev_context import (
    reset_dev_context,
    set_dev_anonymization,
    capture_dev_context,
    add_dev_tool_result,
    update_dev_iteration,
    get_dev_context,
    set_log_func as _set_dev_log_func
)

# Wire up logging to dev_context module
# log() is already available from .logging import above
_set_dev_log_func(log)


# Backend configuration functions - moved to backend_config.py
# Re-exported for backwards compatibility
from .backend_config import (
    get_agent_config,
    is_backend_available,
    get_default_backend,
)


# === CACHE MANAGEMENT ===

def clear_all_caches():
    """
    Clear all module-level caches for fresh state on startup.

    This ensures that when DeskAgent restarts, all caches are cleared
    and fresh data is loaded. Call this once during application startup.
    """
    # 1. Knowledge cache (5-minute TTL)
    invalidate_knowledge_cache()

    # 2. Anonymizer config cache
    try:
        from . import anonymizer
        anonymizer._anonymizer_config_cache = None
        log("[Cache] Anonymizer config cache cleared")
    except Exception:
        pass

    # 3. Demo mode mock cache
    try:
        from .demo_mode import clear_cache as clear_demo_cache
        clear_demo_cache()
        log("[Cache] Demo mode cache cleared")
    except Exception:
        pass

    # 4. Tool bridge cache (for allowed tools filtering)
    try:
        from .tool_bridge import clear_cache as clear_tool_cache
        clear_tool_cache()
        log("[Cache] Tool bridge cache cleared")
    except Exception:
        pass

    log("[Cache] All ai_agent caches cleared")
