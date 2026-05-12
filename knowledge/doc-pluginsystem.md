# Plugin System

The plugin system allows extending DeskAgent with external packages from GitHub or local folders.

## Plugin Structure

Plugins are placed in the `plugins/` folder:

```
plugins/
└── myplugin/                    # Plugin folder (git clone or manual)
    ├── plugin.json              # Manifest (required)
    ├── requirements.txt         # Python dependencies (optional)
    ├── agents/                  # Agent .md files
    │   └── my_agent.md          # -> "myplugin:my_agent"
    ├── skills/                  # Skill .md files
    │   └── my_skill.md          # -> "myplugin:my_skill"
    ├── knowledge/               # Knowledge .md files
    │   └── docs.md              # -> "@myplugin:docs"
    └── mcp/                     # MCP server(s)
        └── __init__.py          # Flat layout -> "myplugin:myplugin"
```

**MCP layouts:** A plugin may ship MCP servers in either layout (or both):

| Layout | Path | Resulting MCP name |
|--------|------|--------------------|
| Flat (single MCP) | `<plugin>/mcp/__init__.py` | `myplugin:myplugin` |
| Nested (multiple MCPs) | `<plugin>/mcp/<name>/__init__.py` | `myplugin:<name>` |

Both are auto-discovered (see `plugins.py`, the discovery counts
`nested_count + flat_count`).

## plugin.json Manifest

Each plugin requires a `plugin.json` file:

```json
{
  "name": "myplugin",
  "version": "1.0.0",
  "description": "Plugin description",
  "author": "Author Name",
  "external_path": "E:\\path\\to\\plugin-resources"
}
```

**Optional fields:**

| Field | Purpose |
|-------|---------|
| `external_path` | Absolute path to an out-of-tree folder holding `agents/`, `skills/`, `mcp/`, `knowledge/`. Used when the plugin is installed via a stub `plugin.json` but the actual resources live elsewhere (e.g. a checked-out dev repo). Local subfolders in the plugin directory still take precedence; `external_path` acts as a fallback. If the path does not exist, the plugin is loaded with an error. |

## Namespace Prefix

All plugin resources automatically receive a prefix with the plugin name:

| Resource | Without plugin | With plugin |
|----------|----------------|-------------|
| Agent | `my_agent` | `myplugin:my_agent` |
| Skill | `my_skill` | `myplugin:my_skill` |
| MCP Server | `myservice` | `myplugin:myservice` |
| Knowledge | `@docs` | `@myplugin:docs` |

## Installation

### Manual (git clone)

```bash
cd plugins
git clone https://github.com/someone/deskagent-plugin-example myplugin
```

### Manual (Copy)

```bash
cp -r /path/to/plugin plugins/myplugin
```

After installation, restart DeskAgent - plugins are detected automatically.

## Use in Agents

### Call Plugin Agent

Plugin agents appear in the UI with prefix and can be executed normally:
- `myplugin:my_agent`

### Plugin MCP in allowed_mcp

```yaml
---
{
  "allowed_mcp": "myplugin:myservice|outlook|billomat"
}
---
```

### Load Plugin Knowledge

```yaml
---
{
  "knowledge": "@myplugin:docs|company"
}
---
```

## Creating a Plugin MCP Server

A plugin can ship a single MCP server in the flat layout, or multiple
MCP servers in the nested layout:

```
myplugin/
└── mcp/
    └── __init__.py          # Flat: one MCP, named like the plugin
```

```
myplugin/
└── mcp/
    ├── service_a/
    │   └── __init__.py      # Nested: myplugin:service_a
    └── service_b/
        └── __init__.py      # Nested: myplugin:service_b
```

**mcp/__init__.py structure:**

```python
#!/usr/bin/env python3
"""
MeinPlugin MCP Server
=====================
Beschreibung des MCP Servers.
"""
import os
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Config loader: DeskAgent paths.load_config()
_scripts_dir = os.environ.get("DESKAGENT_SCRIPTS_DIR")
if _scripts_dir:
    sys.path.insert(0, _scripts_dir)
    from paths import load_config
else:
    # Standalone fallback
    def load_config() -> dict:
        return {}

mcp = FastMCP("myplugin")  # Name = plugin name

# REQUIRED: WebUI icon/color
TOOL_METADATA = {
    "icon": "extension",
    "color": "#1976d2"
}

# Optional: Tools that read external data (prompt injection protection)
HIGH_RISK_TOOLS = set()

# Optional: Destructive tools (require confirmation)
DESTRUCTIVE_TOOLS = set()


def is_configured() -> bool:
    """Checks if the service is available.

    This function is called by the prerequisites system.
    IMPORTANT: Must not require FastMCP imports, since it may be
    called before the full module import.
    """
    config = load_config().get("myplugin", {})

    # Disabled?
    if config.get("enabled") is False:
        return False

    # API key or credentials available?
    return bool(config.get("api_key"))


@mcp.tool()
def my_tool(param: str) -> str:
    """Tool description."""
    return f"Result: {param}"


if __name__ == "__main__":
    mcp.run()
```

**Important fields:**

| Field | Purpose |
|-------|---------|
| `TOOL_METADATA` | Icon + color for WebUI |
| `HIGH_RISK_TOOLS` | Tools with external content (sanitization) |
| `is_configured()` | Prerequisites check |

## Discovery Order

Resources are searched in this order (first match wins):

1. **User folder** (`agents/`, `skills/`, `knowledge/`)
2. **System folder** (`deskagent/agents/`, etc.)
3. **Plugins** (`plugins/*/agents/`, etc.) - with prefix

User/system resources always take precedence over plugins.

## API Functions

```python
from assistant.services.plugins import (
    discover_plugins,           # Dict[name, PluginInfo]
    get_plugin_agents,          # Dict[plugin, Dict[agent, data]]
    get_plugin_skills,          # Dict[plugin, Dict[skill, data]]
    get_plugin_mcp_dirs,        # List[(plugin_name, Path)]
    get_plugin_knowledge_dirs,  # List[(plugin_name, Path)] - knowledge folders
    get_plugin,                 # Optional[PluginInfo]
    list_plugins,               # List[dict]
    clear_plugin_cache,         # Invalidate cache
)
```

## Debugging

Plugin discovery is logged in `system.log`:

```
[Plugins] Discovered: myplugin v1.0.0 (agents:2, skills:1, mcp:1, knowledge:3)
[Plugins] Total discovered: 1 plugins
```

On MCP discovery:

```
[MCP Discovery] Scanning plugin MCP dir: myplugin -> C:\DeskAgent\plugins\myplugin\mcp
[MCP Discovery] Added plugin MCP: myplugin:myservice
```

## Example Plugin

A minimal test plugin:

```
plugins/testplugin/
├── plugin.json
└── agents/
    └── hello.md
```

**plugin.json:**
```json
{
  "name": "testplugin",
  "version": "1.0.0",
  "description": "Test plugin",
  "author": "DeskAgent"
}
```

**agents/hello.md:**
```markdown
---
{
  "category": "system",
  "description": "Test agent from plugin",
  "ai": "claude_sdk"
}
---
# Agent: Hello

Antworte mit "Hello from testplugin!"
```

After restart, `testplugin:hello` appears in the agent list.
