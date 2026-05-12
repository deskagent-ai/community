# DeskAgent + Claude Desktop / Claude Code Integration

DeskAgent can be registered as an **MCP hub** inside Claude Desktop and Claude Code (Cowork). This makes all DeskAgent tools (email, invoicing, DMS, SEPA, PDF, Excel, ...) directly available inside Claude without Claude having to know about each individual MCP server.

> **Architecture in one sentence:** Claude Desktop launches the DeskAgent proxy ([../mcp/anonymization_proxy_mcp.py](../mcp/anonymization_proxy_mcp.py)) as a single MCP server. The proxy loads all enabled DeskAgent MCPs internally and bundles them behind a shared anonymization and security layer.

---

## Prerequisites

| Requirement | Details |
|---|---|
| DeskAgent installed | Windows: via installer, macOS: via `.dmg`, or source build (this repo) |
| Claude Desktop installed | [claude.ai/download](https://claude.ai/download) |
| Configured MCPs | At least one plugin (Outlook, Billomat, ...) configured so the hub has something to expose |

For **Claude Code** additionally:

| Requirement | Details |
|---|---|
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` or the VSCode extension |

---

## Automatic configuration (recommended)

The fastest path is via the DeskAgent UI.

### Through the UI (Settings → Integrations)

1. Open DeskAgent → **Settings** (gear icon) → **Integrations** tab
2. In the **Claude Desktop / Cowork** section click **Set up**
3. Confirmation dialog: DeskAgent will
   - locate the Claude Desktop config file (see [Config paths](#config-paths))
   - read the existing MCP server entries (they stay untouched)
   - add a `deskagent` entry
   - write the file back
4. **Restart Claude Desktop** (quit the app completely, then reopen)
5. In Claude Desktop you can now see DeskAgent under the hammer icon next to the chat input

What the UI does behind the scenes is the `POST /claude-desktop/setup` endpoint in [../scripts/assistant/routes/system.py](../scripts/assistant/routes/system.py). It calls `desk_setup_claude_desktop(transport="stdio")` from [../mcp/desk/claude_desktop.py](../mcp/desk/claude_desktop.py).

### Through the `desk` MCP tool (from inside Claude)

If DeskAgent is already running as an MCP server, Claude can register itself:

```
Use the desk_setup_claude_desktop tool to configure the connection.
```

Available tools in the `desk` MCP:

| Tool | Purpose |
|---|---|
| `desk_setup_claude_desktop(transport="stdio"\|"http")` | Register DeskAgent in `claude_desktop_config.json` |
| `desk_check_claude_desktop()` | Check whether DeskAgent is registered and show details |
| `desk_remove_claude_desktop()` | Remove the `deskagent` entry again |
| `desk_setup_claude_code(scope="user"\|"project")` | Register for Claude Code (`~/.claude.json` or `.mcp.json`) |

---

## Manual configuration

If auto-setup is not an option (portable install, shared machine, custom tweaks), the config file can be edited directly.

### Config paths

| Platform | File |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |
| Claude Code (user scope) | `~/.claude.json` |
| Claude Code (project scope) | `<project>/.mcp.json` |

### Variant A — stdio (standalone, no running DeskAgent server required)

Claude Desktop starts the DeskAgent proxy as a subprocess. DeskAgent itself does **not** need to be running.

> ⚠️ **Verify paths before pasting!** The paths below are **typical** values, but they vary per install variant (per-user vs. system-wide, default vs. custom install dir, source build vs. signed installer). The **most reliable approach**:
>
> 1. Run **auto-setup** once via the UI (Settings → Integrations → Set up)
> 2. Open `claude_desktop_config.json` and read the actual paths the installer wrote
> 3. Use those as your template
>
> The examples below are best-guess templates, not guaranteed constants.

**Schema (all platforms):**

```json
{
  "mcpServers": {
    "deskagent": {
      "command": "<PATH_TO_PYTHON>",
      "args": [
        "<DESKAGENT_DIR>/mcp/anonymization_proxy_mcp.py",
        "--session",
        "claude-desktop"
      ],
      "env": {
        "PYTHONPATH": "<DESKAGENT_DIR>/scripts",
        "DESKAGENT_SCRIPTS_DIR": "<DESKAGENT_DIR>/scripts",
        "DESKAGENT_WORKSPACE_DIR": "<WORKSPACE_DIR>",
        "DESKAGENT_CONFIG_DIR": "<CONFIG_DIR>",
        "ALLOWED_MCP_PATTERN": "outlook|billomat|filesystem|pdf"
      }
    }
  }
}
```

**Typical paths per platform** (verify on your own system):

| Placeholder | Windows (installer, `PrivilegesRequired=lowest`) | macOS (signed build) | Linux (source clone) |
|---|---|---|---|
| `<DESKAGENT_DIR>` | `%LOCALAPPDATA%\Programs\DeskAgent\deskagent`<br>(Inno Setup default, **not** `C:\Program Files\...`) | `/Applications/DeskAgent.app/Contents/Resources/deskagent` *(unverified)* | path to your `git clone` of this repo |
| `<PATH_TO_PYTHON>` | `<DESKAGENT_DIR>\python\python.exe` | `<DESKAGENT_DIR>/python/bin/python3` *(unverified)* | `<DESKAGENT_DIR>/venv/bin/python` |
| `<WORKSPACE_DIR>` | `<INSTALL_ROOT>\workspace` (on Windows this is **inside** the install dir — see [../scripts/paths.py](../scripts/paths.py)) | `~/Library/Application Support/DeskAgent/workspace` | `~/.local/share/deskagent/workspace` (or `<DESKAGENT_DIR>/workspace` for source clones) |
| `<CONFIG_DIR>` | `<INSTALL_ROOT>\config` | analog | analog |

> **Note on Windows path escaping:** values in `claude_desktop_config.json` must use **double backslashes** (`\\`) or forward slashes (`/`). The UI does this automatically.

| Field | Meaning |
|---|---|
| `command` | Path to embedded Python (in build output) or system Python |
| `args[0]` | Path to the proxy script |
| `--session claude-desktop` | Separates session state from the DeskAgent UI |
| `PYTHONPATH` | Must point at `<DESKAGENT_DIR>/scripts/` (see [doc-folder-structure.md](doc-folder-structure.md)) |
| `DESKAGENT_CONFIG_DIR` | User config (`apis.json`, `system.json`, ...) |
| `DESKAGENT_WORKSPACE_DIR` | Logs, temp, exports |
| `ALLOWED_MCP_PATTERN` | Pipe-separated whitelist (optional, default: all active MCPs) |

### Variant B — HTTP (shared hub, DeskAgent must be running)

Multiple clients (Claude Desktop, Claude Code, other MCP clients) share a running DeskAgent hub on `localhost:19001`.

```json
{
  "mcpServers": {
    "deskagent": {
      "type": "streamable-http",
      "url": "http://localhost:19001/mcp",
      "headers": {
        "Authorization": "Bearer <auth-token-from-system.json>"
      }
    }
  }
}
```

**Prerequisite:** the hub must be enabled in DeskAgent:

```json
// config/system.json
"claude_desktop": {
  "hub_enabled": true,
  "auth_token": "<auto-generated>",
  "port": 19001
}
```

The token is shown under **Settings → Integrations** or you can read it directly from `system.json`. It is generated on the first `desk_setup_claude_desktop(transport="http")` call (see `_generate_auth_token` in [../mcp/desk/claude_desktop.py](../mcp/desk/claude_desktop.py)).

### Claude Code (CLI) — manual

User scope (`~/.claude.json`) applies to all projects:

```json
{
  "mcpServers": {
    "deskagent": {
      "command": "<python>",
      "args": ["<deskagent>/mcp/anonymization_proxy_mcp.py", "--session", "claude-code"],
      "env": {
        "PYTHONPATH": "<deskagent>/scripts",
        "DESKAGENT_CONFIG_DIR": "<config-dir>",
        "DESKAGENT_WORKSPACE_DIR": "<workspace-dir>"
      }
    }
  }
}
```

Project scope uses the same schema in `<project>/.mcp.json`.

---

## stdio vs. HTTP — which transport?

| Criterion | stdio | http |
|---|---|---|
| DeskAgent app must be running | no | **yes** |
| Multiple clients share session | no (each client → own proxy) | **yes** |
| Live UI sync with DeskAgent (tasks, history) | limited | **yes** |
| Auth token required | no | yes (Bearer) |
| Reachable from a remote machine | no | localhost only (default) |
| Recommended for | Solo use, "set & forget" | Power users with hub + UI |

The UI default is **stdio** because it works without a running server.

---

## Which MCPs are exposed?

The selection follows a clear priority order (see `_get_configured_mcp_names` in [../mcp/desk/claude_desktop.py](../mcp/desk/claude_desktop.py)):

1. **Explicit whitelist** in `system.json`:
   ```json
   "claude_desktop": {
     "allowed_mcps": ["outlook", "billomat", "filesystem"]
   }
   ```
2. **Auto-detection** (fallback):
   - Scans `deskagent/mcp/` and `plugins/*/mcp/`
   - Excludes MCPs marked `"enabled": false` in `apis.json`
   - Plugin MCPs only when API keys / credentials are configured

The UI offers a multi-select for `allowed_mcps` (endpoint: `GET/POST /claude-desktop/allowed-mcps`).

> **Security note:** the fewer MCPs you expose, the smaller the attack surface for compromised prompts. See [doc-anonymization.md](doc-anonymization.md) for the relevant security model.

---

## Checking status

### From DeskAgent

`GET /claude-desktop/status` returns:

```json
{
  "hub_enabled": false,
  "auth_token": "",
  "port": 19001,
  "configured_in_claude": true,
  "config_path": "C:\\Users\\<user>\\AppData\\Roaming\\Claude\\claude_desktop_config.json",
  "proxy_running": false,
  "allowed_mcps": ["outlook", "billomat"]
}
```

### From Claude

```
desk_check_claude_desktop()
```

Returns transport type, config path, filter pattern.

### Manually in Claude Desktop

Hammer icon (🔨) below the chat input → dropdown lists all MCP servers. `deskagent` must be listed there.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `deskagent` does not show up in Claude Desktop | Claude Desktop not restarted | Quit the app **completely** (tray icon too), then start again |
| "Failed to spawn MCP server" | Wrong Python path in `command` | Check the paths in `claude_desktop_config.json`, re-run auto-setup if unsure |
| Tools visible but "No such tool" error | `ALLOWED_MCP_PATTERN` filter excludes the tool | Extend or remove `allowed_mcps` in `system.json` |
| HTTP variant: 401 Unauthorized | Token mismatch | Re-copy the token from `system.json` into Claude config |
| HTTP variant: Connection refused | Hub not enabled | Set `hub_enabled: true` and restart DeskAgent |
| First tool call is very slow | Lazy-loading of MCPs | Normal on first call, cached afterwards |
| `[sanitize]` shows up in the log | Prompt-injection check detected external content | Expected for emails/PDFs - see security docs |

**Logs:**

| File | Contents |
|---|---|
| `workspace/.logs/system.log` | DeskAgent server activity, MCP proxy startup |
| `workspace/.logs/mcp.log` | MCP tool calls, sanitization, errors |
| `%APPDATA%\Claude\logs\` (Windows) | Claude Desktop's own logs (MCP start, crashes) |

---

## Security (prompt injection)

All high-risk tools (tools that return external content - emails, PDFs, tickets) pass through a sanitization layer inside the anonymization proxy. This applies **also** to accesses from Claude Desktop because they go through the same proxy.

Protection measures:

- **Content wrapping** with untrusted-content delimiters
- **Pattern detection** (e.g. "ignore previous instructions")
- **Unicode sanitization** (zero-width characters, tag characters)
- **Logging** of suspicious patterns

Configurable in `system.json`:

```json
"security": {
  "prompt_injection_protection": true,
  "wrap_external_content": true,
  "log_suspicious_patterns": true
}
```

---

## Cowork plugin (slash commands for Claude Code)

In addition to MCP registration, DeskAgent can generate a **Cowork plugin** that exposes DeskAgent agents as slash commands (`/reply-email`, `/daily-check`, ...) in Claude Code.

Generator: [../scripts/tools/generate_cowork_plugin.py](../scripts/tools/generate_cowork_plugin.py)
Output: [../cowork-plugin/](../cowork-plugin/)

See the Cowork plugin README for details.

---

## References

- Implementation: [../mcp/desk/claude_desktop.py](../mcp/desk/claude_desktop.py)
- HTTP hub: [../scripts/assistant/services/mcp_proxy_manager.py](../scripts/assistant/services/mcp_proxy_manager.py)
- UI endpoints: [../scripts/assistant/routes/system.py](../scripts/assistant/routes/system.py)
- Config schema: [doc-config-reference.md](doc-config-reference.md) (section `claude_desktop`)
- MCP architecture: [doc-creating-mcp-servers.md](doc-creating-mcp-servers.md)
- Anonymization: [doc-anonymization.md](doc-anonymization.md)
