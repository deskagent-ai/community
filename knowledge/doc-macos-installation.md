# DeskAgent macOS Installation Guide

## Installation

### Download and Install

1. Download `DeskAgent-X.Y.Z.dmg` from the releases page
2. Open the DMG file
3. Drag `DeskAgent.app` to your Applications folder
4. Eject the DMG

### First Launch

On first launch, DeskAgent automatically:

1. Creates user data folders in `~/Library/Application Support/DeskAgent/`
2. Opens the setup wizard in your default browser
3. Prompts you to configure API keys

**Gatekeeper Warning:** Since the app is not notarized, macOS may show "unidentified developer" warning:
- Right-click DeskAgent.app → Open → Click "Open" in the dialog
- Or: System Settings → Privacy & Security → scroll down → "Open Anyway"

## Folder Structure

### App Bundle (Read-Only)

```
/Applications/DeskAgent.app/
└── Contents/
    ├── MacOS/
    │   └── DeskAgent              # Main executable
    ├── Resources/                 # Bundled data (system defaults)
    │   ├── python/                # Embedded Python venv (bin/python3, lib/...)
    │   ├── mcp/                   # MCP server scripts
    │   ├── agents/                # System agents (fallback)
    │   ├── skills/                # System skills (fallback)
    │   ├── knowledge/             # System knowledge (fallback)
    │   ├── scripts/templates/     # System templates
    │   ├── config/                # Default configuration
    │   ├── i18n/                  # Translations
    │   ├── mocks/                 # Mock data for development/testing
    │   └── version.json
    └── Info.plist
```

### User Data (Application Support)

```
~/Library/Application Support/DeskAgent/
├── config/                    # Your configuration
│   ├── system.json            # UI settings, preferences
│   ├── backends.json          # AI backend API keys
│   ├── apis.json              # External API credentials
│   └── agents.json            # Agent/skill settings (optional)
├── agents/                    # Your custom agents
├── skills/                    # Your custom skills
├── knowledge/                 # Your knowledge base
└── workspace/                 # Runtime data
    ├── .state/                # Persistent state (API costs, etc.)
    ├── .logs/                 # Log files
    │   ├── system.log         # Server activity
    │   └── agent_latest.txt   # Last agent execution
    ├── .temp/                 # Temporary files
    ├── .context/              # Skill memory/context
    ├── exports/               # Generated PDFs, reports
    └── sepa/                  # SEPA XML files
```

## Configuration

### API Keys Setup

After first launch, open the setup wizard or navigate to Settings:

1. Open DeskAgent (click tray icon or http://localhost:8765)
2. Go to Settings → API Keys
3. Enter your API keys:
   - **Claude API Key** (Anthropic) - for Claude SDK backend
   - **Gemini API Key** (Google) - for Gemini backend
   - **OpenAI API Key** - for OpenAI backend

### Configuration Files

Edit files in `~/Library/Application Support/DeskAgent/config/`:

**system.json** - General settings:
```json
{
  "name": "My Assistant",
  "server_port": 8765,
  "ui": {
    "theme": "dark",
    "language": "en"
  }
}
```

**backends.json** - AI backend API keys:
```json
{
  "ai_backends": {
    "claude_sdk": {
      "api_key": "sk-ant-..."
    },
    "gemini": {
      "api_key": "AIza..."
    }
  }
}
```

## Platform Differences

### Features Not Available on macOS

| Feature | Windows | macOS | Reason |
|---------|---------|-------|--------|
| Outlook COM | Yes | No | Windows-only API |
| Global Hotkeys | Yes | Limited | macOS security restrictions |
| System Tray | Yes | Menu Bar | Different UI paradigm |

### Alternatives on macOS

- **Email:** Use `msgraph` (Office 365) or `gmail` MCP instead of Outlook COM
- **Calendar:** Use `msgraph` or `gmail` MCP
- **Hotkeys:** Use Shortcuts app or BetterTouchTool for global triggers

## Troubleshooting

### App Won't Open

**"DeskAgent is damaged and can't be opened"**
```bash
xattr -cr /Applications/DeskAgent.app
```

**"Unidentified developer" warning**
- System Settings → Privacy & Security → "Open Anyway"

### Port Already in Use

If port 8765 is busy:
```bash
# Find what's using the port
lsof -i :8765

# Kill the process
kill -9 <PID>
```

Or change the port in `~/Library/Application Support/DeskAgent/config/system.json`:
```json
{
  "server_port": 8766
}
```

### View Logs

```bash
# View system log
tail -f ~/Library/Application\ Support/DeskAgent/workspace/.logs/system.log

# View last agent execution
cat ~/Library/Application\ Support/DeskAgent/workspace/.logs/agent_latest.txt
```

### Reset to Defaults

To reset all user settings:
```bash
rm -rf ~/Library/Application\ Support/DeskAgent
```

Next launch will recreate default folders.

## Building from Source

### Requirements

- Python 3.12 (recommended). 3.10/3.11 work, but the `[anonymizer]` extra requires 3.12.
- Xcode Command Line Tools
- Nuitka (for compiled builds)
- create-dmg (optional, for DMG)

!!! note "macOS build runs on macOS only"
    The macOS build path uses `buildrelease/build-nuitka-macos.sh` and must be run
    on an actual macOS host. The `--platform macos` flag in `build.py` is accepted
    on other operating systems for configuration purposes, but the actual compile
    step requires the macOS shell script and Xcode toolchain.

### Build Commands

```bash
# Install Xcode tools
xcode-select --install

# Install dependencies
pip install nuitka ordered-set
brew install create-dmg

# Build
cd buildrelease
python3 build.py --platform macos --release   # Full build with DMG
python3 build.py --platform macos --test      # Quick test (no DMG)
```

### Output

- Test build: `buildrelease/build/dist-macos/DeskAgent.app`
- Release: `buildrelease/build/dist-macos/DeskAgent-X.Y.Z.dmg`

## Uninstallation

1. Quit DeskAgent (right-click menu bar icon → Quit)
2. Delete the app:
   ```bash
   rm -rf /Applications/DeskAgent.app
   ```
3. Optionally delete user data:
   ```bash
   rm -rf ~/Library/Application\ Support/DeskAgent
   ```
