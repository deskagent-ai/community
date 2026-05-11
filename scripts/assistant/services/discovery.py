# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Discovery service for agents and skills.

Scans agent and skill directories, parses frontmatter, and provides
unified configuration by merging with agents.json.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.sse_manager import broadcast_global_event

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR, DESKAGENT_DIR

# Centralized parsing utilities
try:
    from utils.parsing import parse_frontmatter
except ImportError:
    # Fallback for standalone execution
    import re
    def parse_frontmatter(content: str) -> tuple[dict, str]:
        pattern = r'^---\s*\n(.*?)\n---\s*\n?(.*)$'
        match = re.match(pattern, content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1)), match.group(2)
            except json.JSONDecodeError:
                pass
        return {}, content

# Cache for discovered items
_cache = {
    "agents": None,
    "skills": None,
    "categories": None,
    "agent_configs": {},  # name -> merged config
    "skill_configs": {},  # name -> merged config
    "file_mtimes": {},    # file_path -> mtime for cache invalidation
}
_cache_lock = threading.RLock()  # Thread-safe cache access (reentrant for nested calls)


def clear_cache(broadcast: bool = True):
    """Clear all cached discovery data.

    Args:
        broadcast: If True, broadcast agents_changed event to all clients.
    """
    with _cache_lock:
        _cache["agents"] = None
        _cache["skills"] = None
        _cache["categories"] = None
        _cache["agent_configs"].clear()
        _cache["skill_configs"].clear()
        _cache["file_mtimes"].clear()

    if broadcast:
        # Notify all clients (Quick Access, other windows) to reload
        broadcast_global_event("agents_changed", {})


def _is_cache_valid(file_path: str) -> bool:
    """Check if cached config is still valid (file not modified)."""
    if not file_path:
        return True
    try:
        current_mtime = Path(file_path).stat().st_mtime
        with _cache_lock:
            cached_mtime = _cache["file_mtimes"].get(file_path)
        return cached_mtime is not None and cached_mtime == current_mtime
    except (OSError, IOError):
        return False


def _update_mtime(file_path: str):
    """Update cached mtime for a file."""
    if file_path:
        try:
            mtime = Path(file_path).stat().st_mtime
            with _cache_lock:
                _cache["file_mtimes"][file_path] = mtime
        except (OSError, IOError):
            pass


def _is_file_new(file_path: str) -> bool:
    """Check if a file was created/modified today.

    Args:
        file_path: Path to the file to check

    Returns:
        True if file was modified today, False otherwise
    """
    if not file_path:
        return False
    try:
        file_mtime = Path(file_path).stat().st_mtime
        file_date = datetime.fromtimestamp(file_mtime).date()
        today = datetime.now().date()
        return file_date == today
    except (OSError, IOError):
        return False


def load_categories() -> dict:
    """Load categories from categories.json files.

    Merge order (later wins):
    1. deskagent/config/categories.json (system default)
    2. config/categories.json (user override)

    Returns:
        Dict of category_id -> {label, icon, order}
    """
    with _cache_lock:
        if _cache["categories"] is not None:
            return _cache["categories"]

    categories = {}

    # Load system default
    system_path = DESKAGENT_DIR / "config" / "categories.json"
    if system_path.exists():
        try:
            categories = json.loads(system_path.read_text(encoding="utf-8"))
            # Remove _comment field if present
            categories.pop("_comment", None)
        except (json.JSONDecodeError, IOError):
            pass

    # Load user override
    user_path = PROJECT_DIR / "config" / "categories.json"
    if user_path.exists():
        try:
            user_cats = json.loads(user_path.read_text(encoding="utf-8"))
            user_cats.pop("_comment", None)
            # Merge: user overrides system
            for cat_id, cat_data in user_cats.items():
                if cat_id in categories:
                    categories[cat_id].update(cat_data)
                else:
                    categories[cat_id] = cat_data
        except (json.JSONDecodeError, IOError):
            pass

    with _cache_lock:
        _cache["categories"] = categories
    return categories


