# Agent Creation Guide

Complete guide for creating DeskAgent agents - from simple to complex multi-step workflows.

> **See also:**
> - [doc-agent-frontmatter-reference.md](../deskagent/knowledge/doc-agent-frontmatter-reference.md) - All frontmatter options
> - [doc-mcp-tools.md](../deskagent/knowledge/doc-mcp-tools.md) - Available MCP tools

---

## Basic Structure

Agents are Markdown files with JSON frontmatter:

```markdown
---
{
  "category": "kommunikation",
  "description": "Kurzbeschreibung (1 Satz)",
  "icon": "reply",
  "ai": "gemini",
  "allowed_mcp": "outlook|clipboard"
}
---

# Agent: E-Mail beantworten

[Agent-Prompt hier...]
```

**Location:** `agents/my_agent.md` (user folder)

---

## Frontmatter - Most Important Options

### Minimal Configuration

```json
{
  "category": "chat",
  "description": "Was der Agent tut"
}
```

### Typical Configuration

```json
{
  "category": "finance",
  "description": "Erstellt Rechnungen aus E-Mails",
  "icon": "receipt_long",
  "input": ":mail: E-Mail mit Anhang",
  "output": ":receipt: Billomat-Rechnung",

  "ai": "gemini",
  "allowed_mcp": "outlook|billomat|pdf",
  "knowledge": "company|products",

  "order": 50,
  "enabled": true
}
```

### Categories

| ID | Label | Typical use |
|----|-------|-------------|
| `chat` | Chat | General assistance |
| `kommunikation` | Communication | Email, support |
| `finance` | Finance | Invoices, SEPA, DMS |
| `sales` | Sales | Quotes, CRM |
| `system` | System | Maintenance, tests |

---

## Agent Prompt Structure

### Recommended Pattern

```markdown
# Agent: [Klarer Titel]

[1-2 Sätze: Was der Agent tut und wann er verwendet wird]

## Ablauf

### Schritt 1: Daten abrufen
- Tool X aufrufen
- Ergebnis prüfen

### Schritt 2: Verarbeiten
[Anweisungen]

### Schritt 3: Ausgabe
[Was wird produziert]

## Wichtig

[Sicherheitsregeln, Edge Cases]
```

### Structure Variants

**For simple agents:**
```markdown
# Agent: PDF zusammenfassen

Lies die PDF und erstelle eine Zusammenfassung.

## Ablauf
1. PDF mit `fs_read_pdf()` laden
2. Wichtige Punkte extrahieren
3. Zusammenfassung ausgeben

Zusammenfassung erstellt!
```

**For complex workflows:**
```markdown
# Agent: Rechnungen prüfen

## Kontext
[Domain-Wissen, Hintergrund]

## Input
{{INPUT.dateien}}

## Ablauf (STRENGE REIHENFOLGE!)

### Phase 1: Analyse
[Nur lesende Operationen]

### Phase 2: Bestätigung
CONFIRMATION_NEEDED: {...}

### Phase 3: Ausführung
[Schreibende Operationen nach User-OK]

## Fehlerbehandlung
[Was bei Problemen passieren soll]
```

---

## User Dialogs (Follow-up Questions)

For interactive agents that require user input.

### QUESTION_NEEDED - Selection

Displays buttons for selection:

```markdown
QUESTION_NEEDED: {
  "question": "Für welchen Zeitraum soll ich exportieren?",
  "options": [
    {"value": "2025", "label": "Jahr 2025"},
    {"value": "Q4_2024", "label": "Q4 2024"},
    {"value": "dezember", "label": "Dezember 2024"}
  ],
  "allow_custom": true,
  "placeholder": "z.B. 01.10.2024 - 31.12.2024"
}
```

**Fields:**
| Field | Description |
|-------|-------------|
| `question` | The displayed question |
| `options` | Array with `value` (internal) and `label` (displayed) |
| `allow_custom` | User can enter own text (optional) |
| `placeholder` | Hint for custom input (optional) |

**Typical uses:**
- Yes/no questions
- Time range selection
- Mode selection (e.g. "New" vs. "Append")

