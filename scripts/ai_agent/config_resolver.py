# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Config Resolver - Placeholder resolution for agent content
==========================================================
Resolves all placeholder types in agent/skill content:
- Date: {{TODAY}}, {{DATE}}, {{YEAR}}, {{DATE_ISO}}
- Paths: {{LOGS_DIR}}, {{TEMP_DIR}}, {{EXPORTS_DIR}}, etc.
- Config: {{CONFIG.file.path[|fallback]}}

This module is imported by base.py and re-exported for backwards compatibility.
"""

import json
import re
from datetime import datetime


# =============================================================================
# CONFIG Placeholder System
# =============================================================================
# Keys that should never be exposed (security)
CONFIG_REDACTED_PATTERNS = [
    "api_key", "password", "secret", "token",
    "client_secret", "client_id", "private_key"
]


def _is_secret_path(path: str) -> bool:
    """Check if path points to a secret value.

    Args:
        path: Dot-notation path like "apis.gmail.client_secret"

    Returns:
        True if path contains sensitive key patterns
    """
    path_lower = path.lower()
    return any(p in path_lower for p in CONFIG_REDACTED_PATTERNS)


def _resolve_path_in_dict(data: dict, path: str):
    """Resolve dot-notation path in nested dict.

    Args:
        data: Nested dictionary
        path: Dot-separated path like "gmail_support.labels.done"

    Returns:
        Value at path or None if not found
    """
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _load_config_file(file_name: str) -> dict:
    """Load a specific config file by name (without .json extension).

    This is a helper that loads a single config file from the config system.
    Uses lazy import to avoid circular dependencies.

    Args:
        file_name: Config file name without extension (e.g., "apis", "system")

    Returns:
        Config dict or empty dict if not found
    """
    try:
        # Lazy import to avoid circular dependency
        from config import _load_single_config
        filename = f"{file_name}.json"
        return _load_single_config(filename)
    except ImportError:
        # Fallback: try to load directly
        try:
            from paths import get_config_dir, DESKAGENT_DIR
            config_dir = get_config_dir()
            filename = f"{file_name}.json"

            # Try user config first
            user_path = config_dir / filename
            if user_path.exists():
                return json.loads(user_path.read_text(encoding="utf-8"))

            # Fallback to default config
            default_path = DESKAGENT_DIR / "config" / filename
            if default_path.exists():
                return json.loads(default_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def resolve_config_placeholders(content: str) -> str:
    """Replace {{CONFIG.file.path[|fallback]}} with values from config files.

    Syntax: {{CONFIG.<file>.<path>[|<fallback>]}}

    Examples:
        {{CONFIG.triggers.gmail_support.labels.done}} -> "IsDone"
        {{CONFIG.apis.userecho.subdomain}} -> "meine-firma"
        {{CONFIG.system.ui.accent_color|#2196f3}} -> value or fallback

    Security: Paths containing secret patterns return "[REDACTED]"

    Args:
        content: String with optional CONFIG placeholders

    Returns:
        Content with CONFIG placeholders resolved
    """
    # Pattern: {{CONFIG.file.path}} or {{CONFIG.file.path|fallback}}
    pattern = r'\{\{CONFIG\.(\w+)\.([^|}]+)(?:\|([^}]*))?\}\}'

    def replace_match(match):
        file_name = match.group(1)   # "triggers", "apis", "system", etc.
        path = match.group(2)        # "gmail_support.labels.done"
        fallback = match.group(3)    # Optional fallback value

        # Security check - never expose secrets
        if _is_secret_path(path):
            return "[REDACTED]"

        # Load config file
        try:
            config = _load_config_file(file_name)
            if not config:
                return fallback if fallback is not None else match.group(0)
        except Exception:
            return fallback if fallback is not None else match.group(0)

        # Resolve path in config
        value = _resolve_path_in_dict(config, path)
        if value is None:
            return fallback if fallback is not None else match.group(0)

        # Convert to string
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return re.sub(pattern, replace_match, content)


def resolve_all_placeholders(content: str) -> str:
    """
    Resolve ALL placeholders in content (date + path + config).

    Central function for placeholder replacement, used by:
    - load_agent() in agents.py (single source of truth for agent loading)

    Supported placeholders:
    - Date: {{TODAY}}, {{DATE}}, {{YEAR}}, {{DATE_ISO}}
    - System: {{USERNAME}} (current OS username)
    - Paths: {{KNOWLEDGE_DIR}}, {{CUSTOM_KNOWLEDGE_DIR}}, {{TEMP_DIR}}, {{LOGS_DIR}},
             {{EXPORTS_DIR}}, {{WORKSPACE_DIR}}, {{PROJECT_DIR}}, {{DESKAGENT_DIR}},
             {{CONFIG_DIR}}, {{AGENTS_DIR}}
    - Config: {{CONFIG.file.path}} or {{CONFIG.file.path|fallback}}

    Args:
        content: String with optional placeholders

    Returns:
        Content with all placeholders resolved
    """
    # 1. Date placeholders
    now = datetime.now()
    content = content.replace("{{TODAY}}", now.strftime("%d.%m.%Y"))
    content = content.replace("{{DATE}}", now.strftime("%d.%m.%Y"))
    content = content.replace("{{YEAR}}", str(now.year))
    content = content.replace("{{DATE_ISO}}", now.strftime("%Y-%m-%d"))

    # 1.5. System placeholders
    import getpass
    content = content.replace("{{USERNAME}}", getpass.getuser())

    # 2. Path placeholders
    try:
        from paths import (
            get_agents_dir, get_knowledge_dir, get_temp_dir,
            get_logs_dir, get_exports_dir, get_config_dir,
            DESKAGENT_DIR, PROJECT_DIR, WORKSPACE_DIR
        )

        path_replacements = {
            "{{AGENTS_DIR}}": str(get_agents_dir()),
            "{{KNOWLEDGE_DIR}}": str(get_knowledge_dir()),
            "{{CUSTOM_KNOWLEDGE_DIR}}": str(PROJECT_DIR / "knowledge"),  # Always user folder, no fallback
            "{{TEMP_DIR}}": str(get_temp_dir()),
            "{{LOGS_DIR}}": str(get_logs_dir()),
            "{{EXPORTS_DIR}}": str(get_exports_dir()),
            "{{CONFIG_DIR}}": str(get_config_dir()),
            "{{WORKSPACE_DIR}}": str(WORKSPACE_DIR),
            "{{DESKAGENT_DIR}}": str(DESKAGENT_DIR),
            "{{PROJECT_DIR}}": str(PROJECT_DIR),
        }

        for placeholder, value in path_replacements.items():
            # Convert backslashes to forward slashes for cross-platform paths
            content = content.replace(placeholder, value.replace("\\", "/"))

    except ImportError:
        pass

    # 3. Config placeholders ({{CONFIG.file.path}})
    content = resolve_config_placeholders(content)

    return content


# Alias for backwards compatibility (used by _build_security_restrictions in base.py)
_resolve_path_placeholders = resolve_all_placeholders


# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "resolve_all_placeholders",
    "resolve_config_placeholders",
    "_resolve_path_placeholders",  # Backwards compatibility alias
    "CONFIG_REDACTED_PATTERNS",
]
