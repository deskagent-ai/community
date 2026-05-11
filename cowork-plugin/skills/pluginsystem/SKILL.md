# Plugin System

Das Plugin-System ermöglicht das Erweitern von DeskAgent mit externen Paketen aus GitHub oder lokalen Ordnern.

## Plugin-Struktur

Plugins werden im `plugins/` Ordner abgelegt:

```
plugins/
└── myplugin/                    # Plugin-Ordner (git clone oder manuell)
    ├── plugin.json              # Manifest (erforderlich)
    ├── requirements.txt         # Python Dependencies (optional)
    ├── agents/                  # Agent .md Dateien
    │   └── my_agent.md          # -> "myplugin:my_agent"
    ├── skills/                  # Skill .md Dateien
    │   └── my_skill.md          # -> "myplugin:my_skill"
    ├── knowledge/               # Knowledge .md Dateien
    │   └── docs.md              # -> "@myplugin:docs"
    └── mcp/                     # MCP Server (vereinfacht)
        └── __init__.py          # -> "myplugin:myplugin"
```

**Hinweis:** Jedes Plugin hat nur EINEN MCP-Server. Der MCP-Name entspricht dem Plugin-Namen.

## plugin.json Manifest

Jedes Plugin benötigt eine `plugin.json` Datei:

```json
{
  "name": "myplugin",
  "version": "1.0.0",
  "description": "Beschreibung des Plugins",
  "author": "Autor Name"
}
```

## Namespace-Prefix

Alle Plugin-Ressourcen erhalten automatisch einen Prefix mit dem Plugin-Namen:

| Ressource | Ohne Plugin | Mit Plugin |
|-----------|-------------|------------|
| Agent | `my_agent` | `myplugin:my_agent` |
| Skill | `my_skill` | `myplugin:my_skill` |
| MCP Server | `myservice` | `myplugin:myservice` |
| Knowledge | `@docs` | `@myplugin:docs` |

## Installation

### Manuell (git clone)

```bash
cd plugins
git clone https://github.com/someone/deskagent-plugin-example myplugin
```

### Manuell (Kopieren)

```bash
cp -r /path/to/plugin plugins/myplugin
```

Nach der Installation DeskAgent neu starten - Plugins werden automatisch erkannt.

## Verwendung in Agents

### Plugin-Agent aufrufen

Plugin-Agents erscheinen in der UI mit Prefix und können normal ausgeführt werden:
- `myplugin:my_agent`

### Plugin-MCP in allowed_mcp

```yaml
---
{
  "allowed_mcp": "myplugin:myservice|outlook|billomat"
}
---
```

### Plugin-Knowledge laden

```yaml
---
{
  "knowledge": "@myplugin:docs|company"
}
---
```

## Plugin-MCP Server erstellen

Jedes Plugin hat maximal EINEN MCP-Server direkt im `mcp/` Ordner:

```
myplugin/
└── mcp/
    └── __init__.py          # MCP Server (vereinfacht: direkt hier)
```

**mcp/__init__.py Struktur:**

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
    # Standalone-Fallback
    def load_config() -> dict:
        return {}

mcp = FastMCP("myplugin")  # Name = Plugin-Name

# PFLICHT: WebUI Icon/Color
TOOL_METADATA = {
    "icon": "extension",
    "color": "#1976d2"
}

# Optional: Tools die externe Daten lesen (Prompt Injection Protection)
HIGH_RISK_TOOLS = set()

# Optional: Destruktive Tools (benötigen Bestätigung)
DESTRUCTIVE_TOOLS = set()


def is_configured() -> bool:
    """Prüft ob der Service verfügbar ist.

    Diese Funktion wird vom Prerequisites-System aufgerufen.
    WICHTIG: Darf keine FastMCP-Imports benötigen, da sie vor
    dem vollständigen Modul-Import aufgerufen werden kann.
    """
    config = load_config().get("myplugin", {})

    # Deaktiviert?
    if config.get("enabled") is False:
        return False

    # API-Key oder Credentials vorhanden?
    return bool(config.get("api_key"))


@mcp.tool()
def my_tool(param: str) -> str:
    """Tool-Beschreibung."""
    return f"Result: {param}"


if __name__ == "__main__":
    mcp.run()
```

**Wichtige Felder:**

| Feld | Zweck |
|------|-------|
| `TOOL_METADATA` | Icon + Farbe fur WebUI |
| `HIGH_RISK_TOOLS` | Tools mit externem Content (Sanitization) |
| `is_configured()` | Prerequisites-Prüfung |

## Discovery-Reihenfolge

Ressourcen werden in dieser Reihenfolge gesucht (erste Treffer gewinnt):

1. **User-Ordner** (`agents/`, `skills/`, `knowledge/`)
2. **System-Ordner** (`deskagent/agents/`, etc.)
3. **Plugins** (`plugins/*/agents/`, etc.) - mit Prefix

User/System-Ressourcen haben immer Vorrang vor Plugins.

## API-Funktionen

```python
from assistant.services.plugins import (
    discover_plugins,      # Dict[name, PluginInfo]
    get_plugin_agents,     # Dict[plugin, Dict[agent, data]]
    get_plugin_skills,     # Dict[plugin, Dict[skill, data]]
    get_plugin_mcp_dirs,   # List[(plugin_name, Path)]
    get_plugin,            # Optional[PluginInfo]
    list_plugins,          # List[dict]
    clear_plugin_cache,    # Cache invalidieren
)
```

## Debugging

Plugin-Discovery wird in `system.log` protokolliert:

```
[Plugins] Discovered: myplugin v1.0.0 (agents:2, skills:1, mcp:1, knowledge:3)
[Plugins] Total discovered: 1 plugins
```

Bei MCP-Discovery:

```
[MCP Discovery] Scanning plugin MCP dir: myplugin -> C:\DeskAgent\plugins\myplugin\mcp
[MCP Discovery] Added plugin MCP: myplugin:myservice
```

## Beispiel-Plugin

Ein minimales Test-Plugin:

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

Nach Neustart erscheint `testplugin:hello` in der Agent-Liste.