def _scan_md_files(directories: list[Path]) -> dict:
    """Scan directories for .md files and parse frontmatter.

    Args:
        directories: List of directories to scan (in priority order, first wins)

    Returns:
        Dict of name -> {frontmatter, file_path}
    """
    items = {}

    # Scan in reverse order so first directory wins
    for directory in reversed(directories):
        if not directory.exists():
            continue

        for md_file in directory.glob("*.md"):
            name = md_file.stem
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)
                items[name] = {
                    "frontmatter": frontmatter,
                    "file_path": str(md_file),
                }
            except IOError:
                continue

    return items


def discover_agents() -> dict:
    """Discover all agents from agents/ directories and plugins.

    Scan order (first wins for same name):
    1. PROJECT_DIR/agents/
    2. DESKAGENT_DIR/agents/
    3. plugins/*/agents/ (prefixed with plugin_name:)

    Returns:
        Dict of agent_name -> {frontmatter, file_path}
    """
    with _cache_lock:
        if _cache["agents"] is not None:
            return _cache["agents"]

    directories = [
        PROJECT_DIR / "agents",
        DESKAGENT_DIR / "agents",
    ]

    agents = _scan_md_files(directories)

    # Add plugin agents with prefix
    try:
        from .plugins import get_plugin_agents
        for plugin_name, plugin_agents in get_plugin_agents().items():
            for agent_name, agent_data in plugin_agents.items():
                prefixed_name = f"{plugin_name}:{agent_name}"
                if prefixed_name not in agents:  # Don't override user/system
                    agents[prefixed_name] = agent_data
    except ImportError:
        pass  # Plugin system not available

    with _cache_lock:
        _cache["agents"] = agents
        return _cache["agents"]


def discover_skills() -> dict:
    """Discover all skills from skills/ directories and plugins.

    Scan order (first wins for same name):
    1. PROJECT_DIR/skills/
    2. DESKAGENT_DIR/skills/
    3. plugins/*/skills/ (prefixed with plugin_name:)

    Returns:
        Dict of skill_name -> {frontmatter, file_path}
    """
    with _cache_lock:
        if _cache["skills"] is not None:
            return _cache["skills"]

    directories = [
        PROJECT_DIR / "skills",
        DESKAGENT_DIR / "skills",
    ]

    skills = _scan_md_files(directories)

    # Add plugin skills with prefix
    try:
        from .plugins import get_plugin_skills
        for plugin_name, plugin_skills in get_plugin_skills().items():
            for skill_name, skill_data in plugin_skills.items():
                prefixed_name = f"{plugin_name}:{skill_name}"
                if prefixed_name not in skills:  # Don't override user/system
                    skills[prefixed_name] = skill_data
    except ImportError:
        pass  # Plugin system not available

    with _cache_lock:
        _cache["skills"] = skills
        return _cache["skills"]


def _load_legacy_config() -> dict:
    """Load legacy agents.json configuration.

    Returns:
        Dict with 'agents' and 'skills' keys from agents.json
    """
    from config import load_config
    config = load_config()
    return {
        "agents": config.get("agents", {}),
        "skills": config.get("skills", {}),
    }


def _get_config_sources(name: str, item_type: str) -> list[str]:
    """Determine which config sources contribute to an agent/skill config.

    Args:
        name: Agent or skill name
        item_type: "agents" or "skills"

    Returns:
        List of source names that have config for this item
    """
    import json
    sources = []

    # Check deskagent/config/agents.json (system default)
    system_path = DESKAGENT_DIR / "config" / "agents.json"
    if system_path.exists():
        try:
            system_config = json.loads(system_path.read_text(encoding="utf-8"))
            if name in system_config.get(item_type, {}):
                sources.append("deskagent/config")
        except (json.JSONDecodeError, IOError):
            pass

    # Check config/agents.json (user override)
    user_path = PROJECT_DIR / "config" / "agents.json"
    if user_path.exists():
        try:
            user_config = json.loads(user_path.read_text(encoding="utf-8"))
            if name in user_config.get(item_type, {}):
                sources.append("config/")
        except (json.JSONDecodeError, IOError):
            pass

    return sources


