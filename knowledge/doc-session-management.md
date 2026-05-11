# Session Management in DeskAgent

**Version:** 1.0
**Last updated:** 2026-01-14
**Target audience:** AI agents & developers

## Overview

DeskAgent uses a **user-controlled session management system** for persistent conversations across multiple turns. Sessions allow agents and chats to preserve the full context across multiple messages.

### Core Principles

1. **User-Controlled Lifecycle**: Sessions are NOT ended automatically - only the user decides
2. **No Timeout**: No automatic session timeout
3. **Persistent Storage**: All sessions and turns are stored in SQLite
4. **Reactivatable**: Completed sessions can be continued at any time
5. **Knowledge Persistence**: Knowledge is reloaded on every turn

---

## Session Lifecycle

### Status Transitions

```
┌─────────────────────────────────────────────────────┐
│ Session Lifecycle States                            │
├─────────────────────────────────────────────────────┤
│                                                      │
│  START                                               │
│    ↓                                                 │
│  ┌─────────┐                                         │
│  │ active  │ ← Session created on agent start       │
│  └─────────┘                                         │
│    ↓                                                 │
│    │ Task completes                                  │
│    │ → Session STAYS active (no auto-complete!)     │
│    ↓                                                 │
│  ┌─────────┐                                         │
│  │ active  │ ← Follow-up messages possible          │
│  └─────────┘                                         │
│    ↓                                                 │
│    │ User presses Escape/Close                      │
│    ↓                                                 │
│  ┌───────────┐                                       │
│  │ completed │ ← Session ended, stored in DB        │
│  └───────────┘                                       │
│    ↓                                                 │
│    │ User clicks "Continue" in history              │
│    ↓                                                 │
│  ┌─────────┐                                         │
│  │ active  │ ← Session reactivated                  │
│  └─────────┘                                         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Important Rules

- Sessions ALWAYS remain active after task completion
- Follow-up messages find the active session and continue it
- Completed sessions remain in the database and can be continued
- NO automatic `complete_session()` after task end
- NO session timeout

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────┐
│ Session Management Stack                        │
├─────────────────────────────────────────────────┤
│                                                  │
│ ┌─────────────────────────────────────────┐    │
│ │ UI Layer (WebUI)                        │    │
│ │ - closeResult() → /session/end          │    │
│ │ - Clear History → /session/clear        │    │
│ │ - Continue → /history/sessions/{id}/... │    │
│ └─────────────────────────────────────────┘    │
│                   ↓                              │
│ ┌─────────────────────────────────────────┐    │
│ │ API Layer (routes/execution.py)         │    │
│ │ - POST /session/end                     │    │
│ │ - POST /session/clear                   │    │
│ │ - POST /history/sessions/{id}/continue  │    │
│ └─────────────────────────────────────────┘    │
│                   ↓                              │
│ ┌─────────────────────────────────────────┐    │
│ │ State Management (core/state.py)        │    │
│ │ - start_or_continue_session()           │    │
│ │ - end_current_session()                 │    │
│ │ - load_session_for_continue()           │    │
│ └─────────────────────────────────────────┘    │
│                   ↓                              │
│ ┌─────────────────────────────────────────┐    │
│ │ Database Layer (session_store.py)       │    │
│ │ - create_session()                      │    │
│ │ - get_active_session()                  │    │
│ │ - complete_session()                    │    │
│ │ - reactivate_session()                  │    │
│ │ - add_turn()                            │    │
│ └─────────────────────────────────────────┘    │
│                   ↓                              │
│ ┌─────────────────────────────────────────┐    │
│ │ SQLite Database                          │    │
│ │ - sessions table                         │    │
│ │ - turns table                            │    │
│ └─────────────────────────────────────────┘    │
│                                                  │
└─────────────────────────────────────────────────┘
```

### Database Schema

