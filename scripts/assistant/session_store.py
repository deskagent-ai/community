# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Session Store - SQLite-based chat history storage.
==================================================
Stores chat sessions with turns for Continue/Transfer functionality.

Database: Uses same DB as datastore_mcp (workspace/.state/datastore.db)

Tables:
- sessions: Session metadata (agent, backend, model, status, totals)
- turns: Individual conversation turns (user/assistant messages)

Threading: Uses RWLock pattern for concurrent read access.
SQLite WAL mode enables concurrent reads at DB level.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Centralized timestamp utilities
try:
    from utils.timestamp import get_timestamp_iso
except ImportError:
    def get_timestamp_iso(): return datetime.now().isoformat()


# =============================================================================
# Read-Write Lock Implementation
# =============================================================================

class RWLock:
    """
    Simple Read-Write Lock implementation.

    Allows multiple concurrent readers OR a single writer.
    Writers have priority to prevent starvation.
    """

    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    def acquire_read(self):
        """Acquire read lock. Multiple readers can hold simultaneously."""
        with self._read_ready:
            # Wait if writer is active or writers are waiting (writer priority)
            while self._writer_active or self._writers_waiting > 0:
                self._read_ready.wait()
            self._readers += 1

    def release_read(self):
        """Release read lock."""
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def acquire_write(self):
        """Acquire write lock. Exclusive access."""
        with self._read_ready:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                self._read_ready.wait()
            self._writers_waiting -= 1
            self._writer_active = True

    def release_write(self):
        """Release write lock."""
        with self._read_ready:
            self._writer_active = False
            self._read_ready.notify_all()


@contextmanager
def read_lock(rwlock: RWLock):
    """Context manager for read lock."""
    rwlock.acquire_read()
    try:
        yield
    finally:
        rwlock.release_read()


@contextmanager
def write_lock(rwlock: RWLock):
    """Context manager for write lock."""
    rwlock.acquire_write()
    try:
        yield
    finally:
        rwlock.release_write()


# Global RWLock instance for session store
# Replaces simple _db_lock for better concurrent read performance
_rwlock = RWLock()

# Path is set up by assistant/__init__.py
from paths import get_data_dir


# Constants
MAX_CONTENT_LENGTH = 50000  # Truncate very long content
MAX_TURNS_FOR_CONTEXT = 30  # Default, overridable via backends.json "max_context_turns"


def _get_max_context_turns() -> int:
    """Get max_context_turns from config (backends.json), fallback to constant."""
    try:
        from .skills import load_config
        config = load_config()
        return config.get("max_context_turns", MAX_TURNS_FOR_CONTEXT)
    except Exception:
        return MAX_TURNS_FOR_CONTEXT
SESSION_TIMEOUT_MINUTES = 30  # Auto-complete after inactivity
PREVIEW_LENGTH = 100  # Length of preview text in session list

# Database path (lazy initialized)
_db_path: Optional[Path] = None


def _get_db_path() -> Path:
    """Get database path (lazy initialization)."""
    global _db_path
    if _db_path is None:
        _db_path = get_data_dir() / "datastore.db"
    return _db_path