def get_agent_config(agent_name: str) -> dict:
    """Get merged configuration for an agent.

    Merge priority (later wins):
    1. deskagent/config/agents.json (system default)
    2. config/agents.json (user override)
    3. Agent .md frontmatter (highest priority)

    Auto-invalidates cache if the agent file was modified.

    Args:
        agent_name: Name of the agent

    Returns:
        Merged configuration dict, or empty dict if not found
    """
    # Check if cached config is still valid (file not modified)
    with _cache_lock:
        if agent_name in _cache["agent_configs"]:
            cached_config = _cache["agent_configs"][agent_name]
            file_path = cached_config.get("_file_path")
            if _is_cache_valid(file_path):
                return cached_config
            # File was modified - invalidate this agent's cache
            del _cache["agent_configs"][agent_name]
            # Also clear discovered agents to re-scan frontmatter
            _cache["agents"] = None

    # Track config sources for debugging/UI
    sources = _get_config_sources(agent_name, "agents")

    # Start with legacy config from agents.json
    legacy = _load_legacy_config()
    config = legacy.get("agents", {}).get(agent_name, {}).copy()

    # Merge frontmatter (higher priority)
    agents = discover_agents()
    has_frontmatter = False
    if agent_name in agents:
        frontmatter = agents[agent_name]["frontmatter"]
        if frontmatter:  # Only count as source if frontmatter is not empty
            has_frontmatter = True
        config.update(frontmatter)
        file_path = agents[agent_name]["file_path"]
        config["_file_path"] = file_path
        config["_is_new"] = _is_file_new(file_path)
        # Track file mtime for cache invalidation
        _update_mtime(file_path)

    # Apply user config "hidden" field with highest priority (for UI toggle)
    # This allows users to hide/unhide agents via UI regardless of frontmatter setting
    import json
    user_agents_path = PROJECT_DIR / "config" / "agents.json"
    if user_agents_path.exists():
        try:
            user_config = json.loads(user_agents_path.read_text(encoding="utf-8"))
            if agent_name in user_config and "hidden" in user_config[agent_name]:
                config["hidden"] = user_config[agent_name]["hidden"]
        except (json.JSONDecodeError, IOError):
            pass

    # Add frontmatter to sources if it exists and has content
    if has_frontmatter:
        sources.append("Frontmatter")

    config["_config_sources"] = sources

    with _cache_lock:
        _cache["agent_configs"][agent_name] = config
    return config


def get_skill_config(skill_name: str) -> dict:
    """Get merged configuration for a skill.

    Merge priority (later wins):
    1. deskagent/config/agents.json skills section (system default)
    2. config/agents.json skills section (user override)
    3. Skill .md frontmatter (highest priority)

    Auto-invalidates cache if the skill file was modified.

    Args:
        skill_name: Name of the skill

    Returns:
        Merged configuration dict, or empty dict if not found
    """
    # Check if cached config is still valid (file not modified)
    with _cache_lock:
        if skill_name in _cache["skill_configs"]:
            cached_config = _cache["skill_configs"][skill_name]
            file_path = cached_config.get("_file_path")
            if _is_cache_valid(file_path):
                return cached_config
            # File was modified - invalidate this skill's cache
            del _cache["skill_configs"][skill_name]
            # Also clear discovered skills to re-scan frontmatter
            _cache["skills"] = None

    # Track config sources for debugging/UI
    sources = _get_config_sources(skill_name, "skills")

    # Start with legacy config from agents.json
    legacy = _load_legacy_config()
    config = legacy.get("skills", {}).get(skill_name, {}).copy()

    # Merge frontmatter (higher priority)
    skills = discover_skills()
    has_frontmatter = False
    if skill_name in skills:
        frontmatter = skills[skill_name]["frontmatter"]
        if frontmatter:  # Only count as source if frontmatter is not empty
            has_frontmatter = True
        config.update(frontmatter)
        file_path = skills[skill_name]["file_path"]
        config["_file_path"] = file_path
        config["_is_new"] = _is_file_new(file_path)
        # Track file mtime for cache invalidation
        _update_mtime(file_path)

    # Add frontmatter to sources if it exists and has content
    if has_frontmatter:
        sources.append("Frontmatter")

    config["_config_sources"] = sources

    with _cache_lock:
        _cache["skill_configs"][skill_name] = config
    return config


