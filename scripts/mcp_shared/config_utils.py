# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Shared - Configuration Utilities
=====================================
Common configuration loading patterns used across all MCP servers.
"""

import sys
from pathlib import Path
from functools import lru_cache

# Add scripts to path for paths module (if not already)
_scripts_path = str(Path(__file__).parent.parent)
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)

from paths import load_config


def get_mcp_config(mcp_name: str) -> dict:
    """Load configuration for a specific MCP server from apis.json.

    Args:
        mcp_name: Name of the MCP server (e.g., "billomat", "outlook", "sepa")

    Returns:
        Configuration dict for the MCP, or empty dict if not found

    Example:
        config = get_mcp_config("billomat")
        api_key = config.get("api_key")
    """
    try:
        config = load_config()
        return config.get(mcp_name, {})
    except Exception:
        return {}


def is_mcp_configured(mcp_name: str, required_fields: list[str]) -> bool:
    """Check if an MCP server is properly configured.

    Args:
        mcp_name: Name of the MCP server
        required_fields: List of required configuration field names

    Returns:
        True if MCP is configured with all required fields, False otherwise

    Example:
        if is_mcp_configured("billomat", ["api_key", "account_id"]):
            # MCP is ready to use
            ...
    """
    config = get_mcp_config(mcp_name)

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    # Check all required fields are present and non-empty
    for field in required_fields:
        if not config.get(field):
            return False

    return True
