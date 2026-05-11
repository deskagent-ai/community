# Session Management in DeskAgent

**Version:** 1.0
**Letzte Aktualisierung:** 2026-01-14
**Zielgruppe:** KI-Agents & Entwickler

## Übersicht

DeskAgent verwendet ein **benutzergesteuertes Session-Management-System** für persistente Konversationen über mehrere Turns hinweg. Sessions ermöglichen es Agents und Chats, den vollständigen Kontext über mehrere Nachrichten hinweg zu bewahren.

### Kernprinzipien

1. **User-Controlled Lifecycle**: Sessions werden NICHT automatisch beendet - nur der User entscheidet
2. **No Timeout**: Kein automatisches Session-Timeout
3. **Persistent Storage**: Alle Sessions und Turns werden in SQLite gespeichert
4. **Reactivatable**: Completed Sessions können jederzeit fortgesetzt werden
5. **Knowledge Persistence**: Knowledge wird bei jedem Turn neu geladen

---

## Session Lifecycle

### Status-Übergänge

```
┌─────────────────────────────────────────────────────┐
│ Session Lifecycle States                            │
├─────────────────────────────────────────────────────┤
│                                                      │
│  START                                               │
│    ↓                                                 │
│  ┌─────────┐                                         │
│  │ active  │ ← Session erstellt beim Agent-Start    │
│  └─────────┘                                         │
│    ↓                                                 │
│    │ Task completes                                  │
│    │ → Session BLEIBT active (kein auto-complete!)  │
│    ↓                                                 │
│  ┌─────────┐                                         │
│  │ active  │ ← Follow-up Messages möglich           │
│  └─────────┘                                         │
│    ↓                                                 │
│    │ User drückt Escape/Close                       │
│    ↓                                                 │
│  ┌───────────┐                                       │
│  │ completed │ ← Session beendet, in DB gespeichert │
│  └───────────┘                                       │
│    ↓                                                 │
│    │ User klickt "Continue" in History              │
│    ↓                                                 │
│  ┌─────────┐                                         │
│  │ active  │ ← Session reaktiviert                  │
│  └─────────┘                                         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Wichtige Regeln

- ✅ **Sessions bleiben IMMER active** nach Task-Completion
- ✅ **Follow-up Messages** finden die active Session und setzen sie fort
- ✅ **Completed Sessions** bleiben in der Datenbank und können fortgesetzt werden
- ❌ **KEIN automatisches complete_session()** nach Task-Ende
- ❌ **KEIN Session-Timeout**

---

## Architektur

### Komponenten

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

**sessions Table:**
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                -- UUID
    agent_name TEXT NOT NULL,           -- z.B. "chat", "daily_check"
    backend TEXT NOT NULL,              -- z.B. "claude_sdk", "gemini"
    model TEXT,                         -- z.B. "claude-sonnet-4"
    status TEXT NOT NULL,               -- 'active' oder 'completed'
    created_at TEXT NOT NULL,           -- ISO timestamp
    updated_at TEXT NOT NULL,           -- ISO timestamp
    total_tokens INTEGER DEFAULT 0,     -- Summe aller Tokens
    total_cost_usd REAL DEFAULT 0.0,    -- Summe aller Kosten
    preview TEXT,                       -- Erste 100 Zeichen des ersten Turns
    triggered_by TEXT DEFAULT 'webui',  -- 'webui', 'voice', 'workflow', etc.
    log_content TEXT                    -- Optional: Execution logs
);
```