def get_connection() -> sqlite3.Connection:
    """Get database connection with auto-init and optimized settings."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Performance optimizations for concurrent access
    conn.execute("PRAGMA journal_mode=WAL")  # Enables concurrent reads
    conn.execute("PRAGMA busy_timeout=5000")  # 5s timeout on lock conflicts
    conn.execute("PRAGMA foreign_keys = ON")  # Enable CASCADE delete

    _init_tables(conn)
    return conn


def _init_tables(conn: sqlite3.Connection):
    """Create sessions and turns tables if not exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL,
            backend TEXT NOT NULL,
            model TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            total_tokens INTEGER DEFAULT 0,
            total_cost_usd REAL DEFAULT 0.0,
            preview TEXT,
            triggered_by TEXT DEFAULT 'webui'
        );

        -- Add triggered_by column if it doesn't exist (migration for existing DBs)
        -- SQLite doesn't support IF NOT EXISTS for ALTER TABLE, so we check via pragma
    """)

    # Migration: Add columns if missing
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = [row[1] for row in cursor.fetchall()]
    if "triggered_by" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN triggered_by TEXT DEFAULT 'webui'")
    if "log_content" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN log_content TEXT")
    if "sdk_session_id" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN sdk_session_id TEXT")
    if "link_map" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN link_map TEXT")  # JSON string
    if "anonymization_enabled" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN anonymization_enabled INTEGER DEFAULT NULL")

    conn.executescript("""

        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            task_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name);
        CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
    """)
    conn.commit()


# =============================================================================
# Session Management
# =============================================================================

def create_session(agent_name: str, backend: str, model: str = None,
                   triggered_by: str = "webui",
                   anonymization_enabled: bool | None = None) -> str:
    """
    Create new session, returns session_id.

    Args:
        agent_name: Name of the agent (e.g., "chat", "chat_claude")
        backend: AI backend type (e.g., "claude_sdk", "gemini")
        model: Model name (e.g., "claude-sonnet-4")
        triggered_by: What triggered this session:
            - "webui": User clicked tile/chat in WebUI
            - "voice": Voice hotkey
            - "email_watcher": Email auto-watcher
            - "workflow": Another agent started this (desk_run_agent)
            - "api": Direct API call
        anonymization_enabled: Whether PII anonymization was active for this session.
            True = active, False = not active, None = unknown/legacy

    Returns:
        Session ID in format "s_YYYYMMDD_HHMMSS_mmm" (with milliseconds for uniqueness)
    """
    now = datetime.now()
    # Include milliseconds to ensure uniqueness when creating multiple sessions quickly
    session_id = f"s_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond // 1000:03d}"
    now_iso = now.isoformat()

    # Convert bool to INTEGER for SQLite (1/0/NULL)
    anon_value = None
    if anonymization_enabled is True:
        anon_value = 1
    elif anonymization_enabled is False:
        anon_value = 0

    with write_lock(_rwlock):
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO sessions
                   (id, agent_name, backend, model, status, created_at, updated_at,
                    triggered_by, anonymization_enabled)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                (session_id, agent_name, backend, model, now_iso, now_iso,
                 triggered_by, anon_value)
            )
            conn.commit()
        finally:
            conn.close()

    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get session by ID with all turns.

    Args:
        session_id: The session ID to retrieve

    Returns:
        Session dict with turns, or None if not found
    """
    with read_lock(_rwlock):
        conn = get_connection()
        try:
            import json

            # Get session
            cursor = conn.execute(
                """SELECT id, agent_name, backend, model, status, created_at,
                          updated_at, total_tokens, total_cost_usd, preview, triggered_by,
                          log_content, sdk_session_id, link_map, anonymization_enabled
                   FROM sessions WHERE id = ?""",
                (session_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Parse link_map JSON
            link_map = {}
            if row["link_map"]:
                try:
                    link_map = json.loads(row["link_map"])
                except (json.JSONDecodeError, TypeError):
                    pass

            # Convert INTEGER to bool/None for anonymization_enabled
            anon_raw = row["anonymization_enabled"]
            anon_enabled = True if anon_raw == 1 else (False if anon_raw == 0 else None)

            session = {
                "id": row["id"],
                "agent_name": row["agent_name"],
                "backend": row["backend"],
                "model": row["model"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "total_tokens": row["total_tokens"],
                "total_cost_usd": row["total_cost_usd"],
                "preview": row["preview"],
                "triggered_by": row["triggered_by"] or "webui",
                "log_content": row["log_content"],
                "sdk_session_id": row["sdk_session_id"],  # SDK Extended Mode
                "link_map": link_map,  # V2 Link Placeholder System
                "anonymization_enabled": anon_enabled,  # [043] PII anonymization badge
                "turns": []
            }

            # Get turns
            cursor = conn.execute(
                """SELECT id, role, content, tokens, cost_usd, task_id, created_at
                   FROM turns WHERE session_id = ?
                   ORDER BY id ASC""",
                (session_id,)
            )

            for turn_row in cursor.fetchall():
                session["turns"].append({
                    "id": turn_row["id"],
                    "role": turn_row["role"],
                    "content": turn_row["content"],
                    "tokens": turn_row["tokens"],
                    "cost_usd": turn_row["cost_usd"],
                    "task_id": turn_row["task_id"],
                    "created_at": turn_row["created_at"]
                })

            return session
        finally:
            conn.close()


def add_turn(
    session_id: str,
    role: str,
    content: str,
    tokens: int = 0,
    cost_usd: float = 0.0,
    task_id: str = None
) -> bool:
    """
    Add turn to session, update session totals.

    Args:
        session_id: The session to add the turn to
        role: "user" or "assistant"
        content: The message content
        tokens: Token count (input for user, output for assistant)
        cost_usd: Cost of this turn
        task_id: Optional reference to original task

    Returns:
        True if successful, False if session not found
    """
    # Truncate content if too long
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n\n[... truncated ...]"

    now = get_timestamp_iso()

    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # Check session exists
            cursor = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
            if not cursor.fetchone():
                return False

            # Insert turn
            conn.execute(
                """INSERT INTO turns (session_id, role, content, tokens, cost_usd, task_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, role, content, tokens, cost_usd, task_id, now)
            )

            # Update session totals and timestamp
            conn.execute(
                """UPDATE sessions
                   SET total_tokens = total_tokens + ?,
                       total_cost_usd = total_cost_usd + ?,
                       updated_at = ?
                   WHERE id = ?""",
                (tokens, cost_usd, now, session_id)
            )

            # Update preview only if this is a USER message and preview is empty
            # We want to show what the user asked, not the assistant's response
            if role == "user":
                cursor = conn.execute(
                    "SELECT preview FROM sessions WHERE id = ?",
                    (session_id,)
                )
                row = cursor.fetchone()
                if row and not row["preview"]:
                    preview = content[:PREVIEW_LENGTH]
                    if len(content) > PREVIEW_LENGTH:
                        preview += "..."
                    conn.execute(
                        "UPDATE sessions SET preview = ? WHERE id = ?",
                        (preview, session_id)
                    )

            conn.commit()
            return True
        finally:
            conn.close()


def complete_session(session_id: str, log_content: str = None,
                     sdk_session_id: str = None, link_map: dict = None) -> bool:
    """
    Mark session as completed and optionally store log content and link_map.

    Args:
        session_id: The session to complete
        log_content: Optional execution log to store (tool calls, prompts, etc.)
        sdk_session_id: Optional Claude SDK session ID for resume capability
        link_map: Optional link_ref -> web_link mapping (V2 Link System)

    Returns:
        True if successful, False if session not found or already completed
    """
    import json
    now = get_timestamp_iso()
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # Idempotency check: skip if already completed (Bug fix #3)
            cursor = conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row and row[0] == 'completed':
                return True  # Already completed, return success without re-updating

            # Build dynamic UPDATE based on provided fields
            update_fields = ["status = 'completed'", "updated_at = ?"]
            params = [now]

            if log_content:
                # Truncate if too long
                if len(log_content) > MAX_CONTENT_LENGTH:
                    log_content = log_content[:MAX_CONTENT_LENGTH] + "\n\n[... truncated ...]"
                update_fields.append("log_content = ?")
                params.append(log_content)

            if sdk_session_id:
                update_fields.append("sdk_session_id = ?")
                params.append(sdk_session_id)

            if link_map:
                update_fields.append("link_map = ?")
                params.append(json.dumps(link_map, ensure_ascii=False))

            params.append(session_id)
            sql = f"UPDATE sessions SET {', '.join(update_fields)} WHERE id = ?"
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def reactivate_session(session_id: str) -> bool:
    """
    Reactivate a completed session (sets status back to 'active').
    Used when user continues an old session from History.

    Args:
        session_id: The session to reactivate

    Returns:
        True if successful, False if session not found or already active
    """
    now = get_timestamp_iso()
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # Non-atomic check: prevent double-activation (Bug fix #4)
            # If session is already active, skip to prevent two tasks running for same session
            cursor = conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row and row[0] == 'active':
                # Import system_log for logging
                try:
                    from ai_agent.base import system_log
                    system_log(f"[session] Session {session_id} already active, skipping reactivation")
                except ImportError:
                    pass
                return False  # Already active, don't allow double-activation

            cursor = conn.execute(
                "UPDATE sessions SET status = 'active', updated_at = ? WHERE id = ?",
                (now, session_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def store_log_content(session_id: str, log_content: str) -> bool:
    """
    Store execution log content for a session.

    Can be called independently of complete_session if needed.

    Args:
        session_id: The session to update
        log_content: The execution log (tool calls, prompts, debug output)

    Returns:
        True if successful, False if session not found
    """
    # Truncate if too long
    if len(log_content) > MAX_CONTENT_LENGTH:
        log_content = log_content[:MAX_CONTENT_LENGTH] + "\n\n[... truncated ...]"

    now = get_timestamp_iso()
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            cursor = conn.execute(
                "UPDATE sessions SET log_content = ?, updated_at = ? WHERE id = ?",
                (log_content, now, session_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def update_link_map(session_id: str, link_map: dict) -> bool:
    """
    Update link_map for a session (V2 Link Placeholder System).

    Can be called during agent execution to persist link registrations.

    Args:
        session_id: The session to update
        link_map: Dict mapping link_ref to web_link

    Returns:
        True if successful, False if session not found
    """
    import json
    now = get_timestamp_iso()
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            cursor = conn.execute(
                "UPDATE sessions SET link_map = ?, updated_at = ? WHERE id = ?",
                (json.dumps(link_map, ensure_ascii=False), now, session_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def get_link_map(session_id: str) -> dict:
    """
    Get link_map for a session (V2 Link Placeholder System).

    Args:
        session_id: The session to get links for

    Returns:
        Dict mapping link_ref to web_link, or empty dict if not found
    """
    import json
    with read_lock(_rwlock):
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT link_map FROM sessions WHERE id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return {}
        finally:
            conn.close()


# =============================================================================
# Retrieval
# =============================================================================

def get_sessions(
    limit: int = 20,
    offset: int = 0,
    agent_name: str = None,
    status: str = None
) -> List[Dict[str, Any]]:
    """
    Get sessions list (without turns, for performance).

    Args:
        limit: Maximum number of sessions to return
        offset: Number of sessions to skip (for pagination)
        agent_name: Optional filter by agent name
        status: Optional filter by status ("active" or "completed")

    Returns:
        List of session dicts (without turns)
    """
    with read_lock(_rwlock):
        conn = get_connection()
        try:
            # Build query with optional filters
            query = """SELECT id, agent_name, backend, model, status, created_at,
                              updated_at, total_tokens, total_cost_usd, preview, triggered_by,
                              anonymization_enabled
                       FROM sessions WHERE 1=1"""
            params: List[Any] = []

            if agent_name:
                query += " AND agent_name = ?"
                params.append(agent_name)

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            sessions = []

            for row in cursor.fetchall():
                # Count turns for this session
                turn_cursor = conn.execute(
                    "SELECT COUNT(*) FROM turns WHERE session_id = ?",
                    (row["id"],)
                )
                turn_count = turn_cursor.fetchone()[0]

                # Convert INTEGER to bool/None for anonymization_enabled
                anon_raw = row["anonymization_enabled"]
                anon_enabled = True if anon_raw == 1 else (False if anon_raw == 0 else None)

                sessions.append({
                    "id": row["id"],
                    "agent_name": row["agent_name"],
                    "backend": row["backend"],
                    "model": row["model"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "total_tokens": row["total_tokens"],
                    "total_cost_usd": row["total_cost_usd"],
                    "preview": row["preview"],
                    "triggered_by": row["triggered_by"] or "webui",
                    "turn_count": turn_count,
                    "anonymization_enabled": anon_enabled,  # [043] PII anonymization badge
                })

            return sessions
        finally:
            conn.close()


def get_session_context(session_id: str, max_turns: int = None) -> str:
    """
    Build context string for continue/transfer.

    Args:
        session_id: The session to build context from
        max_turns: Maximum number of turns to include

    Returns:
        Formatted string like:
        "Here is our previous conversation:\\n\\nUser: ...\\nAssistant: ...\\n\\n---\\n\\n"
        Returns empty string if session not found.
    """
    def _strip_dialog_meta(content):
        """[060] Strip ---DIALOG_META--- block from turn content before sending to AI."""
        if content and "\n---DIALOG_META---\n" in content:
            return content.split("\n---DIALOG_META---\n")[0]
        return content or ""

    if max_turns is None:
        max_turns = _get_max_context_turns()

    session = get_session(session_id)
    if not session:
        return ""

    turns = session.get("turns", [])
    if not turns:
        return ""

    # Take last N turns if exceeding max
    if len(turns) > max_turns:
        turns = turns[-max_turns:]
        truncated = True
    else:
        truncated = False

    # Build context
    lines = ["Here is our previous conversation:"]
    if truncated:
        lines.append(f"(Showing last {max_turns} of {len(session['turns'])} messages)")
    lines.append("")

    for turn in turns:
        role_label = "User" if turn["role"] == "user" else "Assistant"
        # [060] Strip dialog metadata before sending to AI (prompt pollution prevention)
        content = _strip_dialog_meta(turn['content'])
        lines.append(f"{role_label}: {content}")
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# Actions
# =============================================================================

def get_active_session(agent_name: str) -> Optional[str]:
    """
    Get most recent active session for agent (within timeout).

    Only returns sessions that were triggered interactively (webui, voice).
    Sessions triggered by workflows, email_watcher, api, or auto_chain
    are excluded to prevent automated sessions from being continued
    by manual user interactions.

    Args:
        agent_name: The agent name to find active session for

    Returns:
        Session ID if found, None otherwise
    """
    cutoff = datetime.now() - timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    cutoff_str = cutoff.isoformat()

    with read_lock(_rwlock):
        conn = get_connection()
        try:
            # Exclude workflow/automated sessions from continuation
            # These should remain standalone and not be mixed with interactive sessions
            cursor = conn.execute(
                """SELECT id FROM sessions
                   WHERE agent_name = ?
                     AND status = 'active'
                     AND updated_at > ?
                     AND (triggered_by IS NULL OR triggered_by IN ('webui', 'voice'))
                   ORDER BY updated_at DESC
                   LIMIT 1""",
                (agent_name, cutoff_str)
            )
            row = cursor.fetchone()
            return row["id"] if row else None
        finally:
            conn.close()


def auto_complete_stale_sessions() -> int:
    """
    Mark sessions as completed if inactive > SESSION_TIMEOUT_MINUTES.

    Returns:
        Number of sessions completed
    """
    cutoff = datetime.now() - timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    cutoff_str = cutoff.isoformat()
    now = get_timestamp_iso()

    with write_lock(_rwlock):
        conn = get_connection()
        try:
            cursor = conn.execute(
                """UPDATE sessions
                   SET status = 'completed', updated_at = ?
                   WHERE status = 'active' AND updated_at < ?""",
                (now, cutoff_str)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


# =============================================================================
# Cleanup
# =============================================================================

def delete_session(session_id: str) -> bool:
    """
    Delete session and all its turns.

    Args:
        session_id: The session to delete

    Returns:
        True if session was deleted, False if not found
    """
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # With CASCADE, turns are deleted automatically
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def delete_all_sessions() -> int:
    """
    Delete ALL sessions and their turns.

    Returns:
        Number of sessions deleted
    """
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # Count before delete
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            count = cursor.fetchone()[0]

            # Delete all (turns are deleted via CASCADE)
            conn.execute("DELETE FROM sessions")
            conn.commit()

            return count
        finally:
            conn.close()


def delete_completed_sessions() -> int:
    """
    Delete all completed sessions (keeps active sessions).

    Returns:
        Number of sessions deleted
    """
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # Count before delete
            cursor = conn.execute("SELECT COUNT(*) FROM sessions WHERE status = 'completed'")
            count = cursor.fetchone()[0]

            # Delete completed sessions (turns are deleted via CASCADE)
            conn.execute("DELETE FROM sessions WHERE status = 'completed'")
            conn.commit()

            return count
        finally:
            conn.close()


def cleanup_old_sessions(max_sessions: int = 50) -> int:
    """
    Delete oldest sessions if count exceeds max (FIFO).

    Args:
        max_sessions: Maximum number of sessions to keep

    Returns:
        Number of sessions deleted
    """
    with write_lock(_rwlock):
        conn = get_connection()
        try:
            # Count current sessions
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            count = cursor.fetchone()[0]

            if count <= max_sessions:
                return 0

            # Get IDs of sessions to delete (oldest first)
            to_delete = count - max_sessions
            cursor = conn.execute(
                """SELECT id FROM sessions
                   ORDER BY updated_at ASC
                   LIMIT ?""",
                (to_delete,)
            )
            ids_to_delete = [row["id"] for row in cursor.fetchall()]

            # Delete them
            if ids_to_delete:
                placeholders = ",".join("?" * len(ids_to_delete))
                conn.execute(
                    f"DELETE FROM sessions WHERE id IN ({placeholders})",
                    ids_to_delete
                )
                conn.commit()

            return len(ids_to_delete)
        finally:
            conn.close()


def get_stats() -> Dict[str, Any]:
    """
    Get session statistics.

    Returns:
        Dict with statistics:
        - total_sessions: Total number of sessions
        - active_sessions: Number of active sessions
        - completed_sessions: Number of completed sessions
        - total_turns: Total number of turns across all sessions
        - total_tokens: Sum of all tokens
        - total_cost_usd: Sum of all costs
    """
    with read_lock(_rwlock):
        conn = get_connection()
        try:
            # Session counts
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM sessions WHERE status = 'active'")
            active_sessions = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM sessions WHERE status = 'completed'")
            completed_sessions = cursor.fetchone()[0]

            # Turn count
            cursor = conn.execute("SELECT COUNT(*) FROM turns")
            total_turns = cursor.fetchone()[0]

            # Totals from sessions
            cursor = conn.execute(
                "SELECT COALESCE(SUM(total_tokens), 0), COALESCE(SUM(total_cost_usd), 0.0) FROM sessions"
            )
            row = cursor.fetchone()
            total_tokens = row[0]
            total_cost_usd = row[1]

            return {
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "completed_sessions": completed_sessions,
                "total_turns": total_turns,
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost_usd
            }
        finally:
            conn.close()


# =============================================================================
# Testing Support
# =============================================================================

def _set_db_path(path: Path):
    """Set database path (for testing only)."""
    global _db_path
    _db_path = path


def _reset_db_path():
    """Reset database path to default (for testing only)."""
    global _db_path
    _db_path = None
