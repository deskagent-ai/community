# Creating MCP Servers

Guide for creating MCP (Model Context Protocol) servers for DeskAgent.

## Overview

MCP servers provide tools that can be called by AI agents. Each MCP server is a standalone Python package under `deskagent/mcp/`.

### Architecture

```
AI Agent (Claude, Gemini, etc.)
    ↓ (tool call)
Anonymization Proxy MCP
    ↓ (forwards call)
MCP Server (outlook, billomat, etc.)
    ↓ (result)
Anonymization Proxy MCP
    ↓ (anonymized result)
AI Agent
```

The anonymization proxy:
- Loads all MCP servers automatically from `deskagent/mcp/`
- Anonymizes results from HIGH_RISK_TOOLS
- Protects against prompt injection

## Quick Start

Minimal MCP server in 15 lines:

```python
# deskagent/mcp/example/__init__.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example")

TOOL_METADATA = {"icon": "extension", "color": "#9c27b0"}
HIGH_RISK_TOOLS = set()      # Tools with external content
DESTRUCTIVE_TOOLS = set()    # Tools that modify/delete data
READ_ONLY_TOOLS = set()      # Tools that only read data

def is_configured() -> bool:
    return True

@mcp.tool()
def example_hello(name: str) -> str:
    """Grüßt den Benutzer."""
    return f"Hallo {name}!"

if __name__ == "__main__":
    mcp.run()
```

## Standard Template

### Simple MCP (Single-File)

For MCPs with 3-10 tools. Everything in a single `__init__.py`:

```python
#!/usr/bin/env python3
"""
Example MCP Server.

Beschreibung was dieser MCP macht.
"""

import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Add scripts folder for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from paths import load_config

# Initialize MCP (name = folder name)
mcp = FastMCP("example")

# UI metadata
TOOL_METADATA = {
    "icon": "extension",      # Material Design icon
    "color": "#9c27b0"        # Hex color
}

# Tools that return external content (for prompt injection protection)
HIGH_RISK_TOOLS = {
    "example_read_external",
}

# Tools that modify data (for dry-run mode)
DESTRUCTIVE_TOOLS = {
    "example_write_data",
    "example_delete_data",
}

# Tools that only read data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "example_get_status",
    "example_search",
    "example_read_external",
}

def is_configured() -> bool:
    """Checks if MCP is enabled and configured."""
    config = load_config()
    mcp_config = config.get("example", {})

    # Explicitly disabled?
    if mcp_config.get("enabled") is False:
        return False

    # Required config present?
    api_key = mcp_config.get("api_key")
    return bool(api_key)


@mcp.tool()
def example_get_status() -> str:
    """Gibt den aktuellen Status zurück."""
    try:
        # Implementation
        return "Status: OK"
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
def example_process(data: str, limit: int = 10) -> str:
    """
    Verarbeitet die übergebenen Daten.

    Args:
        data: JSON-String mit Daten
        limit: Maximale Anzahl Ergebnisse (Standard: 10)

    Returns:
        JSON-String mit Ergebnissen
    """
    import json
    try:
        items = json.loads(data)
        result = items[:limit]
        return json.dumps(result, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"Fehler: Ungültiges JSON - {str(e)}"
    except Exception as e:
        return f"Fehler: {str(e)}"


if __name__ == "__main__":
    mcp.run()
```

### Complex MCP (Multi-Module)

For MCPs with 10+ tools. Split into multiple modules:

```
outlook/
├── __init__.py       # Package init, is_configured(), run()
├── base.py           # Shared: mcp, metadata, helpers
├── email_read.py     # Read tools
├── email_write.py    # Write tools
└── calendar.py       # Calendar tools
```

**`__init__.py`:**
```python
"""
Outlook MCP Server.

Module:
- email_read: E-Mails lesen und suchen
- email_write: E-Mails erstellen und antworten
- calendar: Kalender-Operationen
"""

from .base import mcp, HIGH_RISK_TOOLS, DESTRUCTIVE_TOOLS, READ_ONLY_TOOLS, TOOL_METADATA

# Import modules to register tools
from . import email_read
from . import email_write
from . import calendar

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from paths import load_config

__all__ = ['mcp', 'HIGH_RISK_TOOLS', 'DESTRUCTIVE_TOOLS', 'READ_ONLY_TOOLS', 'TOOL_METADATA', 'is_configured']

def is_configured() -> bool:
    """Outlook ist immer verfügbar (lokale COM-Schnittstelle)."""
    config = load_config()
    mcp_config = config.get("outlook", {})
    return mcp_config.get("enabled", True) is not False

def run():
    """MCP Server starten."""
    mcp.run()

if __name__ == "__main__":
    run()
```

