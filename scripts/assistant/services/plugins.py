# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Plugin Discovery Service
========================

Simple plugin system that discovers plugins from the plugins/ folder.
Plugins can contain agents, skills, knowledge, and MCP servers.

Each plugin is a folder with a plugin.json manifest:

    plugins/
    └── myplugin/
        ├── plugin.json      # Required manifest
        ├── agents/          # Optional agent .md files
        ├── skills/          # Optional skill .md files
        ├── knowledge/       # Optional knowledge .md files
        └── mcp/             # Optional MCP servers (packages)

External plugins: plugin.json can reference an external path where
the actual resources (agents, skills, mcp, knowledge) reside:

    plugins/
    └── myplugin/
        └── plugin.json      # Contains "external_path": "E:\\path\\to\\resources"

Resources are prefixed with plugin name: "myplugin:agent_name"
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR


def _log(msg: str):
    """Log to system.log (lazy import to avoid circular dependency)."""
    try:
        from ai_agent.base import system_log
        system_log(msg)
    except ImportError:
        print(msg)


@dataclass
class PluginInfo:
    """Information about a discovered plugin."""
    name: str
    version: str
    description: str
    author: str
    path: Path
    external_path: Optional[Path] = None
    has_agents: bool = False
    has_skills: bool = False
    has_mcp: bool = False
    has_knowledge: bool = False
    agent_count: int = 0
    skill_count: int = 0
    mcp_count: int = 0
    knowledge_count: int = 0
    error: Optional[str] = None

    def content_path_for(self, resource: str) -> Path:
        """Resolve path for a resource type (local first, external fallback).

        Args:
            resource: Subdirectory name (e.g. "agents", "mcp", "knowledge")
        """
        local = self.path / resource
        if local.exists():
            return local
        if self.external_path and (self.external_path / resource).exists():
            return self.external_path / resource
        return local

    @property
    def content_path(self) -> Path:
        """Root path for resources (external_path if set, else path)."""
        return self.external_path if self.external_path else self.path

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON/API."""
        result = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "path": str(self.path),
            "has_agents": self.has_agents,
            "has_skills": self.has_skills,
            "has_mcp": self.has_mcp,
            "has_knowledge": self.has_knowledge,
            "agent_count": self.agent_count,
            "skill_count": self.skill_count,
            "mcp_count": self.mcp_count,
            "knowledge_count": self.knowledge_count,
            "error": self.error
        }
        if self.external_path:
            result["external_path"] = str(self.external_path)
        return result


# Cache for discovered plugins
_plugin_cache: Optional[Dict[str, PluginInfo]] = None


def get_plugins_dir() -> Path:
    """
    Get the plugins directory path.

    Returns:
        Path to SHARED_DIR/plugins/ (created if doesn't exist)
    """
    plugins_dir = PROJECT_DIR / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    return plugins_dir


def clear_plugin_cache():
    """Clear the plugin discovery cache."""
    global _plugin_cache
    _plugin_cache = None
    _log("[Plugins] Cache cleared")


def discover_plugins(force_reload: bool = False) -> Dict[str, PluginInfo]:
    """
    Discover all plugins in the plugins/ folder.

    Scans plugins/ for folders containing a valid plugin.json manifest.
    Results are cached until clear_plugin_cache() is called.

    Args:
        force_reload: Bypass cache and rescan

    Returns:
        Dict of plugin_name -> PluginInfo
    """
    global _plugin_cache

    if _plugin_cache is not None and not force_reload:
        return _plugin_cache

    plugins_dir = get_plugins_dir()
    plugins: Dict[str, PluginInfo] = {}

    if not plugins_dir.exists():
        _log(f"[Plugins] Directory does not exist: {plugins_dir}")
        _plugin_cache = plugins
        return plugins

    # Scan for plugin folders
    for folder in sorted(plugins_dir.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name.startswith('.') or folder.name.startswith('_'):
            continue

        # Check for plugin.json
        manifest_path = folder / "plugin.json"
        if not manifest_path.exists():
            _log(f"[Plugins] Skipping {folder.name}: no plugin.json")
            continue

        # Parse manifest
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            _log(f"[Plugins] Error reading {folder.name}/plugin.json: {e}")
            plugins[folder.name] = PluginInfo(
                name=folder.name,
                version="?",
                description="",
                author="",
                path=folder,
                error=f"Invalid plugin.json: {e}"
            )
            continue

        # Get plugin info from manifest
        plugin_name = manifest.get("name", folder.name)

        # Resolve external_path if specified
        ext_path = None
        if "external_path" in manifest:
            ext_path = Path(manifest["external_path"])
            if not ext_path.is_absolute():
                ext_path = (folder / ext_path).resolve()
            if not ext_path.exists():
                _log(f"[Plugins] {plugin_name}: external_path does not exist: {ext_path}")
                plugins[plugin_name] = PluginInfo(
                    name=plugin_name, version=manifest.get("version", "?"),
                    description=manifest.get("description", ""),
                    author=manifest.get("author", ""), path=folder,
                    external_path=ext_path,
                    error=f"external_path not found: {ext_path}"
                )
                continue
            _log(f"[Plugins] {plugin_name}: using external_path {ext_path}")

        # Check for resources: local folder first, external_path as fallback
        def _resolve_dir(name: str) -> Path:
            local = folder / name
            if local.exists():
                return local
            if ext_path and (ext_path / name).exists():
                return ext_path / name
            return local  # return local (non-existing) for consistent count=0

        agents_dir = _resolve_dir("agents")
        skills_dir = _resolve_dir("skills")
        mcp_dir = _resolve_dir("mcp")
        knowledge_dir = _resolve_dir("knowledge")

        agent_count = len(list(agents_dir.glob("*.md"))) if agents_dir.exists() else 0
        skill_count = len(list(skills_dir.glob("*.md"))) if skills_dir.exists() else 0
        # Count MCPs: nested (mcp/name/__init__.py) + flat (mcp/__init__.py)
        if mcp_dir.exists():
            nested_count = len([d for d in mcp_dir.iterdir()
                                if d.is_dir() and not d.name.startswith('_')
                                and (d / "__init__.py").exists()])
            flat_count = 1 if (mcp_dir / "__init__.py").exists() else 0
            mcp_count = nested_count + flat_count
        else:
            mcp_count = 0
        knowledge_count = len(list(knowledge_dir.glob("**/*.md"))) if knowledge_dir.exists() else 0

        plugins[plugin_name] = PluginInfo(
            name=plugin_name,
            version=manifest.get("version", "0.0.0"),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            path=folder,
            external_path=ext_path,
            has_agents=agent_count > 0,
            has_skills=skill_count > 0,
            has_mcp=mcp_count > 0,
            has_knowledge=knowledge_count > 0,
            agent_count=agent_count,
            skill_count=skill_count,
            mcp_count=mcp_count,
            knowledge_count=knowledge_count
        )

        _log(f"[Plugins] Discovered: {plugin_name} v{plugins[plugin_name].version} "
             f"(agents:{agent_count}, skills:{skill_count}, mcp:{mcp_count}, knowledge:{knowledge_count})")

    _plugin_cache = plugins
    _log(f"[Plugins] Total discovered: {len(plugins)} plugins")
    return plugins


def get_plugin_agents() -> Dict[str, Dict[str, dict]]:
    """
    Get all agents from all plugins.

    Returns:
        Dict of plugin_name -> {agent_name -> {frontmatter, file_path}}
    """
    from .discovery import parse_frontmatter

    result: Dict[str, Dict[str, dict]] = {}

    for plugin_name, plugin in discover_plugins().items():
        if plugin.error or not plugin.has_agents:
            continue

        agents_dir = plugin.content_path_for("agents")
        if not agents_dir.exists():
            continue

        plugin_agents: Dict[str, dict] = {}
        for md_file in agents_dir.glob("*.md"):
            agent_name = md_file.stem
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                # Add plugin info to frontmatter
                frontmatter["_plugin"] = plugin_name
                frontmatter["_plugin_path"] = str(plugin.path)

                plugin_agents[agent_name] = {
                    "frontmatter": frontmatter,
                    "file_path": str(md_file)
                }
            except IOError as e:
                _log(f"[Plugins] Error reading agent {plugin_name}:{agent_name}: {e}")
                continue

        if plugin_agents:
            result[plugin_name] = plugin_agents

    return result


def get_plugin_skills() -> Dict[str, Dict[str, dict]]:
    """
    Get all skills from all plugins.

    Returns:
        Dict of plugin_name -> {skill_name -> {frontmatter, file_path}}
    """
    from .discovery import parse_frontmatter

    result: Dict[str, Dict[str, dict]] = {}

    for plugin_name, plugin in discover_plugins().items():
        if plugin.error or not plugin.has_skills:
            continue

        skills_dir = plugin.content_path_for("skills")
        if not skills_dir.exists():
            continue

        plugin_skills: Dict[str, dict] = {}
        for md_file in skills_dir.glob("*.md"):
            skill_name = md_file.stem
            try:
                content = md_file.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(content)

                # Add plugin info to frontmatter
                frontmatter["_plugin"] = plugin_name
                frontmatter["_plugin_path"] = str(plugin.path)

                plugin_skills[skill_name] = {
                    "frontmatter": frontmatter,
                    "file_path": str(md_file)
                }
            except IOError as e:
                _log(f"[Plugins] Error reading skill {plugin_name}:{skill_name}: {e}")
                continue

        if plugin_skills:
            result[plugin_name] = plugin_skills

    return result


def get_plugin_mcp_dirs() -> List[Tuple[str, Path]]:
    """
    Get MCP directories from all plugins.

    Returns:
        List of (plugin_name, mcp_dir_path) tuples for plugins with MCP servers
    """
    result: List[Tuple[str, Path]] = []

    for plugin_name, plugin in discover_plugins().items():
        if plugin.error or not plugin.has_mcp:
            continue

        mcp_dir = plugin.content_path_for("mcp")
        if mcp_dir.exists() and mcp_dir.is_dir():
            result.append((plugin_name, mcp_dir))

    return result


def get_plugin_knowledge_dirs() -> List[Tuple[str, Path]]:
    """
    Get knowledge directories from all plugins.

    Returns:
        List of (plugin_name, knowledge_dir_path) tuples for plugins with knowledge
    """
    result: List[Tuple[str, Path]] = []

    for plugin_name, plugin in discover_plugins().items():
        if plugin.error or not plugin.has_knowledge:
            continue

        knowledge_dir = plugin.content_path_for("knowledge")
        if knowledge_dir.exists() and knowledge_dir.is_dir():
            result.append((plugin_name, knowledge_dir))

    return result


def get_plugin(name: str) -> Optional[PluginInfo]:
    """
    Get info for a specific plugin.

    Args:
        name: Plugin name

    Returns:
        PluginInfo or None if not found
    """
    plugins = discover_plugins()
    return plugins.get(name)


def list_plugins() -> List[dict]:
    """
    List all plugins with their status.

    Returns:
        List of plugin info dicts
    """
    return [p.to_dict() for p in discover_plugins().values()]