**sessions table:**
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                -- UUID
    agent_name TEXT NOT NULL,           -- e.g. "chat", "daily_check"
    backend TEXT NOT NULL,              -- e.g. "claude_sdk", "gemini"
    model TEXT,                         -- e.g. "claude-sonnet-4"
    status TEXT NOT NULL,               -- 'active' or 'completed'
    created_at TEXT NOT NULL,           -- ISO timestamp
    updated_at TEXT NOT NULL,           -- ISO timestamp
    total_tokens INTEGER DEFAULT 0,     -- Sum of all tokens
    total_cost_usd REAL DEFAULT 0.0,    -- Sum of all costs
    preview TEXT,                       -- First 100 chars of the first turn
    triggered_by TEXT DEFAULT 'webui',  -- 'webui', 'voice', 'workflow', etc.
    log_content TEXT                    -- Optional: execution logs
);
```

**turns table:**
```sql
CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,           -- Foreign key to sessions
    role TEXT NOT NULL,                 -- 'user' or 'assistant'
    content TEXT NOT NULL,              -- Message content
    tokens INTEGER DEFAULT 0,           -- Token count for this turn
    cost_usd REAL DEFAULT 0.0,          -- Cost for this turn
    task_id TEXT,                       -- Optional: task ID
    created_at TEXT NOT NULL,           -- ISO timestamp
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

---

## API Reference

### POST /session/end

Ends the current session (user closes tile/presses Escape).

**Request:**
```bash
POST /session/end
```

**Function:**
- Calls `end_current_session()`
- Marks current session as `status='completed'`
- Session remains in the database
- Can be reactivated later with Continue

**Use:**
```javascript
// webui-tasks.js:1247
await fetch(API + '/session/end', { method: 'POST' });
```

---

### POST /session/clear

Deletes old completed sessions (database cleanup).

**Request:**
```bash
POST /session/clear
```

**Response:**
```json
{
  "status": "ok",
  "message": "Cleared 5 old sessions",
  "deleted": 5
}
```

**Function:**
- Calls `session_store.delete_completed_sessions()`
- Deletes ONLY sessions with `status='completed'`
- Current active session remains unchanged
- All turns of the active session are preserved

**IMPORTANT:** This is a database cleanup, NOT a session reset!

---

### POST /history/sessions/{session_id}/continue

Loads a completed session and reactivates it.

**Request:**
```bash
POST /history/sessions/abc123-def456/continue
```

**Response:**
```json
{
  "agent_name": "chat_claude_sdk",
  "backend": "claude_sdk",
  "model": "claude-sonnet-4",
  "context": "## Previous Conversation:\n...",
  "original_session_id": "abc123-def456"
}
```

**Function:**
- Calls `load_session_for_continue(session_id)`
- Loads all turns of the session into memory
- Calls `reactivate_session()` → `status='completed'` → `'active'`
- Sets session as current session
- The next message continues this session

---

## Code Reference

### Important Functions

#### start_or_continue_session()
**File:** `deskagent/scripts/assistant/core/state.py:215-296`

```python
def start_or_continue_session(agent_name: str, backend: str, model: str,
                               triggered_by: str = "webui") -> Optional[str]:
    """
    Start a new session or continue an existing active session.

    Logic:
    1. Check if interactive trigger (webui, voice) → can continue
    2. Call get_active_session(agent_name)
    3. If found → load turns, continue session
    4. If not found → create new session

    Returns:
        Session ID
    """
```

**Important:**
- Checks `get_active_session(agent_name)` → looks for `status='active'`
- For workflows/email watcher: always new session
- For WebUI/voice: tries to continue

---

#### end_current_session()
**File:** `deskagent/scripts/assistant/core/state.py:396-412`

```python
def end_current_session():
    """
    End the current session (mark as completed).

    Called when:
    - User closes tile (X button)
    - User presses Escape

    Does NOT call on:
    - Task completion (no automatic end!)
    """
    session_store.complete_session(_current_session_id)
```

---

#### load_session_for_continue()
**File:** `deskagent/scripts/assistant/core/state.py:421-465`

```python
def load_session_for_continue(session_id: str) -> Optional[str]:
    """
    Load a session for continuing from History.

    Steps:
    1. Get session from database
    2. Call reactivate_session(session_id) ← IMPORTANT!
    3. Load all turns into memory
    4. Set as current session

    Returns:
        Context string for prompt
    """
```

