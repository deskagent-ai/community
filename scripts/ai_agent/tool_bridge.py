# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP to Ollama Tool Bridge
=========================
Dynamically discovers tools from MCP servers and converts them
to Ollama's native tool format. This bridges MCP tools to work
with direct Ollama API calls.

Usage:
    from tool_bridge import get_ollama_tools, execute_tool

    # Get tools for Ollama API
    tools = get_ollama_tools()

    # Execute a tool by name
    result = execute_tool("get_selected_email", {})
"""

import asyncio
import importlib.util
import inspect
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable
from .logging import log, log_tool_call
from .task_context import get_task_context
from .demo_mode import is_demo_mode_enabled, get_mock_response, apply_mock_delay
from .mcp_health import get_tracker

# NOTE: The following per-task state has been moved to TaskContext:
# - _anonymization_context -> ctx.anon_context
# - _allowed_tools -> ctx.allowed_tools
# - _blocked_tools -> ctx.blocked_tools
# - _dry_run_mode -> ctx.dry_run_mode
# - _test_folder -> ctx.test_folder
# - _simulated_actions -> ctx.simulated_actions
#
# This enables parallel execution of multiple backends without state collision.
# Use get_task_context() to access per-task state.

# Dynamically collected destructive tools from MCP modules
# Populated by _discover_mcp_tools() from each MCP's DESTRUCTIVE_TOOLS set
_destructive_tools: set = set()

# Dynamically collected read-only tools from MCP modules
# Populated by _discover_mcp_tools() from each MCP's READ_ONLY_TOOLS set
_read_only_tools: set = set()

# Path is set up by ai_agent/__init__.py
from paths import get_mcp_dir

# Cache for discovered tools - now per-filter for parallel execution isolation
# Key: filter pattern (or "" for no filter)
# Value: tuple of (tool_cache_dict, function_cache_dict)
_cache_by_filter: dict = {}
_cache_lock = threading.RLock()  # Thread-safe access for _cache_by_filter

# Per-MCP import locks for thread-safe lazy loading (plan-048)
_mcp_import_locks: dict[str, threading.Lock] = {}
_mcp_import_locks_lock = threading.Lock()

# Module whitelist for cache security validation (plan-048)
# Built dynamically from MCP directory on first access
_ALLOWED_MCP_MODULES: set | None = None

# Session-based anonymization context cache for SDK in-process tools
# Key: session_id, Value: AnonymizationContext
_sdk_anon_contexts: dict = {}


def _get_sdk_anon_context(session_id: str):
    """Get or create AnonymizationContext for session.

    Args:
        session_id: Session ID to look up

    Returns:
        AnonymizationContext for this session
    """
    from .anonymizer import AnonymizationContext
    if session_id not in _sdk_anon_contexts:
        _sdk_anon_contexts[session_id] = AnonymizationContext()
    return _sdk_anon_contexts[session_id]


def seed_sdk_anon_context(session_id: str, anon_context) -> None:
    """Seed the SDK anon cache with prompt-mappings from the caller.

    This ensures that tool-call arguments can be de-anonymized even before
    any tool-result anonymization has occurred (which would create mappings
    via _anonymize_sdk_result). Called from claude_agent_sdk.py INPROCESS block.

    Args:
        session_id: Session ID to seed
        anon_context: AnonymizationContext with mappings from prompt anonymization
    """
    if not anon_context or not hasattr(anon_context, 'mappings') or not anon_context.mappings:
        return

    ctx = _get_sdk_anon_context(session_id)
    # Merge prompt mappings into the session context
    ctx.mappings.update(anon_context.mappings)
    if hasattr(anon_context, 'reverse_mappings') and anon_context.reverse_mappings:
        ctx.reverse_mappings.update(anon_context.reverse_mappings)
    if hasattr(anon_context, 'counters') and anon_context.counters:
        for key, val in anon_context.counters.items():
            ctx.counters[key] = max(ctx.counters.get(key, 0), val)
    log(f"[Tool Bridge SDK] Seeded anon cache with {len(anon_context.mappings)} prompt mappings for session {session_id}")


def _clear_sdk_anon_context(session_id: str):
    """Clear anonymization context and PII files when session ends.

    Args:
        session_id: Session ID to clear
    """
    _sdk_anon_contexts.pop(session_id, None)

    # Clean up PII mapping files from disk (plan-080 review recommendation)
    try:
        from paths import get_logs_dir
        temp_dir = get_logs_dir().parent / ".temp"
        for prefix in ("anon_mappings_", "anon_init_"):
            pii_file = temp_dir / f"{prefix}{session_id}.json"
            if pii_file.exists():
                pii_file.unlink()
                log(f"[Tool Bridge SDK] Cleaned up PII file: {pii_file.name}")
    except Exception:
        pass  # Non-fatal - files will be overwritten on next session


# Filesystem tools that modify files - checked against TaskContext.filesystem_write_paths
_FILESYSTEM_WRITE_TOOLS = {"fs_write_file", "fs_copy_file", "fs_delete_file"}


def _check_filesystem_write_allowed(tool_name: str, arguments: dict) -> str | None:
    """Check if filesystem write operation is allowed by TaskContext restrictions.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments (must contain 'path' or 'destination')

    Returns:
        Error message string if blocked, None if allowed
    """
    if tool_name not in _FILESYSTEM_WRITE_TOOLS:
        return None  # Not a filesystem write tool

    ctx = get_task_context()
    allowed_paths = ctx.filesystem_write_paths

    # No restrictions configured = allow all (backward-compatible)
    if not allowed_paths:
        return None

    # Get the target path from arguments
    if tool_name == "fs_copy_file":
        target_path = arguments.get("destination", "")
    else:
        target_path = arguments.get("path", "")

    if not target_path:
        return f"Error: {tool_name} requires a path argument"

    # Normalize path for comparison
    try:
        check_path = str(Path(target_path).resolve()).replace("\\", "/")
    except (OSError, ValueError):
        # Path resolution fails for non-existent or invalid paths
        check_path = target_path.replace("\\", "/")

    # Check against allowed patterns
    for pattern in allowed_paths:
        # Normalize pattern
        try:
            if pattern.endswith("**") or pattern.endswith("*"):
                norm_pattern = pattern.replace("\\", "/")
            else:
                norm_pattern = str(Path(pattern).resolve()).replace("\\", "/")
        except (OSError, ValueError):
            # Pattern path resolution fails - use as-is
            norm_pattern = pattern.replace("\\", "/")

        # Handle ** (recursive) patterns
        if pattern.endswith("/**"):
            base_path = norm_pattern[:-3]  # Remove /**
            try:
                base_path = str(Path(base_path).resolve()).replace("\\", "/")
            except (OSError, ValueError):
                pass  # Keep original base_path if resolution fails
            if check_path.startswith(base_path + "/") or check_path == base_path:
                return None  # Allowed

        # Handle * (single level) patterns
        elif pattern.endswith("/*"):
            base_path = norm_pattern[:-2]  # Remove /*
            try:
                base_path = str(Path(base_path).resolve()).replace("\\", "/")
            except (OSError, ValueError):
                pass  # Keep original base_path if resolution fails
            # Check if path is direct child
            if check_path.startswith(base_path + "/"):
                remaining = check_path[len(base_path)+1:]
                if "/" not in remaining:  # No further subdirs
                    return None  # Allowed

        # Exact file/path match
        else:
            try:
                full_pattern = str(Path(pattern).resolve()).replace("\\", "/")
            except (OSError, ValueError):
                # Pattern resolution fails - use normalized pattern
                full_pattern = norm_pattern
            if check_path == full_pattern:
                return None  # Allowed

    # Path not in whitelist
    log(f"[Tool Bridge] BLOCKED: {tool_name} to '{target_path}' - not in allowed paths: {allowed_paths}")
    return f"Error: Write access denied. Path '{target_path}' is not in allowed write locations. Allowed: {allowed_paths}"


class ToolBridge:
    """
    Simple wrapper class for tool execution.
    Used by Workflow system to call MCP tools.
    """

    def execute(self, tool_name: str, *args, **kwargs) -> Any:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            *args: Positional arguments (mapped to parameter names from tool signature)
            **kwargs: Keyword arguments passed to the tool

        Returns:
            Tool execution result
        """
        # Convert positional args to kwargs using tool signature
        if args:
            if len(args) == 1 and isinstance(args[0], dict) and not kwargs:
                # Single dict argument - use as kwargs directly
                kwargs = args[0]
            else:
                # Map positional args to parameter names from tool signature
                func = get_tool_function(tool_name)
                if func:
                    import inspect
                    sig = inspect.signature(func)
                    param_names = [p.name for p in sig.parameters.values()
                                   if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                                 inspect.Parameter.POSITIONAL_ONLY)]
                    for i, arg in enumerate(args):
                        if i < len(param_names):
                            kwargs[param_names[i]] = arg

        return execute_tool(tool_name, kwargs)