**turns Table:**
```sql
CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,           -- Foreign Key zu sessions
    role TEXT NOT NULL,                 -- 'user' oder 'assistant'
    content TEXT NOT NULL,              -- Message content
    tokens INTEGER DEFAULT 0,           -- Token count für diesen Turn
    cost_usd REAL DEFAULT 0.0,          -- Kosten für diesen Turn
    task_id TEXT,                       -- Optional: Task ID
    created_at TEXT NOT NULL,           -- ISO timestamp
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

---

## API Reference

### POST /session/end

Beendet die aktuelle Session (User schließt Tile/drückt Escape).

**Request:**
```bash
POST /session/end
```

**Funktion:**
- Ruft `end_current_session()` auf
- Markiert aktuelle Session als `status='completed'`
- Session bleibt in Datenbank
- Kann später mit Continue reaktiviert werden

**Verwendung:**
```javascript
// webui-tasks.js:1247
await fetch(API + '/session/end', { method: 'POST' });
```

---

### POST /session/clear

Löscht alte completed Sessions (Database Cleanup).

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

**Funktion:**
- Ruft `session_store.delete_completed_sessions()` auf
- Löscht NUR Sessions mit `status='completed'`
- Aktuelle active Session bleibt unverändert
- Alle Turns der aktiven Session bleiben erhalten

**WICHTIG:** Dies ist ein Database-Cleanup, KEIN Session-Reset!

---

### POST /history/sessions/{session_id}/continue

Lädt eine completed Session und reaktiviert sie.

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

**Funktion:**
- Ruft `load_session_for_continue(session_id)` auf
- Lädt alle Turns der Session ins Memory
- Ruft `reactivate_session()` auf → `status='completed'` → `'active'`
- Setzt Session als current session
- Nächste Message setzt diese Session fort

---

## Code Reference

### Wichtige Funktionen

#### start_or_continue_session()
**Datei:** `deskagent/scripts/assistant/core/state.py:215-296`

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

**Wichtig:**
- Prüft `get_active_session(agent_name)` → sucht `status='active'`
- Bei Workflows/Email-Watcher: immer neue Session
- Bei WebUI/Voice: versucht fortzusetzen

---

#### end_current_session()
**Datei:** `deskagent/scripts/assistant/core/state.py:396-412`

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
**Datei:** `deskagent/scripts/assistant/core/state.py:421-465`

```python
def load_session_for_continue(session_id: str) -> Optional[str]:
    """
    Load a session for continuing from History.

    Steps:
    1. Get session from database
    2. Call reactivate_session(session_id) ← WICHTIG!
    3. Load all turns into memory
    4. Set as current session

    Returns:
        Context string for prompt
    """
```

**KRITISCH:** `reactivate_session()` ist essentiell, damit Follow-up Messages funktionieren!

---

#### reactivate_session()
**Datei:** `deskagent/scripts/assistant/session_store.py:325-346`

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
**Datei:** `deskagent/scripts/assistant/core/agent_task.py:323-346`

```python
def _cleanup_session(self, status: str = "completed"):
    """
    Clean up session after task execution.

    WICHTIG:
    - Entfernt Session aus running_sessions set
    - Broadcast 'session_ended' event
    - Ruft NICHT complete_session() auf!
    - Session bleibt 'active' für Follow-ups
    """
```

**CHANGE HISTORY:**
- Vor dem Fix: Rief `complete_session()` auf → Sessions wurden beendet
- Nach dem Fix: Keine automatische Beendigung → User-controlled

---

## User Flows

### Flow 1: Agent mit Follow-ups

```
┌────────────────────────────────────────────────────┐
│ User Journey: Agent + Follow-up Messages           │
├────────────────────────────────────────────────────┤
│                                                     │
│ 1. User klickt "daily_check" Agent-Tile           │
│    → POST /agent/daily_check                       │
│    → start_or_continue_session("daily_check")     │
│    → Session A erstellt (status='active')         │
│                                                     │
│ 2. Agent läuft, liefert Ergebnis                  │
│    → _cleanup_session() aufgerufen                │
│    → Session A bleibt ACTIVE ✅                     │
│    → Kein complete_session() Call                 │
│                                                     │
│ 3. User tippt im Prompt: "erkläre das genauer"   │
│    → POST /prompt                                  │
│    → start_or_continue_session("daily_check")     │
│    → get_active_session() findet Session A ✅      │
│    → Lädt Turns ins Memory                        │
│    → build_continuation_prompt() baut History     │
│    → AI bekommt vollen Kontext ✅                  │
│                                                     │
│ 4. User: "noch eine Frage"                        │
│    → Session A wird erneut fortgesetzt ✅          │
│                                                     │
│ 5. User drückt Escape                             │
│    → closeResult() → POST /session/end            │
│    → end_current_session()                        │
│    → Session A: status='completed' ✅              │
│    → Bleibt in Database                           │
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
│ 1. User öffnet Chat-Agent                         │
│    → openChat("chat_claude_sdk", "claude_sdk")    │
│    → clearHistory() (löscht alte UI-Inhalte)     │
│    → Session B erstellt (status='active')         │
│                                                     │
│ 2. User: "10 + 10"                                │
│    → POST /prompt                                  │
│    → AI: "20"                                      │
│    → Session B bleibt active ✅                     │
│                                                     │
│ 3. User: "plus 30"                                │
│    → Session B fortsetzt                          │
│    → AI: "50" (hat Kontext!) ✅                    │
│                                                     │
│ 4. User klickt "Clear History" Button             │
│    → POST /session/clear                          │
│    → delete_completed_sessions()                  │
│    → Löscht alte Sessions C, D, E...             │
│    → Session B (active) bleibt! ✅                 │
│    → Alle Turns von B bleiben! ✅                  │
│                                                     │
│ 5. User: "hello" (neues Thema)                    │
│    → Session B fortsetzt (gleiche Session!)       │
│    → Hat noch History von "10+10" und "plus 30" ✅ │
│                                                     │
│ 6. User schließt Chat (X)                         │
│    → POST /session/end                            │
│    → Session B: status='completed'                │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

