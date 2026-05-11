# Configuration Reference

Complete reference for modular configuration files in `config/`.

## Config File Structure

```
config/
├── system.json      # UI, Logging, Email Watchers
├── backends.json    # AI Backend API Keys
├── apis.json        # External APIs (Billomat, UserEcho, SEPA)
└── agents.json      # Skills & Agents Definitions
```

---

## system.json

System-wide settings for UI, logging, and automation.

```json
{
  "context": "Meine Firma GmbH",
  "console_logging": true,
  "developer_mode": true,
  "global_ai_override": null,
  "content_mode": "custom",
  "clear_temp_on_start": true,
  "ui": {
    "use_webview": false,
    "webview_width": 900,
    "webview_height": 1000
  },
  "anonymization": {
    "log_anonymization": true
  },
  "email_watchers": {
    "rules": [...]
  },
  "github_repository": "https://github.com/...",
  "streamdeck_path": "C:\\Program Files\\Elgato\\StreamDeck\\StreamDeck.exe"
}
```

### General Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `clear_temp_on_start` | `true` | Delete `.temp/` folder on startup |
| `console_logging` | `true` | Enable console output |
| `developer_mode` | `false` | Show debug info |
| `global_ai_override` | `null` | Force all agents to use a specific AI backend. Set to a backend ID (e.g. `"gemini"`) or `null`/`"auto"` to use the default resolution logic. |

### Global AI Override

Override the AI backend for all agents from Settings > Preferences.

```json
{
  "global_ai_override": "gemini"
}
```

| Value | Behavior |
|-------|----------|
| `null` | Auto mode - uses agent frontmatter `ai` field, then `default_ai` |
| `"auto"` | Same as `null` |
| `"claude_sdk"` | Force Claude Agent SDK for all agents |
| `"gemini"` | Force Gemini for all agents |
| `"gemini_flash"` | Force Gemini Flash for all agents |
| Any backend ID | Force that backend for all agents |

**Resolution priority (highest to lowest):**
1. Per-call override (`body.backend` in API request)
2. Global AI Override (`global_ai_override` in system.json)
3. Agent frontmatter (`ai` field)
4. `default_ai` from backends.json
5. First available backend (fallback)

**API Endpoints:**
- `GET /config/backend_override` - Get current override and available backends
- `POST /config/backend_override` - Set override (`{"backend": "gemini"}` or `{"backend": "auto"}`)

### Demo Mode

Run agents with simulated data without calling real APIs.

