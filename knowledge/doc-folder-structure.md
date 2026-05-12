# DeskAgent Folder Structure

Central path management via `deskagent/scripts/paths.py`.

## Directory Overview

```
project-root/
├── deskagent/           # DESKAGENT_DIR - Product code (git-managed)
├── config/              # SHARED_DIR - Configuration
├── agents/              # SHARED_DIR - Agent definitions
├── skills/              # SHARED_DIR - Skill definitions
├── knowledge/           # SHARED_DIR - Knowledge base
├── mcp/                 # SHARED_DIR - Custom MCP servers
└── workspace/           # WORKSPACE_DIR - Local runtime data
    ├── .state/          # Hidden - api_costs.json, watcher_state.json
    ├── .logs/           # Hidden - system.log, agent_*.txt
    ├── .temp/           # Hidden - temporary files
    ├── .context/        # Hidden - skill memory
    ├── exports/         # Visible - PDFs, reports, downloads
    └── sepa/            # Visible - SEPA XML files
```

## Directory Types

### 1. DESKAGENT_DIR (Product Code)
**Path:** `deskagent/`

Product source code - updated via git pull. Never modify directly.

```
deskagent/
├── scripts/          # Python modules
├── templates/        # System templates (non-overridable)
├── mcp/              # Standard MCP servers
├── knowledge/        # System knowledge / developer docs
├── agents/           # System agent definitions
├── skills/           # System skill definitions
├── config/           # System default configs (templates)
└── requirements.txt  # Dependencies
```

### 2. SHARED_DIR (Shared Content)
**Path:** Configurable (see Environment Variables)

Team-shareable content. Can reside on a network drive.

```
<shared>/
├── config/           # system.json, backends.json, apis.json, banking.json
├── agents/           # Agent definitions (*.md)
├── skills/           # Skill definitions (*.md)
├── knowledge/        # Knowledge base (*.md)
└── mcp/              # Custom MCP servers (optional)
```

### 3. WORKSPACE_DIR (Local Runtime Data)
**Path:** `workspace/` (configurable)

Machine-specific runtime data. Never shared, never committed.

```
workspace/
├── .state/           # Persistent state (hidden)
│   ├── api_costs.json
│   └── watcher_state.json
├── .logs/            # Log files (hidden)
│   ├── system.log
│   └── agent_*.txt
├── .temp/            # Temporary files (hidden, auto-cleared)
├── .context/         # Skill context/memory (hidden)
├── exports/          # Generated files (visible)
│   └── *.pdf, reports, downloads
└── sepa/             # SEPA XML files (visible)
    └── *.xml
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DESKAGENT_SHARED_DIR` | Path to shared content | Parent of deskagent/ |
| `DESKAGENT_WORKSPACE_DIR` | Path to local workspace | `<project>/workspace/` |

### Configuration Priority

**SHARED_DIR:**
1. Environment variable `DESKAGENT_SHARED_DIR`
2. File `shared_path.txt` (next to deskagent/)
3. Default: Parent of deskagent/

**WORKSPACE_DIR:**
1. Environment variable `DESKAGENT_WORKSPACE_DIR`
2. Default: `<project-root>/workspace/`

### Example shared_path.txt
```
\\server\share\team\aiassistant
# or
Z:\Team\AIAssistant
```

## Command Line Parameters

```batch
start.bat --shared-dir "Z:\Team\AIAssistant" --workspace-dir "D:\DeskAgent\workspace"
```

| Parameter | Sets | Description |
|-----------|------|-------------|
| `--shared-dir <path>` | `DESKAGENT_SHARED_DIR` | Config, agents, skills, knowledge |
| `--workspace-dir <path>` | `DESKAGENT_WORKSPACE_DIR` | Logs, state, exports, sepa |

## Path Functions

Import from `paths.py`:

```python
from paths import (
    # Directory constants
    DESKAGENT_DIR,    # Product code directory
    SHARED_DIR,       # Shared content (may be network)
    WORKSPACE_DIR,    # Local workspace
    PROJECT_DIR,      # Alias for SHARED_DIR (backwards compat)
    LOCAL_DIR,        # Alias for WORKSPACE_DIR (backwards compat)

    # Workspace directories (hidden)
    get_state_dir,    # -> workspace/.state/
    get_data_dir,     # -> workspace/.state/ (alias)
    get_logs_dir,     # -> workspace/.logs/
    get_temp_dir,     # -> workspace/.temp/
    get_context_dir,  # -> workspace/.context/

    # Workspace directories (visible)
    get_exports_dir,  # -> workspace/exports/
    get_sepa_dir,     # -> workspace/sepa/

    # Shared directories
    get_config_dir,   # -> SHARED_DIR/config/
    get_agents_dir,   # -> SHARED_DIR/agents/ or fallback
    get_skills_dir,   # -> SHARED_DIR/skills/ or fallback
    get_knowledge_dir,# -> SHARED_DIR/knowledge/ or fallback

    # Product directories
    get_templates_dir,# -> DESKAGENT_DIR/templates/
    get_mcp_dir,      # -> DESKAGENT_DIR/mcp/
    get_mcp_dirs,     # -> [(path, source), ...] where source is "user" or "product"

    # Utilities
    clear_temp_dir,   # Delete .temp/ contents
    init_directories, # Create all directories (for setup)
)
```