### CONFIRMATION_NEEDED - Confirm Data

Displays an editable form:

```markdown
CONFIRMATION_NEEDED: {
  "question": "Sind die Kundendaten korrekt?",
  "data": {
    "firma": "Max Müller GmbH",
    "email": "info@mueller.de",
    "betrag": "1500"
  },
  "editable_fields": ["email", "betrag"],
  "on_cancel": "abort",
  "on_cancel_message": "Was soll geändert werden?"
}
```

**Fields:**
| Field | Description |
|-------|-------------|
| `question` | Heading |
| `data` | Fields to display |
| `editable_fields` | Which fields are editable |
| `on_cancel` | `"abort"` or `"continue"` |
| `on_cancel_message` | Question on cancel (optional) |

**Typical uses:**
- Check contact data before creation
- Confirm invoice data
- Classification before execution

### CONTINUATION_NEEDED - Batch Continuation

For agents that process many items:

```markdown
CONTINUATION_NEEDED: {
  "message": "10 von 83 Dokumenten verarbeitet",
  "remaining": 73,
  "processed": 10
}
```

**Prerequisite:** `"allow_continuation": true` in the frontmatter

**Behavior:**
- System restarts the agent automatically
- Max 20 continuations (safety)
- Each run is streamed to the UI

### Dialog Workflow Pattern

```markdown
## Ablauf

### Schritt 1: Recherche
[Daten sammeln - nur lesende Tools]

### Schritt 2: Bestätigung anfordern

CONFIRMATION_NEEDED: {
  "question": "Stimmen diese Daten?",
  "data": { ... },
  "editable_fields": [...]
}

**STOP - Warte auf User-Antwort!**

### Schritt 3: Verarbeitung
[Erst NACH Bestätigung ausführen]

Fertig!
```

**IMPORTANT:** Always wait after dialog markers! No parallel tool calls!

---

## Pre-Inputs Dialog

For agents that need files or parameters up front.

### File Upload

```json
{
  "inputs": [
    {
      "name": "files",
      "type": "file",
      "label": "Dateien auswählen",
      "required": true,
      "multiple": true,
      "accept": ".pdf,.csv",
      "folders": true
    }
  ]
}
```

### Text Input

```json
{
  "inputs": [
    {
      "name": "beschreibung",
      "type": "text",
      "label": "Beschreibung",
      "placeholder": "Optional...",
      "multiline": true,
      "rows": 4
    }
  ]
}
```

### Select Dropdown

```json
{
  "inputs": [
    {
      "name": "konto",
      "type": "select",
      "label": "Konto auswählen",
      "required": true,
      "options": [
        {"value": "privat", "label": "Privatkonto"},
        {"value": "firma", "label": "Firmenkonto"}
      ],
      "default": "firma"
    }
  ]
}
```

### Use in Prompt

```markdown
## Ausgewählte Dateien
{{INPUT.files}}

## Konto
{{INPUT.konto}}

## Beschreibung
{{INPUT.beschreibung}}
```

---

## Placeholders

### Date

| Placeholder | Example | Format |
|-------------|---------|--------|
| `{{TODAY}}` | 12.01.2026 | DD.MM.YYYY |
| `{{DATE}}` | 12.01.2026 | Alias for TODAY |
| `{{YEAR}}` | 2026 | YYYY |
| `{{DATE_ISO}}` | 2026-01-12 | YYYY-MM-DD |

### Paths

| Placeholder | Description |
|-------------|-------------|
| `{{EXPORTS_DIR}}` | workspace/exports/ |
| `{{TEMP_DIR}}` | workspace/.temp/ |
| `{{LOGS_DIR}}` | workspace/.logs/ |
| `{{WORKSPACE_DIR}}` | workspace/ |
| `{{KNOWLEDGE_DIR}}` | Knowledge directory (with fallback) |
| `{{CUSTOM_KNOWLEDGE_DIR}}` | User knowledge (always `knowledge/`) |
| `{{AGENTS_DIR}}` | agents/ |
| `{{CONFIG_DIR}}` | config/ |
| `{{PROJECT_DIR}}` | Project root |
| `{{DESKAGENT_DIR}}` | deskagent/ |