def discover_all() -> dict:
    """Discover all agents, skills, and categories.

    Returns complete discovery result for UI and API.

    Returns:
        {
            "agents": {name: config, ...},
            "skills": {name: config, ...},
            "categories": {id: {label, icon, order}, ...}
        }
    """
    categories = load_categories()

    # Build agent configs
    agents = {}
    for name in discover_agents():
        agents[name] = get_agent_config(name)

    # Also include agents only in agents.json (legacy)
    legacy = _load_legacy_config()
    for name, config in legacy.get("agents", {}).items():
        if name not in agents:
            agents[name] = config.copy()

    # Build skill configs
    skills = {}
    for name in discover_skills():
        skills[name] = get_skill_config(name)

    # Also include skills only in agents.json (legacy)
    for name, config in legacy.get("skills", {}).items():
        if name not in skills:
            skills[name] = config.copy()

    return {
        "agents": agents,
        "skills": skills,
        "categories": categories,
    }


def get_all_agent_names() -> list[str]:
    """Get list of all agent names (from files and legacy config)."""
    names = set(discover_agents().keys())
    legacy = _load_legacy_config()
    names.update(legacy.get("agents", {}).keys())
    return sorted(names)


def get_all_skill_names() -> list[str]:
    """Get list of all skill names (from files and legacy config)."""
    names = set(discover_skills().keys())
    legacy = _load_legacy_config()
    names.update(legacy.get("skills", {}).keys())
    return sorted(names)


# =============================================================================
# Agent Prerequisites Check
# =============================================================================

def parse_mcp_pattern(allowed_mcp: str) -> list[str]:
    """Parst allowed_mcp Regex-Pattern zu Liste von MCP-Namen.

    Args:
        allowed_mcp: Regex-Pattern wie "outlook|billomat" oder ".*"

    Returns:
        Liste von MCP-Namen, leer bei Wildcard

    Examples:
        "outlook|billomat" → ["outlook", "billomat"]
        ".*" → []
        "" → []
    """
    if not allowed_mcp or allowed_mcp == ".*":
        return []  # Alle erlaubt = keine spezifischen Anforderungen

    # Einfaches Split bei | (Regex-Alternation)
    return [mcp.strip() for mcp in allowed_mcp.split("|") if mcp.strip()]


# Cache for MCP configuration checks (avoid repeated logging)
_mcp_config_cache = {}


def invalidate_mcp_config_cache(mcp_name: str = None):
    """Invalidiert den MCP-Konfigurations-Cache.

    Seit planfeature-042 wird nur noch _mcp_config_cache geleert.
    Der _mcp_api Cache ist nicht mehr nötig für Prerequisites-Checks
    (diese verwenden jetzt config.load_config() direkt).

    Sollte nach OAuth-Login oder Konfigurationsänderungen aufgerufen werden.

    Args:
        mcp_name: Spezifischer MCP-Name oder None für alle
    """
    global _mcp_config_cache
    if mcp_name:
        _mcp_config_cache.pop(mcp_name, None)
    else:
        _mcp_config_cache.clear()

    try:
        from ai_agent import system_log
        if mcp_name:
            system_log(f"[Prerequisites] Cache invalidated for '{mcp_name}'")
        else:
            system_log(f"[Prerequisites] Cache invalidated (all MCPs)")
    except ImportError:
        pass


