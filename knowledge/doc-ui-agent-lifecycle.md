# DeskAgent UI & Agent Lifecycle

This document clarifies the relationship between UI state, tasks, sessions, and the agent execution lifecycle. Use this as a quick reference when working with agent execution code.

## Terminology

| Term | Definition | Lifetime | Storage |
|------|------------|----------|---------|
| **Task** | A single execution of an Agent/Skill/Prompt | Start → done/error/cancel | In-memory (`state.py`) |
| **Session** | A conversation with multiple turns | Persists across restarts | SQLite (`session_store.py`) |
| **Agent** | A `.md` file with instructions + frontmatter | Static (file) | `agents/*.md` |
| **Backend** | AI provider (claude_sdk, gemini, openai) | Configuration | `backends.json` |

**Key distinction:**
- `task_id` = Current execution being streamed (e.g., `"t_20250116_143025"`)
- `session_id` = Persistent conversation for history/continue (e.g., `"s_20250116_143025_001"`)
- A Task belongs to a Session, but a Session can have multiple Tasks (when dialogs occur)

## UI Components Terminology

Overview of all UI views, panels, and windows:

```
┌────────────────────────────────────────────────────────────────────┐
│  HEADER BAR                                                         │
│  [Logo] [Search] [Stats] [Settings⚙] [History📜]                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  TILE GRID (tileGrid)                                              │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                       │
│  │ Agent  │ │ Agent  │ │ Skill  │ │Workflow│                       │
│  │  Tile  │ │  Tile  │ │  Tile  │ │  Tile  │                       │
│  └────────┘ └────────┘ └────────┘ └────────┘                       │
│  ┌────────┐ ┌────────┐ ┌────────┐                                  │
│  │  ...   │ │  ...   │ │  ...   │                                  │
│  └────────┘ └────────┘ └────────┘                                  │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

| Component | HTML ID/Class | German | Description |
|-----------|---------------|--------|-------------|
| **Tile Grid** | `#tileGrid` / `.tile-grid` | Kachel-Raster | Main view with all Agent/Skill/Workflow tiles |
| **Tile** | `.tile` | Kachel | Single clickable card (Agent, Skill, or Workflow) |
| **Pinned Tile** | `.tile.pinned` | Angeheftete Kachel | Shrunk tile in top-left during agent execution |
| **Result Panel** | `#resultPanel` / `.result-panel` | Ergebnis-Panel | Chat window container (see details below) |
| **Chat Window** | (alias for Result Panel) | Chat-Fenster | Same as Result Panel - the agent conversation area |

**Chat Window Structure (Result Panel):**

```
┌─────────────────────────────────────────────────────┐
│  RESULT PANEL (#resultPanel)                        │
│  ┌─────────────────────────────────────────────────┐│
│  │  RESULT CONTENT (#resultContent)                ││
│  │  ┌─────────────────────────────────────────────┐││
│  │  │ 👤 User: Check my emails                    │││  ← User prompts
│  │  │                                             │││
│  │  │ 🔧 Tool: outlook_get_unread_emails()        │││  ← Tool calls
│  │  │    → Found 5 emails                         │││    (collapsible)
│  │  │                                             │││
│  │  │ 🤖 Agent: Here are your unread emails:      │││  ← Agent responses
│  │  │    1. Invoice from Supplier X               │││    (streaming)
│  │  │    2. Meeting request from Y                │││
│  │  └─────────────────────────────────────────────┘││
│  │                                                 ││
│  │  ┌─────────────────────────────────────────────┐││
│  │  │  DIALOG AREA (when agent asks questions)    │││
│  │  │  ┌─────────────────────────────────────────┐│││
│  │  │  │ Which emails should I archive?          ││││  ← Question
│  │  │  │                                         ││││
│  │  │  │ [Option A] [Option B] [Option C]        ││││  ← Selection buttons
│  │  │  │                                         ││││
│  │  │  │ [Confirm]              [Cancel]         ││││  ← Action buttons
│  │  │  └─────────────────────────────────────────┘│││
│  │  └─────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────┐│
│  │  PROMPT AREA (#promptArea)                      ││
│  │  [Type your follow-up here...           ] [Send]││  ← User input
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

| Sub-Component | HTML ID/Class | German | Description |
|---------------|---------------|--------|-------------|
| **Result Content** | `#resultContent` | Ausgabebereich | Scrollable area with conversation history |
| **Dialog Area** | `.question-dialog` / `.confirm-dialog-overlay` | Fragebereich | Agent questions as form with selection buttons |
| **Prompt Area** | `#promptArea` | Eingabebereich | Text input for follow-up prompts |

**Dialog Types:**

| Type | Trigger | UI Element |
|------|---------|------------|
| **QUESTION_NEEDED** | Agent needs user choice | Radio/checkbox buttons |
| **CONFIRMATION_NEEDED** | Agent needs data verification | Form with editable fields |
| **Text Input** | Agent needs free-form input | Text field + submit |

**Other Panels:**