## Directory Initialization

User directories (`agents/`, `skills/`, `config/`, `workspace/`) are created **at runtime on first startup** by `ensure_first_run_setup()`, not at install/clone time. This ensures CLI parameters (`--workspace-dir`, `--shared-dir`) are respected.

### Startup Sequence

1. **CLI args parsed** (`parse_args()`)
2. **Environment variables set** from `--shared-dir` / `--workspace-dir`
3. **paths module reloaded** to pick up new paths
4. **`ensure_first_run_setup()` called** - creates all directories
5. **System log initialized** (now logs to correct location)

### What Gets Created

```python
from paths import ensure_first_run_setup

# Called automatically in assistant/__init__.py for compiled builds
first_run = ensure_first_run_setup()
# Returns: True if this was first run (directories were created)
```

**Shared directories (SHARED_DIR):**
- `config/` - Configuration files
- `agents/` - Agent definitions
- `skills/` - Skill definitions
- `knowledge/` - Knowledge base

**Workspace directories (WORKSPACE_DIR):**
- `workspace/` - Base workspace folder
- `workspace/.logs/` - Log files
- `workspace/.temp/` - Temporary files
- `workspace/.state/` - Persistent state
- `workspace/.context/` - Skill context/memory
- `workspace/exports/` - Generated files
- `workspace/sepa/` - SEPA XML files

### Why Runtime Creation?

The system intentionally does NOT create user folders at install/clone time. This allows:

1. **CLI parameter support** - `--workspace-dir D:\MyWorkspace` creates folders in the specified location
2. **Environment variable support** - `DESKAGENT_WORKSPACE_DIR` is respected
3. **Clean first-run experience** - Folders appear where the user expects them
4. **Multi-instance support** - Each instance can have its own workspace

## State Files

| File | Location | Module | Purpose |
|------|----------|--------|---------|
| `api_costs.json` | `.state/` | `cost_tracker.py` | Cumulative API costs |
| `watcher_state.json` | `.state/` | `watchers.py` | Email watcher state |

### api_costs.json Structure
```json
{
  "total_usd": 5.82,
  "total_input_tokens": 1600531,
  "total_output_tokens": 13545,
  "task_count": 117,
  "by_model": { ... },
  "by_backend": { ... },
  "by_date": { ... },
  "last_updated": "2025-12-30T22:16:26.640847"
}
```

## Fallback Logic

### Agents and Skills (Merge with Fallback)

Discovery merges user and system definitions:
1. Load all `*.md` from `SHARED_DIR/agents/` (or `/skills/`)
2. Load all `*.md` from `DESKAGENT_DIR/agents/` (or `/skills/`)
3. User definitions override system definitions with same name
4. System-only definitions remain available

**Example:** User has `reply_email.md` → uses user version. System has `daily_check.md` that user doesn't have → system version available.

### Knowledge (Complete Replacement)

Knowledge uses replacement, not merge:
1. Check `SHARED_DIR/knowledge/` for `*.md` files
2. If folder exists AND has content → use ONLY user knowledge
3. If folder doesn't exist OR is empty → use ONLY system knowledge

**Important:** If user creates `knowledge/` folder with ANY files, ALL system knowledge is ignored.

### Summary

| Type | Behavior | Empty User Folder |
|------|----------|-------------------|
| `agents/` | Merge (user overrides, system fallback) | Uses system agents |
| `skills/` | Merge (user overrides, system fallback) | Uses system skills |
| `knowledge/` | Replace (all or nothing) | Uses system knowledge |
| `config/` | User config only (no fallback) | Error - needs config |

This enables:
- Team-shared definitions on network drive
- Local overrides during development
- Clean separation of product vs. user content

## Network Share Setup

For team usage with shared agents/skills:

