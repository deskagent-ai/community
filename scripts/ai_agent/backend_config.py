# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Backend Configuration
========================
Functions for getting and validating AI backend configurations.

Each backend module implements its own check_configured() function that knows
what the backend needs to be considered "available" (API keys, paths, etc.).

Functions:
- get_agent_config: Get configuration for a specific AI backend
- is_backend_available: Check if a backend is configured and usable
- get_default_backend: Get the default backend or first available fallback
"""

import os
import importlib


# =============================================================================
# Backend Type to Module Mapping
# =============================================================================
# Maps backend types to their implementation modules.
# Each module must implement: check_configured(config) -> (bool, str|None)

BACKEND_MODULES = {
    "claude_api": "ai_agent.claude_api",
    "claude_agent_sdk": "ai_agent.claude_agent_sdk",
    "claude_cli": "ai_agent.claude_cli",
    "gemini_adk": "ai_agent.gemini_adk",
    "openai_api": "ai_agent.openai_api",
    "qwen_agent": "ai_agent.qwen_agent",
    "ollama_native": "ai_agent.ollama_native",
}


def get_agent_config(config: dict, agent_name: str = None) -> dict:
    """
    Gets configuration for a specific AI backend.

    Args:
        config: Main configuration from config.json
        agent_name: Backend name (e.g. "claude", "qwen") or None for default

    Returns:
        Agent configuration as dict
    """
    agents = config.get("ai_backends", {})

    if agents:
        default_name = config.get("default_ai", "claude")
        name = agent_name or default_name
        return agents.get(name, agents.get(default_name, {}))
    else:
        return config.get("ai_agent", {})


def _get_backend_module(backend_type: str):
    """
    Dynamically load and return the backend module.

    Args:
        backend_type: Type of backend (e.g., "claude_agent_sdk")

    Returns:
        Module or None if not found/loadable
    """
    module_name = BACKEND_MODULES.get(backend_type)
    if not module_name:
        return None

    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        # Module not installed or import error
        return None


def is_backend_available(backend_name: str, config: dict) -> bool:
    """
    Check if an AI backend is configured and usable.

    Delegates to the backend's own check_configured() function, which knows
    what the specific backend needs (API keys, paths, SDK installation, etc.).

    Args:
        backend_name: Name of the backend to check
        config: Main configuration dict

    Returns:
        True if backend is available and usable
    """
    backends = config.get("ai_backends", {})
    backend_config = backends.get(backend_name)

    if not backend_config:
        return False

    # Explicitly disabled?
    if backend_config.get("enabled") is False:
        return False

    # Get backend type and load its module
    backend_type = backend_config.get("type", "")
    module = _get_backend_module(backend_type)

    if module and hasattr(module, "check_configured"):
        # Let the backend decide if it's configured
        is_configured, issue = module.check_configured(backend_config)
        return is_configured
    else:
        # Unknown backend type or no check_configured function
        # Assume available (allows new types without code changes)
        return True


def get_default_backend(config: dict) -> str:
    """
    Get the default backend or first available fallback.

    Priority:
    1. default_ai from config (if available)
    2. First available backend from ai_backends
    3. Hardcoded "claude" fallback (for error message)

    Args:
        config: Main configuration dict

    Returns:
        Name of available backend to use
    """
    # Lazy import to avoid circular dependency
    from .logging import log

    default = config.get("default_ai", "claude")

    # Is default available?
    if is_backend_available(default, config):
        return default

    # Find first available backend as fallback
    backends = config.get("ai_backends", {})
    for name in backends:
        if is_backend_available(name, config):
            log(f"[AI Agent] Default backend '{default}' not available, using fallback: {name}")
            return name

    # No backend available - return default for error message
    log(f"[AI Agent] WARNING: No available AI backend found!")
    return default


def get_backend_status(backend_name: str, config: dict) -> dict:
    """
    Get detailed status information for a backend.

    Args:
        backend_name: Name of the backend
        config: Main configuration dict

    Returns:
        Dict with status info: available, type, issue (if any)
    """
    backends = config.get("ai_backends", {})
    backend_config = backends.get(backend_name)

    if not backend_config:
        return {"available": False, "type": None, "issue": "Backend not configured"}

    if backend_config.get("enabled") is False:
        return {"available": False, "type": backend_config.get("type"), "issue": "Explicitly disabled"}

    backend_type = backend_config.get("type", "")
    module = _get_backend_module(backend_type)

    if module and hasattr(module, "check_configured"):
        is_configured, issue = module.check_configured(backend_config)
        return {
            "available": is_configured,
            "type": backend_type,
            "issue": issue
        }
    else:
        return {
            "available": True,
            "type": backend_type,
            "issue": None
        }


__all__ = [
    "get_agent_config",
    "is_backend_available",
    "get_default_backend",
    "get_backend_status",
    "BACKEND_MODULES",
]
