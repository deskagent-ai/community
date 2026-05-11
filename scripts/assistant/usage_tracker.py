# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Agent Usage Tracker
===================
Tracks execution counts using datastore counters table.
Counter naming: agent_exec:{agent_name}
"""

import sqlite3
import threading
from typing import Dict
from pathlib import Path

_lock = threading.Lock()
DB_PATH = None


def _get_db_path() -> Path:
    """Get database path (lazy initialization)."""
    global DB_PATH
    if DB_PATH is None:
        from paths import get_data_dir
        DB_PATH = get_data_dir() / "datastore.db"
    return DB_PATH


def increment_agent(agent_name: str) -> int:
    """Increment agent execution counter. Returns new count."""
    return _increment_counter(f"agent_exec:{agent_name}")


def _ensure_table(conn: sqlite3.Connection):
    """Ensure counters table exists (defensive, normally created by datastore MCP)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _increment_counter(name: str) -> int:
    """Atomic counter increment using datastore counters table."""
    with _lock:
        conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)
        try:
            _ensure_table(conn)
            conn.execute("""
                INSERT INTO counters (name, value, updated_at)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    value = value + 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (name,))
            conn.commit()
            row = conn.execute(
                "SELECT value FROM counters WHERE name = ?", (name,)
            ).fetchone()
            return row[0] if row else 1
        finally:
            conn.close()


def get_agent_stats() -> Dict:
    """Get all agent execution statistics."""
    with _lock:
        conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)
        try:
            _ensure_table(conn)
            cursor = conn.execute("""
                SELECT name, value, updated_at FROM counters
                WHERE name LIKE 'agent_exec:%'
                ORDER BY value DESC
            """)
            agents = {}
            total = 0
            for name, value, updated in cursor:
                agent = name.replace("agent_exec:", "")
                agents[agent] = {
                    "executions": value,
                    "last_executed": updated
                }
                total += value
            return {"agents": agents, "total": total}
        finally:
            conn.close()