**`base.py`:**
```python
"""Shared utilities für Outlook MCP."""

import threading
from functools import wraps
from mcp.server.fastmcp import FastMCP

# Shared MCP instance
mcp = FastMCP("outlook")

# Metadata
TOOL_METADATA = {"icon": "mail", "color": "#0078d4"}

HIGH_RISK_TOOLS = {
    "outlook_get_selected_email",
    "outlook_get_email_content",
    "outlook_read_pdf_attachment",
}

DESTRUCTIVE_TOOLS = {
    "outlook_create_reply_draft",
    "outlook_move_email",
    "outlook_delete_email",
}

READ_ONLY_TOOLS = {
    "outlook_get_selected_email",
    "outlook_get_email_content",
    "outlook_search_emails",
    "outlook_list_mail_folders",
}

# Thread-local storage (for COM objects)
_thread_local = threading.local()

def outlook_tool(func):
    """Decorator for unified error handling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return f"Fehler: {str(e)}"
    return wrapper

def get_outlook():
    """Thread-local Outlook COM object."""
    if not hasattr(_thread_local, 'outlook'):
        import win32com.client
        _thread_local.outlook = win32com.client.Dispatch("Outlook.Application")
    return _thread_local.outlook
```

**`email_read.py`:**
```python
"""E-Mail Lese-Tools."""

from .base import mcp, outlook_tool, get_outlook

@mcp.tool()
@outlook_tool
def outlook_get_selected_email() -> str:
    """Gibt die aktuell in Outlook markierte E-Mail zurück."""
    outlook = get_outlook()
    explorer = outlook.ActiveExplorer()
    # ... Implementation
    return result
```

## Tool Definition

### Decorator and Signature

```python
@mcp.tool()
def tool_name(required_param: str, optional_param: int = 10) -> str:
    """
    Kurze Beschreibung (erste Zeile).

    Längere Beschreibung falls nötig.

    Args:
        required_param: Beschreibung des Parameters
        optional_param: Beschreibung mit Default-Wert

    Returns:
        Immer String (MCP-Protokoll Anforderung)
    """
```

### Rules

| Rule | Description |
|------|-------------|
| **Return type** | Always `str` - MCP protocol requirement |
| **Type hints** | Required for all parameters |
| **Docstring** | Required - used as tool description for the LLM |
| **Exceptions** | Never throw - always `return f"Fehler: {str(e)}"` |
| **Naming** | `prefix_action_target`, e.g. `outlook_get_email` |

### Parameter Types

| Python type | Description | Example |
|-------------|-------------|---------|
| `str` | Text | `query: str` |
| `int` | Integer | `limit: int = 10` |
| `float` | Decimal | `threshold: float = 0.5` |
| `bool` | Boolean | `include_body: bool = True` |
| `str` (JSON) | Complex data | `items: str` → `json.loads(items)` |

**Complex parameters as JSON string:**
```python
@mcp.tool()
def process_items(items: str) -> str:
    """
    Args:
        items: JSON-Array, z.B. [{"id": 1, "name": "test"}]
    """
    import json
    item_list = json.loads(items)
    # ...
```

## Metadata

### TOOL_METADATA

UI information for the WebUI:

```python
TOOL_METADATA = {
    "icon": "mail",           # Material Design icon name
    "color": "#0078d4"        # Hex color for UI
}
```

**Common icons by category:**

| Category | Icons |
|----------|-------|
| Email | `mail`, `mail_outline`, `send`, `reply`, `forward` |
| Files | `folder`, `folder_open`, `description`, `attachment` |
| Data | `storage`, `database`, `cloud`, `save` |
| Payment | `payments`, `receipt`, `credit_card`, `attach_money` |
| Support | `support_agent`, `help`, `chat`, `forum` |
| Browser | `language`, `public`, `open_in_new` |
| System | `settings`, `build`, `extension`, `smart_toy` |

**Color palette:**

| Color | Hex | Use |
|-------|-----|-----|
| Blue | `#2196F3` | System, DeskAgent |
| Green | `#4caf50` | Finance, success |
| Red | `#f44336` | PDF, Gmail |
| Orange | `#ff9800` | Browser, warning |
| Purple | `#9c27b0` | Clipboard, tools |
| Pink | `#e91e63` | Support |
| Blue-grey | `#607d8b` | Storage, neutral |

### HIGH_RISK_TOOLS

Tools that return **external/untrusted content**:

```python
HIGH_RISK_TOOLS = {
    "mcp_get_email_content",      # Email body
    "mcp_read_file",              # File content
    "mcp_get_api_response",       # External API
    "mcp_get_clipboard",          # Clipboard
}
```

