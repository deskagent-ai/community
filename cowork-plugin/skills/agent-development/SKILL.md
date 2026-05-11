# DeskAgent Agent Development

This skill teaches you how to create new DeskAgent agents.

DeskAgent agents are Markdown files with JSON frontmatter. They define automated workflows
that use MCP tools (Outlook, Billomat, Filesystem, etc.) to perform business tasks.

## How It Works

1. Agents live in the `agents/` directory as `.md` files
2. DeskAgent's discovery system automatically loads new agents on refresh
3. Each agent has JSON frontmatter (between `---` delimiters) for configuration
4. The markdown body contains the prompt/instructions for the AI

## Creating a New Agent

To create a new agent, write a `.md` file to the `agents/` directory using `fs_write_file()`.

### Minimal Example

```markdown
---
{
  "category": "kommunikation",
  "description": "Summarizes flagged emails",
  "icon": "summarize",
  "allowed_mcp": "outlook",
  "knowledge": "",
  "enabled": true
}
---

# Agent: Summarize Flagged Emails

1. Use `outlook_get_flagged_emails()` to fetch all flagged emails
2. For each email, extract the key points
3. Present a summary table with sender, subject, and key action items
```

### Important Frontmatter Fields

| Field | Description | Example |
|-------|-------------|---------|
| `category` | UI category | `"kommunikation"`, `"finance"`, `"sales"`, `"system"` |
| `description` | Short description (1 sentence) | `"Creates SEPA files from invoices"` |
| `icon` | Material Icon name | `"reply"`, `"receipt_long"`, `"payments"` |
| `ai` | AI backend | `"claude_sdk"` (default), `"gemini"`, `"openai"` |
| `allowed_mcp` | Allowed MCP servers (pipe-separated) | `"outlook\|billomat\|filesystem"` |
| `knowledge` | Knowledge pattern | `"company\|products"`, `""` (none) |
| `tool_mode` | Security mode | `"full"` (default), `"read_only"`, `"write_safe"` |
| `prefetch` | Pre-load data | `["selected_email"]`, `["clipboard"]` |
| `enabled` | Active | `true` (default) |

### Available MCP Servers

| Server | Tools |
|--------|-------|
| `outlook` | Email (read, reply, move, flag), Calendar |
| `msgraph` | Microsoft Graph API (server-side email, calendar) |
| `gmail` | Gmail and Google Calendar |
| `billomat` | Customers, offers, invoices |
| `lexware` | Lexware Office API |
| `sepa` | SEPA XML payment files |
| `filesystem` | File read/write, PDF reading |
| `pdf` | PDF editing |
| `excel` | Excel read/write |
| `clipboard` | System clipboard |
| `paperless` | Paperless-ngx DMS |
| `ecodms` | ecoDMS archive |
| `userecho` | Support tickets |
| `browser` | Browser automation |
| `datastore` | SQLite data storage |
| `desk` | DeskAgent system control |

### Available Placeholders

Use these in agent prompts (replaced at runtime):

| Placeholder | Description |
|-------------|-------------|
| `{{TODAY}}` | Current date (DD.MM.YYYY) |
| `{{YEAR}}` | Current year |
| `{{EXPORTS_DIR}}` | Export directory |
| `{{TEMP_DIR}}` | Temp directory |
| `{{PREFETCH.email}}` | Pre-loaded email (with `prefetch: ["selected_email"]`) |
| `{{PREFETCH.clipboard}}` | Pre-loaded clipboard |
| `{{INPUT.name}}` | User input from pre-inputs dialog |
| `{{PROCEDURE:name}}` | Embedded procedure from `agents/procedures/` |

## Full Frontmatter Reference

Below is the complete reference for all agent frontmatter options.

# Agent Frontmatter Reference

> **✅ Dies ist der empfohlene Weg zur Agent-Konfiguration!**
>
> Agents werden als `.md` Dateien mit JSON-Frontmatter definiert. Die alte `agents.json` ist nur noch Fallback.

Vollständige Referenz aller Frontmatter-Optionen für DeskAgent Agents.

## Format

Agents werden in Markdown-Dateien (`.md`) mit JSON-Frontmatter definiert:

```markdown
---
{
  "category": "finance",
  "description": "Beschreibung des Agents",
  "ai": "gemini",
  ...
}
---

# Agent: Mein Agent

Agent-Prompt hier...
```

## Optionen-Übersicht