def _python_type_to_json_schema(py_type, depth: int = 0) -> dict:
    """Convert Python type hint to JSON Schema type with items for arrays.

    Args:
        py_type: Python type annotation to convert
        depth: Recursion depth counter (max 10, fallback to string)

    Returns:
        JSON Schema dict for the type
    """
    if depth > 10:
        return {"type": "string"}

    if py_type is None or py_type == inspect.Parameter.empty:
        return {"type": "string"}

    type_name = getattr(py_type, '__name__', str(py_type))
    type_str = str(py_type)

    # Handle typing module types (List[str], Optional[str], etc.)
    origin = getattr(py_type, '__origin__', None)
    args = getattr(py_type, '__args__', ())

    # Handle list/List types
    if origin is list or type_name == 'list':
        item_schema = {"type": "string"}  # default
        if args:
            inner = args[0]
            inner_args = getattr(inner, '__args__', ())
            inner_name = getattr(inner, '__name__', str(inner))
            # If inner type is parameterized (e.g. list[str], dict[str, Any]),
            # always recurse to preserve nested structure
            if inner_args:
                item_schema = _python_type_to_json_schema(inner, depth=depth + 1)
            else:
                type_map = {'str': 'string', 'int': 'integer', 'float': 'number',
                            'bool': 'boolean', 'dict': 'object'}
                if inner_name in type_map:
                    item_schema = {"type": type_map[inner_name]}
                else:
                    # Fallback: recurse for unknown types
                    item_schema = _python_type_to_json_schema(inner, depth=depth + 1)
        return {"type": "array", "items": item_schema}

    # Handle Optional types
    if origin is type(None) or 'Optional' in type_str or 'None' in type_str:
        if args:
            inner = args[0]
            return _python_type_to_json_schema(inner, depth=depth + 1)
        return {"type": "string"}

    # Simple type mapping
    type_map = {
        'str': 'string',
        'int': 'integer',
        'float': 'number',
        'bool': 'boolean',
        'list': 'array',
        'dict': 'object',
    }

    json_type = type_map.get(type_name, 'string')

    # Add items for array type (fallback)
    if json_type == 'array':
        return {"type": "array", "items": {"type": "string"}}

    return {"type": json_type}


def _get_default_value(param: inspect.Parameter) -> Any:
    """Get default value for a parameter, if any."""
    if param.default is not inspect.Parameter.empty:
        return param.default
    return None


def _function_to_ollama_tool(func: Callable, prefix: str = "") -> dict:
    """Convert a Python function to Ollama tool schema."""
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or f"Executes {func.__name__}"

    # Build parameters schema
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        # Get type annotation and convert to JSON Schema
        param_type = param.annotation
        prop = _python_type_to_json_schema(param_type)

        # Add description from docstring if available (parse Args section)
        # For now, use parameter name as description
        prop["description"] = f"Parameter: {name}"

        # Check for default value
        default = _get_default_value(param)
        if default is not None:
            prop["default"] = default
        else:
            if param.default is inspect.Parameter.empty:
                required.append(name)

        properties[name] = prop

    # Build tool name with optional prefix
    tool_name = f"{prefix}{func.__name__}" if prefix else func.__name__

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": doc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }


def _load_mcp_package(mcp_dir: Path, package_name: str, init_file: Path) -> object:
    """
    Load an MCP package with proper relative import support.

    Args:
        mcp_dir: The MCP directory
        package_name: Name of the package (e.g., "outlook")
        init_file: Path to __init__.py

    Returns:
        Loaded module or None on error
    """
    try:
        # Check if already loaded
        if package_name in sys.modules:
            return sys.modules[package_name]

        # Ensure mcp_dir is on sys.path so imports like _mcp_api work
        if str(mcp_dir) not in sys.path:
            sys.path.insert(0, str(mcp_dir))

        # Load with submodule search locations for relative imports
        spec = importlib.util.spec_from_file_location(
            package_name,
            init_file,
            submodule_search_locations=[str(init_file.parent)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        # Remove partially-loaded module from sys.modules to prevent
        # _lazy_import_mcp from returning an incomplete module later
        sys.modules.pop(package_name, None)
        log(f"[Tool Bridge] Error loading package {package_name}: {e}")
        return None


def _validate_cache_module(module_name: str) -> bool:
    """Validate that a module name from cache is a legitimate MCP module.

    Prevents path traversal and arbitrary module loading from manipulated cache.

    Args:
        module_name: Module name to validate (e.g., "outlook", "outlook.outlook_calendar")

    Returns:
        True if module is a valid MCP, False otherwise
    """
    global _ALLOWED_MCP_MODULES

    if not module_name:
        return False

    # Path traversal protection
    if ".." in module_name or "/" in module_name or "\\" in module_name:
        log(f"[SECURITY] Blocked path traversal in module: {module_name}")
        return False

    # Build whitelist on first access
    if _ALLOWED_MCP_MODULES is None:
        try:
            mcp_dir = get_mcp_dir()
            _ALLOWED_MCP_MODULES = {
                d.name for d in mcp_dir.iterdir()
                if d.is_dir() and not d.name.startswith("_")
            }
            # Also whitelist plugin MCP modules (plugin_{name}_mcp pattern)
            try:
                from assistant.services.plugins import get_plugin_mcp_dirs
                for plugin_name, _ in get_plugin_mcp_dirs():
                    _ALLOWED_MCP_MODULES.add(f"plugin_{plugin_name}_mcp")
            except ImportError:
                pass
            log(f"[Tool Bridge] Module whitelist built: {len(_ALLOWED_MCP_MODULES)} MCPs")
        except Exception as e:
            log(f"[Tool Bridge] Failed to build module whitelist: {e}")
            return False

    # Extract package name (e.g., "outlook" from "outlook.outlook_calendar")
    package = module_name.split(".")[0]
    return package in _ALLOWED_MCP_MODULES


def _lazy_import_mcp(module_name: str):
    """Import an MCP module with thread-safe locking.

    Uses per-MCP import locks to prevent duplicate imports during
    concurrent lazy loading from multiple threads.

    Args:
        module_name: Module name to import (e.g., "outlook", "outlook.outlook_calendar")

    Returns:
        Loaded module or None on error

    Raises:
        ValueError: If module fails whitelist validation
    """
    # Validate against whitelist
    if not _validate_cache_module(module_name):
        raise ValueError(f"Invalid MCP module: {module_name}")

    # Get or create per-MCP lock
    with _mcp_import_locks_lock:
        if module_name not in _mcp_import_locks:
            _mcp_import_locks[module_name] = threading.Lock()
        mcp_lock = _mcp_import_locks[module_name]

    # Import under lock (prevents duplicate import)
    with mcp_lock:
        # Check if already loaded (double-check after acquiring lock)
        if module_name in sys.modules:
            return sys.modules[module_name]

        log(f"[Tool Bridge] Lazy importing MCP: {module_name}")
        mcp_dir = get_mcp_dir()

        try:
            mod_parts = module_name.split(".")
            package_name = mod_parts[0]

            # Find package directory
            package_dir = mcp_dir / package_name
            if not package_dir.is_dir():
                log(f"[Tool Bridge] Lazy import failed: {package_dir} not found")
                return None

            init_file = package_dir / "__init__.py"
            if not init_file.exists():
                log(f"[Tool Bridge] Lazy import failed: {init_file} not found")
                return None

            # Load the package __init__.py first
            if package_name not in sys.modules:
                # Add MCP directory to path for imports
                if str(mcp_dir) not in sys.path:
                    sys.path.insert(0, str(mcp_dir))

                spec = importlib.util.spec_from_file_location(
                    package_name,
                    init_file,
                    submodule_search_locations=[str(package_dir)]
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[package_name] = module
                spec.loader.exec_module(module)

            # If dotted path, load the submodule too
            if len(mod_parts) > 1:
                submod_name = mod_parts[1]
                submod_file = package_dir / f"{submod_name}.py"
                if submod_file.exists() and module_name not in sys.modules:
                    spec = importlib.util.spec_from_file_location(module_name, submod_file)
                    submodule = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = submodule
                    spec.loader.exec_module(submodule)

            loaded = sys.modules.get(module_name) or sys.modules.get(package_name)
            log(f"[Tool Bridge] Lazy imported: {module_name}")
            return loaded

        except Exception as e:
            log(f"[Tool Bridge] Lazy import error for {module_name}: {e}")
            return None


def _load_schemas_from_cache(mcp_filter: str = None) -> tuple[list, dict] | None:
    """Load tool schemas from proxy_tool_cache.json for fast startup.

    Returns tool definitions and a lazy function map that imports modules
    on first tool call. This avoids importing all MCP modules at startup.

    Cache is validated via:
    - Version check (must be v2)
    - mtime check per MCP file (detects code changes)
    - Module whitelist (security)

    Args:
        mcp_filter: Optional regex to filter by MCP name

    Returns:
        Tuple of (tools_list, function_map) or None if cache invalid/missing
    """
    try:
        from paths import get_logs_dir
        cache_dir = get_logs_dir().parent / ".temp"
        cache_file = cache_dir / "proxy_tool_cache.json"

        if not cache_file.exists():
            return None

        cache_data = json.loads(cache_file.read_text(encoding='utf-8'))

        # Only use v2 cache (v1 lacks security metadata)
        version = cache_data.get("version", 1)
        if version < 2:
            log("[Tool Bridge] Cache v1 found, skipping (need v2)")
            return None

        # Validate tool_bridge.py mtime - schema conversion changes invalidate all schemas
        cached_bridge_mtime = cache_data.get("bridge_mtime", 0)
        bridge_file = Path(__file__)
        try:
            current_bridge_mtime = bridge_file.stat().st_mtime
            if abs(current_bridge_mtime - cached_bridge_mtime) > 0.01:
                log("[Tool Bridge] Cache stale: tool_bridge.py modified since cache build")
                return None
        except OSError:
            pass

        # Validate mtimes - check if any MCP file was modified since cache was built
        cached_mtimes = cache_data.get("mcp_mtimes", {})
        mcp_dir = get_mcp_dir()

        for mcp_name, cached_mtime in cached_mtimes.items():
            init_file = mcp_dir / mcp_name / "__init__.py"
            if init_file.exists():
                try:
                    current_mtime = init_file.stat().st_mtime
                    if abs(current_mtime - cached_mtime) > 0.01:  # Float comparison tolerance
                        log(f"[Tool Bridge] Cache stale: {mcp_name} modified since cache build")
                        return None
                except OSError:
                    return None

        # Check if new MCP directories were added since cache was built
        current_mcps = {
            d.name for d in mcp_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_") and (d / "__init__.py").exists()
        }
        cached_mcp_set = set(cached_mtimes.keys())
        new_mcps = current_mcps - cached_mcp_set
        if new_mcps:
            log(f"[Tool Bridge] Cache stale: new MCPs detected: {new_mcps}")
            return None

        # Build filter regex
        filter_re = None
        if mcp_filter:
            try:
                filter_re = re.compile(f"^({mcp_filter})$", re.IGNORECASE)
            except re.error:
                return None

        # Build tools list and lazy function map from cache
        tools = []
        function_map = {}

        for tool_info in cache_data.get("tools", []):
            tool_name = tool_info["name"]
            module_name = tool_info.get("module", "")

            # Validate module against whitelist
            if module_name and not _validate_cache_module(module_name):
                log(f"[Tool Bridge] Cache: skipping invalid module {module_name}")
                continue

            # Apply MCP filter
            if filter_re and module_name:
                package = module_name.split(".")[0]
                # Map plugin module names: plugin_X_mcp → X:X for filter matching
                if package.startswith("plugin_") and package.endswith("_mcp"):
                    plugin_name = package[7:-4]  # "plugin_sap_mcp" → "sap"
                    package = f"{plugin_name}:{plugin_name}"
                if not filter_re.match(package):
                    continue

            # Build Ollama-format tool definition
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_info.get("description", ""),
                    "parameters": tool_info.get("parameters", {})
                }
            }
            tools.append(tool_def)

            # Populate security metadata sets from cache
            if tool_info.get("is_destructive", False):
                _destructive_tools.add(tool_name)
            if tool_info.get("is_read_only", False):
                _read_only_tools.add(tool_name)

            # Create lazy function wrapper
            _mod = module_name  # Capture for closure

            def _make_lazy_func(tname: str, mod: str):
                def lazy_func(**kwargs):
                    """Lazy-loaded MCP tool function."""
                    # Import on first call
                    module = _lazy_import_mcp(mod)
                    if module is None:
                        return f"Error: Could not import module {mod} for tool {tname}"

                    # Find the actual function
                    func = None

                    # Method 1: FastMCP tool registry
                    mcp_instance = getattr(module, 'mcp', None)
                    if mcp_instance and hasattr(mcp_instance, '_tool_manager'):
                        tool_manager = mcp_instance._tool_manager
                        if hasattr(tool_manager, '_tools'):
                            tool_obj = tool_manager._tools.get(tname)
                            if tool_obj and hasattr(tool_obj, 'fn'):
                                func = tool_obj.fn

                    # Method 2: Direct attribute
                    if not func:
                        func = getattr(module, tname, None)

                    if func and callable(func):
                        # Replace ourselves in function_map with the real function
                        # so subsequent calls skip lazy loading
                        with _cache_lock:
                            for key, (tc, fc) in _cache_by_filter.items():
                                if tname in fc:
                                    fc[tname] = func
                        return func(**kwargs)

                    return f"Error: Function {tname} not found in {mod}"

                lazy_func.__name__ = tname
                lazy_func.__module__ = mod
                return lazy_func

            function_map[tool_name] = _make_lazy_func(tool_name, _mod)

        if tools:
            log(f"[Tool Bridge] Loaded {len(tools)} tools from cache (schema-first)")
            return tools, function_map

        return None

    except Exception as e:
        log(f"[Tool Bridge] Cache load failed: {e}")
        return None


def _discover_mcp_tools(mcp_filter: str = None) -> tuple[list, dict]:
    """
    Discover tools from MCP server modules.

    Supports both:
    - Single files: *_mcp.py
    - Packages: subdirectories with __init__.py

    Uses schema-cache-first strategy: tries to load from proxy_tool_cache.json
    before falling back to full module import discovery.

    Args:
        mcp_filter: Optional regex pattern to filter MCP servers (e.g., "outlook|billomat")

    Returns:
        Tuple of (ollama_tools, function_map)
    """
    # Use filter as cache key (empty string for no filter)
    cache_key = mcp_filter or ""

    # Check if we have cached results for this filter (thread-safe read)
    with _cache_lock:
        if cache_key in _cache_by_filter:
            tool_cache, function_cache = _cache_by_filter[cache_key]
            if tool_cache and function_cache:
                return list(tool_cache.values()), function_cache

    # Try schema-cache-first: load from proxy_tool_cache.json
    cached = _load_schemas_from_cache(mcp_filter)
    if cached is not None:
        tools, function_map = cached
        tool_cache = {t["function"]["name"]: t for t in tools}
        with _cache_lock:
            _cache_by_filter[cache_key] = (tool_cache, function_map)
        return tools, function_map

    # Initialize new caches for this filter
    tool_cache = {}
    function_cache = {}

    # Add MCP directory to path
    mcp_dir = get_mcp_dir()
    if str(mcp_dir) not in sys.path:
        sys.path.insert(0, str(mcp_dir))

    # Add embedded Python's stdlib and site-packages for MCP dependencies
    # Order follows python312._pth: python312.zip, Lib, Lib/site-packages
    # These are needed by MCPs but not bundled by Nuitka:
    # - email.mime (gmail, imap) - in python312.zip
    # - xml.dom (sepa) - in python312.zip
    # - msal (msgraph) - in Lib/site-packages
    try:
        from paths import DESKAGENT_DIR
        python_dir = DESKAGENT_DIR / "python"

        # Add embedded Python paths for MCPs
        # NOTE: Do NOT add python312.zip here - it's already loaded by Nuitka
        # and adding it again at wrong position breaks email.mime imports
        paths_to_add = [
            python_dir / "Lib",
            python_dir / "Lib" / "site-packages",
            python_dir / "Lib" / "site-packages" / "win32",
            python_dir / "Lib" / "site-packages" / "win32" / "lib",
            python_dir / "Lib" / "site-packages" / "Pythonwin",
        ]

        for path in paths_to_add:
            if path.exists() and str(path) not in sys.path:
                # Insert at position 1 to not break pywin32 DLL loading
                # Position 0 is reserved for the current working directory
                sys.path.insert(1, str(path))
                log(f"[Tool Bridge] Added stdlib path: {path}")
    except Exception:
        pass  # Dev mode - path doesn't exist

    tools = []
    function_map = {}

    # Use centralized discovery
    from .mcp_discovery import discover_mcp_servers

    if mcp_filter:
        log(f"[Tool Bridge] MCP filter active: {mcp_filter}")

    # Convert to format expected by tool loading logic
    discovered = discover_mcp_servers(mcp_filter)
    mcp_sources = [
        (s['name'], s['module_name'], s['type'], s['path'])
        for s in discovered
    ]

    for server_name, module_name, source_type, source_path in mcp_sources:
        try:
            # Import the module based on source type
            # Always reload file-based MCPs to pick up changes (important for development)
            if source_type == 'file':
                # Force reload if already loaded - important to pick up new functions!
                if module_name in sys.modules:
                    del sys.modules[module_name]
                # Load single file MCP
                spec = importlib.util.spec_from_file_location(module_name, source_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            else:
                # Load package MCP with relative import support
                module = _load_mcp_package(mcp_dir, module_name, source_path / "__init__.py")
                if module is None:
                    continue

            # Check if MCP is configured (has required credentials/is enabled)
            is_configured_fn = getattr(module, 'is_configured', None)
            if is_configured_fn and callable(is_configured_fn):
                if not is_configured_fn():
                    log(f"[Tool Bridge] MCP '{server_name}' is_configured()=False, loading anyway")
                    # Don't skip - load tools anyway, let tool-call-time errors be explicit
                    # This matches STDIO proxy behavior which also loads without is_configured check

            # Collect DESTRUCTIVE_TOOLS from module (for dry-run mode)
            # Convention: Tool names in DESTRUCTIVE_TOOLS must include their prefix
            destructive_set = getattr(module, 'DESTRUCTIVE_TOOLS', None)
            if destructive_set and isinstance(destructive_set, set):
                _destructive_tools.update(destructive_set)

            # Collect READ_ONLY_TOOLS from module (for tool_mode enforcement)
            read_only_set = getattr(module, 'READ_ONLY_TOOLS', None)
            if read_only_set and isinstance(read_only_set, set):
                _read_only_tools.update(read_only_set)

            # Find the FastMCP instance
            mcp_instance = getattr(module, 'mcp', None)

            if mcp_instance is None:
                continue

            # Get registered tools from FastMCP
            # FastMCP stores tools in _tool_manager.tools or similar
            registered_tools = []

            # Method 1: Check for _tool_manager._tools (FastMCP)
            if hasattr(mcp_instance, '_tool_manager'):
                tool_manager = mcp_instance._tool_manager
                if hasattr(tool_manager, '_tools'):
                    # _tools is a dict of {name: Tool} objects
                    registered_tools = list(tool_manager._tools.values())

            # Method 2: Check for _tools directly on mcp instance
            if not registered_tools and hasattr(mcp_instance, '_tools'):
                registered_tools = list(mcp_instance._tools.values())

            # Convert each tool to Ollama format
            server_tool_count = 0
            for tool in registered_tools:
                # Get the actual function
                if callable(tool):
                    func = tool
                elif hasattr(tool, 'fn'):
                    func = tool.fn
                elif hasattr(tool, 'func'):
                    func = tool.func
                else:
                    continue

                # Skip internal/helper functions
                func_name = func.__name__
                if func_name.startswith('_'):
                    continue

                # Convert to Ollama tool format - function names include their prefix
                # Convention: All MCP functions MUST be prefixed (e.g., outlook_get_email, gmail_search)
                # This ensures unique names for external usage and prevents collisions
                ollama_tool = _function_to_ollama_tool(func, prefix="")
                tools.append(ollama_tool)

                # Store function reference for execution
                function_map[func_name] = func
                server_tool_count += 1

            if server_tool_count > 0:
                log(f"[Tool Bridge] {server_name}: {server_tool_count} tools")

        except Exception as e:
            log(f"[Tool Bridge] Error loading {module_name}: {e}")

    # Cache results for this filter (thread-safe write)
    tool_cache = {t["function"]["name"]: t for t in tools}
    with _cache_lock:
        _cache_by_filter[cache_key] = (tool_cache, function_map)

    log(f"[Tool Bridge] Discovered {len(tools)} tools total")

    # Save tool schemas to cache file for proxy lazy loading
    # This allows the proxy to respond immediately with tool list without importing modules
    _save_proxy_cache(tools, function_map)

    return tools, function_map


def _save_proxy_cache(tools: list, function_map: dict) -> None:
    """Save tool schemas to a JSON cache file (v2 format) for the anonymization proxy.

    This enables the proxy to respond immediately with tool definitions
    without needing to import all MCP modules at startup.

    v2 additions:
    - mcp_mtimes: File modification times for cache invalidation
    - configured_mcps: Which MCPs were configured when cache was built
    - is_high_risk: Per-tool security flag for prompt injection protection
    - is_destructive: Per-tool flag for dry-run mode
    - is_read_only: Per-tool flag for tool_mode enforcement
    """
    try:
        from paths import get_logs_dir
        cache_dir = get_logs_dir().parent / ".temp"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "proxy_tool_cache.json"
        log(f"[Tool Bridge] Creating proxy cache v2 at: {cache_file}")

        # Collect mtime for each MCP module file
        mcp_mtimes = {}
        mcp_dir = get_mcp_dir()
        for d in mcp_dir.iterdir():
            if d.is_dir() and not d.name.startswith("_"):
                init_file = d / "__init__.py"
                if init_file.exists():
                    try:
                        mcp_mtimes[d.name] = init_file.stat().st_mtime
                    except OSError:
                        pass

        # Determine configured MCPs from loaded modules
        configured_mcps = set()
        for tool in tools:
            tool_name = tool["function"]["name"]
            func = function_map.get(tool_name)
            if func:
                mod_name = getattr(func, '__module__', '')
                package = mod_name.split(".")[0] if mod_name else ""
                if package:
                    configured_mcps.add(package)

        # Get tool_bridge.py mtime for schema conversion invalidation
        bridge_mtime = 0
        try:
            bridge_mtime = Path(__file__).stat().st_mtime
        except OSError:
            pass

        # Build cache with tool schemas, module info, and security metadata
        cache_data = {
            "version": 2,
            "generated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
            "bridge_mtime": bridge_mtime,
            "mcp_mtimes": mcp_mtimes,
            "configured_mcps": sorted(configured_mcps),
            "tools": []
        }

        for tool in tools:
            tool_name = tool["function"]["name"]
            func = function_map.get(tool_name)
            if func is None:
                continue

            # Get module info for lazy loading
            module_name = getattr(func, '__module__', None)

            # Determine is_high_risk from module's HIGH_RISK_TOOLS set
            is_high_risk = False
            if module_name:
                package_name = module_name.split(".")[0]
                module_obj = sys.modules.get(package_name) or sys.modules.get(module_name)
                if module_obj:
                    high_risk_set = getattr(module_obj, "HIGH_RISK_TOOLS", None)
                    if high_risk_set and isinstance(high_risk_set, set):
                        is_high_risk = tool_name in high_risk_set
                    # Also check IS_HIGH_RISK flag (all tools in module are high-risk)
                    if getattr(module_obj, "IS_HIGH_RISK", False):
                        is_high_risk = True

            cache_data["tools"].append({
                "name": tool_name,
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get("parameters", {}),
                "module": module_name,
                "is_high_risk": is_high_risk,
                "is_destructive": tool_name in _destructive_tools,
                "is_read_only": tool_name in _read_only_tools,
            })

        # Write cache file
        cache_file.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False), encoding='utf-8')
        log(f"[Tool Bridge] Saved proxy cache v2: {len(cache_data['tools'])} tools, "
            f"{len(configured_mcps)} MCPs, {len(mcp_mtimes)} mtimes")

    except Exception as e:
        import traceback
        log(f"[Tool Bridge] Failed to save proxy cache: {e}")
        log(f"[Tool Bridge] Traceback: {traceback.format_exc()}")


