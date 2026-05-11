# Quick Access Mode

Quick Access is a compact overlay window (280x500px) that provides fast access to DeskAgent agents without opening the full browser interface.

## Opening Quick Access

- **Tray Icon**: Right-click the system tray icon and select "Quick Access"
- **Hotkey**: Configure a global hotkey in settings
- **API**: `POST /quickaccess/toggle` or `POST /quickaccess/open`

## Features

### Compact Tile View
- Shows agent tiles in a narrow, always-on-top window
- Category filtering available via hamburger menu
- Tiles stay in their grid positions (no full-screen takeover)

### Running Agent State
When an agent is running in Quick Access mode:
- **Pulsing border**: Subtle blue border animation indicates activity
- **Spinner**: Small rotating indicator in bottom-right corner (uses tile's icon color)
- **Close button (X)**: Top-right corner to cancel the running agent
- Tiles remain visible (not hidden like in full mode)

### Completion State
After an agent completes:
- **Success**: Green checkmark indicator
- **Error**: Red X indicator
- **Open button**: Top-left corner to view results in full window
- Button stays visible for 15 minutes (auto-dismisses after)

## Open Button Behavior

The "Open" button in Quick Access works like the "Öffnen" button in History:
1. Opens a new 900x700 browser window
2. Loads the session using `continueSession(sessionId)`
3. Shows full conversation with ability to continue chatting
4. Button remains clickable for 15 minutes (multiple opens allowed)

## Dialog Auto-Open Behavior

When an agent needs user input (CONFIRMATION_NEEDED or QUESTION_NEEDED) in Quick Access mode, the system automatically opens the full UI:

1. Dialog is triggered in Quick Access (280x500px - too small for forms)
2. `showConfirmationDialog()` detects `isQuickAccessMode`
3. Opens new 900x700 browser window with `?task=taskId&agent=name`
4. Full UI calls `pollTask()` → receives `pending_input` → shows dialog
5. User can interact with the full-size form
6. After confirmation, task continues in the full UI

This ensures complex confirmation forms (like contact data) are always shown in a properly sized window.

## Technical Implementation

### URL Parameters
- `?quickaccess=1` - Enables Quick Access mode styling
- `?category=finance` - Optional category filter
- `?continue=sessionId` - Opens and continues a specific session
- `?task=taskId&agent=name&isAgent=true` - Takes over a running task (for dialog redirect)

### CSS Classes
| Class | Purpose |
|-------|---------|
| `body.quick-access-mode` | Applied when in Quick Access mode |
| `.tile.pinned` | Tile with running/completed agent |
| `.tile.pinned.qa-running` | Running state with pulsing border |
| `.tile.pinned.qa-success` | Completed successfully |
| `.tile.pinned.qa-error` | Completed with error |
| `.tile.pinned.qa-complete` | Shows Open button |
| `.qa-chat-btn` | The "Open" button element |
| `.pinned-close-btn` | The close/cancel button |

### JavaScript Variables
| Variable | Purpose |
|----------|---------|
| `isQuickAccessMode` | Boolean, true when in Quick Access |
| `currentSessionId` | Session ID for Open button |
| `qaAutoDismissTimer` | 15-minute auto-dismiss timer |

### Key Functions
| Function | File | Purpose |
|----------|------|---------|
| `detectQuickAccessMode()` | webui-core.js | Detects and sets Quick Access mode |
| `showConfirmationDialog()` | webui-dialogs.js | Shows dialog (auto-opens full UI in QA mode) |
| `pinTile(tile)` | webui-ui.js | Pins tile with close button |
| `unpinTile()` | webui-ui.js | Resets tile state |
| `addQuickAccessChatButton(tile)` | webui-agents.js | Adds Open button to tile |
| `openQuickAccessChat()` | webui-tasks.js | Opens session in new window |

## Differences from Full Mode

| Aspect | Full Mode | Quick Access Mode |
|--------|-----------|-------------------|
| Window size | Full browser | 280x500px overlay |
| Tile grid | Hidden during agent | Stays visible |
| Processing overlay | Full-screen | Hidden (use tile state) |
| Result panel | Shows in-window | Opens new window |
| Dialogs (Confirmation/Question) | Inline in result panel | Opens full UI automatically |
| Pinned tile position | Fixed top-left | Stays in grid |
| Close button | Top-right of pinned tile | Top-right of tile |
| Minimize button | Bottom-left of pinned tile | Not shown |

## Files

| File | Purpose |
|------|---------|
| `deskagent/scripts/assistant/quickaccess.py` | Python module for window management |
| `deskagent/scripts/templates/js/webui-core.js` | Mode detection, URL param handling |
| `deskagent/scripts/templates/js/webui-ui.js` | Tile pinning, UI state |
| `deskagent/scripts/templates/js/webui-tasks.js` | Open button, session tracking |
| `deskagent/scripts/templates/js/webui-agents.js` | Chat button creation |
| `deskagent/scripts/templates/themes/styles.css` | Quick Access CSS (search for "QUICK ACCESS MODE") |
