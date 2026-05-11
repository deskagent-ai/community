# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Workflow State Management (SQLite)
==================================
Persists workflow state for auto-resume after crash/restart.

Uses shared datastore.db (tables initialized by datastore MCP).
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

# Use centralized path management
try:
    from paths import get_data_dir
except ImportError:
    # Fallback for direct execution
    def get_data_dir():
        return Path(__file__).parent.parent.parent.parent / "workspace" / ".state"

# Centralized timestamp utilities
try:
    from utils.timestamp import get_timestamp_iso
except ImportError:
    # Fallback for standalone execution
    from datetime import datetime
    def get_timestamp_iso(): return datetime.now().isoformat()

DB_PATH = None  # Lazy initialized
_migrated = False


def _auto_migrate_from_old_db():
    """Auto-migrate from old workflows.db if it exists."""
    global _migrated
    if _migrated:
        return

    _migrated = True
    old_db = get_data_dir() / "workflows.db"

    if not old_db.exists():
        return

    try:
        new_db = get_data_dir() / "datastore.db"

        # Connect to old database
        old_conn = sqlite3.connect(str(old_db))
        old_conn.row_factory = sqlite3.Row

        # Check if old DB has data
        cursor = old_conn.execute("SELECT COUNT(*) FROM workflow_runs")
        count = cursor.fetchone()[0]

        if count == 0:
            old_conn.close()
            old_db.unlink()
            return

        # Connect to new database
        new_conn = sqlite3.connect(str(new_db))

        # Ensure table exists
        new_conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_name TEXT NOT NULL,
                step_index INTEGER DEFAULT 0,
                state TEXT DEFAULT '{}',
                status TEXT DEFAULT 'running',
                created_at TEXT,
                updated_at TEXT,
                error TEXT
            )
        """)

        # Check if new DB already has workflow data
        cursor = new_conn.execute("SELECT COUNT(*) FROM workflow_runs")
        new_count = cursor.fetchone()[0]

        if new_count > 0:
            # Already has data, skip migration
            old_conn.close()
            new_conn.close()
            return

        # Copy data
        cursor = old_conn.execute("SELECT * FROM workflow_runs")
        for row in cursor:
            new_conn.execute("""
                INSERT OR REPLACE INTO workflow_runs
                (id, workflow_name, step_index, state, status, created_at, updated_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["id"], row["workflow_name"], row["step_index"], row["state"],
                  row["status"], row["created_at"], row["updated_at"], row["error"]))

        new_conn.commit()
        old_conn.close()
        new_conn.close()

        # Delete old file after successful migration
        old_db.unlink()

    except Exception:
        pass  # Silently fail, old DB will remain


def _get_db_path() -> Path:
    """Get database path (lazy initialization).

    Uses shared datastore.db instead of separate workflows.db.
    """
    global DB_PATH
    if DB_PATH is None:
        DB_PATH = get_data_dir() / "datastore.db"
    return DB_PATH


def _get_connection() -> sqlite3.Connection:
    """Get database connection.

    Tables are initialized by datastore MCP (_init_tables).
    Fallback CREATE TABLE for standalone usage.
    """
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    # Fallback: create table if datastore MCP hasn't initialized yet
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            step_index INTEGER DEFAULT 0,
            state TEXT DEFAULT '{}',
            status TEXT DEFAULT 'running',
            created_at TEXT,
            updated_at TEXT,
            error TEXT
        )
    """)
    conn.commit()

    # Auto-migrate from old workflows.db if exists
    _auto_migrate_from_old_db()

    return conn


def create_run(run_id: str, workflow_name: str, initial_state: dict) -> None:
    """Create a new workflow run."""
    conn = _get_connection()
    now = get_timestamp_iso()
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, workflow_name, json.dumps(initial_state, ensure_ascii=False), now, now)
    )
    conn.commit()
    conn.close()


def save_state(run_id: str, step_index: int, state: dict) -> None:
    """Save current workflow state (called before each step)."""
    conn = _get_connection()
    now = get_timestamp_iso()

    # Filter out non-serializable attributes
    serializable_state = {}
    for key, value in state.items():
        if key.startswith("_") or key == "tool":
            continue
        try:
            json.dumps(value)
            serializable_state[key] = value
        except (TypeError, ValueError):
            pass  # Skip non-serializable values

    conn.execute(
        "UPDATE workflow_runs SET step_index = ?, state = ?, updated_at = ? WHERE id = ?",
        (step_index, json.dumps(serializable_state, ensure_ascii=False), now, run_id)
    )
    conn.commit()
    conn.close()


def complete(run_id: str, message: str = "Success") -> None:
    """Mark workflow as completed."""
    conn = _get_connection()
    now = get_timestamp_iso()
    conn.execute(
        "UPDATE workflow_runs SET status = ?, updated_at = ? WHERE id = ?",
        (f"completed: {message}", now, run_id)
    )
    conn.commit()
    conn.close()


def fail(run_id: str, error: str) -> None:
    """Mark workflow as failed."""
    conn = _get_connection()
    now = get_timestamp_iso()
    conn.execute(
        "UPDATE workflow_runs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
        ("failed", error, now, run_id)
    )
    conn.commit()
    conn.close()


def get_run(run_id: str) -> Optional[dict]:
    """Get a specific workflow run."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT id, workflow_name, step_index, state, status, created_at, updated_at, error FROM workflow_runs WHERE id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row[0],
        "workflow_name": row[1],
        "step_index": row[2],
        "state": json.loads(row[3]) if row[3] else {},
        "status": row[4],
        "created_at": row[5],
        "updated_at": row[6],
        "error": row[7]
    }


def get_interrupted_runs() -> List[dict]:
    """Get all workflow runs with status 'running' (interrupted by crash)."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT id, workflow_name, step_index, state, status, created_at, updated_at FROM workflow_runs WHERE status = 'running'"
    )
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "workflow_name": row[1],
            "step_index": row[2],
            "state": json.loads(row[3]) if row[3] else {},
            "status": row[4],
            "created_at": row[5],
            "updated_at": row[6]
        }
        for row in rows
    ]


def get_recent_runs(limit: int = 50) -> List[dict]:
    """Get recent workflow runs."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT id, workflow_name, step_index, status, created_at, updated_at, error FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "workflow_name": row[1],
            "step_index": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "error": row[6]
        }
        for row in rows
    ]


def cleanup_old_runs(days: int = 30) -> int:
    """Delete runs older than specified days. Returns count of deleted runs."""
    conn = _get_connection()
    cursor = conn.execute(
        "DELETE FROM workflow_runs WHERE updated_at < datetime('now', ?)",
        (f"-{days} days",)
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted
