# Agent Frontmatter Reference

> **This is the recommended way to configure agents!**
>
> Agents are defined as `.md` files with JSON frontmatter. The old `agents.json` is only a fallback.

Complete reference of all frontmatter options for DeskAgent agents.

## Format

Agents are defined in Markdown files (`.md`) with JSON frontmatter:

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

## Options Overview

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `category` | string | No | UI category |
| `description` | string | No | Short description |
| `icon` | string | No | Material icon name |
| `input` | string | No | Input description |
| `output` | string | No | Output description |
| `ai` | string | No | AI backend |
| `model` | string | No | Specific model (optional) |
| `allowed_mcp` | string | No | Allowed MCP servers |
| `allowed_tools` | array | No | Tool whitelist |
| `blocked_tools` | array | No | Tool blacklist |
| `tool_mode` | string | No | Security mode (`full`, `read_only`) |
| `settings_file` | string | No | Path to agent-specific permissions |
| `filesystem` | object | No | Filesystem restrictions |
| `knowledge` | string | No | Knowledge pattern |
| `inputs` | array | No | Pre-inputs dialog |
| `prefetch` | array | No | Load data before agent start |
| `tool` | object | No | Agent-as-Tool definition |
| `voice_hotkey` | string | No | System-wide hotkey |
| `next_agent` | string | No | Auto-chaining: next agent |
| `pass_result_to_next` | boolean | No | Pass result to next agent |
| `next_agent_inputs` | object | No | Additional inputs for next agent |
| `order` | integer | No | Sort order |
| `enabled` | boolean | No | Agent active (default: true) |
| `hidden` | boolean | No | Hide from UI |
| `use_anonymization_proxy` | boolean | No | PII anonymization |

---

## UI & Display Options

### `category`

Groups the agent in the WebUI sidebar.

**Type:** `string`
**Default:** `"chat"`

**Available categories:**

| ID | Label | Icon |
|----|-------|------|
| `chat` | Chat | chat |
| `kommunikation` | Communication | forum |
| `finance` | Finance | account_balance |
| `sales` | Sales & Marketing | storefront |
| `system` | System | smart_toy |

**Single category:**
```json
"category": "finance"
```

**Multiple categories (pipe-separated):**
```json
"category": "finance|sales"
```

The agent then appears under both "Finance" and "Sales & Marketing".

### `description`

Short description of the agent (1 sentence). Shown in the agent tile.

**Type:** `string`

```json
"description": "Erstellt Angebote aus Kontaktdaten"
```

### `icon`

Material icon name for the agent tile.