> **Full reference:** see [doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md#pfad-platzhalter)

### Example

```markdown
Speichere die Datei in `{{TEMP_DIR}}/export_{{DATE_ISO}}.pdf`
```

---

## Procedures (Reusable Building Blocks)

For code that is used in multiple agents.

### Use Procedure

```markdown
## Zahlungserkennung
{{PROCEDURE:detect_paid}}

## Upload-Workflow
{{PROCEDURE:paperless_upload}}
```

### Create Procedure

File: `agents/procedures/my_procedure.md`

```markdown
### Meine Procedure

1. Schritt eins
2. Schritt zwei

Unterstützt alle Platzhalter: {{TODAY}}, {{TEMP_DIR}}
```

**Search path:**
1. `agents/procedures/` (user - priority)
2. `deskagent/agents/procedures/` (system - fallback)

### Available System Procedures

| Procedure | Description |
|-----------|-------------|
| `detect_paid` | Detects already paid invoices (credit card, PayPal, direct debit) |
| `paperless_upload` | Standard workflow for Paperless upload |

---

## Tool Calls - Patterns

### Call Immediately (simple agents)

```markdown
**WICHTIG:** Rufe die Tools SOFORT auf! Keine Pläne beschreiben!

1. Lies die E-Mail mit `outlook_get_selected_email()`
2. Analysiere den Inhalt
3. Erstelle den Entwurf
```

### Strict Order (complex agents)

```markdown
## Ablauf (STRENGE REIHENFOLGE!)

### Schritt 1: Daten abrufen
Rufe PARALLEL auf:
- `outlook_get_recent_emails()`
- `outlook_get_calendar_events()`

### Schritt 2: WARTEN
**Warte bis BEIDE Ergebnisse da sind!**

### Schritt 3: Verarbeiten
ERST JETZT mit den ECHTEN Daten weiterarbeiten.
```

### Parallel Calls (performance)

```markdown
Rufe **gleichzeitig** auf (sind unabhängig):
- `billomat_search_clients()`
- `clipboard_get()`
- `outlook_get_selected_email()`
```

### Sequential Calls (dependencies)

```markdown
1. Zuerst Kunde suchen:
   `billomat_search_clients("Müller")`

2. WARTEN auf Ergebnis

3. Dann mit client_id:
   `billomat_get_client(client_id)`
```

---

## Security - MCP/Tool Restrictions

### Layer 1: Restrict MCP Servers

```json
"allowed_mcp": "outlook|billomat"
```

Only these MCP servers are loaded.

### Layer 2: Tool Whitelist

```json
"allowed_tools": ["fs_read_file", "fs_list_directory"]
```

Only allow these specific tools.

### Layer 3: Tool Blacklist

```json
"blocked_tools": ["fs_delete_file", "fs_write_file"]
```

Explicitly block these tools.

### Phase Pattern for Critical Operations

```markdown
## Phase 1: Analyse (NUR LESEN!)

**VERBOTEN:**
- Schreibende Operationen
- Löschen
- Verschieben

**ERLAUBT:**
- Alle lesenden Tools
- Planung erstellen

## >>> WARTE AUF USER-BESTÄTIGUNG <<<

## Phase 2: Ausführung

[Erst nach Bestätigung schreibende Operationen]
```

---

## Knowledge Patterns

### Load Selectively

```json
"knowledge": "company|products"
```

Load only `company.md` and `products.md`.

### Subfolder

```json
"knowledge": "linkedin"
```

Load all files in `knowledge/linkedin/`.

### Everything Except...

```json
"knowledge": "^(?!linkedin)"
```

Load everything EXCEPT `linkedin/`.

### Load Nothing (performance)

```json
"knowledge": ""
```

Do not load any knowledge files.

### External Files

```json
"knowledge": "@deskagent/documentation/en/"
```

Load files outside of `knowledge/`.

---

## Agent-as-Tool

Makes an agent available as a structured MCP tool.

```json
{
  "ai": "gemini",
  "tool": {
    "name": "classify_email",
    "description": "Klassifiziert eine E-Mail nach Typ",
    "parameters": {
      "email_content": {
        "type": "string",
        "description": "Der E-Mail-Inhalt",
        "required": true
      }
    },
    "returns": {
      "type": "object",
      "properties": {
        "category": {"type": "string"},
        "priority": {"type": "integer"}
      }
    }
  }
}
```

**Advantages:**
- Structured parameters instead of generic `desk_run_agent()`
- Required parameters are validated
- Ideal for supervisor pattern (Claude orchestrates, Gemini processes)

---

## Final Message - REQUIRED!

Every agent MUST end with a final message:

```markdown
E-Mail-Entwurf erstellt!
Angebot für Müller GmbH ist fertig.
3 Rechnungen exportiert und im Exports-Ordner bereit.
Prüfung abgeschlossen! 15 OK, 2 fehlend.
```

**RULE:** Without a final completion message, the agent is not done.

**NO follow-up question!** Don't ask "Can I help further?" - the user will reach out.

---

## Error Handling

### Standard Pattern

```markdown
## Fehlerbehandlung

- **Kein Kunde gefunden:** Extrahierte Daten anzeigen und fragen
- **PDF nicht lesbar:** Hinweis dass Scan sein könnte
- **API-Fehler:** Fehlermeldung anzeigen und alternativen Weg vorschlagen
- **Mehrdeutige Daten:** Optionen auflisten und User wählen lassen
```

### Graceful Degradation

```markdown
Falls ein Service nicht antwortet:
1. Im Report vermerken
2. Mit verfügbaren Daten weitermachen
3. User am Ende informieren was gefehlt hat
```

---

## Common Errors & Solutions

| Problem | Error | Solution |
|---------|-------|----------|
| User sees only text | Dialog without marker | Use QUESTION_NEEDED/CONFIRMATION_NEEDED |
| Tools called in parallel | Data not yet available | Strict order: fetch → wait → process |
| Writing directly | No confirmation | Phase 1 (analyze) → confirm → Phase 2 (execute) |
| Input not used | `{{INPUT.name}}` missing | Reference all inputs in the prompt |
| No completion | User unsure if done | Final completion message REQUIRED |
| Security issue | Too broad MCP allowance | Make `allowed_mcp` as restrictive as possible |

---

## Full Template

```markdown
---
{
  "category": "kommunikation",
  "description": "Beantwortet E-Mails professionell",
  "icon": "reply",
  "input": ":mail: E-Mail",
  "output": ":edit: Entwurf",

  "ai": "gemini",
  "allowed_mcp": "outlook|clipboard",
  "knowledge": "company|products",

  "order": 50,
  "enabled": true
}
---

# Agent: E-Mail beantworten

Du bist ein professioneller E-Mail-Assistent.

## Ablauf

### Schritt 1: E-Mail lesen
Rufe `outlook_get_selected_email()` auf.

### Schritt 2: Analysieren
- Absender und Anliegen identifizieren
- Tonfall erkennen (formal/informal)

### Schritt 3: Entwurf erstellen
- Professionelle Antwort formulieren
- In Zwischenablage kopieren

## Regeln

- Freundlich aber professionell
- Auf Deutsch antworten, außer Original ist Englisch
- Keine erfundenen Fakten

## Output

Kopiere den Entwurf mit `clipboard_set()`.

E-Mail-Entwurf erstellt und in Zwischenablage kopiert!
```

---

## Checklist for New Agents

- [ ] Frontmatter with category, description, icon
- [ ] AI backend selected (`ai`)
- [ ] MCP servers restricted (`allowed_mcp`)
- [ ] Knowledge pattern set (if not all needed)
- [ ] Clear flow structure
- [ ] User dialogs with QUESTION/CONFIRMATION_NEEDED
- [ ] Error handling defined
- [ ] Final completion message at the end
- [ ] Tested with real data