def set_allowed_tools(tools: list) -> None:
    """
    Set the whitelist of allowed tools for the current task.
    Call this before get_ollama_tools() to filter to only specific tools.

    Args:
        tools: List of tool names to allow (e.g., ["read_file", "list_directory"])
               If None, all tools from allowed MCP servers are available.

    Note:
        This is stored in TaskContext for per-task isolation.
    """
    ctx = get_task_context()
    ctx.allowed_tools = set(tools) if tools else None
    if tools:
        log(f"[Tool Bridge] Allowed tools set: {tools}")


def clear_allowed_tools() -> None:
    """Clear the allowed tools whitelist (allows all tools again)."""
    ctx = get_task_context()
    ctx.allowed_tools = None


def set_blocked_tools(tools: list) -> None:
    """
    Set the blacklist of blocked tools for the current task.
    Call this before get_ollama_tools() to block specific tools.

    Args:
        tools: List of tool names to block (e.g., ["delete_email", "graph_delete_email"])
               If None, no tools are blocked.

    Note:
        This is stored in TaskContext for per-task isolation.
    """
    ctx = get_task_context()
    ctx.blocked_tools = set(tools) if tools else None
    if tools:
        log(f"[Tool Bridge] Blocked tools set: {tools}")


def clear_blocked_tools() -> None:
    """Clear the blocked tools blacklist (no tools blocked)."""
    ctx = get_task_context()
    ctx.blocked_tools = None