def _check_plugin_mcp_configured(plugin_name: str) -> bool:
    """Prüft ob ein Plugin-MCP konfiguriert ist.

    Plugin-MCPs liegen unter plugins/{plugin_name}/mcp/__init__.py
    Da das Laden des Moduls Abhängigkeiten (FastMCP) erfordert die zur
    Startup-Zeit nicht verfügbar sind, prüfen wir die Konfiguration direkt.

    Die Konvention ist:
    - Plugin-Name == Config-Key (z.B. "sap" -> config["sap"])
    - Wenn config[plugin_name]["enabled"] == False -> nicht konfiguriert
    - Wenn config[plugin_name]["api_key"] oder ähnlich vorhanden -> konfiguriert

    Args:
        plugin_name: Name des Plugins (z.B. "sap", "myplugin")

    Returns:
        True wenn konfiguriert oder keine Konfiguration nötig
    """
    try:
        from ai_agent import system_log
    except ImportError:
        system_log = lambda msg: print(msg)

    try:
        from .plugins import get_plugin, get_plugins_dir
        from config import load_config

        # Resolve plugin content path (supports external_path)
        plugin_info = get_plugin(plugin_name)
        if plugin_info and not plugin_info.error:
            plugin_mcp_init = plugin_info.content_path / "mcp" / "__init__.py"
        else:
            plugins_dir = get_plugins_dir()
            plugin_mcp_init = plugins_dir / plugin_name / "mcp" / "__init__.py"

        if not plugin_mcp_init.exists():
            system_log(f"[Prerequisites] Plugin MCP '{plugin_name}' not found")
            return False

        # Konfiguration direkt prüfen (ohne Modul-Import)
        config = load_config()
        plugin_config = config.get(plugin_name, {})

        # Wenn explizit deaktiviert
        if plugin_config.get("enabled") is False:
            system_log(f"[Prerequisites] Plugin MCP '{plugin_name}' is disabled")
            return False

        # Prüfe ob API-Key oder Credentials vorhanden
        # Verschiedene Plugins nutzen verschiedene Felder
        has_api_key = bool(plugin_config.get("api_key"))
        has_username = bool(plugin_config.get("username"))
        has_base_url = bool(plugin_config.get("base_url"))

        # Für Plugins mit API-Key (z.B. SAP)
        if has_api_key:
            system_log(f"[Prerequisites] Plugin MCP '{plugin_name}' is configured (api_key)")
            return True

        # Fuer Plugins mit Credentials (Username + Base-URL Pattern)
        if has_username and has_base_url:
            system_log(f"[Prerequisites] Plugin MCP '{plugin_name}' is configured (credentials)")
            return True

        # Kein Konfigurationsfeld gefunden
        system_log(f"[Prerequisites] Plugin MCP '{plugin_name}' has no configuration")
        return False

    except Exception as e:
        try:
            from ai_agent import system_log
            system_log(f"[Prerequisites] Error checking plugin MCP '{plugin_name}': {e}")
        except ImportError:
            print(f"[Prerequisites] Error checking plugin MCP '{plugin_name}': {e}")
        return False