| Component | HTML ID/Class | German | Description |
|-----------|---------------|--------|-------------|
| **History Panel** | `#historyPanel` / `.history-panel` | Verlauf-Panel | Slide-in panel from right with session history |
| **Settings Panel** | `#settingsPanel` / `.settings-panel` | Einstellungen | API keys, backend settings (modal overlay) |
| **System Panel** | `#systemPanel` / `.system-panel` | System-Panel | Multi-tab panel for system configuration (see below) |
| **Watcher Panel** | `#watcherPanel` / `.watcher-panel` | Watcher-Panel | Email watcher status and controls |
| **Quick Access Window** | `?quickaccess` URL param | Schnellzugriff | Compact 280x500px overlay (separate window mode) |

**System Panel Tabs:**

The System Panel contains multiple configuration tabs:

```
┌─────────────────────────────────────────────────────────────────────┐
│  System                                                              │
│  ┌────────┬────────┬──────────┬─────────┬────────┬───────────┬─────┐│
│  │ Lizenz │ Update │ Optionen │ Support │ System │ Microsoft │ ... ││
│  └────────┴────────┴──────────┴─────────┴────────┴───────────┴─────┘│
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                                                                 ││
│  │  [Tab Content Area]                                             ││
│  │                                                                 ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

| Tab | German | Purpose |
|-----|--------|---------|
| **Lizenz** | License | License status, activation, device management |
| **Update** | Update | Version info, update check, changelog |
| **Optionen** | Options | General preferences, UI settings |
| **Support** | Support | Help links, feedback, diagnostics |
| **System** | System | System info, paths, environment |
| **Microsoft** | Microsoft | Office 365/Graph API settings |
| **Tests** | Tests | Development testing tools |
| **Context** | Context | AI context window, token usage |
| **Logs** | Logs | System logs, debug output |

**Visual Hierarchy:**

```
┌─ Full Mode ──────────────────────────┐
│                                      │
│  [Tile Grid] ──click──► [Pinned Tile]│
│                              +       │
│                         [Chat Window]│
│                                      │
│  [History Panel] ◄── slide in/out    │
│  [Settings Panel] ◄── modal overlay  │
│                                      │
└──────────────────────────────────────┘

┌─ Quick Access Mode ──────────────────┐
│                                      │
│  [Tile Grid] stays visible           │
│  [Tile] shows status only            │
│  [Chat Window] opens in NEW window   │
│                                      │
└──────────────────────────────────────┘
```

**State Transitions:**

| From | Action | To |
|------|--------|-----|
| Tile Grid | Click tile | Pinned Tile + Chat Window |
| Tile Grid | Right-click tile | Context Menu |
| Chat Window | Escape / Close | Tile Grid |
| Chat Window | Minimize | Tile Grid (task continues) |
| Tile Grid | Click History icon | History Panel (slides in) |
| History Panel | Click session | Pinned Tile + Chat Window |
| Any | Click Settings icon | Settings Panel (overlay) |

### Context Menu (Right-Click on Tile)

| Action | Description | Visibility |
|--------|-------------|------------|
| Run | Normal execution | Always |
| Preview | Dry-run / Backend comparison (Ctrl+Shift) | Always |
| Pre-Prompt | Add context before running (Shift) | Always |
| Run with: {backend} | Override AI backend | Multiple backends |
| **Run without Anonymization** | Skip PII anonymization [044] | Expert Mode only |
| Pin / Unpin | Toggle pinned state | Always |
| Hide / Unhide | Toggle visibility | Always |
| Edit | Modify agent via AI (Ctrl) | Always |
| Improve | AI-powered agent improvement | Always |
| Edit file | Open in editor | Expert Mode only |

## Data Flow: Agent Start to Response

```
┌─────────────────────────────────────────────────────────────────┐
│  USER CLICKS AGENT TILE                                          │
└──────────────────────┬──────────────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  WebUI: runAgent(name)      │
        │  POST /agent/{name}         │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────────────┐
        │  execution.py:                      │
        │   1. generate_task_id()             │
        │   2. create_task_entry() → state.py │
        │   3. create_queue() → sse_manager   │
        │   4. Thread.start()                 │
        │   5. Return {task_id} immediately   │
        └──────────────┬──────────────────────┘
                       │
        ┌──────────────▼──────────────────────┐
        │  WebUI: streamTask(taskId)          │
        │  EventSource: GET /task/{taskId}/stream │
        └──────────────┬──────────────────────┘
                       │
                       │  ◄─── SSE Events ───┐
                       │                      │
        ┌──────────────▼─────────┐    ┌──────┴────────────┐
        │  UI Updates:           │    │  Worker Thread:   │
        │   - resultContent      │    │   AgentTask.exec  │
        │   - tokenStats         │    │   → AI Backend    │
        │   - costBadge          │    │   → MCP Tools     │
        └────────────────────────┘    └───────────────────┘
```

## Session vs Task Relationship

```
Session (SQLite)                    Task (In-Memory)
─────────────────                   ────────────────
s_20250116_143025
    │
    ├── Turn 1: User "Check..."
    │                               task_id: 1 (RUNNING)
    │   [Agent runs...]                  │
    │   [Tool calls...]                  │
    │                                    │
    ├── Turn 2: Assistant "Found..."     │
    │                               task_id: 1 (DONE)
    │
    │   ─── CONFIRMATION_NEEDED ───
    │
    ├── Turn 3: User "Yes, correct"
    │                               task_id: 2 (RUNNING)
    │   [Agent continues...]             │
    │                                    │
    ├── Turn 4: Assistant "Done"         │
    │                               task_id: 2 (DONE)
    │
    └── status: "completed"
