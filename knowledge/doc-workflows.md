# Workflows

Deterministic flows for recurring tasks.

## Workflows vs Agents

| | Agent | Workflow |
|---|-------|----------|
| Decisions | AI decides | Fixed logic |
| Reliability | May vary | 100% reproducible |
| Use case | Creative tasks | Routine processes |
| Example | "Compose a reply" | "Tag → Send → Tag" |

**Tip:** Workflows can call agents for creative subtasks.

## Workflow Files

```
workflows/                    <- User workflows (priority 1)
└── my_workflow.py

deskagent/workflows/          <- System workflows (priority 2)
├── email_reply.py
└── invoice_processing.py
```

**Override principle:** User workflows override system workflows with the same name.

## Minimal Workflow

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

## Available MCP Servers

| Server | Description |
|--------|-------------|
| `outlook` | Email & calendar |
| `gmail` | Gmail & Google Calendar |
| `msgraph` | Microsoft Graph API |
| `billomat` | Invoices & customers |
| `datastore` | Database (SQLite) |
| `desk` | DeskAgent control |
| `paperless` | Document management |
| `sepa` | SEPA transfers |

**Tool call:** `self.tool.<tool_name>(<parameter>)`

## Flow Control

```python
@step
def pruefe_bedingung(self):
    if self.tool.db_contains("blocklist", self.sender) == "true":
        return "skip"      # End workflow (success)

    if not self.hat_berechtigung:
        return "pause"     # Pause (can be resumed)

    if self.fehler:
        return "goto:fehlerbehandlung"  # Jump to step
```

| Return value | Effect |
|--------------|--------|
| `None` | Next step |
| `"skip"` | End workflow |
| `"pause"` | Pause |
| `"goto:step_name"` | Jump to step |

## AI in Workflows

Call agents for text generation:

```python
@step
def generiere_antwort(self):
    self.antwort = self.tool.desk_run_agent_sync(
        "support_reply",
        f'{{"email_content": "{self.email_text}"}}'
    )
```

## Starting Workflows

**Via API:**
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

Workflows appear as tiles like agents. All metadata in the Python class:

```python
class MeinWorkflow(Workflow):
    name = "Anzeigename"           # Display name on tile
    icon = "envelope"              # FontAwesome Icon
    allowed_mcp = ["outlook"]      # Allowed MCP servers
    category = "email"             # Grouping (optional)
    description = "Info"           # Tooltip (optional)
    hidden = False                 # Hide (optional)
```

**API:**
- `GET /api/workflows` - List all workflows
- `POST /api/workflows/{id}/start` - Start workflow
- `GET /api/workflows/runs` - Running workflows

## Auto-Resume

Workflows save their state after each step. On restart, interrupted workflows are resumed automatically.