def is_mcp_configured(mcp_name: str) -> bool:
    """Prüft ob ein MCP konfiguriert ist.

    Verwendet deklarativen Schema-Check via INTEGRATION_SCHEMA.
    Fallback auf Legacy importlib-basiertes is_configured() für Plugin-MCPs
    oder wenn Schema-Check fehlschlägt.

    Args:
        mcp_name: Name des MCP-Servers (z.B. "billomat", "outlook")
                  oder Plugin-MCP im Format "plugin:mcp" (z.B. "sap:sap")

    Returns:
        True wenn konfiguriert oder keine Konfiguration nötig
    """
    global _mcp_config_cache

    # Return cached result if available
    if mcp_name in _mcp_config_cache:
        return _mcp_config_cache[mcp_name]

    from .mcp_hints import needs_configuration

    # Plugin-MCP? Behält Legacy-Approach
    if ":" in mcp_name:
        plugin_name = mcp_name.split(":", 1)[0]
        result = _check_plugin_mcp_configured(plugin_name)
        _mcp_config_cache[mcp_name] = result
        return result

    # MCPs ohne Konfigurationsbedarf sind immer verfügbar
    if not needs_configuration(mcp_name):
        _mcp_config_cache[mcp_name] = True
        return True

    # Outlook Sonderfall: COM-Check (System-Requirement, keine Config)
    if mcp_name == "outlook":
        result = _check_outlook_configured()
        _mcp_config_cache[mcp_name] = result
        return result

    # NEUER WEG: Deklarativer Schema-Check via INTEGRATION_SCHEMA
    try:
        from .integration_schema import check_mcp_configured_from_schema, get_schema_for_mcp
        from ai_agent import system_log

        result = check_mcp_configured_from_schema(mcp_name)
        system_log(f"[Prerequisites] MCP '{mcp_name}' schema-check = {result}")
        _mcp_config_cache[mcp_name] = result
        return result
    except Exception as e:
        # Fallback: Legacy importlib-Check
        try:
            from ai_agent import system_log
            system_log(f"[Prerequisites] Schema-check failed for '{mcp_name}': {e}, using legacy")
        except ImportError:
            pass
        return _legacy_is_mcp_configured(mcp_name)


def _check_outlook_configured() -> bool:
    """Prüft Outlook COM-Verfügbarkeit (System-Check, keine Config).

    Returns:
        True wenn Outlook COM verfügbar ist
    """
    try:
        from config import load_config
        config = load_config()
        if config.get("outlook", {}).get("enabled") is False:
            return False
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        return outlook is not None
    except Exception:
        return False