**When to mark:**
- Email/message content
- File content (text, PDF, attachments)
- External API responses
- User input (clipboard, forms)
- Search results with full text

**Do not mark:**
- Configuration checks
- Lists with metadata (IDs, names)
- Self-generated data

### IS_HIGH_RISK (MCP-Level)

Simpler alternative to HIGH_RISK_TOOLS - marks **all tools** of an MCP as high-risk:

```python
# MCP-level flag: all tools process external content
IS_HIGH_RISK = True

# Note: With IS_HIGH_RISK=True individual HIGH_RISK_TOOLS are not needed
```

**When to use:**
- Support ticket systems (userecho)
- Messaging systems (all messages come from external)
- MCPs where ALL data comes from external users

**Example:**
```python
# userecho MCP - all tickets come from customers
IS_HIGH_RISK = True  # All tools are sanitized
```

**Advantage:**
- Simpler than listing every tool individually
- No risk of forgetting new tools
- Clear marking that the entire MCP handles external data

### DESTRUCTIVE_TOOLS

Tools that **modify, create or delete data**:

```python
DESTRUCTIVE_TOOLS = {
    "mcp_create_item",            # Create
    "mcp_update_item",            # Update
    "mcp_delete_item",            # Delete
    "mcp_move_item",              # Move
    "mcp_mark_as_done",           # Change status
}
```

These are simulated in dry-run mode instead of executed.

### READ_ONLY_TOOLS

Tools that **only read data** without making changes:

```python
READ_ONLY_TOOLS = {
    "mcp_get_item",               # Read single item
    "mcp_search_items",           # Search
    "mcp_list_items",             # List
    "mcp_get_status",             # Read status
    "mcp_check_connection",       # Check connection
}
```

**When to mark:**
- All GET/read operations
- Search queries
- Status checks
- Configuration queries

**Do not mark:**
- Tools that modify/create/delete data
- Tools with side effects (e.g. sending)

**Purpose:** For `tool_mode: "read_only"` agents. These can only call tools from READ_ONLY_TOOLS.

**Safe default:** Tools that are NOT in READ_ONLY_TOOLS are blocked in read_only mode!

## Configuration

### is_configured() Pattern

Every MCP must implement `is_configured()`:

```python
def is_configured() -> bool:
    """
    Checks if MCP is enabled and configured.

    Returns:
        False if:
        - Explicitly disabled (enabled: false)
        - Required credentials missing

        True otherwise.
    """
    config = load_config()
    mcp_config = config.get("mcp_name", {})

    # Explicitly disabled?
    if mcp_config.get("enabled") is False:
        return False

    # Check required config
    api_key = mcp_config.get("api_key")
    account_id = mcp_config.get("id")

    return bool(api_key and account_id)
```

### Load Config

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from paths import load_config

config = load_config()

# APIs (config/apis.json)
billomat_key = config.get("billomat", {}).get("api_key")

# System (config/system.json)
log_enabled = config.get("agent_logging", {}).get("enabled", True)
```

### Config Files

| File | Content |
|------|---------|
| `config/apis.json` | External API credentials |
| `config/system.json` | System settings |
| `config/backends.json` | AI backend configs |

**Example `apis.json`:**
```json
{
  "billomat": {
    "enabled": true,
    "id": "account_id",
    "api_key": "api_key_123"
  },
  "example": {
    "enabled": true,
    "api_key": "my_key"
  }
}
```

## Error Handling

### Standard Pattern

```python
@mcp.tool()
def my_tool(param: str) -> str:
    try:
        result = risky_operation(param)
        return f"Erfolgreich: {result}"
    except ValueError as e:
        return f"Fehler bei Validierung: {str(e)}"
    except Exception as e:
        return f"Fehler: {str(e)}"
```

### Rules

| Rule | Example |
|------|---------|
| Never throw exceptions | `return f"Fehler: ..."` instead of `raise` |
| German error messages | `"Fehler: E-Mail nicht gefunden"` |
| Provide context | `"Fehler bei API-Aufruf: 401 Unauthorized"` |
| Short and informative | No stack traces, only message |

### System Logging

For debugging in `workspace/.logs/system.log`:

```python
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): print(msg)

# Use
system_log(f"[MyMCP] Processing {item_id}")
system_log(f"[MyMCP] Error: {e}")
```

## Best Practices

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Folder | lowercase | `deskagent/mcp/billomat/` |
| MCP name | = folder name | `FastMCP("billomat")` |
| Tool name | `prefix_action_target` | `billomat_create_invoice` |
| Prefix | = MCP name | `outlook_`, `gmail_`, `fs_` |

### Caching

For API calls with rare changes:

```python
import time