def set_mcp_filter(mcp_filter: str) -> None:
    """
    Set the MCP filter for the current task.

    This enables parallel execution of multiple agents with different MCP filters
    without cache collision. The filter is stored per-task in TaskContext.

    Args:
        mcp_filter: Regex pattern to filter MCP servers (e.g., "outlook|gmail")
                    If None, all MCP servers are available.

    Note:
        This is stored in TaskContext for per-task isolation.
        Call this at the start of a task before using get_ollama_tools().
    """
    ctx = get_task_context()
    ctx.mcp_filter = mcp_filter
    if mcp_filter:
        log(f"[Tool Bridge] MCP filter set for task: {mcp_filter}")


def clear_mcp_filter() -> None:
    """Clear the MCP filter (allows all MCP servers)."""
    ctx = get_task_context()
    ctx.mcp_filter = None


def get_mcp_filter() -> str:
    """
    Get the current task's MCP filter.

    Returns:
        The MCP filter pattern or None if not set.
    """
    ctx = get_task_context()
    return ctx.mcp_filter


def set_dry_run_mode(enabled: bool) -> None:
    """
    Enable or disable dry-run mode.
    In dry-run mode, destructive operations are simulated instead of executed.

    Args:
        enabled: True to enable dry-run mode

    Note:
        This is stored in TaskContext for per-task isolation.
    """
    ctx = get_task_context()
    ctx.dry_run_mode = enabled
    if enabled:
        ctx.simulated_actions = []  # Reset simulated actions list
        log(f"[Tool Bridge] DRY-RUN mode enabled")
    else:
        ctx.simulated_actions = []


def set_test_folder(folder: str) -> None:
    """
    Set the test folder for redirecting read operations in test scenarios.

    Args:
        folder: Folder name in Outlook (e.g., "TestData")

    Note:
        This is stored in TaskContext for per-task isolation.
    """
    ctx = get_task_context()
    ctx.test_folder = folder
    if folder:
        log(f"[Tool Bridge] Test folder set: {folder}")


def get_simulated_actions() -> list:
    """
    Get the list of simulated actions from dry-run mode.

    Returns:
        List of dicts with {tool, args, simulated_result}
    """
    ctx = get_task_context()
    return ctx.simulated_actions.copy()


def clear_dry_run() -> None:
    """Reset dry-run mode and clear simulated actions."""
    ctx = get_task_context()
    ctx.dry_run_mode = False
    ctx.test_folder = None
    ctx.simulated_actions = []


def get_ollama_tools(mcp_filter: str = None, allowed_tools: list = None, blocked_tools: list = None, tool_mode: str = None) -> list:
    """
    Get all discovered tools in Ollama format.

    Args:
        mcp_filter: Optional regex pattern to filter MCP servers (e.g., "outlook|billomat")
        allowed_tools: Optional whitelist of tool names (overrides TaskContext.allowed_tools)
                       If set, only these tools are returned.
        blocked_tools: Optional blacklist of tool names (overrides TaskContext.blocked_tools)
                       If set, these tools are excluded.
        tool_mode: Optional security mode ("full", "read_only", "write_safe")
                   - "full": All tools allowed (default)
                   - "read_only": Only READ_ONLY_TOOLS allowed
                   - "write_safe": READ_ONLY_TOOLS + non-destructive write tools

    Returns:
        List of tool definitions for Ollama API
    """
    ctx = get_task_context()
    tools, _ = _discover_mcp_tools(mcp_filter)

    # Use passed allowed_tools or fall back to TaskContext setting
    effective_allowed = allowed_tools if allowed_tools is not None else ctx.allowed_tools

    # Use passed blocked_tools or fall back to TaskContext setting
    effective_blocked = blocked_tools if blocked_tools is not None else ctx.blocked_tools

    # Filter to only allowed tools (whitelist)
    # Supports both exact match ("filesystem_read_file") and suffix match ("read_file")
    if effective_allowed:
        original_count = len(tools)

        def matches_allowed(tool_name: str) -> bool:
            # Exact match
            if tool_name in effective_allowed:
                return True
            # Suffix match (e.g., "read_file" matches "filesystem_read_file")
            for allowed in effective_allowed:
                if tool_name.endswith(f"_{allowed}"):
                    return True
            return False

        tools = [t for t in tools if matches_allowed(t.get("function", {}).get("name", ""))]
        log(f"[Tool Bridge] Filtered to {len(tools)}/{original_count} allowed tools: {effective_allowed}")

    # Filter out blocked tools (blacklist)
    # Applied after whitelist, supports same matching logic
    if effective_blocked:
        original_count = len(tools)

        def matches_blocked(tool_name: str) -> bool:
            # Exact match
            if tool_name in effective_blocked:
                return True
            # Suffix match (e.g., "delete_email" matches "outlook_delete_email")
            for blocked in effective_blocked:
                if tool_name.endswith(f"_{blocked}"):
                    return True
            return False

        tools = [t for t in tools if not matches_blocked(t.get("function", {}).get("name", ""))]
        log(f"[Tool Bridge] Blocked {original_count - len(tools)} tools: {effective_blocked}")

    # === tool_mode enforcement ===
    # Filter tools based on security mode
    if tool_mode and tool_mode != "full":
        original_count = len(tools)
        read_only_tools = get_read_only_tools()
        destructive_tools = get_destructive_tools()

        if tool_mode == "read_only":
            # Only allow tools in READ_ONLY_TOOLS
            tools = [t for t in tools if t.get("function", {}).get("name", "") in read_only_tools]
            log(f"[Tool Bridge] tool_mode=read_only: Filtered to {len(tools)}/{original_count} read-only tools")

        elif tool_mode == "write_safe":
            # Allow READ_ONLY_TOOLS + tools that are NOT in DESTRUCTIVE_TOOLS
            def is_write_safe(tool_name: str) -> bool:
                # Always allow read-only tools
                if tool_name in read_only_tools:
                    return True
                # Block destructive tools (delete, remove, etc.)
                if tool_name in destructive_tools:
                    return False
                # Allow all other tools (write but not delete)
                return True

            tools = [t for t in tools if is_write_safe(t.get("function", {}).get("name", ""))]
            log(f"[Tool Bridge] tool_mode=write_safe: Filtered to {len(tools)}/{original_count} write-safe tools")

    return tools


def get_tool_function(name: str) -> Callable | None:
    """
    Get the actual Python function for a tool name.

    Args:
        name: Tool name

    Returns:
        Callable function or None if not found
    """
    # Use task-specific filter for parallel execution isolation
    mcp_filter = get_mcp_filter()
    _, function_map = _discover_mcp_tools(mcp_filter)
    return function_map.get(name)


def set_anonymization_context(context) -> None:
    """
    Set the anonymization context for de-anonymizing tool inputs.

    Args:
        context: AnonymizationContext from anonymizer module

    Note:
        This is stored in TaskContext for per-task isolation.
    """
    ctx = get_task_context()
    ctx.anon_context = context
    if context and hasattr(context, 'mappings'):
        log(f"[Tool Bridge] Anonymization context set ({len(context.mappings)} mappings)")