def _legacy_is_mcp_configured(mcp_name: str) -> bool:
    """Legacy: Lädt MCP-Modul via importlib für is_configured().

    Nur noch für Plugin-MCPs oder als Fallback wenn Schema-Check fehlschlägt.

    Args:
        mcp_name: Name des MCP-Servers

    Returns:
        True wenn konfiguriert oder keine Konfiguration nötig
    """
    global _mcp_config_cache
    import importlib.util
    import sys

    try:
        from ai_agent import system_log

        # MCP-Verzeichnis finden (System-MCPs)
        mcp_dir = DESKAGENT_DIR / "mcp" / mcp_name

        # Package-basierte MCPs (haben __init__.py)
        init_file = mcp_dir / "__init__.py"
        if init_file.exists():
            module_name = mcp_name

            # Add MCP parent directory to path for imports
            mcp_parent = str(DESKAGENT_DIR / "mcp")
            if mcp_parent not in sys.path:
                sys.path.insert(0, mcp_parent)

            # Modul laden (nur wenn nicht bereits geladen)
            if module_name not in sys.modules:
                spec = importlib.util.spec_from_file_location(module_name, init_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

            module = sys.modules.get(module_name)
            if module:
                is_configured_fn = getattr(module, 'is_configured', None)
                if is_configured_fn and callable(is_configured_fn):
                    result = is_configured_fn()
                    if mcp_name not in _mcp_config_cache:
                        system_log(f"[Prerequisites] MCP '{mcp_name}' legacy is_configured() = {result}")
                    _mcp_config_cache[mcp_name] = result
                    return result
                else:
                    if mcp_name not in _mcp_config_cache:
                        system_log(f"[Prerequisites] MCP '{mcp_name}' has no is_configured() function")
                    _mcp_config_cache[mcp_name] = True
                    return True

        # Fallback: Einzel-Datei MCPs (mcp_name.py)
        single_file = DESKAGENT_DIR / "mcp" / f"{mcp_name}_mcp.py"
        if single_file.exists():
            module_name = f"mcp_{mcp_name}_check"

            mcp_parent = str(DESKAGENT_DIR / "mcp")
            if mcp_parent not in sys.path:
                sys.path.insert(0, mcp_parent)

            spec = importlib.util.spec_from_file_location(module_name, single_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                is_configured_fn = getattr(module, 'is_configured', None)
                if is_configured_fn and callable(is_configured_fn):
                    result = is_configured_fn()
                    _mcp_config_cache[mcp_name] = result
                    return result

        _mcp_config_cache[mcp_name] = False
        return False

    except Exception as e:
        if mcp_name not in _mcp_config_cache:
            from ai_agent import system_log
            system_log(f"[Prerequisites] Legacy error checking MCP '{mcp_name}': {e}")
        _mcp_config_cache[mcp_name] = False
        return False


async def preload_prerequisites():
    """Lädt alle MCP-Konfigurationsstatus vor.

    Wird nach warmup_mcp_tools() im Background-Startup aufgerufen
    um den Cache zu füllen. So sind Prerequisites korrekt wenn
    die UI nach Startup-Complete refresht.
    """
    from .mcp_hints import get_mcp_names

    try:
        from ai_agent import system_log
    except ImportError:
        system_log = lambda msg: print(msg)

    mcp_names = get_mcp_names()
    checked_mcps = []

    for mcp_name in mcp_names:
        # is_mcp_configured() füllt den Cache
        result = is_mcp_configured(mcp_name)
        if result:
            checked_mcps.append(mcp_name)

    system_log(f"[Startup] Prerequisites preloaded for {len(mcp_names)} MCPs ({len(checked_mcps)} configured)")
    return checked_mcps


def check_agent_prerequisites(agent_config: dict, ai_backends: dict = None) -> dict:
    """Prüft ob Agent-Voraussetzungen erfüllt sind.

    Analysiert allowed_mcp, prüft MCP-Konfiguration und Backend-Verfügbarkeit.

    Args:
        agent_config: Agent-Konfiguration (aus get_agent_config)
        ai_backends: Dict der verfügbaren AI-Backends (optional)

    Returns:
        {
            "ready": bool,              # Alle Voraussetzungen erfüllt
            "missing_mcps": [...],      # Liste fehlender MCPs
            "missing_backend": str|None # Name des fehlenden Backends
            "warning": str | None       # Formatierte Warnung für UI
        }
    """
    from .mcp_hints import get_setup_message, needs_configuration

    missing_mcps = []
    missing_backend = None

    # 1. Check MCP requirements
    allowed_mcp = agent_config.get("allowed_mcp", "")
    if allowed_mcp and allowed_mcp != ".*":
        required_mcps = parse_mcp_pattern(allowed_mcp)
        for mcp_name in required_mcps:
            if not needs_configuration(mcp_name):
                continue
            if not is_mcp_configured(mcp_name):
                missing_mcps.append(mcp_name)

    # 2. Check AI Backend availability
    fallback_backend = None
    if ai_backends is not None:
        required_backend = agent_config.get("ai", "")
        if required_backend and required_backend not in ai_backends:
            # Required backend not available - check if ANY backend exists as fallback
            if ai_backends:
                # Use first available backend as fallback (don't block the agent)
                fallback_backend = next(iter(ai_backends.keys()))
            else:
                # No backends at all - this is a blocking issue
                missing_backend = required_backend

    # Build result - only block if NO backend available at all
    ready = len(missing_mcps) == 0 and missing_backend is None
    warning = get_setup_message(missing_mcps) if missing_mcps else None

    return {
        "ready": ready,
        "missing_mcps": missing_mcps,
        "missing_backend": missing_backend,
        "fallback_backend": fallback_backend,  # Backend that will be used instead
        "warning": warning
    }