**CRITICAL:** `reactivate_session()` is essential for follow-up messages to work!

---

#### reactivate_session()
**File:** `deskagent/scripts/assistant/session_store.py:325-346`

```python
def reactivate_session(session_id: str) -> bool:
    """
    Reactivate a completed session (sets status back to 'active').

    SQL:
        UPDATE sessions
        SET status = 'active', updated_at = ?
        WHERE id = ?

    Returns:
        True if successful
    """
```

---

#### _cleanup_session()
**File:** `deskagent/scripts/assistant/core/agent_task.py:323-346`

```python
def _cleanup_session(self, status: str = "completed"):
    """
    Clean up session after task execution.

    IMPORTANT:
    - Removes session from running_sessions set
    - Broadcast 'session_ended' event
    - Does NOT call complete_session()!
    - Session remains 'active' for follow-ups
    """
```

**CHANGE HISTORY:**
- Before the fix: called `complete_session()` → sessions were terminated
- After the fix: no automatic termination → user-controlled

---

## User Flows

### Flow 1: Agent with Follow-ups

```
┌────────────────────────────────────────────────────┐
│ User Journey: Agent + Follow-up Messages           │
├────────────────────────────────────────────────────┤
│                                                     │
│ 1. User clicks "daily_check" agent tile           │
│    → POST /agent/daily_check                       │
│    → start_or_continue_session("daily_check")     │
│    → Session A created (status='active')          │
│                                                     │
│ 2. Agent runs, returns result                     │
│    → _cleanup_session() called                    │
│    → Session A remains ACTIVE                     │
│    → No complete_session() call                   │
│                                                     │
│ 3. User types in prompt: "explain in more detail" │
│    → POST /prompt                                  │
│    → start_or_continue_session("daily_check")     │
│    → get_active_session() finds Session A         │
│    → Loads turns into memory                      │
│    → build_continuation_prompt() builds history   │
│    → AI gets full context                         │
│                                                     │
│ 4. User: "one more question"                      │
│    → Session A is continued again                 │
│                                                     │
│ 5. User presses Escape                            │
│    → closeResult() → POST /session/end            │
│    → end_current_session()                        │
│    → Session A: status='completed'                │
│    → Remains in database                          │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

### Flow 2: Chat + Clear History

```
┌────────────────────────────────────────────────────┐
│ User Journey: Chat + Clear History                 │
├────────────────────────────────────────────────────┤
│                                                     │
│ 1. User opens chat agent                          │
│    → openChat("chat_claude_sdk", "claude_sdk")    │
│    → clearHistory() (clears old UI content)       │
│    → Session B created (status='active')          │
│                                                     │
│ 2. User: "10 + 10"                                │
│    → POST /prompt                                  │
│    → AI: "20"                                      │
│    → Session B remains active                     │
│                                                     │
│ 3. User: "plus 30"                                │
│    → Session B continued                          │
│    → AI: "50" (has context!)                      │
│                                                     │
│ 4. User clicks "Clear History" button             │
│    → POST /session/clear                          │
│    → delete_completed_sessions()                  │
│    → Deletes old sessions C, D, E...             │
│    → Session B (active) remains!                  │
│    → All turns of B remain!                       │
│                                                     │
│ 5. User: "hello" (new topic)                      │
│    → Session B continued (same session!)          │
│    → Still has history of "10+10" and "plus 30"   │
│                                                     │
│ 6. User closes chat (X)                           │
│    → POST /session/end                            │
│    → Session B: status='completed'                │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

### Flow 3: Continue from History