def clear_anonymization_context() -> None:
    """Clear the anonymization context."""
    ctx = get_task_context()
    ctx.anon_context = None


def _deanonymize_value(value: Any) -> Any:
    """De-anonymize a single value if it contains placeholders."""
    ctx = get_task_context()
    anon_context = ctx.anon_context

    if anon_context is None:
        return value

    if not hasattr(anon_context, 'mappings') or not anon_context.mappings:
        return value

    if isinstance(value, str):
        result = value
        for placeholder, original in anon_context.mappings.items():
            if placeholder in result:
                result = result.replace(placeholder, original)
        return result
    elif isinstance(value, list):
        return [_deanonymize_value(item) for item in value]
    elif isinstance(value, dict):
        return {k: _deanonymize_value(v) for k, v in value.items()}
    else:
        return value


def _deanonymize_arguments(arguments: dict) -> dict:
    """De-anonymize all string values in arguments dict."""
    ctx = get_task_context()
    if ctx.anon_context is None:
        return arguments

    result = {}
    for key, value in arguments.items():
        result[key] = _deanonymize_value(value)

    # Log if any changes were made
    if result != arguments:
        log(f"[Tool Bridge] De-anonymized arguments")

    return result


def execute_tool(name: str, arguments: dict, skip_logging: bool = False, config: dict = None) -> str:
    """
    Execute a tool by name with given arguments.

    In dry-run mode, destructive operations are simulated and logged
    instead of being executed.

    In demo mode, mock responses are returned from mocks/*.json files
    instead of executing the real tool.

    Args:
        name: Tool name
        arguments: Dictionary of arguments
        skip_logging: If True, skip logging to anon_messages.log (for background tasks like watchers)
        config: Optional config dict for demo mode check

    Returns:
        Tool result as string
    """
    from .event_publishing import publish_tool_event
    import time
    import json

    # Get task context for dry-run mode and other per-task state
    ctx = get_task_context()

    # Check for demo mode first - return mock responses
    # Load config if not provided
    if config is None:
        try:
            from paths import load_config
            config = load_config()
        except ImportError:
            try:
                from paths import load_config
                config = load_config()
            except ImportError:
                config = {}

    if is_demo_mode_enabled(config):
        log(f"[Tool Bridge] DEMO MODE: Intercepting {name}")

        # Get mock response for this tool (fallback="error" ensures unmocked tools don't execute)
        mock_response = get_mock_response(name, arguments, config=config, fallback="error")

        # Apply simulated delay if configured
        apply_mock_delay(name, config=config)

        # Publish tool events for UI
        publish_tool_event(name, "executing")
        time.sleep(0.1)  # Small delay for realistic feel
        publish_tool_event(name, "complete", 0.1)

        log(f"[Tool Bridge] DEMO MODE: Returning mock response ({len(mock_response)} chars)")
        return mock_response  # Always return mock (or error message if no mock defined)

    # Check for dry-run mode and destructive tools
    # _destructive_tools is global (shared discovery data, not per-task)
    global _destructive_tools

    if ctx.dry_run_mode and name in _destructive_tools:
        # Simulate the operation instead of executing
        log(f"[Tool Bridge] DRY-RUN: Simulating {name}")

        # De-anonymize arguments for logging (but not execution)
        deanon_args = _deanonymize_arguments(arguments)

        # Create simulated result
        simulated_result = {
            "success": True,
            "simulated": True,
            "action": name,
            "args": deanon_args,
            "message": f"[DRY-RUN] Would execute: {name}"
        }

        # Add to simulated actions list (per-task)
        ctx.simulated_actions.append({
            "tool": name,
            "args": deanon_args,
            "simulated_result": simulated_result
        })

        # Publish tool event for UI tracking
        publish_tool_event(name, "executing")
        publish_tool_event(name, "complete", 0.0)

        # Return a descriptive result for the AI
        result_str = json.dumps(simulated_result, ensure_ascii=False, indent=2)
        log(f"[Tool Bridge] DRY-RUN result: {result_str[:200]}...")
        return result_str

    # Check filesystem write restrictions (per-agent whitelist)
    # This enforces agent-level restrictions on file writes
    if fs_error := _check_filesystem_write_allowed(name, arguments):
        log(f"[Tool Bridge] Filesystem restriction blocked: {name}")
        return fs_error

    func = get_tool_function(name)

    # Get task-specific MCP filter
    mcp_filter = get_mcp_filter()
    cache_key = mcp_filter or ""

    if not func:
        # Tool not found - try invalidating cache and reloading modules
        log(f"[Tool Bridge] Tool '{name}' not in cache, invalidating and reloading...")
        # Invalidate cache for current filter only (thread-safe)
        with _cache_lock:
            if cache_key in _cache_by_filter:
                del _cache_by_filter[cache_key]

        # Also clear _mcp_api cache so MCPs reload fresh config
        try:
            import _mcp_api
            _mcp_api.clear_cache()
            log("[Tool Bridge] Cleared _mcp_api cache for reload")
        except ImportError:
            pass

        # Retry after cache clear
        func = get_tool_function(name)

        if not func:
            # Still not found - try auto-correction for Gemini's shortened names
            _, function_map = _discover_mcp_tools(mcp_filter)
            available = list(function_map.keys())

            # Auto-correct: Check if requested name is a suffix of an actual tool
            # e.g., "msgraph_get_email" -> "msgraph_graph_get_email"
            corrected = None
            name_parts = name.split('_', 1)  # ["msgraph", "get_email"]
            if len(name_parts) == 2:
                prefix, suffix = name_parts
                for tool_name in available:
                    if tool_name.startswith(prefix + '_') and tool_name.endswith('_' + suffix):
                        corrected = tool_name
                        break

            # Auto-correct: Unprefixed tool names only
            # e.g., "create_reply_draft" -> "gmail_create_reply_draft" (if gmail in filter)
            # IMPORTANT: Do NOT correct if tool has a known provider prefix - that would
            # cause gmail_xxx to be redirected to outlook_xxx when Gmail is not in filter!
            if not corrected:
                # Check if tool has a known provider prefix
                tool_action = name
                original_provider = None
                known_providers = ['outlook', 'gmail', 'msgraph', 'graph']
                for prov in known_providers:
                    if name.startswith(prov + '_'):
                        original_provider = prov
                        tool_action = name[len(prov) + 1:]  # Remove prefix
                        break

                # Only auto-correct if:
                # 1. Tool has NO provider prefix (unprefixed tool), OR
                # 2. Tool has provider prefix AND that provider is in current filter
                should_autocorrect = (original_provider is None)
                if original_provider and mcp_filter:
                    # Check if original provider is in the filter
                    import re
                    filter_pattern = f"^({mcp_filter})$"
                    should_autocorrect = bool(re.match(filter_pattern, original_provider))

                if should_autocorrect:
                    # Search for this action in available tools
                    for tool_name in available:
                        if tool_name.endswith('_' + tool_action):
                            corrected = tool_name
                            log(f"[Tool Bridge] Auto-corrected unprefixed '{name}' -> '{corrected}'")
                            break
                else:
                    # Provider-specific tool not in filter - don't redirect to different provider!
                    log(f"[Tool Bridge] Tool '{name}' has provider '{original_provider}' not in filter '{mcp_filter}' - NOT auto-correcting to different provider")

            if corrected:
                log(f"[Tool Bridge] Auto-corrected '{name}' -> '{corrected}'")
                func = function_map.get(corrected)

            if not func:
                log(f"[Tool Bridge] ERROR: Tool '{name}' not found after reload!")
                log(f"[Tool Bridge] Current MCP filter: {mcp_filter}")
                log(f"[Tool Bridge] Available tools ({len(available)}): {available[:20]}{'...' if len(available) > 20 else ''}")

                # Check for similar names (typo detection)
                similar = [t for t in available if name.split('_')[-1] in t or t.split('_')[-1] in name]
                if similar:
                    log(f"[Tool Bridge] Similar tools found: {similar}")

                return f"Error: Unknown tool '{name}'"

    try:
        # Log tool call BEFORE de-anonymization (shows what AI sent - with placeholders)
        # Skip logging for background tasks (watchers) to prevent log bloat
        if not skip_logging:
            args_str = json.dumps(arguments, ensure_ascii=False, default=str)
            log_tool_call(name, "CALL", args_str)

        # De-anonymize arguments before execution
        deanon_args = _deanonymize_arguments(arguments)

        # Publish tool start event
        publish_tool_event(name, "executing")

        log(f"[Tool Bridge] Executing: {name}({deanon_args})")
        start_time = time.time()

        # Handle async functions (e.g., browser tools using Playwright)
        if asyncio.iscoroutinefunction(func):
            log(f"[Tool Bridge] Running async function: {name}")
            # Check if we're already in an async context
            try:
                loop = asyncio.get_running_loop()
                # Already in async context - use nest_asyncio or run in thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, func(**deanon_args))
                    result = future.result(timeout=120)  # 2 min timeout
            except RuntimeError:
                # No running loop - safe to use asyncio.run()
                result = asyncio.run(func(**deanon_args))
        else:
            result = func(**deanon_args)

        duration = time.time() - start_time

        # Publish tool complete event
        publish_tool_event(name, "complete", duration)

        result_str = str(result) if result is not None else ""
        # NOTE: RESULT logging happens in backend AFTER anonymization
        log(f"[Tool Bridge] Result: {result_str[:200]}...")
        return result_str
    except Exception as e:
        log(f"[Tool Bridge] Error executing {name}: {e}")
        # Publish tool complete even on error
        publish_tool_event(name, "complete")
        error_msg = f"Error executing {name}: {str(e)}"
        return error_msg


