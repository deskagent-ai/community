# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Metadata Service
====================
Collects TOOL_METADATA from all MCP modules for dynamic WebUI icons/colors.

Uses centralized MCP discovery from ai_agent.mcp_discovery when available.
"""

import importlib.util
from pathlib import Path

# Import system_log for logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# Cache for metadata (loaded once on startup)
_tool_metadata_cache: dict = None


def _extract_metadata_via_ast(module_file: Path) -> dict | None:
    """Extract TOOL_METADATA from a Python file using AST parsing.

    Avoids executing the module (and its imports like _mcp_api).
    Works for metadata defined as pure dict literals.
    """
    import ast
    try:
        source = module_file.read_text(encoding='utf-8')
        tree = ast.parse(source)
    except (SyntaxError, IOError):
        return None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "TOOL_METADATA":
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    return None
    return None


def _load_metadata_from_file(module_file: Path, mcp_name: str) -> dict | None:
    """Load TOOL_METADATA from a single MCP module file.

    Uses AST-based extraction first (no code execution), falls back to
    exec_module for dynamic metadata.

    Args:
        module_file: Path to the Python file
        mcp_name: Name of the MCP server

    Returns:
        Metadata dict or None if not available
    """
    # Phase 1: AST extraction (no code execution, no import errors)
    raw = _extract_metadata_via_ast(module_file)
    if raw and isinstance(raw, dict):
        return {
            'icon': raw.get('icon', 'build'),
            'color': raw.get('color', '#757575'),
            'beta': raw.get('beta', False)
        }

    # Phase 2: exec_module fallback for dynamic metadata
    try:
        spec = importlib.util.spec_from_file_location(
            f"{mcp_name}_meta", module_file
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'TOOL_METADATA'):
            meta = module.TOOL_METADATA
            return {
                'icon': meta.get('icon', 'build'),
                'color': meta.get('color', '#757575'),
                'beta': meta.get('beta', False)
            }
    except Exception:
        pass  # AST already tried, no need to log exec_module failure

    return None


def collect_tool_metadata() -> dict:
    """Collect TOOL_METADATA from all MCP modules.

    Uses centralized MCP discovery (ai_agent.mcp_discovery) when available.
    Falls back to direct directory scanning for standalone use.

    Returns:
        Dict mapping MCP name to metadata:
        {
            "outlook": {"icon": "mail", "color": "#0078d4"},
            "billomat": {"icon": "payments", "color": "#4caf50"},
            ...
        }
    """
    metadata = {}

    # Try centralized MCP discovery first
    try:
        from ai_agent.mcp_discovery import discover_mcp_servers

        servers = discover_mcp_servers()  # No filter = all servers
        for server in servers:
            mcp_name = server['name']
            path = server['path']

            # Determine file to load based on type
            if server['type'] == 'file':
                module_file = path
            else:  # package or plugin
                module_file = path / "__init__.py"

            if not module_file.exists():
                continue

            meta = _load_metadata_from_file(module_file, mcp_name)
            if meta:
                metadata[mcp_name] = meta

        return metadata

    except ImportError:
        system_log("[MCP Metadata] Fallback: discover_mcp_servers not available")

    # Fallback: Direct directory scanning (standalone mode)
    try:
        from paths import get_mcp_dir
        mcp_dir = get_mcp_dir()
    except ImportError:
        mcp_dir = Path(__file__).parent.parent.parent.parent / "mcp"

    if not mcp_dir.exists():
        return metadata

    # 1. Legacy single-file MCPs: *_mcp.py
    for mcp_file in mcp_dir.glob("*_mcp.py"):
        if mcp_file.stem == "anonymization_proxy_mcp":
            continue

        mcp_name = mcp_file.stem.replace('_mcp', '')
        meta = _load_metadata_from_file(mcp_file, mcp_name)
        if meta:
            metadata[mcp_name] = meta

    # 2. Package-based MCPs: folder/__init__.py
    for item in mcp_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            init_file = item / "__init__.py"
            if init_file.exists():
                mcp_name = item.name
                if mcp_name in metadata:
                    continue

                meta = _load_metadata_from_file(init_file, mcp_name)
                if meta:
                    metadata[mcp_name] = meta

    return metadata


def get_tool_metadata() -> dict:
    """Get cached tool metadata.

    Metadata is collected once on first call and cached.
    Call reload_tool_metadata() to refresh.
    """
    global _tool_metadata_cache
    if _tool_metadata_cache is None:
        _tool_metadata_cache = collect_tool_metadata()
    return _tool_metadata_cache


def reload_tool_metadata() -> dict:
    """Force reload of tool metadata from MCP files."""
    global _tool_metadata_cache
    _tool_metadata_cache = collect_tool_metadata()
    return _tool_metadata_cache