```
┌────────────────────────────────────────────────────┐
│ User Journey: Continue session from history        │
├────────────────────────────────────────────────────┤
│                                                     │
│ 1. User ended Session C yesterday                 │
│    → Session C (status='completed')               │
│    → 10 turns saved                               │
│                                                     │
│ 2. User opens history panel                       │
│    → GET /history/sessions                        │
│    → Sees list of all sessions (incl. C)          │
│                                                     │
│ 3. User clicks "Continue" on session C            │
│    → POST /history/sessions/C/continue            │
│    → load_session_for_continue("C")               │
│    → reactivate_session("C") ← CRITICAL!          │
│    → Session C: status='completed' → 'active'     │
│    → Loads all 10 turns into memory               │
│    → Sets _current_session_id = C                 │
│                                                     │
│ 4. Frontend shows Session C in chat               │
│    → All 10 turns visible                         │
│                                                     │
│ 5. User: "and what was the result again?"         │
│    → POST /prompt                                  │
│    → start_or_continue_session()                  │
│    → get_active_session() finds C (is active!)    │
│    → Continues session C                          │
│    → AI has full context of the 10 old turns      │
│                                                     │
│ 6. User: further follow-ups                       │
│    → Session C continues indefinitely             │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

## Knowledge Persistence

### How Knowledge Works

Knowledge is reloaded **on every turn**, NOT once per session.

**Flow:**
```python
# On every turn:
1. start_or_continue_session()     # Loads session + history
2. build_continuation_prompt()     # Builds user prompt with history
3. process_agent()
   → ai_agent.call_agent()
      → build_system_prompt()      # ← Knowledge is loaded HERE!
         → load_knowledge_cached()  # 5-minute cache
```

**Code:** `deskagent/scripts/ai_agent/base.py:945-1062`

```python
def build_system_prompt(agent_config: dict, config: dict = None) -> str:
    """
    Builds complete system prompt including knowledge.

    Order:
    1. Base system prompt
    2. Date/time context
    3. Security warnings
    4. System templates (dialogs)
    5. Knowledge ← here!
    6. Agent instructions
    7. Workspace directories
    8. Security restrictions
    """
    # ...
    knowledge = load_knowledge_cached(knowledge_pattern)
    # ...
```

**Knowledge Cache:**
- `_knowledge_cache_ttl = 300` (5 minutes)
- Cache key: MD5 hash of the knowledge pattern
- Pattern from agent config: `"knowledge": "company|products"`

**Example:**
```
Turn 1 (10:00): Knowledge loaded (cache miss)
Turn 2 (10:02): Knowledge from cache (< 5 min)
Turn 3 (10:06): Knowledge reloaded (cache expired)
```

---

## Debugging & Monitoring

### Check Logs

**System log:** `workspace/.logs/system.log`

```bash
grep -i "session" workspace/.logs/system.log | tail -20
```

**Important log messages:**
```
[Session] Created new session abc123 (triggered_by: webui)
[Session] Continuing session abc123
[Session] Loaded 5 turns from history
[AgentTask] Session abc123 kept active (user controls lifecycle)
[Session] Current session ended by user
[Session] Loaded & reactivated session abc123 (10 turns)
[Session] Cleared 3 completed sessions (active session preserved)
```

---

### Inspect Database Directly

```bash
# SQLite CLI
sqlite3 workspace/.state/sessions.db

# Show all sessions
SELECT id, agent_name, status, created_at,
       (SELECT COUNT(*) FROM turns WHERE session_id = sessions.id) as turn_count
FROM sessions
ORDER BY updated_at DESC
LIMIT 10;

# Active sessions
SELECT * FROM sessions WHERE status = 'active';

# Turns of a session
SELECT role, substr(content, 1, 50), created_at
FROM turns
WHERE session_id = 'abc123'
ORDER BY id;
```

---

### Common Problems & Solutions

#### Problem: "Follow-up message creates a new session"

**Symptom:**
- User sends follow-up
- AI has no context of the previous message

**Cause:**
- Session is not `status='active'`

**Check:**
```python
# In system.log:
grep "get_active_session" workspace/.logs/system.log
```

**Fix:**
- Make sure `_cleanup_session()` does NOT call `complete_session()`
- Code: `agent_task.py:343-346`

---

#### Problem: "Continue from history does not work"

**Symptom:**
- User clicks Continue
- Next message has no history

**Cause:**
- `reactivate_session()` is not called
- Session remains `status='completed'`

**Fix:**
- `load_session_for_continue()` must call `reactivate_session()`
- Code: `state.py:443-444`

---

#### Problem: "Knowledge missing in follow-ups"

**Symptom:**
- First message has knowledge
- Follow-ups have no knowledge

**Cause:**
- `build_system_prompt()` is not called on every turn

**Check:**
```python
# ai_agent/base.py should be called on EVERY call_agent()
grep "build_system_prompt" workspace/.logs/system.log
```

**Fix:**
- `build_system_prompt()` must be in `call_agent()`, not only on session start
- Code: `ai_agent/claude_agent_sdk.py:536`

---

## Best Practices for Developers

### 1. NEVER change session status automatically

**Wrong:**
```python
def _execute_agent(self):
    # ... agent runs ...
    session_store.complete_session(self._session_id)  # NO!