_cache = {}
_cache_time = 0
CACHE_TTL = 3600  # 1 hour

def get_cached(key: str, fetch_fn):
    """Cache with TTL."""
    global _cache, _cache_time

    if time.time() - _cache_time > CACHE_TTL:
        _cache = {}

    if key not in _cache:
        _cache[key] = fetch_fn()
        _cache_time = time.time()

    return _cache[key]
```

### API Requests

Standard pattern for HTTP calls:

```python
import json
import urllib.request
import urllib.error

def api_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """HTTP Request to external API."""
    url = f"https://api.example.com/{endpoint}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}
```

### Thread Safety

For COM objects or non-thread-safe resources:

```python
import threading

_thread_local = threading.local()

def get_resource():
    """Thread-local resource."""
    if not hasattr(_thread_local, 'resource'):
        _thread_local.resource = create_resource()
    return _thread_local.resource
```

## Reference Implementations

| MCP | Type | Description | Study for |
|-----|------|-------------|-----------|
| `clipboard/` | Simple | 3 tools | Minimal example |
| `datastore/` | Simple | SQLite storage | Database integration |
| `pdf/` | Simple | PDF manipulation | File processing |
| `outlook/` | Complex | Email via COM | Multi-module, decorators |
| `billomat/` | Complex | REST API | API integration, caching |
| `gmail/` | Complex | OAuth2 API | Auth, token refresh |

## Link Placeholder System (V2)

When MCP tools return items with web URLs (emails, tickets, documents), they should be registered via the **Link Registry System**. This prevents transcription errors when LLMs copy long IDs.

### Concept

- MCP registers URL via `register_link()`
- AI only sees short placeholder `{{LINK:ref}}`
- WebUI replaces placeholder on display

### Implementation

```python
# Import at the top of the file:
import sys
from pathlib import Path
mcp_root = str(Path(__file__).parent.parent)
if mcp_root not in sys.path:
    sys.path.insert(0, mcp_root)
from _link_utils import make_link_ref, LINK_TYPE_EMAIL  # or other type
from _mcp_api import register_link
```

```python
# In the tool function:
@mcp.tool()
def my_get_emails() -> str:
    emails = []
    for msg in fetch_messages():
        msg_id = msg["id"]

        # V2 Link System: register URL, only link_ref to AI
        link_ref = make_link_ref(msg_id, LINK_TYPE_EMAIL)
        register_link(link_ref, f"https://example.com/mail/{msg_id}")

        emails.append({
            "id": msg_id,
            "link_ref": link_ref,  # Short hash (8 chars)
            # Do NOT return web_link - AI should not see URL!
            "subject": msg["subject"],
        })

    return json.dumps({"emails": emails})
```

### Available Type Constants

```python
from _link_utils import (
    LINK_TYPE_EMAIL,      # "email"
    LINK_TYPE_EVENT,      # "event"
    LINK_TYPE_TICKET,     # "ticket"
    LINK_TYPE_DOCUMENT,   # "doc"
    LINK_TYPE_INVOICE,    # "invoice"
    LINK_TYPE_CONTACT,    # "contact"
    LINK_TYPE_OFFER,      # "offer"
)
```

### When to Use

| Use case | Use link-ref? |
|----------|---------------|
| Emails with Outlook web link | Yes |
| Tickets with web portal link | Yes |
| Documents in DMS with URL | Yes |
| Local file paths | No |
| IDs without web access | No |

### Debug

If problems occur, check:
1. `[LinkRegistry] register_link(...)` in the log?
2. Session ID correct? (must match the DeskAgent session)
3. Does `link_map` have entries at session end?

See also: [doc-link-placeholder-system.md](../docs/doc-link-placeholder-system.md)

## Checklist for New MCPs

- [ ] Folder created under `deskagent/mcp/`
- [ ] `__init__.py` with `mcp = FastMCP("name")`
- [ ] `TOOL_METADATA` with icon and color
- [ ] `HIGH_RISK_TOOLS` defined (can be empty)
- [ ] `DESTRUCTIVE_TOOLS` defined (can be empty)
- [ ] `READ_ONLY_TOOLS` defined (all read tools)
- [ ] `is_configured()` implemented
- [ ] All tools decorated with `@mcp.tool()`
- [ ] All tools return `str`
- [ ] Error handling with `"Fehler: ..."` format
- [ ] Docstrings for all tools
- [ ] Config documented in `apis.json`
- [ ] Link refs for web URLs (`register_link`)
