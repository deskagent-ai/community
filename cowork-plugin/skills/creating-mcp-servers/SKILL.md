# MCP Server erstellen

Anleitung zur Erstellung von MCP (Model Context Protocol) Servern für DeskAgent.

## Übersicht

MCP Server stellen Tools bereit, die von AI-Agents aufgerufen werden können. Jeder MCP Server ist ein eigenständiges Python-Package unter `deskagent/mcp/`.

### Architektur

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

Der Anonymization Proxy:
- Lädt alle MCP-Server automatisch aus `deskagent/mcp/`
- Anonymisiert Ergebnisse von HIGH_RISK_TOOLS
- Schützt vor Prompt Injection

## Quick Start

Minimaler MCP Server in 15 Zeilen:

```python
# deskagent/mcp/example/__init__.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example")

TOOL_METADATA = {"icon": "extension", "color": "#9c27b0"}
HIGH_RISK_TOOLS = set()      # Tools mit externen Inhalten
DESTRUCTIVE_TOOLS = set()    # Tools die Daten ändern/löschen
READ_ONLY_TOOLS = set()      # Tools die nur Daten lesen

def is_configured() -> bool:
    return True

@mcp.tool()
def example_hello(name: str) -> str:
    """Grüßt den Benutzer."""
    return f"Hallo {name}!"

if __name__ == "__main__":
    mcp.run()
```

## Standard-Template

### Einfacher MCP (Single-File)

Für MCPs mit 3-10 Tools. Alles in einer `__init__.py`:

```python
#!/usr/bin/env python3
"""
Example MCP Server.

Beschreibung was dieser MCP macht.
"""

import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Scripts-Ordner für Imports hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from paths import load_config

# MCP initialisieren (Name = Ordnername)
mcp = FastMCP("example")

# UI Metadaten
TOOL_METADATA = {
    "icon": "extension",      # Material Design Icon
    "color": "#9c27b0"        # Hex-Farbe
}

# Tools die externe Inhalte zurückgeben (für Prompt Injection Schutz)
HIGH_RISK_TOOLS = {
    "example_read_external",
}

# Tools die Daten modifizieren (für Dry-Run Modus)
DESTRUCTIVE_TOOLS = {
    "example_write_data",
    "example_delete_data",
}

# Tools die nur Daten lesen (für tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "example_get_status",
    "example_search",
    "example_read_external",
}

def is_configured() -> bool:
    """Prüft ob MCP aktiviert und konfiguriert ist."""
    config = load_config()
    mcp_config = config.get("example", {})

    # Explizit deaktiviert?
    if mcp_config.get("enabled") is False:
        return False

    # Erforderliche Config vorhanden?
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

### Komplexer MCP (Multi-Module)

Für MCPs mit 10+ Tools. Aufgeteilt in mehrere Module:

```
outlook/
├── __init__.py       # Package-Init, is_configured(), run()
├── base.py           # Shared: mcp, Metadaten, Helper
├── email_read.py     # Lese-Tools
├── email_write.py    # Schreib-Tools
└── calendar.py       # Kalender-Tools
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

# Module importieren um Tools zu registrieren
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

# Shared MCP Instance
mcp = FastMCP("outlook")

# Metadaten
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

# Thread-lokaler Speicher (für COM-Objekte)
_thread_local = threading.local()

