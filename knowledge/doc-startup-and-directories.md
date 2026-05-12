# DeskAgent Startup & Directory Structure

## Quick Start

```batch
cd deskagent
start.bat
```

DeskAgent starts on **http://localhost:8765/** by default.

## Startup Sequence

DeskAgent follows a specific startup order to ensure CLI arguments are respected:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. deskagent_main.py → init_platform()                         │
│     - Platform-specific setup (PATH, etc.)                      │
│     - NO folder creation here                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. assistant/__init__.py → main()                              │
│     - Parse CLI arguments (--port, --workspace-dir, etc.)       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. Set environment variables                                   │
│     - DESKAGENT_WORKSPACE_DIR (from --workspace-dir)            │
│     - DESKAGENT_SHARED_DIR (from --shared-dir)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. Reload paths module                                         │
│     - Re-evaluates WORKSPACE_DIR and SHARED_DIR                 │
│     - Now uses CLI-provided paths                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. ensure_first_run_setup()                                    │
│     - Creates folders in CORRECT location                       │
│     - Respects --workspace-dir and --shared-dir                 │
│     - Only runs for compiled builds (first run detection)       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. init_system_log()                                           │
│     - Initialize logging to workspace/.logs/                    │
│     - Log file now in correct location                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. Continue normal startup                                     │
│     - Load config, start HTTP server, create tray, etc.         │
└─────────────────────────────────────────────────────────────────┘
```

**Why this order matters:**

- CLI arguments (`--workspace-dir`, `--shared-dir`) must be parsed BEFORE folders are created
- Environment variables must be set BEFORE paths module is used
- Logging must be initialized AFTER paths are configured (so logs go to correct location)
- Platform init (`init_platform()`) only does platform-specific setup, NOT folder creation

## Command Line Parameters

| Parameter | Short | Description | Example |
|-----------|-------|-------------|---------|
| `--port` | `-p` | HTTP server port | `--port 8766` |
| `--shared-dir` | | Shared content directory | `--shared-dir "Z:\Team\AI"` |
| `--workspace-dir` | | Local workspace directory | `--workspace-dir "D:\DeskAgent"` |

### Examples

```batch
:: Start on different port
start.bat --port 8766

:: Full custom setup
start.bat --port 8766 --shared-dir "Z:\Team\AIAssistant" --workspace-dir "D:\MyDeskAgent"

:: Team setup: shared config, local workspace
start.bat --shared-dir "\\server\share\deskagent"
```

## Directory Structure

DeskAgent uses two directory concepts:

### Shared Directory (Team Content)

Contains configuration, agents, skills, and knowledge that can be shared across a team.

```
<shared-dir>/
├── config/
│   ├── system.json      # UI, logging, server settings
│   ├── backends.json    # AI backend configurations
│   ├── apis.json        # External API credentials
│   ├── banking.json     # SEPA bank accounts
│   ├── agents.json      # Agent definitions (legacy fallback)
│   └── categories.json  # UI category definitions
├── agents/              # Custom agents (.md files)
├── skills/              # Custom skills (.md files)
├── knowledge/           # Knowledge base (.md files)
└── mcp/                 # Custom MCP servers (optional)
```

Note: `templates/` is always read from `DESKAGENT_DIR/templates/` (system, not user-overridable).

**Default:** Parent of `deskagent/` folder (e.g., `C:\Users\you\deskagent-project\`)

**Environment variable:** `DESKAGENT_SHARED_DIR`

### Workspace Directory (Local Data)

Contains runtime data, logs, and exports - typically local per user/machine.

```
<workspace-dir>/
├── .logs/
│   ├── system.log           # Server activity log
│   └── agent_*.txt          # Agent execution logs
├── .temp/                   # Temporary files (cleared on start)
├── .state/
│   ├── deskagent.pid        # Process ID file
│   └── browser_consent.json # Browser integration consent
└── exports/                 # Generated files (PDFs, reports)
```

**Default:** `<shared-dir>/workspace/`

**Environment variable:** `DESKAGENT_WORKSPACE_DIR`

## Startup Modes

Configured in `config/system.json`:

```json
{
  "startup_mode": "foreground"
}
```

| Mode | Description |
|------|-------------|
| `foreground` | Console window visible, logs to console |
| `background` | No console window, runs silently (pythonw) |

## Multiple Instances

Run multiple DeskAgent instances on different ports:

```batch
:: Instance 1: Production (default port)
start.bat