def list_tools() -> list[str]:
    """
    List all available tool names.

    Returns:
        List of tool names
    """
    # Use task-specific filter for parallel execution isolation
    mcp_filter = get_mcp_filter()
    _, function_map = _discover_mcp_tools(mcp_filter)
    return list(function_map.keys())



def clear_cache():
    """Clear the tool cache to force re-discovery."""
    global _cache_by_filter, _destructive_tools, _read_only_tools
    with _cache_lock:
        _cache_by_filter = {}
    _destructive_tools = set()
    _read_only_tools = set()
    log("[Tool Bridge] Cache cleared")


def get_destructive_tools() -> set:
    """
    Get the set of destructive tool names (dynamically collected from MCPs).

    Returns:
        Set of prefixed tool names that are destructive (simulated in dry-run mode)
    """
    return _destructive_tools.copy()


def get_read_only_tools() -> set:
    """
    Get the set of read-only tool names (dynamically collected from MCPs).

    Returns:
        Set of prefixed tool names that only read data without modifications.
        Used by tool_mode: "read_only" for safe operation enforcement.
    """
    return _read_only_tools.copy()


def warmup_mcp_tools(mcp_filter: str = None):
    """Pre-load MCP tools at startup to reduce first-click latency.

    Supports selective warmup: only loads configured/filtered MCPs instead
    of all 25+ modules. This reduces startup from ~280s to ~60s.

    If mcp_filter is None, automatically determines configured MCPs via
    schema-based config check (no MCP import needed).

    Args:
        mcp_filter: Optional regex pattern to filter MCPs (e.g., "outlook|billomat").
                    If None, loads only configured MCPs.
    """
    import time as _time
    start = _time.time()

    try:
        # If no explicit filter, determine configured MCPs from schema
        effective_filter = mcp_filter
        if effective_filter is None:
            effective_filter = _get_configured_mcp_filter()

        if effective_filter:
            log(f"[Tool Bridge] Warming up configured MCPs: {effective_filter}")
        else:
            log("[Tool Bridge] Warming up ALL MCP tools (no config filter)...")

        tools, _ = _discover_mcp_tools(effective_filter)
        elapsed = _time.time() - start
        log(f"[Tool Bridge] Warmup complete: {len(tools)} tools loaded in {elapsed:.1f}s")
    except Exception as e:
        log(f"[Tool Bridge] Warmup error: {e}")


def _get_configured_mcp_filter() -> str | None:
    """Determine which MCPs are configured and return as filter pattern.

    Uses schema-based config check (no MCP import needed) to build a
    regex pattern of configured MCP names.

    Returns:
        Regex pattern like "outlook|billomat|filesystem|clipboard" or None if
        schema check fails (fallback to loading all).
    """
    try:
        from assistant.services.integration_schema import get_all_integration_schemas, check_mcp_configured_from_schema
        from assistant.services.mcp_hints import needs_configuration

        schemas = get_all_integration_schemas()

        if not schemas:
            log("[Tool Bridge] No schemas loaded, loading all MCPs")
            return None

        configured = []

        for mcp_name, schema in schemas.items():
            # MCPs without config requirement are always available
            if not needs_configuration(mcp_name):
                configured.append(mcp_name)
                continue

            # Special case: Outlook needs COM check, not schema check
            if mcp_name == "outlook":
                try:
                    import win32com.client
                    from config import load_config
                    config = load_config()
                    if config.get("outlook", {}).get("enabled") is not False:
                        outlook = win32com.client.Dispatch("Outlook.Application")
                        if outlook:
                            configured.append(mcp_name)
                except Exception:
                    pass
                continue

            # Schema-based check (no MCP import needed)
            try:
                if check_mcp_configured_from_schema(mcp_name):
                    configured.append(mcp_name)
            except Exception:
                pass

        if configured:
            pattern = "|".join(sorted(configured))
            log(f"[Tool Bridge] Configured MCPs ({len(configured)}): {pattern}")
            return pattern
        else:
            log("[Tool Bridge] No configured MCPs found, loading all")
            return None

    except Exception as e:
        log(f"[Tool Bridge] Config filter error: {e}, loading all MCPs")
        return None


# =============================================================================
# In-Process SDK MCP Server Support (planfeature-018)
# =============================================================================

def get_sdk_mcp_tools(
    mcp_filter: str = None,
    allowed_tools: list = None,
    blocked_tools: list = None,
    tool_mode: str = None,
    use_anonymization: bool = False,
    session_id: str = None,
    config: dict = None,
) -> list:
    """
    Get tools converted to Claude Agent SDK format for in-process MCP server.

    Uses the same filtering logic as get_ollama_tools() to ensure identical
    behavior between in-process and proxy-based transports.

    Args:
        mcp_filter: Regex pattern to filter MCP servers (e.g., "outlook|billomat")
        allowed_tools: Tool name whitelist (Layer 2)
        blocked_tools: Tool name blacklist (Layer 3)
        tool_mode: Security mode - "full", "read_only", "write_safe" (Layer 4)
        use_anonymization: Whether to wrap tools with anonymization
        session_id: Session ID for anonymization context
        config: Optional global config dict for anonymization settings

    Returns:
        List of SdkMcpTool instances for use with create_sdk_mcp_server()
    """
    from claude_agent_sdk import tool as sdk_tool

    # Get filtered tools using existing logic (respects Layer 1-4)
    ollama_tools = get_ollama_tools(
        mcp_filter=mcp_filter,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        tool_mode=tool_mode
    )

    # Get function map for creating handlers
    _, function_map = _discover_mcp_tools(mcp_filter)

    sdk_tools = []

    for tool_def in ollama_tools:
        func_def = tool_def.get("function", {})
        tool_name = func_def.get("name", "")
        description = func_def.get("description", "")
        parameters = func_def.get("parameters", {})

        # Get the actual function
        func = function_map.get(tool_name)
        if func is None:
            log(f"[Tool Bridge] Warning: No function for {tool_name}")
            continue

        # Convert JSON Schema parameters to SDK input_schema format
        # SDK accepts: dict mapping param names to types, or JSON Schema dict
        input_schema = _convert_params_to_sdk_schema(parameters)

        # Create the tool handler
        handler = _create_sdk_tool_handler(
            func,
            tool_name,
            use_anonymization=use_anonymization,
            session_id=session_id,
            config=config
        )

        # Use SDK's @tool decorator to create SdkMcpTool
        sdk_mcp_tool = sdk_tool(tool_name, description, input_schema)(handler)
        sdk_tools.append(sdk_mcp_tool)

    log(f"[Tool Bridge] Created {len(sdk_tools)} SDK MCP tools")
    return sdk_tools


def _is_complex_param(param_def: dict) -> bool:
    """Check if a parameter definition has complex/nested types.

    Complex types require full JSON Schema to be passed to the SDK
    instead of simplified Python type mapping.

    Args:
        param_def: JSON Schema parameter definition

    Returns:
        True if the parameter has nested structure (array of objects,
        array of arrays, object with properties)
    """
    json_type = param_def.get("type", "string")
    # Array with object or array items
    if json_type == "array":
        items = param_def.get("items", {})
        item_type = items.get("type") if isinstance(items, dict) else None
        if item_type == "object" or item_type == "array":
            return True
    # Object with properties
    if json_type == "object" and "properties" in param_def:
        return True
    return False