def outlook_tool(func):
    """Decorator für einheitliches Error Handling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return f"Fehler: {str(e)}"
    return wrapper

def get_outlook():
    """Thread-lokales Outlook COM-Objekt."""
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

## Tool-Definition

### Decorator und Signatur

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

### Regeln

| Regel | Beschreibung |
|-------|--------------|
| **Return Type** | Immer `str` - MCP-Protokoll Anforderung |
| **Type Hints** | Pflicht für alle Parameter |
| **Docstring** | Pflicht - wird als Tool-Beschreibung für LLM verwendet |
| **Exceptions** | Nie werfen - immer `return f"Fehler: {str(e)}"` |
| **Naming** | `prefix_action_target`, z.B. `outlook_get_email` |

### Parameter-Typen

| Python Type | Beschreibung | Beispiel |
|-------------|--------------|----------|
| `str` | Text | `query: str` |
| `int` | Ganzzahl | `limit: int = 10` |
| `float` | Dezimalzahl | `threshold: float = 0.5` |
| `bool` | Boolean | `include_body: bool = True` |
| `str` (JSON) | Komplexe Daten | `items: str` → `json.loads(items)` |

**Komplexe Parameter als JSON-String:**
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

## Metadaten

### TOOL_METADATA

UI-Informationen für die WebUI:

```python
TOOL_METADATA = {
    "icon": "mail",           # Material Design Icon Name
    "color": "#0078d4"        # Hex-Farbe für UI
}
```

**Häufige Icons nach Kategorie:**

| Kategorie | Icons |
|-----------|-------|
| E-Mail | `mail`, `mail_outline`, `send`, `reply`, `forward` |
| Dateien | `folder`, `folder_open`, `description`, `attachment` |
| Daten | `storage`, `database`, `cloud`, `save` |
| Zahlung | `payments`, `receipt`, `credit_card`, `attach_money` |
| Support | `support_agent`, `help`, `chat`, `forum` |
| Browser | `language`, `public`, `open_in_new` |
| System | `settings`, `build`, `extension`, `smart_toy` |

**Farb-Palette:**

| Farbe | Hex | Verwendung |
|-------|-----|------------|
| Blau | `#2196F3` | System, DeskAgent |
| Grün | `#4caf50` | Finanzen, Erfolg |
| Rot | `#f44336` | PDF, Gmail |
| Orange | `#ff9800` | Browser, Warnung |
| Lila | `#9c27b0` | Clipboard, Tools |
| Pink | `#e91e63` | Support |
| Blaugrau | `#607d8b` | Storage, Neutral |

### HIGH_RISK_TOOLS

Tools die **externe/nicht vertrauenswürdige Inhalte** zurückgeben:

```python
HIGH_RISK_TOOLS = {
    "mcp_get_email_content",      # E-Mail Body
    "mcp_read_file",              # Dateiinhalt
    "mcp_get_api_response",       # Externe API
    "mcp_get_clipboard",          # Zwischenablage
}
```

**Wann markieren:**
- E-Mail/Nachrichteninhalt
- Dateiinhalt (Text, PDF, Attachments)
- Externe API-Responses
- User-Input (Clipboard, Formulare)
- Suchergebnisse mit Volltext

**Nicht markieren:**
- Konfigurationsprüfungen
- Listen mit Metadaten (IDs, Namen)
- Selbst generierte Daten

### IS_HIGH_RISK (MCP-Level)

Einfachere Alternative zu HIGH_RISK_TOOLS - markiert **alle Tools** eines MCPs als high-risk:

```python
# MCP-Level Flag: Alle Tools verarbeiten externe Inhalte
IS_HIGH_RISK = True

# Note: Mit IS_HIGH_RISK=True sind individuelle HIGH_RISK_TOOLS nicht nötig
```

**Wann verwenden:**
- Support-Ticket-Systeme (userecho)
- Messaging-Systeme (alle Nachrichten von extern)
- MCPs wo ALLE Daten von externen Benutzern kommen

**Beispiel:**
```python
# userecho MCP - alle Tickets kommen von Kunden
IS_HIGH_RISK = True  # Alle Tools werden sanitized
```

**Vorteil:**
- Einfacher als jedes Tool einzeln zu listen
- Kein Risiko dass neue Tools vergessen werden
- Klare Markierung dass der gesamte MCP externe Daten verarbeitet

### DESTRUCTIVE_TOOLS

Tools die **Daten modifizieren, erstellen oder löschen**:

```python
DESTRUCTIVE_TOOLS = {
    "mcp_create_item",            # Erstellen
    "mcp_update_item",            # Ändern
    "mcp_delete_item",            # Löschen
    "mcp_move_item",              # Verschieben
    "mcp_mark_as_done",           # Status ändern
}
```

Diese werden im Dry-Run Modus simuliert statt ausgeführt.

### READ_ONLY_TOOLS

Tools die **nur Daten lesen** ohne Änderungen vorzunehmen:

```python
READ_ONLY_TOOLS = {
    "mcp_get_item",               # Einzelnes Item lesen
    "mcp_search_items",           # Suche
    "mcp_list_items",             # Auflistung
    "mcp_get_status",             # Status abrufen
    "mcp_check_connection",       # Verbindung prüfen
}
```

**Wann markieren:**
- Alle GET/Lese-Operationen
- Suchanfragen
- Status-Checks
- Konfigurationsabfragen

**Nicht markieren:**
- Tools die Daten ändern/erstellen/löschen
- Tools mit Seiteneffekten (z.B. Versand)

**Zweck:** Für `tool_mode: "read_only"` Agents. Diese können nur Tools aus READ_ONLY_TOOLS aufrufen.

**Safe Default:** Tools die NICHT in READ_ONLY_TOOLS stehen werden im read_only mode blockiert!

## Konfiguration

### is_configured() Pattern

Jeder MCP muss `is_configured()` implementieren:

```python
def is_configured() -> bool:
    """
    Prüft ob MCP aktiviert und konfiguriert ist.

    Returns:
        False wenn:
        - Explizit deaktiviert (enabled: false)
        - Erforderliche Credentials fehlen

        True sonst.
    """
    config = load_config()
    mcp_config = config.get("mcp_name", {})

    # Explizit deaktiviert?
    if mcp_config.get("enabled") is False:
        return False

    # Erforderliche Config prüfen
    api_key = mcp_config.get("api_key")
    account_id = mcp_config.get("id")

    return bool(api_key and account_id)
```

### Config laden

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

### Config-Dateien

| Datei | Inhalt |
|-------|--------|
| `config/apis.json` | Externe API-Credentials |
| `config/system.json` | System-Einstellungen |
| `config/backends.json` | AI-Backend Configs |

**Beispiel `apis.json`:**
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

### Standard-Pattern

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

### Regeln

| Regel | Beispiel |
|-------|----------|
| Nie Exceptions werfen | `return f"Fehler: ..."` statt `raise` |
| Deutsche Fehlermeldungen | `"Fehler: E-Mail nicht gefunden"` |
| Kontext angeben | `"Fehler bei API-Aufruf: 401 Unauthorized"` |
| Kurz und informativ | Keine Stacktraces, nur Message |

### System Logging

Für Debugging in `workspace/.logs/system.log`:

```python
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): print(msg)

# Verwendung
system_log(f"[MyMCP] Processing {item_id}")
system_log(f"[MyMCP] Error: {e}")
```

## Best Practices

### Naming Conventions

| Element | Convention | Beispiel |
|---------|------------|----------|
| Ordner | lowercase | `deskagent/mcp/billomat/` |
| MCP Name | = Ordnername | `FastMCP("billomat")` |
| Tool Name | `prefix_action_target` | `billomat_create_invoice` |
| Prefix | = MCP Name | `outlook_`, `gmail_`, `fs_` |

### Caching

Für API-Aufrufe mit seltenen Änderungen:

```python
import time

_cache = {}
_cache_time = 0
CACHE_TTL = 3600  # 1 Stunde

def get_cached(key: str, fetch_fn):
    """Cache mit TTL."""
    global _cache, _cache_time

    if time.time() - _cache_time > CACHE_TTL:
        _cache = {}

    if key not in _cache:
        _cache[key] = fetch_fn()
        _cache_time = time.time()

    return _cache[key]
```

### API-Requests

Standard-Pattern für HTTP-Aufrufe:

```python
import json
import urllib.request
import urllib.error

def api_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """HTTP Request an externe API."""
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

### Thread-Safety

Für COM-Objekte oder nicht-thread-safe Ressourcen:

```python
import threading

_thread_local = threading.local()

def get_resource():
    """Thread-lokale Ressource."""
    if not hasattr(_thread_local, 'resource'):
        _thread_local.resource = create_resource()
    return _thread_local.resource
```

## Referenz-Implementierungen

| MCP | Typ | Beschreibung | Studieren für |
|-----|-----|--------------|---------------|
| `clipboard/` | Einfach | 3 Tools | Minimales Beispiel |
| `datastore/` | Einfach | SQLite Storage | Datenbank-Integration |
| `pdf/` | Einfach | PDF-Bearbeitung | Datei-Verarbeitung |
| `outlook/` | Komplex | E-Mail via COM | Multi-Module, Decorators |
| `billomat/` | Komplex | REST API | API-Integration, Caching |
| `gmail/` | Komplex | OAuth2 API | Auth, Token-Refresh |

## Link-Platzhalter System (V2)

Wenn MCP-Tools Items mit Web-URLs zurückgeben (E-Mails, Tickets, Dokumente), sollten diese über das **Link Registry System** registriert werden. Das verhindert Transcription-Errors wenn LLMs lange IDs kopieren.

### Konzept

- MCP registriert URL über `register_link()`
- AI sieht nur kurzen Platzhalter `{{LINK:ref}}`
- WebUI ersetzt Platzhalter beim Anzeigen

### Implementierung

```python
# Am Anfang der Datei importieren:
import sys
from pathlib import Path
mcp_root = str(Path(__file__).parent.parent)
if mcp_root not in sys.path:
    sys.path.insert(0, mcp_root)
from _link_utils import make_link_ref, LINK_TYPE_EMAIL  # oder anderer Typ
from _mcp_api import register_link
```

```python
# In der Tool-Funktion:
@mcp.tool()
def my_get_emails() -> str:
    emails = []
    for msg in fetch_messages():
        msg_id = msg["id"]

        # V2 Link System: URL registrieren, nur link_ref an AI
        link_ref = make_link_ref(msg_id, LINK_TYPE_EMAIL)
        register_link(link_ref, f"https://example.com/mail/{msg_id}")

        emails.append({
            "id": msg_id,
            "link_ref": link_ref,  # Kurzer Hash (8 chars)
            # web_link NICHT zurückgeben - AI soll URL nicht sehen!
            "subject": msg["subject"],
        })

    return json.dumps({"emails": emails})
```

### Verfügbare Typ-Konstanten

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

### Wann verwenden

| Anwendungsfall | Link-Ref verwenden? |
|----------------|---------------------|
| E-Mails mit Outlook Web Link | ✅ Ja |
| Tickets mit Web-Portal Link | ✅ Ja |
| Dokumente in DMS mit URL | ✅ Ja |
| Lokale Dateipfade | ❌ Nein |
| IDs ohne Web-Zugang | ❌ Nein |

### Debug

Bei Problemen prüfen:
1. `[LinkRegistry] register_link(...)` im Log?
2. Session-ID korrekt? (muss mit DeskAgent Session übereinstimmen)
3. `link_map` hat Einträge bei Session-Ende?

Siehe auch: [doc-link-placeholder-system.md](../docs/doc-link-placeholder-system.md)

## Checkliste für neue MCPs

- [ ] Ordner unter `deskagent/mcp/` angelegt
- [ ] `__init__.py` mit `mcp = FastMCP("name")`
- [ ] `TOOL_METADATA` mit Icon und Farbe
- [ ] `HIGH_RISK_TOOLS` definiert (kann leer sein)
- [ ] `DESTRUCTIVE_TOOLS` definiert (kann leer sein)
- [ ] `READ_ONLY_TOOLS` definiert (alle Lese-Tools)
- [ ] `is_configured()` implementiert
- [ ] Alle Tools mit `@mcp.tool()` dekoriert
- [ ] Alle Tools returnen `str`
- [ ] Error Handling mit `"Fehler: ..."` Format
- [ ] Docstrings für alle Tools
- [ ] Config in `apis.json` dokumentiert
- [ ] Link-Refs für Web-URLs verwenden (`register_link`)
