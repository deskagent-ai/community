# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Discovery - Server discovery for AI backends
=================================================

Centralized discovery of MCP servers for all AI backend implementations.
Supports:
- Legacy *_mcp.py files (e.g., outlook_mcp.py)
- Package-based MCPs (e.g., mcp/gmail/__init__.py)
- Plugin MCPs (e.g., plugins/*/mcp/*)
"""

import re
import sys
from pathlib import Path

# Path is set up by ai_agent/__init__.py
from paths import get_mcp_dir, PROJECT_DIR
from mcp_shared.constants import WINDOWS_ONLY_MCP

__all__ = [
    "WINDOWS_ONLY_MCP",
    "discover_mcp_servers",
]


def discover_mcp_servers(mcp_filter: str = None) -> list[dict]:
    """
    Discover available MCP servers from the mcp/ directory.

    Supports both:
    - Legacy *_mcp.py files (e.g., outlook_mcp.py)
    - Package-based MCPs (e.g., mcp/gmail/__init__.py)
    - Plugin MCPs (e.g., plugins/*/mcp/*)

    Args:
        mcp_filter: Optional regex pattern to filter servers (e.g., "gmail|datastore")

    Returns:
        List of dicts with: name, type ('file'|'package'|'plugin'), path
        Example: [
            {'name': 'gmail', 'type': 'package', 'path': Path('.../mcp/gmail')},
            {'name': 'outlook_mcp', 'type': 'file', 'path': Path('.../mcp/outlook_mcp.py')}
        ]
    """
    # Lazy import to avoid circular dependency
    from .logging import system_log

    mcp_dir = get_mcp_dir()
    servers = []

    # Debug: Log mcp_dir and filter
    system_log(f"[MCP Discovery] mcp_dir: {mcp_dir}")
    system_log(f"[MCP Discovery] mcp_dir exists: {mcp_dir.exists()}")
    system_log(f"[MCP Discovery] filter: {mcp_filter}")

    # Compile filter pattern if provided
    mcp_pattern = None
    if mcp_filter:
        try:
            mcp_pattern = re.compile(f"^({mcp_filter})$", re.IGNORECASE)
            system_log(f"[MCP Discovery] Compiled pattern: ^({mcp_filter})$")
        except re.error as e:
            system_log(f"[MCP Discovery] Invalid filter pattern: {e}")

    # Track discovered names to avoid duplicates
    discovered = set()

    # Method 1: Legacy *_mcp.py files
    for mcp_file in sorted(mcp_dir.glob("*_mcp.py")):
        # Skip proxy (handled separately)
        if mcp_file.name == "anonymization_proxy_mcp.py":
            continue

        server_name = mcp_file.stem.replace("_mcp", "")

        # Skip Windows-only on non-Windows
        if sys.platform != 'win32' and server_name in WINDOWS_ONLY_MCP:
            continue

        # Apply filter
        if mcp_pattern and not mcp_pattern.match(server_name):
            continue

        discovered.add(server_name)
        servers.append({
            'name': server_name,
            'type': 'file',
            'path': mcp_file,
            'module_name': mcp_file.stem
        })

    # Method 2: Package-based MCP servers (mcp/gmail/__init__.py)
    system_log(f"[MCP Discovery] Scanning for package MCPs in: {mcp_dir}")
    try:
        folders = list(mcp_dir.iterdir())
        system_log(f"[MCP Discovery] Found {len(folders)} items in mcp_dir")
    except Exception as e:
        system_log(f"[MCP Discovery] ERROR iterating mcp_dir: {e}")
        return servers

    for mcp_folder in sorted(folders):
        if not mcp_folder.is_dir():
            continue
        if mcp_folder.name.startswith('_'):  # Skip __pycache__ etc.
            continue

        init_file = mcp_folder / "__init__.py"
        if not init_file.exists():
            system_log(f"[MCP Discovery] Skipped {mcp_folder.name}: no __init__.py")
            continue

        server_name = mcp_folder.name

        # Skip if already discovered via legacy method
        if server_name in discovered:
            continue

        # Skip Windows-only on non-Windows
        if sys.platform != 'win32' and server_name in WINDOWS_ONLY_MCP:
            continue

        # Apply filter
        if mcp_pattern:
            match = mcp_pattern.match(server_name)
            system_log(f"[MCP Discovery] Filter test: '{server_name}' vs pattern -> {bool(match)}")
            if not match:
                continue

        system_log(f"[MCP Discovery] Added package MCP: {server_name}")
        servers.append({
            'name': server_name,
            'type': 'package',
            'path': mcp_folder,
            'module_name': server_name
        })

    # Method 3: Plugin MCP servers (plugins/*/mcp/*)
    # Supports two structures:
    # - Flat:   plugins/sap/mcp/__init__.py       -> server_name = "sap:sap"
    # - Nested: plugins/sap/mcp/custom/__init__.py -> server_name = "sap:custom"
    try:
        from assistant.services.plugins import get_plugin_mcp_dirs
        for plugin_name, plugin_mcp_dir in get_plugin_mcp_dirs():
            system_log(f"[MCP Discovery] Scanning plugin MCP dir: {plugin_name} -> {plugin_mcp_dir}")

            # Flat structure: mcp/__init__.py directly (MCP name = plugin name)
            flat_init = plugin_mcp_dir / "__init__.py"
            if flat_init.exists():
                server_name = f"{plugin_name}:{plugin_name}"
                if server_name not in discovered:
                    if not mcp_pattern or mcp_pattern.match(server_name):
                        discovered.add(server_name)
                        system_log(f"[MCP Discovery] Added plugin MCP (flat): {server_name}")
                        servers.append({
                            'name': server_name,
                            'type': 'plugin',
                            'path': plugin_mcp_dir,
                            'module_name': f"plugin_{plugin_name}_mcp",
                            'plugin': plugin_name
                        })
                    else:
                        system_log(f"[MCP Discovery] Plugin flat filter: '{server_name}' -> no match")

            # Nested structure: mcp/servername/__init__.py (existing behavior)
            for mcp_folder in sorted(plugin_mcp_dir.iterdir()):
                if not mcp_folder.is_dir():
                    continue
                if mcp_folder.name.startswith('_'):
                    continue

                init_file = mcp_folder / "__init__.py"
                if not init_file.exists():
                    continue

                # Prefix with plugin name
                server_name = f"{plugin_name}:{mcp_folder.name}"

                # Skip if already discovered (e.g. flat structure matched same name)
                if server_name in discovered:
                    continue

                # Apply filter
                if mcp_pattern:
                    match = mcp_pattern.match(server_name)
                    system_log(f"[MCP Discovery] Plugin filter test: '{server_name}' vs pattern -> {bool(match)}")
                    if not match:
                        continue

                discovered.add(server_name)
                system_log(f"[MCP Discovery] Added plugin MCP (nested): {server_name}")
                servers.append({
                    'name': server_name,
                    'type': 'plugin',
                    'path': mcp_folder,
                    'module_name': f"plugins.{plugin_name}.mcp.{mcp_folder.name}",
                    'plugin': plugin_name
                })
    except ImportError:
        pass  # Plugin system not available

    system_log(f"[MCP Discovery] Total servers found: {len(servers)}")
    return servers