```

**Right:**
```python
def _execute_agent(self):
    # ... agent runs ...
    # Session remains active for follow-ups
    system_log(f"[AgentTask] Session {self._session_id} kept active")
```

---

### 2. Always Use Explicit session_id Parameter

**Wrong:**
```python
add_turn_to_session("user", prompt)  # Uses global variable
```

**Right:**
```python
add_turn_to_session("user", prompt, session_id=self._session_id)
```

**Reason:** With parallel tasks, global variables may be incorrect.

---

### 3. Don't Forget Session Reactivation

When implementing a new "Continue" function:

**Always call `reactivate_session()`:**
```python
def my_continue_function(session_id: str):
    session = session_store.get_session(session_id)
    session_store.reactivate_session(session_id)  # ← IMPORTANT!
    # ... rest of logic ...
```

---

### 4. Document Knowledge Pattern Explicitly

In agent frontmatter:
```json
{
  "knowledge": "company|products",  // Explicit pattern
  // NOT: omit field (loads everything)
  // NOT: "" (loads nothing)
}
```

---

## Migration Notes

### From Old System (before 2026-01-14)

**Old logic:**
- Sessions were completed automatically after every task
- Follow-ups did not work
- Continue did not reactivate sessions

**New logic:**
- Sessions remain active until the user closes
- Follow-ups work indefinitely
- Continue resumes sessions

**Migration steps:**
1. Merge all commits from branch `claude/fix-agent-chat-knowledge-Fgcbk`
2. Optionally delete old active sessions from DB (timeout)
3. Inform users about the new Continue function

---

## Testing

### Manual Test Plan

**Test 1: Follow-up Messages**
```
1. Start agent "daily_check"
2. Wait for completion
3. Type "explain that" in prompt
4. Expected: AI has context
```

**Test 2: Session Continue**
```
1. Start agent, send 2 messages
2. Close (Escape)
3. Open history panel
4. Click "Continue" on the session
5. Send new message
6. Expected: AI has full context of the 2 old messages
```

**Test 3: Clear History**
```
1. Create 3 sessions, close 2 of them
2. Open the third session (active)
3. Click "Clear History"
4. Expected: active session remains, 2 old ones deleted
```

**Test 4: Knowledge Persistence**
```
1. Start chat with knowledge pattern "company|products"
2. Ask: "What is {{Firma}}?"
3. Expected: AI knows the product
4. Follow-up: "And DeskAgent?"
5. Expected: AI knows both products
```

---

## Further Documentation

- **Session Store API:** `deskagent/scripts/assistant/session_store.py`
- **State Management:** `deskagent/scripts/assistant/core/state.py`
- **Agent Task Execution:** `deskagent/scripts/assistant/core/agent_task.py`
- **API Routes:** `deskagent/scripts/assistant/routes/execution.py`, `routes/history.py`
- **Knowledge System:** `deskagent/knowledge/doc-knowledge-system.md`

---

## Changelog

**2026-01-14 - v1.0 - Initial Release**
- Complete redesign of session management
- User-controlled lifecycle implemented
- Session reactivation added
- Clear History = database cleanup (not session reset)
- Removed automatic `complete_session()` calls
- Knowledge persistence ensured on every turn

**Commits:**
- `941b3b1` - Add knowledge field to chat agent
- `ecd54fe` - Fix chat history continuation condition
- `5b618ca` - Keep chat sessions active for multi-turn
- `bcd21b4` - Complete session lifecycle management
- `ce86c8a` - Reactivate completed sessions when continued

---

**End of documentation**