| Option | Typ | Pflicht | Beschreibung |
|--------|-----|---------|--------------|
| `category` | string | Nein | UI-Kategorie |
| `description` | string | Nein | Kurzbeschreibung |
| `icon` | string | Nein | Material Icon Name |
| `input` | string | Nein | Input-Beschreibung |
| `output` | string | Nein | Output-Beschreibung |
| `ai` | string | Nein | AI Backend |
| `model` | string | Nein | Spezifisches Modell (optional) |
| `allowed_mcp` | string | Nein | Erlaubte MCP-Server |
| `allowed_tools` | array | Nein | Tool-Whitelist |
| `blocked_tools` | array | Nein | Tool-Blacklist |
| `tool_mode` | string | Nein | Security-Modus (`full`, `read_only`) |
| `settings_file` | string | Nein | Pfad zu Agent-spezifischen Permissions |
| `filesystem` | object | Nein | Dateisystem-Einschränkungen |
| `knowledge` | string | Nein | Knowledge-Pattern |
| `inputs` | array | Nein | Pre-Inputs Dialog |
| `prefetch` | array | Nein | Daten vor Agent-Start laden |
| `tool` | object | Nein | Agent-as-Tool Definition |
| `voice_hotkey` | string | Nein | Systemweiter Hotkey |
| `next_agent` | string | Nein | Auto-Chaining: Nächster Agent |
| `pass_result_to_next` | boolean | Nein | Result an nächsten Agent übergeben |
| `next_agent_inputs` | object | Nein | Zusätzliche Inputs für nächsten Agent |
| `order` | integer | Nein | Sortierreihenfolge |
| `enabled` | boolean | Nein | Agent aktiv (Default: true) |
| `hidden` | boolean | Nein | Aus UI ausblenden |
| `use_anonymization_proxy` | boolean | Nein | PII-Anonymisierung |

---

## UI & Display Optionen

### `category`

Gruppiert den Agent in der WebUI-Sidebar.

**Typ:** `string`
**Standard:** `"chat"`

**Verfügbare Kategorien:**

| ID | Label | Icon |
|----|-------|------|
| `chat` | Chat | chat |
| `kommunikation` | Kommunikation | forum |
| `finance` | Finanzen | account_balance |
| `sales` | Vertrieb & Marketing | storefront |
| `system` | System | smart_toy |

**Einzelne Kategorie:**
```json
"category": "finance"
```

**Mehrere Kategorien (Pipe-getrennt):**
```json
"category": "finance|sales"
```

Agent erscheint dann sowohl unter "Finanzen" als auch unter "Vertrieb & Marketing".

### `description`

Kurze Beschreibung des Agents (1 Satz). Wird in der Agent-Kachel angezeigt.

**Typ:** `string`

```json
"description": "Erstellt Angebote aus Kontaktdaten"
```

### `icon`

Material Icon Name für die Agent-Kachel.