**Type:** `string`
**Icons:** [Material Icons](https://fonts.google.com/icons)

```json
"icon": "request_quote"
```

**Commonly used icons:**

| Icon | Use |
|------|-----|
| `reply` | Reply to email |
| `receipt_long` | Invoices |
| `request_quote` | Quotes |
| `credit_card` | Credit cards |
| `support_agent` | Support |
| `help_center` | Help |
| `content_copy` | Duplicates |
| `folder_open` | Files |

### `input` / `output`

Description of input and output with optional icon.

**Type:** `string`
**Format:** `:icon: Text`

```json
"input": ":mail: E-Mail",
"output": ":edit: Entwurf"
```

**Icon mapping:**

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

Sort order in the UI. Lower values appear higher up.

**Type:** `integer`
**Default:** `50`

```json
"order": 10
```

### `enabled`

Enables/disables the agent. Disabled agents do not appear in the UI.

**Type:** `boolean`
**Default:** `true`

```json
"enabled": false
```

### `hidden`

Hides the agent from the WebUI, but it remains available (e.g. for automated workflows).

**Type:** `boolean`
**Default:** `false`

```json
"hidden": true
```

**Use case:** Agents that are only called by email watchers or other agents.

---

## AI Backend Options

### `ai`

The AI backend for this agent.

**Type:** `string`
**Default:** Backend listed under `default_ai` in `backends.json` (system default: `"gemini"`)

**Available backends:**

| Backend | Description | Price/1M token |
|---------|-------------|----------------|
| `claude_sdk` | Claude Agent SDK (default model: Opus 4.6, requires `[claude-sdk]` extra) | $15/$75 (Opus) |
| `gemini` | Google Gemini 2.5 Pro | $1.25/$10 |
| `gemini_flash` | Google Gemini 2.5 Flash | $0.30/$2.50 |
| `gemini_3` | Google Gemini 3 Pro (preview) | $2/$12 |
| `gemini_3_flash` | Google Gemini 3 Flash (preview) | $0.50/$3 |
| `openai` | OpenAI GPT API (default model: `gpt-5`) | $1.25/$10 |
| `mistral` | Mistral API | $2/$6 |
| `qwen` | Qwen via Ollama | free |

```json
"ai": "gemini"
```

### `model`

Specific AI model (optional). Overrides the backend's default model.

**Type:** `string`
**Default:** Backend-dependent (`claude-opus-4-6` for claude_sdk)

**Available models (Claude):**

| Model ID | Description | Price/1M token |
|----------|-------------|----------------|
| `claude-opus-4-6` | Claude Opus 4.6 (default) | $15/$75 |
| `claude-sonnet-4-5-20250929` | Claude Sonnet 4.5 | $3/$15 |
| `claude-haiku-4-5-20251001` | Claude Haiku 4.5 | $0.80/$4 |

```json
"model": "claude-sonnet-4-5-20250929"
```

**Note:** Use only when a model other than the default is needed.

### `use_anonymization_proxy` / `anonymize`

Enables PII anonymization (names, emails, etc.) in tool responses.

**Type:** `boolean`
**Default:** `false`

```json
"anonymize": true
```

Or alternatively (older key, also supported):
```json
"use_anonymization_proxy": true
```

**Priority logic (centrally controlled):**

The anonymization decision follows a fixed priority:

| # | Condition | Result | Source |
|---|-----------|--------|--------|
| 0 | **Expert Override** via context menu | OFF | expert-override |
| 1 | Agent frontmatter `anonymize: false` | OFF | agent-off |
| 2 | Agent frontmatter `anonymize: true` + global UI OFF | OFF | global-off |
| 3 | Agent frontmatter `anonymize: true` + global UI ON | ON | agent-on |
| 4 | No agent setting + global UI OFF | OFF | global-off |
| 5 | No agent setting + global UI ON + backend ON | ON | backend |
| 6 | No agent setting + global UI ON + backend OFF | OFF | backend-off |

**Important:**
- **Expert Override** [044]: Right-click on agent tile > "Run without anonymization" (only visible in Expert Mode). Has the highest priority and overrides all other settings.
- The **global UI setting** (Settings Dialog > Anonymization Toggle) takes precedence over backend defaults
- An agent can only **enable** anonymization when global is ON
- An agent can **always disable** anonymization with `anonymize: false`

**What is anonymized?**

| Content type | Anonymized? | Reason |
|--------------|-------------|--------|
| **Agent prompt** (from `.md` file) | No | System instructions contain folder names, workflow terms |
| **User input** (after `### Input:`) | Yes | External data (emails, PDFs) |
| **Tool results** | Yes (via proxy) | External data |
| **Confirmation dialogs** | Yes | Contain user data |

**Technical background:**

The agent prompt (before the `### Input:` marker) is NOT anonymized. This prevents false positives for German terms like "Done-Ordner", "NIEMALS", "Ganztaegig", which Presidio incorrectly recognizes as person names.

Only the input area (after `### Input:`) with real user data is anonymized. For continuation prompts (after CONFIRMATION_NEEDED), the agent content is also placed before the marker.

**Note:** Increases security with external AI backends (Gemini, OpenAI).

### `sdk_mode`

SDK mode for Claude SDK backend.

**Type:** `string`
**Default:** `"extended"`
**Only for:** `claude_sdk` backend

| Mode | Description |
|------|-------------|
| `extended` | Extended SDK features (sessions, AskUserQuestion) - **default** |
| `legacy` | Old behavior (no new features) |

```json
"sdk_mode": "legacy"  // only if old behavior is desired
```

**Features in extended mode:**
- **Sessions:** SDK session ID is saved for resume capability
- **AskUserQuestion:** SDK tool for native dialogs (instead of QUESTION_NEEDED marker)
- **Structured Outputs:** `output_schema` for JSON-schema-validated responses

### `output_schema`

JSON schema for structured responses (only `sdk_mode: extended`).

**Type:** `object` (JSON schema)
**Default:** `null`
**Only for:** `claude_sdk` backend with `sdk_mode: extended`

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

Allowed MCP servers as pipe-separated regex pattern.

**Type:** `string`
**Default:** All MCP servers allowed

```json
"allowed_mcp": "outlook|billomat|clipboard"
```

**Available MCP servers:**

| Server | Description |
|--------|-------------|
| `outlook` | Email, calendar (local Outlook COM) |
| `msgraph` | Microsoft Graph API (Mail, Calendar, Teams) |
| `gmail` | Gmail and Google Calendar |
| `imap` | IMAP/SMTP for generic mail providers |
| `billomat` | Customers, quotes, invoices |
| `lexware` | Lexware Office API (beta) |
| `sevdesk` | sevDesk API (beta) |
| `userecho` | Support tickets |
| `sepa` | SEPA XML transfers, CAMT.052 read |
| `filesystem` | File operations |
| `pdf` | PDF manipulation |
| `excel` | Excel `.xlsx` read/write |
| `clipboard` | Clipboard |
| `datastore` | SQLite data store |
| `browser` | Browser automation (CDP) |
| `paperless` | Paperless-ngx DMS |
| `ecodms` | ecoDMS archive |
| `telegram` | Telegram Bot API (beta) |
| `linkedin` | LinkedIn (beta) |
| `instagram` | Instagram (beta) |
| `chart` | Chart/graph generation |
| `project` | Claude Code CLI in other projects |
| `desk` | DeskAgent system control |

### `allowed_tools`

Explicit whitelist of individual tools (in addition to `allowed_mcp`).

**Type:** `array[string]`

```json
"allowed_tools": ["fs_read_file", "fs_list_directory", "fs_get_file_info"]
```

**Use case:** Read-only agents that may only use specific tools.

### `blocked_tools`

Blacklist of tools to block.

**Type:** `array[string]`

```json
"blocked_tools": ["fs_delete_file", "fs_write_file"]
```

**Security model (defense in depth):**

```
Layer 1: allowed_mcp     → Which MCP servers are loaded
Layer 2: allowed_tools   → Whitelist of specific tools
Layer 3: blocked_tools   → Blacklist of tools
Layer 4: filesystem      → Path-based restrictions
```

### `filesystem`

Path-based restrictions for filesystem operations.

**Type:** `object`

```json
"filesystem": {
  "write": ["{{EXPORTS_DIR}}/**"]
}
```

**Sub-fields:**

| Field | Type | Description |
|-------|------|-------------|
| `write` | array[string] | Allowed paths for write operations |

**Affected tools:**
- `fs_write_file` - Write file
- `fs_copy_file` - Copy file (target path is checked)
- `fs_delete_file` - Delete file

**Path syntax:**

| Pattern | Description | Example |
|---------|-------------|---------|
| `{{EXPORTS_DIR}}/**` | Recursive, all subfolders | `exports/invoices/2025/file.pdf` allowed |
| `{{TEMP_DIR}}/*` | Only direct files | `temp/file.txt` allowed, `temp/sub/file.txt` blocked |
| `{{WORKSPACE_DIR}}/data.json` | Exact path | Only this single file |

**Placeholders:** All path placeholders are supported (see below).

**Security:**
- Without `filesystem.write` → All paths allowed (backward-compatible)
- With `filesystem.write: []` → No write operations allowed
- Paths are normalized and checked against the whitelist
- Blocked accesses are logged in the system log

**Example - Chat agent only in exports:**

```json
{
  "ai": "claude_sdk",
  "allowed_mcp": "outlook|filesystem|clipboard",
  "filesystem": {
    "write": ["{{EXPORTS_DIR}}/**"]
  }
}
```

**Example - Read-only agent:**

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

Security mode for tool execution. Restricts which tool categories are allowed.

**Type:** `string`
**Default:** `"full"`
**Backend:** All (claude_sdk, gemini, openai, mistral)

| Mode | Description | Allowed tools |
|------|-------------|---------------|
| `"full"` | All tools allowed (default) | Everything |
| `"read_only"` | Only read operations | READ_ONLY_TOOLS |
| `"write_safe"` | Write, but no delete | READ_ONLY_TOOLS + write tools (without DESTRUCTIVE_TOOLS) |

**Read-only mode blocks:**
- Bash tool (completely, only claude_sdk)
- Write, Edit SDK tools (only claude_sdk)
- All MCP tools NOT defined in `READ_ONLY_TOOLS`

**Read-only mode allows:**
- Read, Grep, Glob, WebFetch, WebSearch SDK tools (claude_sdk)
- MCP tools from `READ_ONLY_TOOLS` (explicit whitelist)

**Write-safe mode:**
- All READ_ONLY_TOOLS
- Write operations (create, update, write)
- No delete operations (delete, remove, clear)

**Example - Secure email analysis (read_only):**

```json
{
  "ai": "claude_sdk",
  "tool_mode": "read_only",
  "allowed_mcp": "outlook",
  "use_anonymization_proxy": true
}
```

This agent can **read** emails but not send/delete/move them.

**Example - Create invoices (write_safe):**

```json
{
  "ai": "gemini",
  "tool_mode": "write_safe",
  "allowed_mcp": "billomat"
}
```

This agent can **create** invoices but not **delete** them.

**Security:**
- Tools that are not explicitly categorized as read-only are blocked in read_only (safe default)
- Protects against prompt injection: external email content cannot trigger write operations
- Bash is completely blocked in read_only (no shell exploits possible)

**Combination with other security options:**

```json
{
  "ai": "claude_sdk",
  "tool_mode": "read_only",
  "allowed_mcp": "paperless",
  "use_anonymization_proxy": true,
  "filesystem": {"write": []}
}
```

This is the safest configuration for agents that process external data.

### `settings_file`

Path to an agent-specific Claude Code settings file for Bash permissions.

**Type:** `string` (file path)
**Default:** `null` (uses global `.claude/settings.json`)
**Backend:** Only `claude_sdk`

```json
"settings_file": "config/agent-permissions.json"
```

**Use:**
Enables per-agent Bash permissions instead of global settings.

**Example settings file:**

```json
{
  "permissions": {
    "allow": ["Bash(git:*)"],
    "ask": ["Bash(npm:*)"],
    "deny": ["Bash(rm -rf:*)"]
  }
}
```

**Path resolution:**
- Relative paths: relative to project root (`PROJECT_DIR`)
- Absolute paths: used directly

**Combination with tool_mode:**

```json
{
  "ai": "claude_sdk",
  "tool_mode": "read_only",
  "settings_file": "config/readonly-permissions.json"
}
```

**Note:** `settings_file` overrides the global settings from `.claude/settings.json` for this agent.

---

## Knowledge

### `knowledge`

Pattern for the knowledge base (regex).

**Type:** `string`
**Default:** All `knowledge/**/*.md` are loaded

```json
"knowledge": "company|products"
```

**Pattern syntax:**

| Pattern | Description | Match |
|---------|-------------|-------|
| `company` | File or subfolder | `company.md` |
| `linkedin` | Subfolder | `linkedin/*.md` |
| `company\|products` | Regex OR | `company.md`, `products.md` |
| `^(?!linkedin)` | Negative regex | Everything EXCEPT `linkedin/` |
| `""` (empty) | Loads NOTHING | - |
| missing/`null` | Loads ALL | All `.md` files |
| `@path/file.md` | External file | Outside `knowledge/` |
| `@deskagent/docs/` | External folder | Recursive, all `.md` |

**Examples:**

```json
// Only company and product info
"knowledge": "company|products"

// LinkedIn subfolder
"knowledge": "linkedin"

// External documentation
"knowledge": "@deskagent/documentation/en/"

// Load nothing (performance)
"knowledge": ""
```

---

## Pre-Inputs Dialog

### `inputs`

Defines a dialog for data entry before agent start.

**Type:** `array[object]`

```json
"inputs": [
  {"name": "files", "type": "file", "label": "Dateien", "required": true, "multiple": true, "accept": ".pdf"},
  {"name": "description", "type": "text", "label": "Beschreibung", "placeholder": "Optional..."}
]
```

#### Input Fields (all types)

| Property | Type | Description |
|----------|------|-------------|
| `name` | string | Field ID for `{{INPUT.name}}` placeholder |
| `type` | `"file"` \| `"text"` | Input type |
| `label` | string | Display label in dialog |
| `required` | boolean | Required field (default: false) |

#### File-Specific (`type: "file"`)

| Property | Type | Description |
|----------|------|-------------|
| `multiple` | boolean | Allow multiple files |
| `accept` | string | File filter (e.g. `.pdf,.docx`) |
| `folders` | boolean | Allow folder selection |

#### Text-Specific (`type: "text"`)

| Property | Type | Description |
|----------|------|-------------|
| `default` | string | Default value |
| `placeholder` | string | Placeholder text |
| `multiline` | boolean | Multi-line text field |
| `rows` | number | Number of rows (default: 8) |

#### Use in Prompt

```markdown
## Ausgewählte Dateien
{{INPUT.files}}

## Beschreibung
{{INPUT.description}}
```

**UI behavior:**
- Agents with inputs show an `upload_file` badge on the tile
- Click opens a dialog with drag & drop for files
- Files are passed as absolute paths

---

## Pre-fetching (Performance)

### `prefetch`

Loads data **before** agent start to reduce response time.

**Type:** `array[string]`
**Default:** `[]` (no prefetch)

```json
"prefetch": ["selected_email"]
```

**Available prefetch types:**

| Type | Tool | Placeholder | Description |
|------|------|-------------|-------------|
| `selected_email` | `outlook_get_selected_email` | `{{PREFETCH.email}}` | Selected email (Outlook Desktop) |
| `selected_emails` | `outlook_get_selected_emails` | `{{PREFETCH.emails}}` | All selected emails |
| `graph_selected_email` | `graph_get_email` | `{{PREFETCH.email}}` | Email via Microsoft Graph |
| `clipboard` | `clipboard_get_clipboard` | `{{PREFETCH.clipboard}}` | Clipboard content |

**Performance benefit:**

Without prefetch:
```
Agent starts → AI decides which tool → Tool is called → AI processes
              ~200ms                 ~300ms          ~500ms
```

With prefetch:
```
Agent starts ─┬─ Prefetch email (~500ms) ─┐
              └─ Load agent config         ├─→ AI processes immediately
                  (~200ms)                  ┘
```

**Time saved:** ~500ms (email already in context)

**Use in prompt:**

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

**Note:** The email is formatted automatically with subject, sender, date, and body.

**Error handling:**
- If prefetch fails (e.g. no email selected), the placeholder contains an error message
- The agent continues and can react to the error

**Combinable with:**
- `inputs`: Prefetch + user dialog
- `knowledge`: Prefetch + knowledge base
- `tool_mode`: Prefetch + security restrictions

---

## Voice Hotkey

### `voice_hotkey`

System-wide voice hotkey for this agent.

**Type:** `string`
**Format:** Modifier+Key (e.g. `Ctrl+Shift+O`)

```json
"voice_hotkey": "Ctrl+Shift+Backspace"
```

**Workflow:**
1. Focus email/document
2. Press hotkey → recording starts
3. Speak instruction
4. Press hotkey again → agent starts with transcription

**Multiple agents can have different hotkeys:**

```json
// reply_email.md
"voice_hotkey": "Ctrl+Shift+Backspace"

// summarize.md
"voice_hotkey": "Ctrl+Shift+S"
```

**Example: Voice Task Agent (speech to task file):**

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

The transcription is passed automatically as `_context` to the agent and can be referenced in the prompt.

---

## Agent-as-Tool

### `tool`

Makes the agent available as a structured MCP tool for other agents.

**Type:** `object`

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

#### Tool Schema

| Field | Type | Description |
|-------|------|-------------|
| `tool.name` | string | Tool name (snake_case) |
| `tool.description` | string | Description for the LLM |
| `tool.parameters` | object | Parameter definitions |
| `tool.returns` | object | Return schema (documentation) |

#### Parameter Definition

```json
"parameters": {
  "param_name": {
    "type": "string",       // string, array, object, integer, boolean
    "description": "...",
    "required": true
  }
}
```

#### Complete Example

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

**Advantages:**
- LLM sees structured parameters instead of generic `desk_run_agent()`
- Required parameters are validated
- Supervisor pattern: Claude orchestrates, Gemini processes

---

## Auto-Chaining

Deterministic, system-controlled agent chaining. After successful completion of an agent, the next one is started automatically.

### `next_agent`

Name of the agent started automatically after successful completion.

**Type:** `string`

```json
"next_agent": "step2"
```

### `pass_result_to_next`

Passes the result of the current agent as `previous_result` to the next.

**Type:** `boolean`
**Default:** `false`

```json
"pass_result_to_next": true
```

### `next_agent_inputs`

Additional inputs for the next agent.

**Type:** `object`

```json
"next_agent_inputs": {
  "mode": "verbose",
  "limit": 10
}
```

### Example: Mail Sorting Chain

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
User starts: classify_spam
  ↓
classify_spam → SUCCESS
  ↓
System starts automatically: classify_invoices
  ↓
classify_invoices → SUCCESS
  ↓
End
```

**Advantages:**
- Deterministic - system controls, not the AI
- Crash-safe - the chain stops on error
- Debuggable - clear order in the log

---

## Placeholders in the Prompt

The following placeholders are replaced on load:

### Date Placeholders

| Placeholder | Example | Description |
|-------------|---------|-------------|
| `{{TODAY}}` | 29.12.2025 | Today's date (DD.MM.YYYY) |
| `{{DATE}}` | 29.12.2025 | Alias for TODAY |
| `{{YEAR}}` | 2025 | Current year |
| `{{DATE_ISO}}` | 2025-12-29 | ISO format (YYYY-MM-DD) |

### Path Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{{EXPORTS_DIR}}` | Export directory (`workspace/exports/`) |
| `{{TEMP_DIR}}` | Temp directory (`workspace/.temp/`) |
| `{{LOGS_DIR}}` | Log directory (`workspace/.logs/`) |
| `{{WORKSPACE_DIR}}` | Workspace directory (`workspace/`) |
| `{{KNOWLEDGE_DIR}}` | Knowledge directory (user folder with fallback to system) |
| `{{CUSTOM_KNOWLEDGE_DIR}}` | User knowledge directory (always `knowledge/`, no fallback) |
| `{{AGENTS_DIR}}` | Agents directory (user folder with fallback) |
| `{{CONFIG_DIR}}` | Config directory (`config/`) |
| `{{PROJECT_DIR}}` | Project root (`aiassistant/`) |
| `{{DESKAGENT_DIR}}` | DeskAgent directory (`deskagent/`) |

### Input Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{{INPUT.name}}` | Value from pre-inputs dialog |

### Prefetch Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{{PREFETCH.email}}` | Prefetched email (formatted) |
| `{{PREFETCH.emails}}` | Prefetched emails (multiple) |
| `{{PREFETCH.clipboard}}` | Prefetched clipboard content |

### Procedure Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{{PROCEDURE:name}}` | Content from `agents/procedures/name.md` |

---

## Merge Priorities

Configuration is merged from multiple sources:

```
1. Agent .md frontmatter        ← Highest priority
2. config/agents.json           ← User override
3. deskagent/config/agents.json ← System default
```

**Example:** If `ai: "gemini"` is in the frontmatter, it overrides any value from `agents.json`.

---

## Complete Example

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

## See Also

- [docs/creating-agents.md](creating-agents.md) - Agent creation guide
- [docs/agent-as-tool-architecture.md](agent-as-tool-architecture.md) - Supervisor pattern
- [docs/mcp-tools.md](mcp-tools.md) - Available MCP tools