1. Create shared folder: `\\server\share\aiassistant\`
2. Copy `config/`, `agents/`, `skills/`, `knowledge/` there
3. Configure via one of:
   - Set env var: `DESKAGENT_SHARED_DIR=\\server\share\aiassistant`
   - Create `shared_path.txt` with the path
   - Use CLI: `start.bat --shared-dir "\\server\share\aiassistant"`
4. Local workspace stays on each machine

## Distribution Layouts

DeskAgent ships in two ways. The folder layout is the same; only the
entry-point and how `DESKAGENT_DIR` is populated differs.

### Source install (open source, this repository)

Cloned tree on disk:

```
<project>/                    # SHARED_DIR (the directory you cloned into)
├── deskagent/                # DESKAGENT_DIR - this checkout
│   ├── scripts/              # Python source
│   ├── mcp/                  # MCP servers
│   ├── agents/               # System agents
│   ├── skills/               # System skills
│   ├── knowledge/            # System knowledge / developer docs
│   ├── templates/            # System templates
│   ├── config/               # Default config templates
│   ├── python/               # Optional: Windows embedded Python (created by setup-python.bat)
│   ├── venv/                 # Optional: Unix venv (created by setup-unix.sh)
│   ├── start.bat / start.sh  # Launcher
│   └── ...
```

User folders (`agents/`, `skills/`, `config/`, `knowledge/`, `workspace/`) at the
SHARED_DIR level are created automatically on first run, NOT at clone time.

### Commercial distribution (signed installer, optional)

The Windows / macOS signed installer (Nuitka-compiled binary, sold
separately) lays the files out the same way, with these differences:

- `DeskAgent.exe` (compiled) replaces `start.bat` + scripts directory
- `python/` is always present (embedded Python is bundled)
- An auto-updater is wired in
- A Commercial License removes the AGPL source-disclosure obligation

```
C:\Program Files\DeskAgent\   # SHARED_DIR
├── deskagent/                # DESKAGENT_DIR
│   ├── DeskAgent.exe         # Compiled main binary
│   ├── python/               # Embedded Python for MCP servers
│   ├── mcp/, agents/, skills/, knowledge/, templates/, config/
└── DeskAgent.bat             # Launcher shortcut
```

In both cases, user folders are created on first run by
`ensure_first_run_setup()`, which honors `--workspace-dir` /
`--shared-dir` CLI flags and the `DESKAGENT_*_DIR` env vars.

### macOS

The macOS build creates an app bundle. User data is stored in Application Support:

**App Bundle (read-only):**
```
/Applications/DeskAgent.app/
└── Contents/
    ├── MacOS/
    │   └── DeskAgent              # Compiled executable
    ├── Resources/                 # DESKAGENT_DIR (bundled data)
    │   ├── python/venv/           # Python virtualenv for MCP
    │   ├── mcp/                   # MCP servers
    │   ├── agents/                # System agents (fallback)
    │   ├── skills/                # System skills (fallback)
    │   ├── knowledge/             # System knowledge (fallback)
    │   ├── templates/             # System templates
    │   ├── config/                # Default config (fallback)
    │   └── version.json
    └── Info.plist
```

**User Data (created on first run):**
```
~/Library/Application Support/DeskAgent/  # SHARED_DIR + WORKSPACE_DIR
├── config/                    # User config
├── agents/                    # User agents
├── skills/                    # User skills
├── knowledge/                 # User knowledge
└── workspace/                 # Runtime data
    ├── .state/
    ├── .logs/
    ├── .temp/
    ├── .context/
    ├── exports/
    └── sepa/
```

**First-Run Behavior:**
On first launch, `ensure_first_run_setup()` automatically creates the Application Support folder structure. This happens AFTER CLI arguments are parsed, so `--shared-dir` and `--workspace-dir` are respected. The setup wizard then opens in the browser to configure API keys.

### Linux

Linux uses XDG directories:

**Executable:**
- Installed or extracted to user's choice (e.g., `/opt/DeskAgent/` or `~/Apps/DeskAgent/`)

**User Data (created on first run):**
```
~/.local/share/deskagent/     # SHARED_DIR + WORKSPACE_DIR
├── config/
├── agents/
├── skills/
├── knowledge/
└── workspace/
    ├── .state/
    ├── .logs/
    ├── .temp/
    ├── .context/
    ├── exports/
    └── sepa/
```

Respects `XDG_DATA_HOME` if set.

### Platform Path Summary

| Directory | Windows | macOS | Linux |
|-----------|---------|-------|-------|
| DESKAGENT_DIR | `{install}\deskagent\` | `*.app/Contents/Resources/` | `{install}/deskagent/` |
| SHARED_DIR | `{install}\` | `~/Library/Application Support/DeskAgent/` | `~/.local/share/deskagent/` |
| WORKSPACE_DIR | `{install}\workspace\` | `~/Library/Application Support/DeskAgent/workspace/` | `~/.local/share/deskagent/workspace/` |
| Logs | `{install}\workspace\.logs\` | `~/Library/Application Support/DeskAgent/workspace/.logs/` | `~/.local/share/deskagent/workspace/.logs/` |

**Key difference from a fresh clone:**
- In a clean source clone: `deskagent/` contains source code + system agents/skills/knowledge
- In the commercial signed distribution: `deskagent/` additionally contains the compiled `DeskAgent.exe` (Nuitka build)

The fallback logic is identical in both layouts - user folders override
system folders in `deskagent/`.

## Security Considerations

- **API Keys:** In `SHARED_DIR/config/` - protect network share appropriately
- **Workspace:** Never synced, contains no secrets
- **Temp Files:** Auto-cleaned, may contain sensitive content temporarily
- **Exports:** User-generated files, handle according to content