**Typ:** `string`
**Icons:** [Material Icons](https://fonts.google.com/icons)

```json
"icon": "request_quote"
```

**Häufig verwendete Icons:**

| Icon | Verwendung |
|------|------------|
| `reply` | E-Mail antworten |
| `receipt_long` | Rechnungen |
| `request_quote` | Angebote |
| `credit_card` | Kreditkarten |
| `support_agent` | Support |
| `help_center` | Hilfe |
| `content_copy` | Duplikate |
| `folder_open` | Dateien |

### `input` / `output`

Beschreibung von Input und Output mit optionalem Icon.

**Typ:** `string`
**Format:** `:icon: Text`

```json
"input": ":mail: E-Mail",
"output": ":edit: Entwurf"
```

**Icon-Mapping:**

| Shortcode | Icon |
|-----------|------|
| `:mail:` | mail |
| `:edit:` | edit |
| `:receipt:` | receipt |
| `:description:` | description |
| `:contact_mail:` | contact_mail |
| `:folder_open:` | folder_open |
| `:checklist:` | checklist |
| `:credit_card:` | credit_card |

### `order`

Sortierreihenfolge in der UI. Niedrigere Werte erscheinen weiter oben.

**Typ:** `integer`
**Standard:** `50`

```json
"order": 10
```

### `enabled`

Aktiviert/Deaktiviert den Agent. Deaktivierte Agents erscheinen nicht in der UI.

**Typ:** `boolean`
**Standard:** `true`

```json
"enabled": false
```

### `hidden`

Versteckt den Agent aus der WebUI, aber er bleibt verfügbar (z.B. für automatische Workflows).

**Typ:** `boolean`
**Standard:** `false`

```json
"hidden": true
```

**Anwendungsfall:** Agents die nur von Email-Watchern oder anderen Agents aufgerufen werden.

---

## AI Backend Optionen

### `ai`

Das AI Backend für diesen Agent.

**Typ:** `string`
**Standard:** `"claude_sdk"`

**Verfügbare Backends:**

| Backend | Beschreibung | Preis/1M Token |
|---------|--------------|----------------|
| `claude_sdk` | Claude Agent SDK (empfohlen) | $3/$15 |
| `gemini` | Google Gemini API | $1.25/$10 |
| `openai` | OpenAI GPT API | $2.50/$10 |
| `mistral` | Mistral API | $2/$6 |
| `qwen` | Qwen via Ollama | kostenlos |

```json
"ai": "gemini"
```

### `model`

Spezifisches AI-Modell (optional). Überschreibt das Standard-Modell des Backends.

**Typ:** `string`
**Standard:** Backend-abhängig (`claude-opus-4-6` für claude_sdk)

**Verfügbare Modelle (Claude):**

| Model ID | Beschreibung | Preis/1M Token |
|----------|--------------|----------------|
| `claude-opus-4-6` | Claude Opus 4.6 (Standard) | $15/$75 |
| `claude-sonnet-4-5-20250929` | Claude Sonnet 4.5 | $3/$15 |
| `claude-haiku-4-5-20251001` | Claude Haiku 4.5 | $0.80/$4 |

```json
"model": "claude-sonnet-4-5-20250929"
```

**Hinweis:** Nur verwenden wenn ein anderes Modell als der Standard benötigt wird.

### `use_anonymization_proxy` / `anonymize`

Aktiviert PII-Anonymisierung (Names, E-Mails, etc.) in Tool-Responses.

**Typ:** `boolean`
**Standard:** `false`

```json
"anonymize": true
```

Oder alternativ (aelterer Key, wird ebenfalls unterstuetzt):
```json
"use_anonymization_proxy": true
```

**Prioritaets-Logik (zentral gesteuert):**

Die Anonymisierungs-Entscheidung folgt einer festen Prioritaet:

| # | Bedingung | Ergebnis | Source |
|---|-----------|----------|--------|
| 0 | **Expert Override** via Kontextmenue | OFF | expert-override |
| 1 | Agent-Frontmatter `anonymize: false` | OFF | agent-off |
| 2 | Agent-Frontmatter `anonymize: true` + Global UI OFF | OFF | global-off |
| 3 | Agent-Frontmatter `anonymize: true` + Global UI ON | ON | agent-on |
| 4 | Kein Agent-Setting + Global UI OFF | OFF | global-off |
| 5 | Kein Agent-Setting + Global UI ON + Backend ON | ON | backend |
| 6 | Kein Agent-Setting + Global UI ON + Backend OFF | OFF | backend-off |

**Wichtig:**
- **Expert Override** [044]: Rechtsklick auf Agent-Tile > "Ohne Anonymisierung starten" (nur im Expert Mode sichtbar). Hat die hoechste Prioritaet und ueberschreibt alle anderen Einstellungen.
- Das **globale UI-Setting** (Settings Dialog > Anonymization Toggle) hat Vorrang vor Backend-Defaults
- Ein Agent kann Anonymisierung nur **aktivieren** wenn global ON ist
- Ein Agent kann Anonymisierung **immer deaktivieren** mit `anonymize: false`

**Was wird anonymisiert?**

| Content-Typ | Anonymisiert? | Grund |
|-------------|---------------|-------|
| **Agent-Prompt** (aus `.md` Datei) | Nein | System-Anweisungen enthalten Ordnernamen, Workflow-Begriffe |
| **User-Input** (nach `### Input:`) | Ja | Externe Daten (E-Mails, PDFs) |
| **Tool-Results** | Ja (via Proxy) | Externe Daten |
| **Confirmation-Dialoge** | Ja | Enthalten User-Daten |

**Technischer Hintergrund:**

Der Agent-Prompt (vor `### Input:` Marker) wird NICHT anonymisiert. Dies verhindert False-Positives bei deutschen Begriffen wie "Done-Ordner", "NIEMALS", "Ganztaegig", die Presidio faelschlicherweise als Personennamen erkennt.

Nur der Input-Bereich (nach `### Input:`) mit echten User-Daten wird anonymisiert. Bei Continuation-Prompts (nach CONFIRMATION_NEEDED) wird der Agent-Content ebenfalls vor den Marker gesetzt.

**Hinweis:** Erhoet die Sicherheit bei externen AI-Backends (Gemini, OpenAI).

### `sdk_mode`

SDK-Modus für Claude SDK Backend.

**Typ:** `string`
**Standard:** `"extended"`
**Nur für:** `claude_sdk` Backend

| Modus | Beschreibung |
|-------|--------------|
| `extended` | Erweiterte SDK Features (Sessions, AskUserQuestion) - **Standard** |
| `legacy` | Altes Verhalten (keine neuen Features) |

```json
"sdk_mode": "legacy"  // nur wenn alte Verhalten gewünscht
```

**Features in Extended Mode:**
- **Sessions:** SDK Session-ID wird gespeichert für Resume-Capability
- **AskUserQuestion:** SDK-Tool für native Dialoge (statt QUESTION_NEEDED Marker)
- **Structured Outputs:** `output_schema` für JSON-Schema-validierte Responses

### `output_schema`

JSON-Schema für strukturierte Responses (nur `sdk_mode: extended`).

**Typ:** `object` (JSON Schema)
**Standard:** `null`
**Nur für:** `claude_sdk` Backend mit `sdk_mode: extended`

```json
"output_schema": {
  "type": "object",
  "properties": {
    "customer_name": {"type": "string"},
    "total": {"type": "number"}
  },
  "required": ["customer_name", "total"]
}
```

---

## Security & Tools

### `allowed_mcp`

Erlaubte MCP-Server als Pipe-getrenntes Regex-Pattern.

**Typ:** `string`
**Standard:** Alle MCP-Server erlaubt

```json
"allowed_mcp": "outlook|billomat|clipboard"
```

**Verfügbare MCP-Server:**

| Server | Beschreibung |
|--------|--------------|
| `outlook` | E-Mail, Kalender (lokal) |
| `msgraph` | Microsoft Graph API |
| `gmail` | Gmail und Google Calendar |
| `billomat` | Kunden, Angebote, Rechnungen |
| `lexware` | Lexware Office API |
| `userecho` | Support-Tickets |
| `sepa` | SEPA XML Überweisungen |
| `filesystem` | Dateioperationen |
| `pdf` | PDF-Bearbeitung |
| `clipboard` | Zwischenablage |
| `datastore` | SQLite-Datenspeicher |
| `browser` | Browser-Automatisierung |
| `paperless` | Paperless-ngx DMS |
| `ecodms` | ecoDMS Archiv |

### `allowed_tools`

Explizite Whitelist einzelner Tools (zusätzlich zu `allowed_mcp`).

**Typ:** `array[string]`

```json
"allowed_tools": ["fs_read_file", "fs_list_directory", "fs_get_file_info"]
```

**Anwendungsfall:** Read-only Agents die nur bestimmte Tools nutzen dürfen.

### `blocked_tools`

Blacklist von Tools die gesperrt werden sollen.

**Typ:** `array[string]`

```json
"blocked_tools": ["fs_delete_file", "fs_write_file"]
```

**Sicherheitsmodell (Defense-in-Depth):**

```
Layer 1: allowed_mcp     → Welche MCP-Server werden geladen
Layer 2: allowed_tools   → Whitelist spezifischer Tools
Layer 3: blocked_tools   → Blacklist von Tools
Layer 4: filesystem      → Pfad-basierte Einschränkungen
```

### `filesystem`

Pfad-basierte Einschränkungen für Dateisystem-Operationen.

**Typ:** `object`

```json
"filesystem": {
  "write": ["{{EXPORTS_DIR}}/**"]
}
```

**Unterfelder:**

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `write` | array[string] | Erlaubte Pfade für Schreiboperationen |

**Betroffene Tools:**
- `fs_write_file` - Datei schreiben
- `fs_copy_file` - Datei kopieren (Ziel-Pfad wird geprüft)
- `fs_delete_file` - Datei löschen

**Pfad-Syntax:**

| Pattern | Beschreibung | Beispiel |
|---------|--------------|----------|
| `{{EXPORTS_DIR}}/**` | Rekursiv alle Unterordner | `exports/invoices/2025/file.pdf` ✅ |
| `{{TEMP_DIR}}/*` | Nur direkte Dateien | `temp/file.txt` ✅, `temp/sub/file.txt` ❌ |
| `{{WORKSPACE_DIR}}/data.json` | Exakter Pfad | Nur diese eine Datei |

**Platzhalter:** Alle Pfad-Platzhalter werden unterstützt (siehe unten).

**Sicherheit:**
- Ohne `filesystem.write` → Alle Pfade erlaubt (backward-compatible)
- Mit `filesystem.write: []` → Keine Schreiboperationen erlaubt
- Pfade werden normalisiert und gegen Whitelist geprüft
- Blockierte Zugriffe werden im System-Log protokolliert

**Beispiel - Chat-Agent nur in exports:**

```json
{
  "ai": "claude_sdk",
  "allowed_mcp": "outlook|filesystem|clipboard",
  "filesystem": {
    "write": ["{{EXPORTS_DIR}}/**"]
  }
}
```

**Beispiel - Read-Only Agent:**

```json
{
  "ai": "gemini",
  "allowed_mcp": "filesystem",
  "allowed_tools": ["fs_read_file", "fs_list_directory"],
  "filesystem": {
    "write": []
  }
}
```

### `tool_mode`

Security-Modus für Tool-Ausführung. Schränkt ein welche Tool-Kategorien erlaubt sind.

**Typ:** `string`
**Standard:** `"full"`
**Backend:** Alle (claude_sdk, gemini, openai, mistral)

| Modus | Beschreibung | Erlaubte Tools |
|-------|--------------|----------------|
| `"full"` | Alle Tools erlaubt (Default) | Alles |
| `"read_only"` | Nur Lese-Operationen | READ_ONLY_TOOLS |
| `"write_safe"` | Schreiben, aber nicht löschen | READ_ONLY_TOOLS + Write-Tools (ohne DESTRUCTIVE_TOOLS) |

**Read-Only Modus blockiert:**
- ❌ Bash Tool (komplett, nur claude_sdk)
- ❌ Write, Edit SDK Tools (nur claude_sdk)
- ❌ Alle MCP-Tools die NICHT in `READ_ONLY_TOOLS` definiert sind

**Read-Only Modus erlaubt:**
- ✅ Read, Grep, Glob, WebFetch, WebSearch SDK Tools (claude_sdk)
- ✅ MCP-Tools aus `READ_ONLY_TOOLS` (explizite Whitelist)

**Write-Safe Modus:**
- ✅ Alle READ_ONLY_TOOLS
- ✅ Schreiboperationen (create, update, write)
- ❌ Löschoperationen (delete, remove, clear)

**Beispiel - Sichere E-Mail-Analyse (read_only):**

```json
{
  "ai": "claude_sdk",
  "tool_mode": "read_only",
  "allowed_mcp": "outlook",
  "use_anonymization_proxy": true
}
```

Dieser Agent kann E-Mails **lesen** aber nicht senden/löschen/verschieben.

**Beispiel - Rechnungen erstellen (write_safe):**

```json
{
  "ai": "gemini",
  "tool_mode": "write_safe",
  "allowed_mcp": "billomat"
}
```

Dieser Agent kann Rechnungen **erstellen** aber nicht **löschen**.

**Sicherheit:**
- Tools die nicht explizit als read-only kategorisiert sind werden in read_only blockiert (Safe Default)
- Schützt vor Prompt Injection: Externe E-Mail-Inhalte können keine Write-Operationen auslösen
- Bash ist komplett blockiert in read_only (keine Shell-Exploits möglich)

**Kombination mit anderen Security-Optionen:**

```json
{
  "ai": "claude_sdk",
  "tool_mode": "read_only",
  "allowed_mcp": "paperless",
  "use_anonymization_proxy": true,
  "filesystem": {"write": []}
}
```

Dies ist die sicherste Konfiguration für Agents die externe Daten verarbeiten.

### `settings_file`

Pfad zu einer Agent-spezifischen Claude Code Settings-Datei für Bash-Permissions.

**Typ:** `string` (Dateipfad)
**Standard:** `null` (verwendet globale `.claude/settings.json`)
**Backend:** Nur `claude_sdk`

```json
"settings_file": "config/agent-permissions.json"
```

**Verwendung:**
Ermöglicht per-Agent Bash-Permissions statt globaler Settings.

**Beispiel Settings-Datei:**

```json
{
  "permissions": {
    "allow": ["Bash(git:*)"],
    "ask": ["Bash(npm:*)"],
    "deny": ["Bash(rm -rf:*)"]
  }
}
```

**Pfad-Auflösung:**
- Relative Pfade: Relativ zum Projekt-Root (`PROJECT_DIR`)
- Absolute Pfade: Werden direkt verwendet

**Kombination mit tool_mode:**

```json
{
  "ai": "claude_sdk",
  "tool_mode": "read_only",
  "settings_file": "config/readonly-permissions.json"
}
```

**Hinweis:** `settings_file` überschreibt die globalen Settings aus `.claude/settings.json` für diesen Agent.

---

## Knowledge

### `knowledge`

Pattern für die Wissensbasis (Regex).

**Typ:** `string`
**Standard:** Alle `knowledge/**/*.md` werden geladen

```json
"knowledge": "company|products"
```

**Pattern-Syntax:**

| Pattern | Beschreibung | Match |
|---------|--------------|-------|
| `company` | Datei oder Unterordner | `company.md` |
| `linkedin` | Unterordner | `linkedin/*.md` |
| `company\|products` | Regex OR | `company.md`, `products.md` |
| `^(?!linkedin)` | Negativ-Regex | Alles AUSSER `linkedin/` |
| `""` (leer) | Lädt NICHTS | - |
| fehlt/`null` | Lädt ALLES | Alle `.md` Dateien |
| `@path/file.md` | Externe Datei | Außerhalb `knowledge/` |
| `@deskagent/docs/` | Externer Ordner | Rekursiv alle `.md` |

**Beispiele:**

```json
// Nur Firmen- und Produktinfos
"knowledge": "company|products"

// LinkedIn-Unterordner
"knowledge": "linkedin"

// Externe Dokumentation
"knowledge": "@deskagent/documentation/en/"

// Nichts laden (performance)
"knowledge": ""
```

---

## Pre-Inputs Dialog

### `inputs`

Definiert einen Dialog zur Dateneingabe vor Agent-Start.

**Typ:** `array[object]`

```json
"inputs": [
  {"name": "files", "type": "file", "label": "Dateien", "required": true, "multiple": true, "accept": ".pdf"},
  {"name": "description", "type": "text", "label": "Beschreibung", "placeholder": "Optional..."}
]
```

#### Input-Felder (alle Typen)

| Property | Typ | Beschreibung |
|----------|-----|--------------|
| `name` | string | Feld-ID für `{{INPUT.name}}` Platzhalter |
| `type` | `"file"` \| `"text"` | Eingabetyp |
| `label` | string | Anzeige-Label im Dialog |
| `required` | boolean | Pflichtfeld (Standard: false) |

#### Datei-spezifisch (`type: "file"`)

| Property | Typ | Beschreibung |
|----------|-----|--------------|
| `multiple` | boolean | Mehrere Dateien erlauben |
| `accept` | string | Dateifilter (z.B. `.pdf,.docx`) |
| `folders` | boolean | Ordnerauswahl erlauben |

#### Text-spezifisch (`type: "text"`)

| Property | Typ | Beschreibung |
|----------|-----|--------------|
| `default` | string | Standardwert |
| `placeholder` | string | Platzhaltertext |
| `multiline` | boolean | Mehrzeiliges Textfeld |
| `rows` | number | Anzahl Zeilen (Standard: 8) |

#### Verwendung im Prompt

```markdown
## Ausgewählte Dateien
{{INPUT.files}}

## Beschreibung
{{INPUT.description}}
```

**UI-Verhalten:**
- Agents mit Inputs zeigen ein `upload_file` Badge auf der Kachel
- Klick öffnet Dialog mit Drag & Drop für Dateien
- Dateien werden als absolute Pfade übergeben

---

## Pre-fetching (Performance)

### `prefetch`

Lädt Daten **vor** Agent-Start, um die Reaktionszeit zu reduzieren.

**Typ:** `array[string]`
**Standard:** `[]` (kein Prefetch)

```json
"prefetch": ["selected_email"]
```

**Verfügbare Prefetch-Typen:**

| Typ | Tool | Platzhalter | Beschreibung |
|-----|------|-------------|--------------|
| `selected_email` | `outlook_get_selected_email` | `{{PREFETCH.email}}` | Markierte E-Mail (Outlook Desktop) |
| `selected_emails` | `outlook_get_selected_emails` | `{{PREFETCH.emails}}` | Alle markierten E-Mails |
| `graph_selected_email` | `graph_get_email` | `{{PREFETCH.email}}` | E-Mail via Microsoft Graph |
| `clipboard` | `clipboard_get_clipboard` | `{{PREFETCH.clipboard}}` | Zwischenablage-Inhalt |

**Performance-Vorteil:**

Ohne Prefetch:
```
Agent startet → AI denkt welches Tool → Tool wird aufgerufen → AI verarbeitet
              ~200ms              ~300ms                ~500ms
```

Mit Prefetch:
```
Agent startet ─┬─ Prefetch E-Mail (~500ms) ─┐
               └─ Agent-Config laden        ├─→ AI verarbeitet sofort
                   (~200ms)                 ┘
```

**Zeitersparnis:** ~500ms (E-Mail bereits im Kontext)

**Verwendung im Prompt:**

```markdown
---
{
  "prefetch": ["selected_email"],
  "allowed_mcp": "outlook"
}
---

# Agent: E-Mail Antwort

## Zu beantwortende E-Mail

{{PREFETCH.email}}

## Aufgabe

Analysiere die E-Mail oben und erstelle einen Antwort-Entwurf...
```

**Hinweis:** Die E-Mail wird automatisch formatiert mit Betreff, Absender, Datum und Body.

**Fehlerbehandlung:**
- Falls Prefetch fehlschlägt (z.B. keine E-Mail ausgewählt), enthält der Platzhalter eine Fehlermeldung
- Der Agent läuft weiter und kann auf den Fehler reagieren

**Kombinierbar mit:**
- `inputs`: Prefetch + User-Dialog
- `knowledge`: Prefetch + Wissensbasis
- `tool_mode`: Prefetch + Security-Einschränkungen

---

## Voice Hotkey

### `voice_hotkey`

Systemweiter Voice-Hotkey für diesen Agent.

**Typ:** `string`
**Format:** Modifier+Key (z.B. `Ctrl+Shift+O`)

```json
"voice_hotkey": "Ctrl+Shift+Backspace"
```

**Workflow:**
1. E-Mail/Dokument fokussieren
2. Hotkey drücken → Aufnahme startet
3. Anweisung sprechen
4. Hotkey nochmal → Agent startet mit Transkription

**Mehrere Agents können unterschiedliche Hotkeys haben:**

```json
// reply_email.md
"voice_hotkey": "Ctrl+Shift+Backspace"

// summarize.md
"voice_hotkey": "Ctrl+Shift+S"
```

**Beispiel: Voice Task Agent (Sprache zu Task-Datei):**

```markdown
---
{
  "ai": "claude_sdk",
  "voice_hotkey": "ctrl+shift+t",
  "allowed_mcp": "project",
  "knowledge": ""
}
---

# Agent: Voice Task

Transkription an project_ask weiterleiten um /task im Zielprojekt auszufuehren.
```

Die Transkription wird automatisch als `_context` an den Agent uebergeben und kann im Prompt referenziert werden.

---

## Agent-as-Tool

### `tool`

Macht den Agent als strukturiertes MCP-Tool für andere Agents verfügbar.

**Typ:** `object`

```json
"tool": {
  "name": "classify_emails",
  "description": "E-Mails klassifizieren nach Typ",
  "parameters": {
    "emails": {
      "type": "array",
      "description": "Zu klassifizierende E-Mails",
      "required": true
    }
  },
  "returns": {
    "type": "object",
    "properties": {
      "classifications": {"type": "array"}
    }
  }
}
```

#### Tool-Schema

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `tool.name` | string | Tool-Name (snake_case) |
| `tool.description` | string | Beschreibung für LLM |
| `tool.parameters` | object | Parameter-Definitionen |
| `tool.returns` | object | Return-Schema (Dokumentation) |

#### Parameter-Definition

```json
"parameters": {
  "param_name": {
    "type": "string",       // string, array, object, integer, boolean
    "description": "...",
    "required": true
  }
}
```

#### Vollständiges Beispiel

```markdown
---
{
  "ai": "gemini",
  "allowed_mcp": "",
  "knowledge": "",
  "tool": {
    "name": "test_echo",
    "description": "Echoes input message for testing",
    "parameters": {
      "message": {
        "type": "string",
        "description": "Message to echo back",
        "required": true
      },
      "prefix": {
        "type": "string",
        "description": "Optional prefix",
        "required": false
      }
    },
    "returns": {
      "type": "object",
      "properties": {
        "echo": {"type": "string"},
        "timestamp": {"type": "string"}
      }
    }
  }
}
---

# Agent: Test Echo

{{INPUT.message}}
{{INPUT.prefix}}

Return JSON with echo and timestamp.
```

**Vorteile:**
- LLM sieht strukturierte Parameter statt generischem `desk_run_agent()`
- Pflichtparameter werden validiert
- Supervisor-Pattern: Claude orchestriert, Gemini verarbeitet

---

## Auto-Chaining

Deterministische, system-gesteuerte Agent-Verkettung. Nach erfolgreichem Abschluss eines Agents wird automatisch der nächste gestartet.

### `next_agent`

Name des Agents der nach erfolgreichem Abschluss automatisch gestartet wird.

**Typ:** `string`

```json
"next_agent": "step2"
```

### `pass_result_to_next`

Übergibt das Result des aktuellen Agents als `previous_result` an den nächsten.

**Typ:** `boolean`
**Standard:** `false`

```json
"pass_result_to_next": true
```

### `next_agent_inputs`

Zusätzliche Inputs für den nächsten Agent.

**Typ:** `object`

```json
"next_agent_inputs": {
  "mode": "verbose",
  "limit": 10
}
```

### Beispiel: Mail-Sortierung Chain

```markdown
<!-- agents/classify_spam.md -->
---
{
  "ai": "gemini",
  "allowed_mcp": "outlook",
  "next_agent": "classify_invoices"
}
---

# Spam Classifier

1. Hole ungelesene E-Mails
2. Finde Spam
3. Verschiebe nach ToDelete
```

**Workflow:**
```
User startet: classify_spam
  ↓
classify_spam → ✅ SUCCESS
  ↓
System startet automatisch: classify_invoices
  ↓
classify_invoices → ✅ SUCCESS
  ↓
Ende
```

**Vorteile:**
- ✅ Deterministisch - System steuert, nicht AI
- ✅ Crash-Safe - bei Fehler stoppt die Chain
- ✅ Debugbar - klare Reihenfolge im Log

---

## Platzhalter im Prompt

Folgende Platzhalter werden beim Laden ersetzt:

### Datum-Platzhalter

| Platzhalter | Beispiel | Beschreibung |
|-------------|----------|--------------|
| `{{TODAY}}` | 29.12.2025 | Heutiges Datum (DD.MM.YYYY) |
| `{{DATE}}` | 29.12.2025 | Alias für TODAY |
| `{{YEAR}}` | 2025 | Aktuelles Jahr |
| `{{DATE_ISO}}` | 2025-12-29 | ISO-Format (YYYY-MM-DD) |

### Pfad-Platzhalter

| Platzhalter | Beschreibung |
|-------------|--------------|
| `{{EXPORTS_DIR}}` | Export-Verzeichnis (`workspace/exports/`) |
| `{{TEMP_DIR}}` | Temp-Verzeichnis (`workspace/.temp/`) |
| `{{LOGS_DIR}}` | Log-Verzeichnis (`workspace/.logs/`) |
| `{{WORKSPACE_DIR}}` | Workspace-Verzeichnis (`workspace/`) |
| `{{KNOWLEDGE_DIR}}` | Knowledge-Verzeichnis (User-Ordner mit Fallback auf System) |
| `{{CUSTOM_KNOWLEDGE_DIR}}` | User Knowledge-Verzeichnis (immer `knowledge/`, kein Fallback) |
| `{{AGENTS_DIR}}` | Agents-Verzeichnis (User-Ordner mit Fallback) |
| `{{CONFIG_DIR}}` | Config-Verzeichnis (`config/`) |
| `{{PROJECT_DIR}}` | Projekt-Root (`aiassistant/`) |
| `{{DESKAGENT_DIR}}` | DeskAgent-Verzeichnis (`deskagent/`) |

### Input-Platzhalter

| Platzhalter | Beschreibung |
|-------------|--------------|
| `{{INPUT.name}}` | Wert aus Pre-Inputs Dialog |

### Prefetch-Platzhalter

| Platzhalter | Beschreibung |
|-------------|--------------|
| `{{PREFETCH.email}}` | Vorgeladene E-Mail (formatted) |
| `{{PREFETCH.emails}}` | Vorgeladene E-Mails (multiple) |
| `{{PREFETCH.clipboard}}` | Vorgeladener Clipboard-Inhalt |

### Procedure-Platzhalter

| Platzhalter | Beschreibung |
|-------------|--------------|
| `{{PROCEDURE:name}}` | Inhalt aus `agents/procedures/name.md` |

---

## Merge-Prioritäten

Konfiguration wird aus mehreren Quellen gemerged:

```
1. Agent .md Frontmatter       ← Höchste Priorität
2. config/agents.json          ← User-Override
3. deskagent/config/agents.json← System-Default
```

**Beispiel:** Wenn `ai: "gemini"` im Frontmatter steht, überschreibt es jeden Wert aus `agents.json`.

---

## Vollständiges Beispiel

```markdown
---
{
  "category": "finance",
  "description": "Vergleicht Kreditkartenbuchungen mit Rechnungen",
  "icon": "credit_card",
  "input": ":credit_card: Kreditkartenabrechnung + :receipt: Rechnungen",
  "output": ":checklist: Abgleich-Report",

  "ai": "gemini",
  "allowed_mcp": "filesystem",
  "allowed_tools": ["fs_read_file", "fs_read_pdf", "fs_list_directory"],

  "knowledge": "",

  "order": 63,
  "enabled": true,

  "inputs": [
    {"name": "statements", "type": "file", "label": "Kreditkartenabrechnungen", "required": true, "multiple": true, "accept": ".pdf,.csv"},
    {"name": "invoices", "type": "file", "label": "Rechnungen", "required": true, "multiple": true, "folders": true, "accept": ".pdf"}
  ]
}
---

# Agent: Kreditkartenabrechnung prüfen

## Kreditkartenabrechnungen
{{INPUT.statements}}

## Rechnungen
{{INPUT.invoices}}

## Aufgabe

1. Abrechnungen einlesen mit `fs_read_pdf()`
2. Rechnungen mit `fs_read_pdfs_batch()` laden
3. Buchungen mit Rechnungen abgleichen
4. Fehlende Belege auflisten
```

---

## Siehe auch

- [docs/creating-agents.md](creating-agents.md) - Agent-Erstellung Guide
- [docs/agent-as-tool-architecture.md](agent-as-tool-architecture.md) - Supervisor-Pattern
- [docs/mcp-tools.md](mcp-tools.md) - Verfügbare MCP-Tools


## Example Agents

### reply_email.md

```markdown
---
{
  "category": "kommunikation",
  "description": "Erstellt professionellen Antwort-Entwurf auf markierte Outlook E-Mail",
  "icon": "reply",
  "input": ":mail: E-Mail",
  "output": ":edit: Entwurf",
  "allowed_mcp": "outlook|msgraph|clipboard",
  "knowledge": "company|products",
  "prefetch": ["selected_email"],
  "order": 10,
  "enabled": true
}
---

# Agent: E-Mail Antwort (Outlook)

Erstelle einen professionellen Antwort-Entwurf auf die folgende E-Mail.

## Zu beantwortende E-Mail

{{PREFETCH.email}}

## Ablauf

**WICHTIG:** Rufe die Tools SOFORT auf! Keine Pläne beschreiben!

1. **Analysiere die E-Mail oben** (sie wurde bereits geladen)

2. **Entwurf erstellen** - Rufe `outlook_create_reply_draft(body, reply_all=True)` auf

## Regeln

### Persönliche Anrede
**WICHTIG:** Beginne die Antwort IMMER mit einer persönlichen Anrede:
- "Hi [Vorname]," oder "Hallo [Vorname]," (informell)
- "Dear [Vorname]," oder "Liebe/r [Vorname]," (formell)
- Extrahiere den Vornamen aus dem Absender-Feld (z.B. "John Smith" → "John")
- Danach eine Leerzeile, dann ggf. die Gruß-Erwiderung

... (truncated)
```

### daily_check.md

```markdown
---
{
  "name": "Täglicher Check",
  "category": "kommunikation",
  "description": "Taeglicher Ueberblick: Termine, offene Angebote, Rechnungen",
  "icon": "checklist",
  "input": ":inbox: Posteingang",
  "output": ":task_alt: Report",
  "allowed_mcp": "msgraph",
  "tool_mode": "read_only",
  "knowledge": "company|products",
  "order": 20,
  "enabled": true
}
---

# Agent: Daily Check

Taeglicher Ueberblick ueber Termine, offene Punkte und Rechnungen.

**WICHTIG:** Dieser Agent sortiert KEINE E-Mails! Die Sortierung erfolgt durch den `mailsort` Agent.

## Link-Format

**WICHTIG:** Verwende fuer Links die Platzhalter-Syntax mit dem `link_ref` Feld aus der API-Antwort:

```markdown
[Anzeigetext]({{LINK:link_ref}})
```

Beispiele aus API-Responses:
- Email mit `"link_ref": "a3f2b1c8"` → `[Betreff]({{LINK:a3f2b1c8}})`
- Event mit `"link_ref": "b2c4d6e8"` → `[Meeting]({{LINK:b2c4d6e8}})`

**NICHT** die volle URL aus `web_link` kopieren! Das System ersetzt die Platzhalter automatisch.

## Kontext

Du bist der E-Mail-Assistent. Du hilfst bei der taeglichen Uebersicht ueber Termine, offene Punkte und Rechnungen.

... (truncated)
```

### create_offer.md

```markdown
---
{
  "name": "Angebot erstellen",
  "category": "sales",
  "description": "Erstellt Angebote aus Kontaktdaten (Clipboard/E-Mail)",
  "icon": "request_quote",
  "input": ":contact_mail: Kontaktdaten",
  "output": ":description: Angebot",
  "allowed_mcp": "billomat|lexware|outlook|clipboard",
  "knowledge": "company|products",
  "prefetch": ["selected_email", "clipboard"],
  "order": 50,
  "enabled": true
}
---

# Agent: Create Offer

You are a sales assistant. Your task is to create professional offers based on contact data from clipboard or email.

**Quality first:** Only proceed when you are confident about the data. If anything is unclear or ambiguous, ask the user for clarification before creating contacts or offers.

## Vorab geladene Daten

**E-Mail:**
{{PREFETCH.email}}

**Clipboard:**
{{PREFETCH.clipboard}}

## Step 1: Find Contact Data

Use the pre-loaded data above (email and clipboard).
Use the source with more complete contact data (company, name, email, address).
If both are empty: Ask the user for contact data.

## Step 2: Extract Contact Data

Extract:
- **Company name** (IMPORTANT: Always the company, not the person's name!)
... (truncated)
```

