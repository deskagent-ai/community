# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Persistent API Cost Tracker (SQLite)
====================================
Tracks cumulative API costs across server restarts.
Stores data in workspace/.state/datastore.db (shared with datastore MCP).
"""

import sqlite3
import threading
from pathlib import Path
import sys

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# Path is set up by assistant/__init__.py
from paths import get_data_dir

# Centralized timestamp utilities
try:
    from utils.timestamp import get_timestamp_date, get_timestamp_iso
except ImportError:
    from datetime import datetime
    def get_timestamp_date(): return datetime.now().strftime("%Y-%m-%d")
    def get_timestamp_iso(): return datetime.now().isoformat()

# Thread lock for safe concurrent access
_lock = threading.Lock()

# Database path
DB_PATH = None
_migrated = False


def _get_db_path() -> Path:
    """Get database path (lazy initialization)."""
    global DB_PATH
    if DB_PATH is None:
        DB_PATH = get_data_dir() / "datastore.db"
    return DB_PATH


def _auto_migrate_from_json():
    """Auto-migrate from api_costs.json if it exists."""
    global _migrated
    if _migrated:
        return

    _migrated = True
    json_file = get_data_dir() / "api_costs.json"

    if not json_file.exists():
        return

    try:
        import json
        data = json.loads(json_file.read_text(encoding="utf-8"))

        conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)

        # Check if already migrated (has data)
        cursor = conn.execute("SELECT task_count FROM api_costs WHERE id = 1")
        row = cursor.fetchone()
        if row and row[0] > 0:
            conn.close()
            return  # Already has data, skip migration

        # Migrate totals
        conn.execute("""
            INSERT OR REPLACE INTO api_costs (id, total_usd, total_input_tokens, total_output_tokens,
                                   total_audio_seconds, task_count, last_updated)
            VALUES (1, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("total_usd", 0),
            data.get("total_input_tokens", 0),
            data.get("total_output_tokens", 0),
            data.get("total_audio_seconds", 0),
            data.get("task_count", 0),
            data.get("last_updated")
        ))

        # Migrate by_model
        for model, stats in data.get("by_model", {}).items():
            conn.execute("""
                INSERT OR REPLACE INTO api_costs_by_model (model, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (model, stats.get("cost_usd", 0), stats.get("input_tokens", 0),
                  stats.get("output_tokens", 0), stats.get("audio_seconds", 0), stats.get("task_count", 0)))

        # Migrate by_backend
        for backend, stats in data.get("by_backend", {}).items():
            conn.execute("""
                INSERT OR REPLACE INTO api_costs_by_backend (backend, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (backend, stats.get("cost_usd", 0), stats.get("input_tokens", 0),
                  stats.get("output_tokens", 0), stats.get("audio_seconds", 0), stats.get("task_count", 0)))

        # Migrate by_date
        for date, stats in data.get("by_date", {}).items():
            conn.execute("""
                INSERT OR REPLACE INTO api_costs_by_date (date, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (date, stats.get("cost_usd", 0), stats.get("input_tokens", 0),
                  stats.get("output_tokens", 0), stats.get("audio_seconds", 0), stats.get("task_count", 0)))

        conn.commit()
        conn.close()

        # Delete old file after successful migration
        json_file.unlink()
        system_log(f"[CostTracker] Auto-migrated from api_costs.json and deleted old file")

    except Exception as e:
        system_log(f"[CostTracker] Auto-migration failed: {e}")


def _get_connection() -> sqlite3.Connection:
    """Get database connection with auto-init tables."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Ensure tables exist (fallback if datastore MCP hasn't initialized)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_costs (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_usd REAL DEFAULT 0,
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            total_audio_seconds REAL DEFAULT 0,
            task_count INTEGER DEFAULT 0,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS api_costs_by_model (
            model TEXT PRIMARY KEY,
            cost_usd REAL DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            audio_seconds REAL DEFAULT 0,
            task_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS api_costs_by_backend (
            backend TEXT PRIMARY KEY,
            cost_usd REAL DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            audio_seconds REAL DEFAULT 0,
            task_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS api_costs_by_date (
            date TEXT PRIMARY KEY,
            cost_usd REAL DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            audio_seconds REAL DEFAULT 0,
            task_count INTEGER DEFAULT 0
        );
    """)
    conn.commit()

    # Auto-migrate from old JSON file if exists
    _auto_migrate_from_json()

    return conn


def _ensure_totals_row(conn: sqlite3.Connection):
    """Ensure the single totals row exists."""
    cursor = conn.execute("SELECT id FROM api_costs WHERE id = 1")
    if cursor.fetchone() is None:
        conn.execute("""
            INSERT INTO api_costs (id, total_usd, total_input_tokens, total_output_tokens,
                                   total_audio_seconds, task_count, last_updated)
            VALUES (1, 0, 0, 0, 0, 0, NULL)
        """)
        conn.commit()


def add_cost(
    cost_usd: float = None,
    input_tokens: int = None,
    output_tokens: int = None,
    model: str = None,
    task_type: str = None,
    task_name: str = None,
    backend: str = None,
    audio_seconds: float = None
):
    """
    Add a cost entry.

    Args:
        cost_usd: Cost in USD (optional - calculated if tokens provided)
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model name (e.g., "claude-sonnet-4", "whisper-1")
        task_type: "skill", "agent", "prompt", or "transcription"
        task_name: Name of the skill/agent
        backend: Backend name (e.g., "claude_sdk", "gemini", "whisper")
        audio_seconds: Duration of audio in seconds (for Whisper API)
    """
    with _lock:
        conn = _get_connection()
        try:
            _ensure_totals_row(conn)

            today = get_timestamp_date()
            now = get_timestamp_iso()

            # Update totals
            conn.execute("""
                UPDATE api_costs SET
                    total_usd = total_usd + ?,
                    total_input_tokens = total_input_tokens + ?,
                    total_output_tokens = total_output_tokens + ?,
                    total_audio_seconds = total_audio_seconds + ?,
                    task_count = task_count + 1,
                    last_updated = ?
                WHERE id = 1
            """, (
                cost_usd or 0,
                input_tokens or 0,
                output_tokens or 0,
                audio_seconds or 0,
                now
            ))

            # Update by_model
            if model:
                conn.execute("""
                    INSERT INTO api_costs_by_model (model, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(model) DO UPDATE SET
                        cost_usd = cost_usd + excluded.cost_usd,
                        input_tokens = input_tokens + excluded.input_tokens,
                        output_tokens = output_tokens + excluded.output_tokens,
                        audio_seconds = audio_seconds + excluded.audio_seconds,
                        task_count = task_count + 1
                """, (model, cost_usd or 0, input_tokens or 0, output_tokens or 0, audio_seconds or 0))

            # Update by_backend
            if backend:
                conn.execute("""
                    INSERT INTO api_costs_by_backend (backend, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(backend) DO UPDATE SET
                        cost_usd = cost_usd + excluded.cost_usd,
                        input_tokens = input_tokens + excluded.input_tokens,
                        output_tokens = output_tokens + excluded.output_tokens,
                        audio_seconds = audio_seconds + excluded.audio_seconds,
                        task_count = task_count + 1
                """, (backend, cost_usd or 0, input_tokens or 0, output_tokens or 0, audio_seconds or 0))

            # Update by_date
            conn.execute("""
                INSERT INTO api_costs_by_date (date, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(date) DO UPDATE SET
                    cost_usd = cost_usd + excluded.cost_usd,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    audio_seconds = audio_seconds + excluded.audio_seconds,
                    task_count = task_count + 1
            """, (today, cost_usd or 0, input_tokens or 0, output_tokens or 0, audio_seconds or 0))

            conn.commit()
        finally:
            conn.close()


def get_costs() -> dict:
    """Get current cost statistics."""
    with _lock:
        conn = _get_connection()
        try:
            _ensure_totals_row(conn)

            # Get totals
            cursor = conn.execute("SELECT * FROM api_costs WHERE id = 1")
            row = cursor.fetchone()

            result = {
                "total_usd": row["total_usd"] or 0.0,
                "total_input_tokens": row["total_input_tokens"] or 0,
                "total_output_tokens": row["total_output_tokens"] or 0,
                "total_audio_seconds": row["total_audio_seconds"] or 0.0,
                "task_count": row["task_count"] or 0,
                "last_updated": row["last_updated"],
                "by_model": {},
                "by_backend": {},
                "by_date": {}
            }

            # Get by_model
            cursor = conn.execute("SELECT * FROM api_costs_by_model ORDER BY cost_usd DESC")
            for row in cursor:
                result["by_model"][row["model"]] = {
                    "cost_usd": row["cost_usd"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "audio_seconds": row["audio_seconds"],
                    "task_count": row["task_count"]
                }

            # Get by_backend
            cursor = conn.execute("SELECT * FROM api_costs_by_backend ORDER BY cost_usd DESC")
            for row in cursor:
                result["by_backend"][row["backend"]] = {
                    "cost_usd": row["cost_usd"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "audio_seconds": row["audio_seconds"],
                    "task_count": row["task_count"]
                }

            # Get by_date
            cursor = conn.execute("SELECT * FROM api_costs_by_date ORDER BY date DESC")
            for row in cursor:
                result["by_date"][row["date"]] = {
                    "cost_usd": row["cost_usd"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "audio_seconds": row["audio_seconds"],
                    "task_count": row["task_count"]
                }

            return result
        finally:
            conn.close()


def get_today_costs() -> dict:
    """Get costs for today only."""
    with _lock:
        conn = _get_connection()
        try:
            today = get_timestamp_date()
            cursor = conn.execute(
                "SELECT * FROM api_costs_by_date WHERE date = ?",
                (today,)
            )
            row = cursor.fetchone()

            if row:
                return {
                    "cost_usd": row["cost_usd"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "audio_seconds": row["audio_seconds"],
                    "task_count": row["task_count"]
                }
            else:
                return {
                    "cost_usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "audio_seconds": 0.0,
                    "task_count": 0
                }
        finally:
            conn.close()


def reset_costs():
    """Reset all costs (use with caution)."""
    with _lock:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM api_costs")
            conn.execute("DELETE FROM api_costs_by_model")
            conn.execute("DELETE FROM api_costs_by_backend")
            conn.execute("DELETE FROM api_costs_by_date")
            conn.commit()
        finally:
            conn.close()


def get_summary() -> dict:
    """Get a summary suitable for WebUI display."""
    with _lock:
        conn = _get_connection()
        try:
            _ensure_totals_row(conn)

            # Get totals
            cursor = conn.execute("SELECT * FROM api_costs WHERE id = 1")
            totals = cursor.fetchone()

            # Get today's costs
            today = get_timestamp_date()
            cursor = conn.execute(
                "SELECT cost_usd, task_count FROM api_costs_by_date WHERE date = ?",
                (today,)
            )
            today_row = cursor.fetchone()

            return {
                "total_usd": round(totals["total_usd"] or 0, 4),
                "today_usd": round(today_row["cost_usd"], 4) if today_row else 0.0,
                "total_tasks": totals["task_count"] or 0,
                "today_tasks": today_row["task_count"] if today_row else 0,
                "total_tokens": (totals["total_input_tokens"] or 0) + (totals["total_output_tokens"] or 0),
                "last_updated": totals["last_updated"]
            }
        finally:
            conn.close()


def get_costs_with_anthropic(config: dict = None) -> dict:
    """
    Get costs with optional Anthropic API data for comparison.

    If admin_api_key is configured, includes Anthropic-reported costs.
    Otherwise, returns local tracking only.

    Args:
        config: Full config dict. If None, loads from config files.

    Returns:
        {
            "local": {...},
            "anthropic": {...} or None,
            "anthropic_available": bool,
            "anthropic_configured": bool,
            "recommended_source": "local" or "anthropic",
            "discrepancy_pct": float or None
        }
    """
    if config is None:
        try:
            from ..skills import load_config
            config = load_config()
        except ImportError:
            config = {}

    result = {
        "local": get_costs(),
        "anthropic": None,
        "anthropic_available": False,
        "anthropic_configured": False,
        "recommended_source": "local",
        "discrepancy_pct": None,
        "cache_age_seconds": None,
        "last_error": None
    }

    # Try to get Anthropic data
    try:
        from . import anthropic_admin

        result["anthropic_configured"] = anthropic_admin.is_configured(config)

        if result["anthropic_configured"]:
            comparison = anthropic_admin.get_costs_comparison(config)

            if comparison.get("anthropic_available"):
                result["anthropic"] = comparison.get("anthropic")
                result["anthropic_available"] = True
                result["cache_age_seconds"] = comparison.get("cache_age_seconds")

                # Calculate discrepancy
                local_total = result["local"].get("total_usd", 0)
                anthro_total = result["anthropic"].get("total_usd", 0) if result["anthropic"] else 0

                if anthro_total > 0:
                    discrepancy = (local_total - anthro_total) / anthro_total * 100
                    result["discrepancy_pct"] = round(discrepancy, 1)
                    # Recommend Anthropic if available (more accurate)
                    result["recommended_source"] = "anthropic"

            if comparison.get("last_error"):
                result["last_error"] = comparison["last_error"]

    except ImportError:
        # anthropic_admin module not available
        pass
    except Exception as e:
        result["last_error"] = str(e)

    return result
