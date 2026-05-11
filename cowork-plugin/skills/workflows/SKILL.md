# Workflows

Deterministische Abläufe für wiederkehrende Aufgaben.

## Workflows vs Agents

| | Agent | Workflow |
|---|-------|----------|
| Entscheidungen | AI entscheidet | Feste Logik |
| Zuverlässigkeit | Kann variieren | 100% reproduzierbar |
| Anwendung | Kreative Aufgaben | Routine-Prozesse |
| Beispiel | "Formuliere Antwort" | "Tag → Sende → Tag" |

**Tipp:** Workflows können Agents für kreative Teilaufgaben aufrufen.

## Workflow-Dateien

```
workflows/                    <- User-Workflows (Priorität 1)
└── mein_workflow.py

deskagent/workflows/          <- System-Workflows (Priorität 2)
├── email_reply.py
└── invoice_processing.py
```

**Override-Prinzip:** User-Workflows überschreiben System-Workflows mit gleichem Namen.

## Minimaler Workflow

```python
# workflows/mein_workflow.py
from workflows import Workflow, step

class MeinWorkflow(Workflow):
    """Kurze Beschreibung."""

    name = "Mein Workflow"           # Name in WebUI
    icon = "cog"                     # FontAwesome Icon
    allowed_mcp = ["outlook"]        # Erlaubte MCP-Server

    @step
    def schritt_eins(self):
        result = self.tool.outlook_get_selected_email()
        self.email_data = result

    @step
    def schritt_zwei(self):
        print(f"E-Mail: {self.email_data}")
```

## Verfügbare MCP-Server

| Server | Beschreibung |
|--------|--------------|
| `outlook` | E-Mail & Kalender |
| `gmail` | Gmail & Google Calendar |
| `msgraph` | Microsoft Graph API |
| `billomat` | Rechnungen & Kunden |
| `datastore` | Datenbank (SQLite) |
| `desk` | DeskAgent-Steuerung |
| `paperless` | Dokumentenmanagement |
| `sepa` | SEPA-Überweisungen |

**Tool-Aufruf:** `self.tool.<tool_name>(<parameter>)`

## Flow-Kontrolle

```python
@step
def pruefe_bedingung(self):
    if self.tool.db_contains("blocklist", self.sender) == "true":
        return "skip"      # Workflow beenden (Erfolg)

    if not self.hat_berechtigung:
        return "pause"     # Pausieren (kann fortgesetzt werden)

    if self.fehler:
        return "goto:fehlerbehandlung"  # Zu Step springen
```

| Return-Wert | Wirkung |
|-------------|---------|
| `None` | Nächster Step |
| `"skip"` | Workflow beenden |
| `"pause"` | Pausieren |
| `"goto:step_name"` | Zu Step springen |

## AI in Workflows

Agents für Textgenerierung aufrufen:

```python
@step
def generiere_antwort(self):
    self.antwort = self.tool.desk_run_agent_sync(
        "support_reply",
        f'{{"email_content": "{self.email_text}"}}'
    )
```

## Workflow starten

**Per API:**
```bash
curl -X POST http://localhost:8765/api/workflows/email_reply/start \
     -H "Content-Type: application/json" \
     -d '{"email_id": "ABC123"}'
```

**In Python:**
```python
from workflows import manager
manager.start("email_reply", email_id="ABC123")
```

## WebUI Integration

Workflows erscheinen als Tiles wie Agents. Alle Metadaten in der Python-Klasse:

```python
class MeinWorkflow(Workflow):
    name = "Anzeigename"           # Name auf Tile
    icon = "envelope"              # FontAwesome Icon
    allowed_mcp = ["outlook"]      # Erlaubte MCP-Server
    category = "email"             # Gruppierung (optional)
    description = "Info"           # Tooltip (optional)
    hidden = False                 # Ausblenden (optional)
```

**API:**
- `GET /api/workflows` - Liste aller Workflows
- `POST /api/workflows/{id}/start` - Workflow starten
- `GET /api/workflows/runs` - Laufende Workflows

## Auto-Resume

Workflows speichern nach jedem Step ihren Zustand. Bei Neustart werden unterbrochene Workflows automatisch fortgesetzt.