def _convert_params_to_sdk_schema(json_schema_params: dict) -> dict:
    """
    Convert JSON Schema parameters to SDK input_schema format.

    The SDK accepts either:
    - A dict mapping parameter names to Python types: {"name": str}
    - A full JSON Schema dict (passed through)

    For tools with complex parameter types (array of objects, nested arrays),
    the full JSON Schema is passed through so the SDK can generate correct
    tool calls with proper inner structure.

    Args:
        json_schema_params: JSON Schema parameters from Ollama tool format

    Returns:
        Dict suitable for SDK's tool() decorator
    """
    properties = json_schema_params.get("properties", {})

    if not properties:
        return {}

    # Check if any parameter has complex types (nested objects, arrays of objects)
    has_complex = any(
        _is_complex_param(param_def)
        for param_def in properties.values()
    )

    if has_complex:
        # Pass through full JSON Schema for complex types
        return json_schema_params

    # Simplified type mapping for simple cases
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    result = {}
    for param_name, param_def in properties.items():
        json_type = param_def.get("type", "string")
        python_type = type_map.get(json_type, str)
        result[param_name] = python_type

    return result


def _create_sdk_tool_handler(
    func: Callable,
    tool_name: str,
    use_anonymization: bool = False,
    session_id: str = None,
    config: dict = None
) -> Callable:
    """
    Create an async handler for SDK MCP tool that wraps the original function.

    Handles:
    - Sync to async conversion
    - De-anonymization of inputs
    - Anonymization of outputs (if enabled)
    - Error handling
    - Result formatting

    Args:
        func: The original MCP tool function
        tool_name: Tool name for logging
        use_anonymization: Whether to anonymize/deanonymize
        session_id: Session ID for anonymization
        config: Optional global config dict for anonymization settings

    Returns:
        Async handler function compatible with SDK tool() decorator
    """

    async def sdk_handler(args: dict) -> dict:
        """SDK-compatible async handler that wraps the MCP tool."""
        from .event_publishing import publish_tool_event
        import time as time_module

        try:
            # De-anonymize inputs if anonymization is active
            if use_anonymization and session_id:
                args = _deanonymize_sdk_args(args, session_id)

            # Publish tool start event
            publish_tool_event(tool_name, "executing")
            start_time = time_module.time()

            # Execute the tool
            if asyncio.iscoroutinefunction(func):
                result = await func(**args)
            else:
                # Run sync function in executor to avoid blocking
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: func(**args))

            duration = time_module.time() - start_time
            publish_tool_event(tool_name, "complete", duration)

            # Convert result to string
            result_str = str(result) if result is not None else ""

            # Anonymize output if enabled
            if use_anonymization and session_id:
                result_str = _anonymize_sdk_result(result_str, tool_name, session_id, config)

            log(f"[Tool Bridge SDK] {tool_name} completed in {duration:.2f}s")

            # Return in SDK expected format
            return {
                "content": [{"type": "text", "text": result_str}]
            }

        except Exception as e:
            log(f"[Tool Bridge SDK] Error in {tool_name}: {e}")
            publish_tool_event(tool_name, "complete")
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "is_error": True
            }

    return sdk_handler


def _apply_deanon_mappings(args: dict, mappings: dict) -> dict:
    """Apply de-anonymization mappings to tool arguments.

    Recursively replaces placeholders in strings, lists, and nested dicts.

    Args:
        args: Tool arguments with potential placeholders
        mappings: Dict of placeholder -> original value

    Returns:
        De-anonymized arguments
    """
    def deanonymize_value(value):
        if isinstance(value, str):
            result = value
            for placeholder, original in mappings.items():
                if placeholder in result:
                    result = result.replace(placeholder, original)
            return result
        elif isinstance(value, list):
            return [deanonymize_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: deanonymize_value(v) for k, v in value.items()}
        return value

    return {k: deanonymize_value(v) for k, v in args.items()}


def _deanonymize_sdk_args(args: dict, session_id: str) -> dict:
    """
    De-anonymize arguments using session-specific mappings.

    Checks in-memory cache first (fast, INPROCESS path), then falls back
    to file-based mappings (HTTP-Proxy backward compat).

    Args:
        args: Tool arguments with potential placeholders
        session_id: Session ID to load mappings for

    Returns:
        De-anonymized arguments
    """
    try:
        # 1. In-memory cache (fast, always current - INPROCESS path)
        if session_id in _sdk_anon_contexts:
            ctx = _sdk_anon_contexts[session_id]
            if ctx.mappings:
                return _apply_deanon_mappings(args, ctx.mappings)

        # 2. File fallback (HTTP-Proxy backward compat)
        from paths import get_logs_dir
        temp_dir = get_logs_dir().parent / ".temp"
        mappings_file = temp_dir / f"anon_mappings_{session_id}.json"

        if not mappings_file.exists():
            # Try init file
            mappings_file = temp_dir / f"anon_init_{session_id}.json"

        if mappings_file.exists():
            import json
            mappings = json.loads(mappings_file.read_text(encoding='utf-8'))
            return _apply_deanon_mappings(args, mappings)

    except Exception as e:
        log(f"[Tool Bridge SDK] De-anonymization error: {e}")

    return args


def _anonymize_sdk_result(result: str, tool_name: str, session_id: str, config: dict = None) -> str:
    """Anonymize tool result if it contains HIGH_RISK content.

    Uses anonymize_with_context() for session-consistent placeholders.
    Appends <!--ANON:...--> metadata for SDK to parse.

    Args:
        result: Tool result string
        tool_name: Tool name to check against HIGH_RISK_TOOLS
        session_id: Session ID for context
        config: Optional global config dict for anonymization settings
                (pii_types, language, whitelist from system.json)

    Returns:
        Anonymized result with ANON metadata, or original if not high-risk
    """
    try:
        from .anonymizer import anonymize_with_context, is_available

        if not is_available():
            return result

        # Check if this tool reads external content
        # HIGH_RISK_TOOLS are defined per-MCP module
        is_high_risk = any(action in tool_name for action in [
            "_get_", "_read_", "_search_", "_list_"
        ])

        if not is_high_risk:
            return result

        if not config:
            from paths import load_config
            config = load_config()

        ctx = _get_sdk_anon_context(session_id)

        # Track count before for "new" calculation
        prev_count = len(ctx.mappings)

        # Anonymize with session context for consistent placeholders
        anonymized, ctx = anonymize_with_context(result, config, ctx)

        # Update cache with potentially updated context
        _sdk_anon_contexts[session_id] = ctx

        new_count = len(ctx.mappings) - prev_count
        total = len(ctx.mappings)

        if total > 0:
            # Build entity summary (PERSON:5,EMAIL:3,...)
            entity_counts: dict[str, int] = {}
            for placeholder in ctx.mappings.keys():
                match = re.match(r'<([A-Z_]+)_\d+>', placeholder)
                if match:
                    etype = match.group(1)
                    entity_counts[etype] = entity_counts.get(etype, 0) + 1
            entity_summary = ",".join(f"{k}:{v}" for k, v in entity_counts.items())

            # Encode mappings as base64 for SDK parsing
            import base64
            mappings_b64 = base64.b64encode(
                json.dumps(ctx.mappings, ensure_ascii=False).encode()
            ).decode()

            # Append ANON metadata for parse_anon_metadata() in claude_agent_sdk.py
            anonymized += f"\n<!--ANON:{total}|{new_count}|{entity_summary}|{mappings_b64}-->"

            # Write mappings file for de-anonymization of tool inputs
            from paths import get_logs_dir
            temp_dir = get_logs_dir().parent / ".temp"
            temp_dir.mkdir(exist_ok=True)
            mappings_file = temp_dir / f"anon_mappings_{session_id}.json"
            mappings_file.write_text(
                json.dumps(ctx.mappings, ensure_ascii=False),
                encoding='utf-8'
            )

            if new_count > 0:
                log(f"[Tool Bridge SDK] Anonymized {tool_name}: {new_count} new, {total} total entities")

        return anonymized

    except Exception as e:
        log(f"[Tool Bridge SDK] Anonymization error: {e}")
        import traceback
        log(f"[Tool Bridge SDK] Traceback: {traceback.format_exc()}")

    return result