```json
"demo_mode": {
  "enabled": true,
  "mocks_dir": "workspace/mocks"
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable demo mode |
| `mocks_dir` | `workspace/mocks` | Custom path for user mock files |

**Environment Variable:** `DESKAGENT_DEMO_MODE=1` (overrides config)

**Mock Files:** JSON files in `deskagent/mocks/` (defaults) or `workspace/mocks/` (user overrides).

### UI Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `use_webview` | `false` | Use native window instead of browser |
| `webview_width` | `900` | Window width in pixels |
| `webview_height` | `1000` | Window height in pixels |

### Anonymization Settings

```json
"anonymization": {
  "enabled": true,
  "pii_types": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "URL"],
  "language": "de",
  "log_anonymization": true
}
```

### Anonymization Proxy Settings

Fine-tune which tools get anonymized in the dynamic proxy.

```json
"anonymization_proxy": {
  "no_anonymize_output": ["delete_email", "move_email"],
  "no_deanonymize_input": ["open_url"]
}
```

### Email Watchers

Automatic rules for incoming emails.

```json
"email_watchers": {
  "enabled": false,
  "check_interval": 60,
  "rules": [
    {
      "name": "Newsletter Filter",
      "enabled": true,
      "match": { "from_pattern": "(newsletter|noreply)@" },
      "actions": [{ "type": "move_to_folder", "folder": "ToDelete" }]
    }
  ]
}
```

---

## backends.json

AI backend API keys and configurations.

```json
{
  "ai_backends": {
    "gemini": {
      "api_key": "AIza..."
    },
    "claude": {
      "path": "path/to/claude.cmd"
    },
    "claude_api": {
      "api_key": "sk-ant-..."
    }
  }
}
```

### Available Backend Types

| Backend | Type | Description | Price/1M Token |
|---------|------|-------------|----------------|
| `claude_sdk` | `claude_agent_sdk` | Agent SDK + MCP Tools (recommended) | $3/$15 |
| `gemini` | `gemini_adk` | Google Gemini 2.5 Pro | $1.25/$10 |
| `gemini_flash` | `gemini_adk` | Google Gemini 2.5 Flash | $0.30/$2.50 |
| `gemini_3` | `gemini_adk` | **Google Gemini 3 Pro** (Preview, better tool handling) | $2/$12 |
| `gemini_3_flash` | `gemini_adk` | **Google Gemini 3 Flash** (Preview) | $0.50/$3 |
| `openai` | `openai_api` | OpenAI GPT API (gpt-4o, gpt-4o-mini) | $2.50/$10 |
| `mistral` | `openai_api` | Mistral API (OpenAI-compatible) | $2/$6 |
| `qwen` | `qwen_agent` | Qwen via Ollama | free |
| `mistral_local` | `ollama_native` | Mistral via Ollama (local) | free |
| `claude` | `claude_cli` | Claude Code CLI | $3/$15 |

### Claude Agent SDK Options

```json
"claude_sdk": {
  "type": "claude_agent_sdk",
  "permission_mode": "bypassPermissions",
  "use_anonymization_proxy": true,
  "mcp_transport": "inprocess"
}
```

**Permission Modes:**
- `"default"` - Ask before each tool call
- `"acceptEdits"` - Auto-approve file edits
- `"bypassPermissions"` - Auto-approve all tools

**MCP Transport Modes:**
- `"inprocess"` - In-process SDK MCP (most stable, no network)
- `"stdio"` - Subprocess (default)
- `"sse"` - SSE HTTP proxy
- `"streamable-http"` - HTTP proxy

---

## .claude/settings.json

Claude Code native permission settings. These are loaded automatically when using `claude_sdk` backend.

```json
{
  "permissions": {
    "allow": [
      "Bash(git:*)",
      "Bash(npm install:*)"
    ],
    "ask": [
      "Bash"
    ],
    "deny": [
      "Bash(rm -rf:*)"
    ]
  }
}
```

**Pattern Format:** `Tool(pattern:*)`

| Example | Description |
|---------|-------------|
| `Bash(git:*)` | Allow all git commands |
| `Bash(npm install:*)` | Allow npm install |
| `Bash(rm -rf:*)` | Deny rm -rf commands |

**Location:** `.claude/settings.json` in project root.

### Per-Agent Settings

Agents can use custom settings via `settings_file` frontmatter:

```json
{
  "ai": "claude_sdk",
  "settings_file": "config/agent-readonly-permissions.json"
}
```

This allows different permission levels for different agents.

---

## apis.json

External API credentials.

```json
{
  "billomat": {
    "id": "your-billomat-id",
    "api_key": "your-api-key",
    "app_id": "...",
    "app_secret": "..."
  },
  "userecho": {
    "subdomain": "your-subdomain",
    "api_key": "your-api-key"
  },
  "sepa": {
    "meinefirma": {
      "name": "Meine Firma GmbH",
      "iban": "DE...",
      "bic": "...",
      "currency": "EUR"
    },
    "private": {
      "name": "Personal Name",
      "iban": "DE...",
      "bic": "...",
      "currency": "EUR"
    },
    "default": "meinefirma"
  }
}
```

### SEPA Configuration

Multi-account support for SEPA transfers.

| Field | Description |
|-------|-------------|
| `name` | Account holder name |
| `iban` | IBAN (validated) |
| `bic` | BIC/SWIFT code |
| `currency` | Currency code (default: EUR) |
| `default` | Default account key |

---

## agents.json (Legacy/Fallback)

> **Note:** `agents.json` is the **old way**. The recommended way is configuration directly in the **JSON frontmatter of the .md file**.
>
> See **[doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md)** for the complete reference.

This file is only used as fallback/override for agents without frontmatter.

```json
{
  "skills": {
    "skill_name": { ... }
  },
  "agents": {
    "agent_name": { ... }
  }
}
```

### Recommended Way: Frontmatter in .md Files

Agents are defined in Markdown files (`agents/*.md`) with JSON frontmatter:

```markdown
---
{
  "category": "finance",
  "description": "Erstellt Rechnung aus E-Mail",
  "ai": "gemini",
  "allowed_mcp": "billomat|outlook",
  "order": 50
}
---

# Agent: Rechnung erstellen

Agent-Anweisungen hier...
```

**Advantages:**
- Everything in one file (configuration + prompt)
- Easier to version
- No synchronization between files needed

### Merge Priority

```
1. Agent .md frontmatter        ← Highest priority (recommended!)
2. config/agents.json           ← User override (legacy)
3. deskagent/config/agents.json ← System default
```

### Legacy: agents.json Format

If needed (e.g. for skills without their own .md file):

```json
"agent_name": {
  "description": "What this agent does",
  "ai": "gemini",
  "enabled": true,
  "allowed_mcp": "outlook|billomat"
}
```

See **[doc-agent-frontmatter-reference.md](doc-agent-frontmatter-reference.md)** for complete options.

### Knowledge Pattern Examples

- `"company|products"` - Load files matching "company" OR "products"
- `"^(?!linkedin)"` - Load all EXCEPT "linkedin"
- `"faq"` - Load only files containing "faq"
- (no pattern) - Load ALL .md files

### MCP Server Names

| Server | Description |
|--------|-------------|
| `outlook` | Email, Calendar (local COM) |
| `msgraph` | Microsoft Graph API |
| `gmail` | Gmail, Google Calendar |
| `billomat` | Customers, Invoices |
| `lexware` | Lexware Office API |
| `userecho` | Support Tickets |
| `sepa` | SEPA Transfers |
| `filesystem` | File operations |
| `pdf` | PDF manipulation |
| `clipboard` | Clipboard access |
| `datastore` | SQLite storage |
| `browser` | Browser automation |
| `paperless` | Paperless-ngx DMS |
| `ecodms` | ecoDMS archive |
| `project` | Claude Code CLI |
| `desk` | DeskAgent control |

See **[doc-mcp-tools.md](doc-mcp-tools.md)** for all tool parameters.

---

## Quick Reference

| File | Purpose | Key Settings |
|------|---------|--------------|
| `system.json` | System config | UI, logging, watchers |
| `backends.json` | AI backends | API keys, models |
| `apis.json` | External APIs | Billomat, UserEcho, SEPA |
| `agents.json` | Workflows | Skills, agents, MCP access |