```

## Context Preservation Requirement

**CRITICAL:** The full conversation context MUST be preserved throughout the entire agent lifecycle. This is a fundamental requirement for all AI backend implementations.

**Scope:** This requirement applies **per agent session**. Every new agent start begins with fresh context. The context is NOT shared between different agents.

### When Context MUST Be Preserved

| Situation | Requirement |
|-----------|-------------|
| **After CONFIRMATION_NEEDED** | Agent receives all previous turns + user confirmation |
| **After QUESTION_NEEDED** | Agent receives all previous turns + user answer |
| **On user follow-up prompt** | Agent receives the entire conversation so far |
| **On session continuation (history)** | Agent receives all saved turns of the session |
| **After tool calls** | Tool results remain in context for follow-up reasoning |

### What Belongs to the Context

```
Conversation Context (sent to AI backend)
├── System prompt (agent instructions)
├── Knowledge (loaded knowledge base)
├── Turn 1: User prompt
├── Turn 2: Assistant response
│   ├── Tool calls (name, parameters)
│   └── Tool results (return values)
├── Turn 3: User input (dialog response or follow-up)
├── Turn 4: Assistant response
│   └── ...
└── [Current turn]
```

### Implementation Requirements

**Backend implementations must:**

1. **Store conversation history** - All turns (user + assistant) in a list
2. **Include tool results** - Tool calls and their results as part of the assistant turns
3. **Continue on dialog response** - Append user input as a new turn, do not restart
4. **Load on session continue** - Restore saved turns from `session_store`

**Anti-pattern (WRONG):**
```python
# WRONG: Context is lost
def handle_dialog_response(response):
    # Starts new conversation - loses all context!
    return ai_client.chat([{"role": "user", "content": response}])
```

**Correct implementation:**
```python
# CORRECT: Context is preserved
def handle_dialog_response(response, conversation_history):
    # Appends user response to existing history
    conversation_history.append({"role": "user", "content": response})
    return ai_client.chat(conversation_history)
```

### Technical Implementation

| Component | Responsibility |
|-----------|----------------|
| `AgentTask` | Holds `conversation_history` during task execution |
| `session_store.py` | Persists turns in SQLite for session continuation |
| AI backend (claude_sdk, gemini, etc.) | Sends full history on every API call |
| `routes/execution.py` | Loads session context on continue/dialog response |

### Verification

If you experience context loss, check:

1. **Agent log** (`workspace/.logs/agent_latest.txt`) - Shows sent messages
2. **Session store** - `GET /sessions/{session_id}` returns the full session including all turns
3. **SSE events** - `content_sync` event contains the current conversation state

## Status Transitions

### Task Status

```
              ┌─────────┐
              │ created │
              └────┬────┘
                   │
              ┌────▼────┐
        ┌─────┤ running ├─────┐
        │     └────┬────┘     │
        │          │          │
   ┌────▼───┐ ┌────▼────┐ ┌───▼─────┐
   │ error  │ │  done   │ │cancelled│
   └────────┘ └─────────┘ └─────────┘
```

### Session Status

```
            ┌────────┐
            │ active │◄──────────────┐
            └───┬────┘               │
                │                    │ reactivate_session()
                │ complete_session() │ (History Continue)
                ▼                    │
          ┌───────────┐              │
          │ completed ├──────────────┘
          └───────────┘
```

**Note:** Sessions auto-complete after **30 minutes** of inactivity (`SESSION_TIMEOUT_MINUTES` in session_store.py).

### UI State Flags (webui-core.js)

**Primary Flags:**

| Flag | When `true` | When `false` |
|------|-------------|--------------|
| `currentTaskId` | Task is running, can be cancelled | Task ended (done/error/cancel) |
| `currentSessionId` | Active session for history | No active session |
| `isAppendMode` | After dialog response OR during SSE continuation | After task completion or cancel |
| `isChatMode` | Conversation UI visible | Tile grid visible |
| `isQuickAccessMode` | Compact 280x500 overlay | Full browser window |

**Additional State Variables:**

| Flag | Purpose | Default |
|------|---------|---------|
| `currentTaskTile` | Track which tile is processing | `null` |
| `pinnedTile` | Pinned tile during workflow execution | `null` |
| `cancelRequestedForTask` | Task ID being cancelled (race condition guard) | `null` |
| `correctionMode` | Object when user clicks "Correct" button | `null` |
| `isSubmittingResponse` | Guard against double dialog submission | `false` |
| `currentUserPrompt` | Initial user prompt for chat history | `null` |
| `userPromptDisplayed` | Prevents duplicate prompt display | `false` |
| `pinnedAgents` | User favorites (Set) | `Set()` |

## Standard Agent Flow (Full Mode)

When the user clicks an agent tile in the standard Tile-View, the following visual flow occurs:

```
1. INITIAL STATE                    2. AGENT STARTS
┌─────────────────────────┐         ┌─────────────────────────┐
│  ┌────┐ ┌────┐ ┌────┐   │         │  ┌────┐  ← Tile shrinks │
│  │ A1 │ │ A2 │ │ A3 │   │ ──────► │  │ A2●│    to top-left  │
│  └────┘ └────┘ └────┘   │  click  │  │ X─ │    (pinned)     │
│  ┌────┐ ┌────┐ ┌────┐   │  A2     │  └────┘                 │
│  │ A4 │ │ A5 │ │ A6 │   │         │  ┌─────────────────────┐│
│  └────┘ └────┘ └────┘   │         │  │   Chat Window       ││
│                         │         │  │   ⏳ Processing...   ││
│                         │         │  │                     ││
└─────────────────────────┘         │  │   [prompt input]    ││
                                    │  └─────────────────────┘│
                                    └─────────────────────────┘

