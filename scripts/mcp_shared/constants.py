# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Shared - Constants
======================
Centralized constants used across MCP servers and ai_agent modules.

This is the SINGLE SOURCE OF TRUTH for these values.
"""

# MCP servers that only work on Windows (use pywin32/COM)
# These are excluded from discovery on non-Windows platforms.
# Format: server names (not filenames) as used in mcp_discovery
WINDOWS_ONLY_MCP = ['outlook', 'clipboard']
