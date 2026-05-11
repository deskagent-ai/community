# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Shared Module
=================
Centralized utilities shared across all MCP servers.

This module eliminates code duplication by providing common functions
for email processing, configuration, and constants.

Usage (absolute imports from PYTHONPATH):
    from mcp_shared.email_utils import extract_latest_message, html_to_text
    from mcp_shared.config_utils import get_mcp_config, is_mcp_configured
    from mcp_shared.constants import WINDOWS_ONLY_MCP
"""

from .email_utils import extract_latest_message, html_to_text
from .config_utils import get_mcp_config, is_mcp_configured
from .constants import WINDOWS_ONLY_MCP

__all__ = [
    # Email utilities
    "extract_latest_message",
    "html_to_text",
    # Config utilities
    "get_mcp_config",
    "is_mcp_configured",
    # Constants
    "WINDOWS_ONLY_MCP",
]