3. AGENT RESPONDS                   4. USER INTERACTION
┌─────────────────────────┐         ┌─────────────────────────┐
│  ┌────┐                 │         │  ┌────┐                 │
│  │ A2●│                 │         │  │ A2●│                 │
│  │ X─ │                 │         │  │ X─ │                 │
│  └────┘                 │         │  └────┘                 │
│  ┌─────────────────────┐│         │  ┌─────────────────────┐│
│  │   Chat Window       ││         │  │ User: Follow-up?    ││
│  │   Agent response... ││         │  │ Agent: Here's more..││
│  │   (streaming)       ││  ◄────► │  │                     ││
│  │                     ││  prompt │  │                     ││
│  │   [prompt input]    ││         │  │   [prompt input]    ││
│  └─────────────────────┘│         │  └─────────────────────┘│
└─────────────────────────┘         └─────────────────────────┘
```

**Key UI Elements:**

| Element | Position | Purpose |
|---------|----------|---------|
| **Pinned Tile** | Top-left (70px, 12px) | Shows running agent, shrinks from original size |
| **Close Button (X)** | Top-right of pinned tile | Cancel and return to tile grid |
| **Minimize Button (─)** | Bottom-left of pinned tile | Continue task in background |
| **Chat Window** | Main area (resultPanel) | Shows agent responses, accepts prompts |
| **Prompt Input** | Bottom of chat window | Follow-up prompts to agent |

**Cancel Options:**

| Method | Behavior |
|--------|----------|
| **Escape key** | Cancels running task, returns to tile grid |
| **Close button (X)** | Same as Escape - cancels and closes |
| **Minimize button (─)** | Task continues in background, returns to tile grid |

**CSS Classes Applied:**

```css
.tile.pinned {
    position: fixed;
    top: 70px;
    left: 12px;
    width: 160px;
    min-height: 100px;
    padding: 16px 12px;
    z-index: 200;
}

.tile-grid.has-pinned {
    flex: 0 0 0;
    min-height: 0;
    max-height: 0;
    overflow: visible;
}
```

**Code Flow:**

1. `runAgent(name)` → Creates task, calls `pinTile(tile)`
2. `pinTile()`:
   - Moves tile to `document.body` (fixed positioning)
   - Adds `.pinned` class (shrinks tile)
   - Adds close/minimize buttons
   - Adds `.has-pinned` to tile-grid (collapses grid)
3. `showResultPanel()` → Chat window appears with streaming content
4. User can type in prompt area → Continues session
5. `closeResult()` or `Escape`:
   - Calls `unpinTile()` (restores tile to grid)
   - Hides result panel
   - Returns to tile grid

**Files:** [webui-ui.js:70](deskagent/scripts/templates/js/webui-ui.js#L70) (`pinTile`), [webui-agents.js:1995](deskagent/scripts/templates/js/webui-agents.js#L1995) (Escape handler)

## Thinking/Processing Overlay

When the agent is processing (thinking), a visible overlay appears inside the Chat Window:

```
┌─────────────────────────────────────────┐
│  ┌────┐                                 │
│  │ A2●│                                 │
│  └────┘                                 │
│  ┌─────────────────────────────────────┐│
│  │  ┌─────────────────────────────┐    ││
│  │  │      [Icon floating]        │    ││
│  │  │                             │    ││
│  │  │      Verarbeite...          │    ││
│  │  │                             │    ││
│  │  │          12s                │    ││
│  │  │      Claude SDK             │    ││
│  │  │      1.2k tokens            │    ││
│  │  │                             │    ││
│  │  │    [Cancel (ESC)]           │    ││
│  │  └─────────────────────────────┘    ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

**Overlay Elements:**

| Element | HTML ID | Description |
|---------|---------|-------------|
| **Container** | `#aiProcessingOverlay` | Full overlay with `data-mode` attribute |
| **Icon** | `.ai-processing-icon` | Animated floating icon (56px, float animation) |
| **Text** | `.ai-processing-text` | "Verarbeite..." with animated dots |
| **Timer** | `#aiProcessingTimer` | Elapsed seconds (updates every 1s) |
| **Status** | `#aiProcessingStatus` | Backend name (Claude SDK, Gemini, etc.) |
| **Context** | `.ai-processing-context` | Token count and breakdown (optional) |
| **Cancel** | Button in overlay | Red button + ESC keyboard hint |