:: Instance 2: Testing
start.bat --port 8766 --workspace-dir "D:\DeskAgent-Test"

:: Instance 3: Development
start.bat --port 8767 --shared-dir "E:\dev\deskagent-dev"
```

Each instance needs:
- Unique port
- Separate workspace directory (for PID file and logs)

## Custom Start Scripts

Create a wrapper script for your environment:

```batch
@echo off
:: my_deskagent.bat - Custom DeskAgent launcher

call "C:\DeskAgent\deskagent\start.bat" ^
  --port 8766 ^
  --shared-dir "Z:\Team\AIAssistant" ^
  --workspace-dir "%USERPROFILE%\DeskAgent"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DESKAGENT_SHARED_DIR` | Override shared directory |
| `DESKAGENT_WORKSPACE_DIR` | Override workspace directory |
| `PYTHONPATH` | Set automatically to `deskagent/scripts/` |

## Directory Resolution Priority

1. **Command line** (`--shared-dir`, `--workspace-dir`)
2. **Environment variables** (`DESKAGENT_SHARED_DIR`, `DESKAGENT_WORKSPACE_DIR`)
3. **Defaults** (relative to `deskagent/` folder)

## Platform Initialization

**Location:** `deskagent/scripts/assistant/platform.py`

Platform initialization (`init_platform()`) handles platform-specific setup but does NOT create folders:

| Platform | Setup |
|----------|-------|
| Windows | Add bundled Python to PATH |
| macOS | (Reserved for future menu bar setup) |
| Linux | (Reserved for future AppIndicator setup) |

**Important:** First-run folder creation is handled separately in `assistant/__init__.py` AFTER CLI arguments are parsed. This ensures `--workspace-dir` and `--shared-dir` are respected.

## First-Run Directory Creation

Neither `git clone` nor the signed installer create user folders themselves. Directories are created **at runtime on first startup** by `ensure_first_run_setup()`. This ensures CLI parameters are respected.

**Shared directories created:**
- `config/` - Configuration files
- `agents/` - User agent definitions
- `skills/` - User skill definitions
- `knowledge/` - User knowledge base

**Workspace directories created:**
- `workspace/.logs/` - Log files
- `workspace/.temp/` - Temporary files
- `workspace/.state/` - Persistent state (PID, costs)
- `workspace/.context/` - Skill context/memory
- `workspace/exports/` - Generated files
- `workspace/sepa/` - SEPA XML files

**Why runtime creation?**
- CLI support: `--workspace-dir D:\MyWorkspace` creates folders in the specified location
- Environment variable support: `DESKAGENT_WORKSPACE_DIR` is respected
- Multi-instance support: Each instance can have its own workspace
- Clean updates: Git pull doesn't conflict with user folders

## Verifying Setup

Check if DeskAgent is running:

```powershell
# Check server status
curl http://localhost:8765/agents

# Check specific port
curl http://localhost:8766/agents
```

Check logs:

```powershell
# View system log
Get-Content workspace\.logs\system.log -Tail 50

# View latest agent log
Get-Content workspace\.logs\agent_latest.txt
```

## Troubleshooting

### Port Already in Use

DeskAgent automatically finds the next free port if the configured port is busy.

Check the console output or system.log for the actual port.

### Config Not Found

Ensure `config/system.json` exists in the shared directory. DeskAgent falls back to defaults from `deskagent/config/`.

### Python Not Found

DeskAgent looks for Python in this order:
1. `./python/python.exe` (embedded Python, populated by `setup-python.bat` on Windows or shipped by the signed installer)
2. `./venv/bin/python` (created by `setup-unix.sh` on macOS/Linux)
3. `py` (Python launcher on Windows)
4. `python3.12` / `python3` / `python` from PATH

If none is found:
- Windows: run `setup-python.bat` (downloads embedded Python 3.12)
- macOS/Linux: install Python 3.12 first (`brew install python@3.12`,
  `apt install python3.12`, or `dnf install python3.12`), then run
  `./setup-unix.sh`.