### Flow 3: Continue from History

```
┌────────────────────────────────────────────────────┐
│ User Journey: Session aus History fortsetzen       │
├────────────────────────────────────────────────────┤
│                                                     │
│ 1. User hatte gestern Session C beendet           │
│    → Session C (status='completed')               │
│    → 10 Turns gespeichert                         │
│                                                     │
│ 2. User öffnet History Panel                      │
│    → GET /history/sessions                        │
│    → Sieht Liste aller Sessions (inkl. C)         │
│                                                     │
│ 3. User klickt "Continue" bei Session C          │
│    → POST /history/sessions/C/continue            │
│    → load_session_for_continue("C")               │
│    → reactivate_session("C") ← KRITISCH!         │
│    → Session C: status='completed' → 'active' ✅   │
│    → Lädt alle 10 Turns ins Memory                │
│    → Sets _current_session_id = C                 │
│                                                     │
│ 4. Frontend zeigt Session C im Chat              │
│    → Alle 10 Turns sichtbar                       │
│                                                     │
│ 5. User: "und was war nochmal das Ergebnis?"     │
│    → POST /prompt                                  │
│    → start_or_continue_session()                  │
│    → get_active_session() findet C (ist active!) ✅│
│    → Fortsetzt Session C                          │
│    → AI hat vollen Kontext der 10 alten Turns ✅  │
│                                                     │
│ 6. User: weitere Follow-ups                       │
│    → Session C wird unbegrenzt fortgesetzt ✅      │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

## Knowledge Persistence

### Wie Knowledge funktioniert

Knowledge wird bei **jedem Turn** neu geladen, NICHT einmal pro Session.

**Ablauf:**
```python
# Bei jedem Turn:
1. start_or_continue_session()     # Lädt Session + History
2. build_continuation_prompt()     # Baut User-Prompt mit History
3. process_agent()
   → ai_agent.call_agent()
      → build_system_prompt()      # ← HIER wird Knowledge geladen!
         → load_knowledge_cached()  # 5-Minuten Cache
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
    5. Knowledge ← Hier!
    6. Agent instructions
    7. Workspace directories
    8. Security restrictions
    """
    # ...
    knowledge = load_knowledge_cached(knowledge_pattern)
    # ...
```

**Knowledge Cache:**
- `_knowledge_cache_ttl = 300` (5 Minuten)
- Cache Key: MD5 hash des Knowledge-Patterns
- Pattern aus Agent-Config: `"knowledge": "company|products"`

**Beispiel:**
```
Turn 1 (10:00): Knowledge geladen (Cache Miss)
Turn 2 (10:02): Knowledge aus Cache (< 5 Min)
Turn 3 (10:06): Knowledge neu geladen (Cache expired)
```

---

## Debugging & Monitoring

### Logs prüfen

**System Log:** `workspace/.logs/system.log`

```bash
grep -i "session" workspace/.logs/system.log | tail -20
```

**Wichtige Log-Meldungen:**
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

### Database direkt inspizieren

```bash
# SQLite CLI
sqlite3 workspace/.state/sessions.db

# Alle Sessions anzeigen
SELECT id, agent_name, status, created_at,
       (SELECT COUNT(*) FROM turns WHERE session_id = sessions.id) as turn_count
FROM sessions
ORDER BY updated_at DESC
LIMIT 10;

# Aktive Sessions
SELECT * FROM sessions WHERE status = 'active';

# Turns einer Session
SELECT role, substr(content, 1, 50), created_at
FROM turns
WHERE session_id = 'abc123'
ORDER BY id;
```

---

### Häufige Probleme & Lösungen

#### Problem: "Follow-up Message erstellt neue Session"

**Symptom:**
- User sendet Follow-up
- AI hat keinen Kontext der vorherigen Message

**Ursache:**
- Session ist nicht `status='active'`

**Prüfen:**
```python
# In system.log:
grep "get_active_session" workspace/.logs/system.log
```

**Fix:**
- Sicherstellen dass `_cleanup_session()` NICHT `complete_session()` aufruft
- Code: `agent_task.py:343-346`

---

#### Problem: "Continue aus History funktioniert nicht"

**Symptom:**
- User klickt Continue
- Nächste Message hat keine History

**Ursache:**
- `reactivate_session()` wird nicht aufgerufen
- Session bleibt `status='completed'`

**Fix:**
- `load_session_for_continue()` muss `reactivate_session()` aufrufen
- Code: `state.py:443-444`

---

#### Problem: "Knowledge fehlt in Follow-ups"

**Symptom:**
- Erste Message hat Knowledge
- Follow-ups haben kein Knowledge

**Ursache:**
- `build_system_prompt()` wird nicht bei jedem Turn aufgerufen

**Prüfen:**
```python
# ai_agent/base.py sollte bei JEDEM call_agent() aufgerufen werden
grep "build_system_prompt" workspace/.logs/system.log
```

**Fix:**
- `build_system_prompt()` muss in `call_agent()` sein, nicht nur bei Session-Start
- Code: `ai_agent/claude_agent_sdk.py:536`

---

## Best Practices für Entwickler

### 1. Session-Status NIEMALS automatisch ändern

❌ **Falsch:**
```python
def _execute_agent(self):
    # ... agent runs ...
    session_store.complete_session(self._session_id)  # NEIN!
```

✅ **Richtig:**
```python
def _execute_agent(self):
    # ... agent runs ...
    # Session bleibt active für Follow-ups
    system_log(f"[AgentTask] Session {self._session_id} kept active")
```

---

### 2. Immer explizite session_id Parameter verwenden

❌ **Falsch:**
```python
add_turn_to_session("user", prompt)  # Nutzt globale Variable
```

✅ **Richtig:**
```python
add_turn_to_session("user", prompt, session_id=self._session_id)
```

**Grund:** Bei parallelen Tasks können globale Variablen falsch sein.

---

### 3. Session-Reactivation nicht vergessen

Wenn eine neue "Continue"-Funktion implementiert wird:

✅ **Immer reactivate_session() aufrufen:**
```python
def my_continue_function(session_id: str):
    session = session_store.get_session(session_id)
    session_store.reactivate_session(session_id)  # ← WICHTIG!
    # ... rest of logic ...
```

---

### 4. Knowledge-Pattern explizit dokumentieren

In Agent-Frontmatter:
```json
{
  "knowledge": "company|products",  // Explizites Pattern
  // NICHT: Feld weglassen (lädt alles)
  // NICHT: "" (lädt nichts)
}
```

---

## Migration Notes

### Von altem System (vor 2026-01-14)

**Alte Logik:**
- Sessions wurden nach jedem Task automatisch completed
- Follow-ups funktionierten nicht
- Continue reaktivierte Sessions nicht

**Neue Logik:**
- Sessions bleiben active bis User schließt
- Follow-ups funktionieren unbegrenzt
- Continue setzt Sessions fort

**Migration-Schritte:**
1. Alle Commits von Branch `claude/fix-agent-chat-knowledge-Fgcbk` mergen
2. Alte active Sessions aus DB löschen (optional, da Timeout)
3. Users informieren über neue Continue-Funktion

---

## Testing

### Manueller Test-Plan

**Test 1: Follow-up Messages**
```
1. Start Agent "daily_check"
2. Warte auf Completion
3. Schreibe "erkläre das" im Prompt
4. ✅ Erwartung: AI hat Kontext
```

**Test 2: Session Continue**
```
1. Start Agent, schreibe 2 Messages
2. Close (Escape)
3. Öffne History Panel
4. Klicke "Continue" bei der Session
5. Schreibe neue Message
6. ✅ Erwartung: AI hat vollen Kontext der 2 alten Messages
```

**Test 3: Clear History**
```
1. Erstelle 3 Sessions, schließe 2 davon
2. Öffne dritte Session (active)
3. Klicke "Clear History"
4. ✅ Erwartung: Aktive Session bleibt, 2 alte gelöscht
```

**Test 4: Knowledge Persistence**
```
1. Start Chat mit Knowledge-Pattern "company|products"
2. Frage: "Was ist {{Mein Produkt}}?"
3. ✅ Erwartung: AI kennt Produkt
4. Follow-up: "Und {{anderes Produkt}}?"
5. ✅ Erwartung: AI kennt beide Produkte
```

---

## Weitere Dokumentation

- **Session Store API:** `deskagent/scripts/assistant/session_store.py`
- **State Management:** `deskagent/scripts/assistant/core/state.py`
- **Agent Task Execution:** `deskagent/scripts/assistant/core/agent_task.py`
- **API Routes:** `deskagent/scripts/assistant/routes/execution.py`, `routes/history.py`
- **Knowledge System:** `deskagent/knowledge/doc-knowledge-system.md`

---

## Changelog

**2026-01-14 - v1.0 - Initial Release**
- Komplettes Redesign des Session-Management
- User-controlled Lifecycle implementiert
- Session Reactivation hinzugefügt
- Clear History = Database Cleanup (nicht Session-Reset)
- Automatische complete_session() Calls entfernt
- Knowledge Persistence bei jedem Turn sichergestellt

**Commits:**
- `941b3b1` - Add knowledge field to chat agent
- `ecd54fe` - Fix chat history continuation condition
- `5b618ca` - Keep chat sessions active for multi-turn
- `bcd21b4` - Complete session lifecycle management
- `ce86c8a` - Reactivate completed sessions when continued

---

**Ende der Dokumentation**