**Overlay Modes:**

| Mode | `data-mode` | Behavior |
|------|-------------|----------|
| **hidden** | `hidden` | Overlay not visible |
| **loading** | `loading` | Full screen overlay during initial startup |
| **thinking** | `thinking` | Inside result panel during conversation |

**When Overlay Appears:**
1. User submits prompt → `showThinkingOverlay(true, "Chat • Claude SDK")`
2. Agent continues after dialog → Overlay reappears
3. Agent starts processing → Overlay visible until first token streams

**Styling:**
- Pulsing card animation: `thinkingPulse 2.5s ease-in-out infinite`
- Icon float animation: `iconFloat 2s ease-in-out infinite`
- Glass morphism: `backdrop-filter: blur(16px)`
- Loading dots: 4-step animation, 1.5s cycle

**Files:** [webui-ui.js:340](deskagent/scripts/templates/js/webui-ui.js#L340) (`showProcessingOverlay`), [webui-ui.js:510](deskagent/scripts/templates/js/webui-ui.js#L510) (`showThinkingOverlay` - legacy wrapper), [styles.css:1361-1650](deskagent/scripts/templates/themes/styles.css#L1361)

## UI Modes: Full vs Quick Access

DeskAgent has two display modes with different behaviors during agent execution:

### Full Mode (Default Browser)

See **Standard Agent Flow** section above for detailed flow. Summary:

- Tile shrinks and pins to top-left corner
- Tile grid collapses (hidden)
- Chat window opens with streaming responses
- User has full control: prompt, view responses, cancel/minimize
- Escape or close button cancels and returns to tile grid

### Quick Access Mode (Compact Overlay)

In Quick Access mode, the UI stays unchanged - only the tile shows status:

```
QUICK ACCESS WINDOW              NORMAL WEB-UI (if open)
┌──────────────────┐             ┌─────────────────────────┐
│  Tiles STAY      │             │  Tiles STAY             │
│  ┌────┐ ┌────┐   │             │  ┌────┐ ┌────┐ ┌────┐   │
│  │ A1 │ │ A2 │   │             │  │ A1 │ │ A2 │ │ A3 │   │
│  └────┘ └────┘   │             │  └────┘ └────┘ └────┘   │
│  ┌────┐ ┌────┐   │             │  ┌────┐ ┌────┐ ┌────┐   │
│  │ A3●│ │ A4 │   │  sync  ──►  │  │ A4●│ │ A5 │ │ A6 │   │
│  │ ⟳ │ └────┘   │  badges     │  │(1)●│ └────┘ └────┘   │
│  └────┘         │             │                         │
└──────────────────┘             └─────────────────────────┘
     ↑                                    ↑
     Pulsing border                       Running badge
     + spinner                            shows count
```

**Quick Access Behavior:**
- **UI stays unchanged** - no pinned tile, no chat window opens
- **Tile shows status only** - pulsing border + spinner while running
- **Running badge syncs** to any open normal Web-UI (via global SSE events)
- **After completion**: tile shows ✓/✗ and "Open" button
- **"Open" button**: Opens new 900x700 window with full conversation

```
AFTER COMPLETION:
┌──────────────────┐
│  ┌────┐ ┌────┐   │
│  │ A1 │ │ A2 │   │
│  └────┘ └────┘   │
│  ┌────┐ ┌────┐   │
│  │ A3✓│ │ A4 │   │  ← Completed: checkmark + "Open" button
│  │Open│ └────┘   │
│  └────┘         │
└──────────────────┘
     │
     └─► Click "Open" → New window with full chat
```

**Key Differences:**

| Aspect | Full Mode | Quick Access |
|--------|-----------|--------------|
| Window | Full browser | 280x500px overlay |
| On agent start | Tile pins, chat opens | Tile shows status only |
| Tiles during run | Grid collapses | Grid stays visible |
| User interaction | Prompt in chat window | Wait for completion |
| Result display | In-window chat panel | Opens new window |
| Other open UIs | Not affected (separate session) | Badge shows on tiles |
| URL param | - | `?quickaccess` |

**Detection:** `detectQuickAccessMode()` checks: `?quickaccess` URL param (no `=1` needed) OR window width < 300px.

## Background Tasks & Running Badges

When agents run in the background (EmailWatcher, API, or minimized), the UI shows status on tiles:

```
┌────────────────────────────────────────┐
│  Tile Grid                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │ Agent A │  │ Agent B │  │ Agent C │ │
│  │    (2)● │  │         │  │    (1)● │ │
│  └─────────┘  └─────────┘  └─────────┘ │
│                                         │
│  (2)● = 2 instances running             │
│  (1)● = 1 instance running              │
└────────────────────────────────────────┘
```

**Running Badge System:**

```javascript
// webui-tasks.js
let runningTasks = {
    agents: { "daily_check": 2, "reply_email": 1 },
    skills: {},
    workflows: { "email_autoreply": { run_123: {...} } }
};
```

**Global SSE Events (task events stream):**

| Event | Action |
|-------|--------|
| `task_started` | `runningTasks[type][name]++`, add badge |
| `task_ended` | `runningTasks[type][name]--`, remove badge if 0 |
| `initial_state` | Sync `runningTasks` on page load |

**Files:** `webui-tasks.js:setTileBadge()`, `webui-tasks.js:updateAllBadges()`

## Result Button (Quick Access)

After an agent completes in Quick Access mode, a result button appears on the tile:

```
Completion States:
┌────────┐  ┌────────┐  ┌────────┐
│   ✓    │  │   ✗    │  │   ⊘    │
│  Open  │  │  Open  │  │        │
│success │  │ error  │  │cancelled│
└────────┘  └────────┘  └────────┘
```

**Behavior:**
1. Button appears after `task_complete` or `task_error`
2. Clicking "Open" opens new 900x700 window (centered) with `?continue=sessionId`
3. Button auto-dismisses after **15 minutes** (`qaAutoDismissTimer`)
4. Multiple clicks allowed (re-opens session)

**Timing:**
- Status badges (✓/✗) visible for **3 seconds**, then fade
- Open button visible for **15 minutes**
- Button position: top-left (4px, 4px) with Material Icon `open_in_new`

**CSS Classes:**

| Class | State |
|-------|-------|
| `.qa-running` | Pulsing border, spinner visible |
| `.qa-success` | Green checkmark |
| `.qa-error` | Red X |
| `.qa-complete` | Open button visible |

**Files:** `webui-agents.js:addQuickAccessChatButton()`, `webui-tasks.js:openQuickAccessChat()`

## History Panel

All agent sessions are persisted and accessible via the History panel:

```
┌─────────────────────────────────┐
│  History (slide-in from right)  │
│  ┌────────────────────────────┐ │
│  │ Daily Check          2m ago│ │
│  │ claude_sdk   $0.02   1.2k  │ │
│  │ [Continue]                 │ │
│  ├────────────────────────────┤ │
│  │ Reply Email         15m ago│ │
│  │ gemini      $0.01    800   │ │
│  │ [Continue]                 │ │
│  └────────────────────────────┘ │
└─────────────────────────────────┘
```

**Session Data Shown:**
- Agent name and icon
- Backend used
- Cost (USD)
- Token count
- Relative timestamp
- Running indicator (if active)

**Instant Availability:**

Sessions appear in the History Panel **immediately** when an agent starts (within ~20ms):

```
USER CLICKS TILE                    HISTORY PANEL
      │                                   │
      ▼                                   │
  Task created                            │
      │                                   │
      ▼                                   │
  Session created in SQLite               │
      │                                   │
      ▼                                   │
  broadcast("session_started") ──────────►│ Event received
      │                                   │
      │                                   ▼
      │                             loadHistoryQuiet()
      │                                   │
      ▼                                   ▼
  Agent starts processing           Session appears with
                                    running indicator (●)
```

- `session_started` SSE event is broadcast to all connected browsers
- History Panel adds session with running indicator immediately
- User can **open running session** from History (click to view live progress)
- Full conversation context available even while agent runs

**Files:** `agent_task.py:402-421`, `webui-history.js:1478-1485`

**Running Indicator Lifecycle (Session-Level):**

The running indicator (pulsing blue/green dot) tracks whether an agent is currently executing within a session. Both initial agent starts AND follow-up prompts (chat continuations) trigger the indicator:

```
Agent Start (_execute_agent):             Prompt Continuation (_execute_prompt):
  start_or_continue_session()                start_or_continue_session()
       │ force_new_session=True                  │ force_new_session=False
       ▼                                         ▼
  _running_sessions.add(id)  ✅           _running_sessions.add(id)  ✅ [035]
  broadcast("session_started") ✅         broadcast("session_started") ✅ [035]
       │                                         │
       ▼                                         ▼
  Agent processes...                        Agent processes...
       │                                         │
       ▼                                         ▼
  _cleanup_session()                        _cleanup_session()
       │                                         │
       ▼                                         ▼
  remove_running_session(id) ✅            remove_running_session(id) ✅
  broadcast("session_ended") ✅            broadcast("session_ended") ✅
```

Key points:
- `_running_sessions` is a `set` -- `add()` is idempotent, so double-adds are harmless
- `session_started`/`session_ended` events are consumed by both History panel (running dot) and Task panel (mini-tiles)
- The `/task/active` endpoint returns `get_running_sessions()` for SSE reconnect sync
- Frontend `runningSessions.add()` is also idempotent (Set), so duplicate events are safe

**Session Card Visual States:**

| CSS Class | Meaning | Visual |
|-----------|---------|--------|
| `.running` (status dot) | Agent is currently executing | Pulsing green dot + spinner |
| `.selected` | User clicked card for detail view | Accent border + light accent bg |
| `.workflow-session` | Triggered by workflow | Purple left border |
| `.current-chat` | Session is currently shown in chat window | Accent border (2px) + light accent bg |
| `.confirming-delete` | Delete confirmation shown | Red bg + red border |

**Session Card Badges:**

| Badge | CSS Class | Condition | Visual |
|-------|-----------|-----------|--------|
| Backend badge | `.history-backend-badge` | Always shown | Colored pill (gemini=blue, claude=amber, etc.) |
| Trigger badge | `.history-trigger-badge` | Always shown | 14px Material Icon (mouse, mic, account_tree, api) |
| Anonymization badge | `.history-anon-badge` | `anonymization_enabled === true` | 14px shield icon in accent color with light bg [043] |

The anonymization badge (shield icon) shows only when PII anonymization was active during the session. Old sessions (before feature [043]) have `anonymization_enabled = null` and show no badge. The status is resolved once at session creation via `resolve_anonymization_setting()` and stored as a boolean in the `sessions` SQLite table.

States are combinable: a session can be `.running` AND `.current-chat` simultaneously.

The `.current-chat` highlight is driven by the `da:current-session-changed` custom DOM event, dispatched from `webui-tasks.js` on session start/end/error and from `webui-history.js` on `continueSession()`. The global `currentSessionId` variable (in `webui-core.js`) is the source of truth.

**Actions:**
- **Click session** → Load full conversation in result panel
- **"Continue" button** → Resume conversation with context (also highlights card)
- **Running sessions** → Show live status, can cancel

**Continue Session Flow:**

```
1. User clicks "Continue"
2. POST /sessions/{session_id}/continue → Loads session into state
3. GET /sessions/{session_id} → Returns previous turns for display
4. UI shows conversation
5. User types follow-up
6. POST /prompt with session_id → Continues same session
```

**What User Sees on Continue:**

When clicking "Continue", the full conversation history is displayed in the chat window:

```
┌─────────────────────────────────────────┐
│  ┌────┐                                 │
│  │ A2●│  (Pinned tile appears)          │
│  └────┘                                 │
│  ┌─────────────────────────────────────┐│
│  │  👤 User: Check my emails           ││  ← Original prompt
│  │                                     ││
│  │  🤖 Agent: Found 5 unread emails:   ││  ← Agent response
│  │     1. Invoice from Supplier X      ││
│  │     2. Meeting request from Y       ││
│  │     ...                             ││
│  │                                     ││
│  │  👤 User: Archive the newsletters   ││  ← Follow-up (if any)
│  │                                     ││
│  │  🤖 Agent: Archived 3 newsletters   ││
│  │                                     ││
│  │  ─────────────────────────────────  ││
│  │  [Type follow-up prompt here...]    ││  ← User can continue
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

**User Control in Continue Mode:**
- Full conversation history visible (all User/Agent turns)
- User can type follow-up prompts in the input area
- Session context is preserved (agent remembers previous turns)
- Cancel with Escape or close button (same as new agent)
- Minimize to run follow-up in background

## Chat Content Persistence

**Important:** The agent chat content is **fully persistent**. What you see during live agent execution is **identical** to what you see when returning via History → Continue:

```
LIVE EXECUTION                      HISTORY → CONTINUE
┌─────────────────────┐             ┌─────────────────────┐
│ 👤 Check emails     │             │ 👤 Check emails     │
│                     │             │                     │
│ 🔧 outlook_get...   │  ═══════    │ 🔧 outlook_get...   │
│ 🔧 outlook_move...  │  IDENTICAL  │ 🔧 outlook_move...  │
│                     │  ═══════    │                     │
│ 🤖 Found 5 emails:  │             │ 🤖 Found 5 emails:  │
│    - Invoice...     │             │    - Invoice...     │
│    - Meeting...     │             │    - Meeting...     │
└─────────────────────┘             └─────────────────────┘
```

**What is preserved:**
- All user prompts (initial + follow-ups)
- All agent responses (streaming content)
- Tool call history (MCP calls with parameters)
- Tool results (what tools returned)
- Dialogs and user confirmations
- Token counts and costs

**Storage:** Session data is persisted to SQLite (`session_store.py`) after each turn, ensuring nothing is lost even if the browser is closed.

**Files:** `webui-history.js`, `session_store.py:get_session_context()`

## Critical Code Paths

### 1. Task Creation (Backend)

**File:** `routes/execution.py` → `core/state.py` → `core/sse_manager.py`

```python
# execution.py:_create_and_start_task()
task_id = generate_task_id()           # state.py
create_task_entry(task_id, {...})      # state.py (in-memory dict)
create_queue(task_id)                  # sse_manager.py (asyncio Queue)
Thread(target=runner_func).start()     # AgentTask in thread
return {"task_id": task_id}            # Immediate response
```

### 2. SSE Event Publishing

**File:** `core/sse_manager.py`

```python
def publish_event(task_id, event_type, data):
    queue = get_queue(task_id)              # Per-task queue
    _event_loop.call_soon_threadsafe(       # Thread-safe bridge
        lambda: queue.put(SSEEvent(...))
    )
```

**Event Types:**

| Event | Trigger | Frontend Handler |
|-------|---------|------------------|
| `task_start` | Task begins | Show processing overlay, reset anon badge [033: ViewContext guard] |
| `token` | Streaming output | Append to result panel [030: ViewContext guard] |
| `content_sync` | Full content update | Sync entire result panel [030: ViewContext guard] |
| `tool_call` | MCP tool executed | Show in tool log |
| `anonymization` | PII stats available | Update anon badge [030: ViewContext guard] |
| `dev_context` | Iteration info (tokens, tools) | Update dev panel |
| `pending_input` | Dialog required | Show dialog UI |
| `task_complete` | Success | Show results, update costs |
| `task_error` | Failure | Show error message |
| `task_cancelled` | User cancelled | Reset UI |
| `ping` | Keep-alive | Maintain SSE connection |

**ViewContext Guards (030/033):** SSE events for `token`, `content_sync`, `anonymization`, and `task_start` (anon badge reset) check `ViewContext.isViewed(taskId)` before updating UI elements. State is always written to `TaskState` regardless of which task is viewed. The `da:view-switched` event restores stats, context, overlay, and anon badge from the switched-to task's state.

### 3. Dialog Flow (CONFIRMATION_NEEDED / QUESTION_NEEDED)

```
Backend                              Frontend
───────                              ────────
1. Agent needs user input
2. publish_pending_input(
     dialog_type, fields)
                                     3. SSE event: pending_input
                                     4. showConfirmationDialog()
                                        or showQuestionDialog()
                                     5. isAppendMode = true
                                     6. User interacts
                                     7. POST /task/{id}/respond
8. resume_agent(response)
9. Agent continues
                                     10. SSE: token, task_complete
                                     11. appendResultToPanel()
                                     12. isAppendMode = false
```

## FAQ: Common Confusion Points

### Q: What's the difference between Task and Session?

**Task** = A single execution, lives in memory, has a `task_id`
**Session** = A conversation persisted to SQLite, has a `session_id`

One session can span multiple tasks when dialogs occur. The session stores all turns for history continuation.

### Q: Where are costs tracked?

**Two systems:**

| System | Purpose | Storage |
|--------|---------|---------|
| Backend (`cost_tracker.py`) | Actual costs per backend | SQLite `costs` table |
| Session (`session_store.py`) | Per-conversation costs | SQLite `sessions.total_cost_usd` |
| Frontend (`webui-core.js`) | Display only | JavaScript memory |

The backend calculates costs in `AgentTask._execute_agent()` and sends them via SSE to the UI.

### Q: When is `isAppendMode` true?

Only after a dialog response:

```javascript
// webui-dialogs.js:submitDialogResponse()
isAppendMode = true;  // Set before continuing
await fetch(`/task/${taskId}/respond`, {...});
streamTask(taskId);   // Continue streaming

// After completion:
if (isAppendMode) {
    appendResultToPanel(content);  // Append, don't replace
    isAppendMode = false;          // Reset
}
```

### Q: How are parallel agent confirmations isolated? [046]

When two agents run in parallel and both request user confirmation, the session isolation works through three mechanisms:

1. **Backend (interaction.py):** `request_confirmation()` captures `session_id` from the `TaskContext` (available in the Agent-Thread) and stores it in `PendingConfirmation`. When `submit_response()` is called from the HTTP-Thread (which has NO TaskContext), it reads `session_id` from the stored `PendingConfirmation` and passes it to `add_turn_to_session()`.

2. **SSE Events (sse_manager.py):** `publish_event()` centrally injects `task_id` into ALL event payloads. This means every SSE event carries its task identity.

3. **Frontend (webui-tasks.js):** `createGuardedHandler()` validates that incoming SSE events match the expected `task_id` for this EventSource connection. Events for different tasks are silently dropped. This guards `pending_input`, `task_complete`, and `task_error` handlers.

```
Agent-Thread A (session s_001):
  request_confirmation() → PendingConfirmation(session_id="s_001")
  → SSE: { event: "pending_input", data: { task_id: "task-001", ... } }
  → Frontend: createGuardedHandler checks task_id matches

HTTP-Thread (POST /task/task-001/respond):
  submit_response() → reads session_id from PendingConfirmation → "s_001"
  → add_turn_to_session(session_id="s_001")  // correct session!
```

### Q: What's the difference between `broadcast_global_event` and `publish_event`?

| Function | Purpose | Recipients |
|----------|---------|------------|
| `publish_event(task_id, ...)` | Task-specific events (token, tool_call) | Only the SSE client for this task_id |
| `broadcast_global_event(...)` | Global events (task_started, task_ended) | ALL connected clients |

Global events power the "Running Tasks" badge in the header.

### Q: Why is `currentTaskId` sometimes null when an agent is running?

`currentTaskId` is only set for UI-connected tasks. Agents started via EmailWatcher, Workflow, or API don't have a UI connection, so no `currentTaskId` is set in the browser.

## File Reference

| Component | Key Files |
|-----------|-----------|
| **HTTP Routes** | `routes/execution.py` |
| **Task State** | `core/state.py`, `core/agent_task.py` |
| **SSE Manager** | `core/sse_manager.py`, `core/streaming.py` |
| **Session Store** | `session_store.py` |
| **AI Backends** | `ai_agent/claude_agent_sdk.py`, `ai_agent/gemini_adk.py` |
| **Frontend Core** | `templates/js/webui-core.js` |
| **Frontend Tasks** | `templates/js/webui-tasks.js` |
| **Frontend Dialogs** | `templates/js/webui-dialogs.js` |
| **Frontend History** | `templates/js/webui-history.js` |
| **Frontend Agents** | `templates/js/webui-agents.js` |
| **Quick Access** | `quickaccess.py`, `knowledge/doc-quick-access.md` |
