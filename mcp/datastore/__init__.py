#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
DataStore MCP Server
====================
Simple SQLite-based persistent data storage.
Provides collections (lists), key-value pairs, and counters.

Database: workspace/.state/datastore.db (auto-created)
"""

import json
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# DeskAgent MCP API (provides config, paths, logging via HTTP)
from _mcp_api import load_config, get_data_dir

mcp = FastMCP("datastore")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "storage",
    "color": "#607d8b"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Datenspeicher",
    "icon": "storage",
    "color": "#607d8b",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

# No high-risk tools - this is internal data storage
HIGH_RISK_TOOLS = set()

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "db_list",
    "db_contains",
    "db_search",
    "db_get",
    "db_get_counter",
    "db_doc_get",
    "db_doc_list",
    "db_doc_find",
    "db_doc_collections",
    "db_collections",
    "db_api_costs",
    "db_stats",
}

# Destructive tools that modify data
DESTRUCTIVE_TOOLS = {
    "db_add",
    "db_remove",
    "db_clear",
    "db_set",
    "db_delete",
    "db_increment",
    "db_reset_counter",
    "db_doc_save",
    "db_doc_delete",
}


def get_db_path() -> Path:
    """Get database file path."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "datastore.db"


def get_connection() -> sqlite3.Connection:
    """Get database connection with auto-init."""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _init_tables(conn)
    return conn


def _init_tables(conn: sqlite3.Connection):
    """Initialize database tables if they don't exist."""
    conn.executescript("""
        -- DataStore MCP tables
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection TEXT NOT NULL,
            value TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(collection, value)
        );

        CREATE TABLE IF NOT EXISTS keyvalue (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_collections_name ON collections(collection);

        -- Documents table (structured JSON objects)
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT NOT NULL,
            collection TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (collection, id)
        );

        CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection);

        -- Workflow State tables (formerly workflows.db)
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            step_index INTEGER DEFAULT 0,
            state TEXT DEFAULT '{}',
            status TEXT DEFAULT 'running',
            created_at TEXT,
            updated_at TEXT,
            error TEXT
        );

        -- API Costs tables (formerly api_costs.json)
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


def is_configured() -> bool:
    """Check if datastore is enabled.

    Enabled by default. Can be disabled via apis.json:
    "datastore": {"enabled": false}
    """
    config = load_config()
    mcp_config = config.get("datastore", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


# =============================================================================
# Collections (Lists)
# =============================================================================

@mcp.tool()
def db_add(collection: str, value: str) -> str:
    """
    Add an item to a collection.

    Duplicates are ignored (each value is unique per collection).
    Timestamp is automatically recorded.

    Args:
        collection: Name of the collection (e.g., "spam_senders")
        value: Value to add (e.g., "spam@example.com")

    Returns:
        Success message or error
    """
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO collections (collection, value) VALUES (?, ?)",
                (collection, value)
            )
            conn.commit()
            if conn.total_changes > 0:
                return f"OK: Added '{value}' to '{collection}'"
            else:
                return f"OK: '{value}' already exists in '{collection}'"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_remove(collection: str, value: str) -> str:
    """
    Remove an item from a collection.

    Args:
        collection: Name of the collection
        value: Value to remove

    Returns:
        Success message or error
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM collections WHERE collection = ? AND value = ?",
                (collection, value)
            )
            conn.commit()
            if cursor.rowcount > 0:
                return f"OK: Removed '{value}' from '{collection}'"
            else:
                return f"OK: '{value}' not found in '{collection}'"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_list(collection: str) -> str:
    """
    List all items in a collection.

    Args:
        collection: Name of the collection

    Returns:
        JSON array of items with timestamps
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT value, added_at FROM collections WHERE collection = ? ORDER BY added_at DESC",
                (collection,)
            )
            items = [{"value": row["value"], "added": row["added_at"]} for row in cursor]
            return json.dumps(items, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_contains(collection: str, value: str) -> str:
    """
    Check if an item exists in a collection.

    Args:
        collection: Name of the collection
        value: Value to check

    Returns:
        "true" or "false"
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM collections WHERE collection = ? AND value = ?",
                (collection, value)
            )
            exists = cursor.fetchone() is not None
            return "true" if exists else "false"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_search(collection: str, pattern: str) -> str:
    """
    Search items in a collection containing a pattern.

    Args:
        collection: Name of the collection
        pattern: Search pattern (case-insensitive substring match)

    Returns:
        JSON array of matching items
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT value, added_at FROM collections WHERE collection = ? AND value LIKE ? ORDER BY added_at DESC",
                (collection, f"%{pattern}%")
            )
            items = [{"value": row["value"], "added": row["added_at"]} for row in cursor]
            return json.dumps(items, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_clear(collection: str) -> str:
    """
    Delete all items in a collection.

    Args:
        collection: Name of the collection to clear

    Returns:
        Success message with count of deleted items
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM collections WHERE collection = ?",
                (collection,)
            )
            conn.commit()
            return f"OK: Deleted {cursor.rowcount} items from '{collection}'"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Key-Value Store
# =============================================================================

@mcp.tool()
def db_set(key: str, value: str) -> str:
    """
    Store a value by key.

    Overwrites existing value if key exists.

    Args:
        key: Key name
        value: Value to store

    Returns:
        Success message
    """
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO keyvalue (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value)
            )
            conn.commit()
            return f"OK: Set '{key}'"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_get(key: str) -> str:
    """
    Retrieve a value by key.

    Args:
        key: Key name

    Returns:
        The stored value or "null" if not found
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT value FROM keyvalue WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            if row:
                return row["value"]
            else:
                return "null"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_delete(key: str) -> str:
    """
    Delete a key-value pair.

    Args:
        key: Key name to delete

    Returns:
        Success message
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM keyvalue WHERE key = ?",
                (key,)
            )
            conn.commit()
            if cursor.rowcount > 0:
                return f"OK: Deleted '{key}'"
            else:
                return f"OK: Key '{key}' not found"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Counters
# =============================================================================

@mcp.tool()
def db_increment(name: str, amount: int = 1) -> str:
    """
    Increment a counter (creates if not exists).

    Args:
        name: Counter name
        amount: Amount to increment by (default: 1)

    Returns:
        New counter value
    """
    try:
        conn = get_connection()
        try:
            # Upsert pattern
            conn.execute("""
                INSERT INTO counters (name, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    value = value + excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (name, amount))
            conn.commit()

            # Get new value
            cursor = conn.execute("SELECT value FROM counters WHERE name = ?", (name,))
            row = cursor.fetchone()
            return str(row["value"])
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_get_counter(name: str) -> str:
    """
    Get counter value.

    Args:
        name: Counter name

    Returns:
        Counter value (0 if not exists)
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT value FROM counters WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
            return str(row["value"]) if row else "0"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_reset_counter(name: str) -> str:
    """
    Reset counter to 0.

    Args:
        name: Counter name

    Returns:
        Success message
    """
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO counters (name, value, updated_at) VALUES (?, 0, CURRENT_TIMESTAMP)",
                (name,)
            )
            conn.commit()
            return f"OK: Reset counter '{name}' to 0"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Documents (Structured JSON Objects)
# =============================================================================

@mcp.tool()
def db_doc_save(collection: str, doc_id: str, data: str) -> str:
    """
    Save a document (structured JSON object).

    Creates or updates a document. Use for storing contacts, leads, projects, etc.

    Args:
        collection: Collection name (e.g., "contacts", "leads", "projects")
        doc_id: Unique document ID (e.g., "max_mueller", "project_123")
        data: JSON object with document fields (e.g., {"name": "Max", "email": "max@test.de"})

    Returns:
        Success message with created/updated status
    """
    try:
        # Validate JSON
        try:
            parsed = json.loads(data) if isinstance(data, str) else data
            data_str = json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON - {str(e)}"

        conn = get_connection()
        try:
            # Check if exists
            cursor = conn.execute(
                "SELECT 1 FROM documents WHERE collection = ? AND id = ?",
                (collection, doc_id)
            )
            exists = cursor.fetchone() is not None

            if exists:
                conn.execute(
                    "UPDATE documents SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE collection = ? AND id = ?",
                    (data_str, collection, doc_id)
                )
                action = "Updated"
            else:
                conn.execute(
                    "INSERT INTO documents (collection, id, data) VALUES (?, ?, ?)",
                    (collection, doc_id, data_str)
                )
                action = "Created"

            conn.commit()
            return f"OK: {action} document '{doc_id}' in '{collection}'"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_doc_get(collection: str, doc_id: str) -> str:
    """
    Get a document by ID.

    Args:
        collection: Collection name
        doc_id: Document ID

    Returns:
        JSON object with document data, or null if not found
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT data, created_at, updated_at FROM documents WHERE collection = ? AND id = ?",
                (collection, doc_id)
            )
            row = cursor.fetchone()
            if row:
                result = json.loads(row["data"])
                result["_id"] = doc_id
                result["_created"] = row["created_at"]
                result["_updated"] = row["updated_at"]
                return json.dumps(result, ensure_ascii=False)
            else:
                return "null"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_doc_list(collection: str) -> str:
    """
    List all documents in a collection.

    Args:
        collection: Collection name

    Returns:
        JSON array of documents with their IDs
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, data, created_at, updated_at FROM documents WHERE collection = ? ORDER BY updated_at DESC",
                (collection,)
            )
            docs = []
            for row in cursor:
                doc = json.loads(row["data"])
                doc["_id"] = row["id"]
                doc["_created"] = row["created_at"]
                doc["_updated"] = row["updated_at"]
                docs.append(doc)
            return json.dumps(docs, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_doc_delete(collection: str, doc_id: str) -> str:
    """
    Delete a document.

    Args:
        collection: Collection name
        doc_id: Document ID to delete

    Returns:
        Success message
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM documents WHERE collection = ? AND id = ?",
                (collection, doc_id)
            )
            conn.commit()
            if cursor.rowcount > 0:
                return f"OK: Deleted document '{doc_id}' from '{collection}'"
            else:
                return f"OK: Document '{doc_id}' not found in '{collection}'"
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_doc_find(collection: str, field: str, value: str) -> str:
    """
    Find documents where a field matches a value.

    Uses case-insensitive substring matching.

    Args:
        collection: Collection name
        field: Field name to search (e.g., "company", "email", "status")
        value: Value to search for (substring match)

    Returns:
        JSON array of matching documents
    """
    try:
        conn = get_connection()
        try:
            # Use json_extract for field search with LIKE for substring match
            cursor = conn.execute("""
                SELECT id, data, created_at, updated_at FROM documents
                WHERE collection = ?
                AND json_extract(data, '$.' || ?) LIKE ?
                ORDER BY updated_at DESC
            """, (collection, field, f"%{value}%"))
            docs = []
            for row in cursor:
                doc = json.loads(row["data"])
                doc["_id"] = row["id"]
                doc["_created"] = row["created_at"]
                doc["_updated"] = row["updated_at"]
                docs.append(doc)
            return json.dumps(docs, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_doc_collections() -> str:
    """
    List all document collections with counts.

    Returns:
        JSON array of collection names with document counts
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute("""
                SELECT collection, COUNT(*) as count
                FROM documents
                GROUP BY collection
                ORDER BY collection
            """)
            collections = [{"name": row["collection"], "count": row["count"]} for row in cursor]
            return json.dumps(collections, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Info & Statistics
# =============================================================================

@mcp.tool()
def db_collections() -> str:
    """
    List all collection names.

    Returns:
        JSON array of collection names with item counts
    """
    try:
        conn = get_connection()
        try:
            cursor = conn.execute("""
                SELECT collection, COUNT(*) as count
                FROM collections
                GROUP BY collection
                ORDER BY collection
            """)
            collections = [{"name": row["collection"], "count": row["count"]} for row in cursor]
            return json.dumps(collections, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_api_costs() -> str:
    """
    Get API cost statistics.

    Returns cumulative costs for all AI API calls (Claude, Gemini, OpenAI, Whisper).
    Includes breakdown by model, backend, and date.

    Returns:
        JSON with total costs, tokens, and breakdowns
    """
    try:
        conn = get_connection()
        try:
            # Get totals
            cursor = conn.execute("SELECT * FROM api_costs WHERE id = 1")
            row = cursor.fetchone()

            if not row:
                return json.dumps({"total_usd": 0, "task_count": 0, "message": "No cost data yet"})

            result = {
                "total_usd": round(row["total_usd"] or 0, 4),
                "total_input_tokens": row["total_input_tokens"] or 0,
                "total_output_tokens": row["total_output_tokens"] or 0,
                "total_audio_seconds": round(row["total_audio_seconds"] or 0, 1),
                "task_count": row["task_count"] or 0,
                "last_updated": row["last_updated"],
                "by_model": {},
                "by_backend": {},
                "by_date": {}
            }

            # Get by_model (top 5)
            cursor = conn.execute("SELECT * FROM api_costs_by_model ORDER BY cost_usd DESC LIMIT 5")
            for row in cursor:
                result["by_model"][row["model"]] = {
                    "cost_usd": round(row["cost_usd"], 4),
                    "tasks": row["task_count"]
                }

            # Get by_backend
            cursor = conn.execute("SELECT * FROM api_costs_by_backend ORDER BY cost_usd DESC")
            for row in cursor:
                result["by_backend"][row["backend"]] = {
                    "cost_usd": round(row["cost_usd"], 4),
                    "tasks": row["task_count"]
                }

            # Get by_date (last 7 days)
            cursor = conn.execute("SELECT * FROM api_costs_by_date ORDER BY date DESC LIMIT 7")
            for row in cursor:
                result["by_date"][row["date"]] = {
                    "cost_usd": round(row["cost_usd"], 4),
                    "tasks": row["task_count"]
                }

            return json.dumps(result, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def db_stats() -> str:
    """
    Show database statistics.

    Returns:
        JSON with stats (collections, items, keys, counters, size)
    """
    try:
        conn = get_connection()
        try:
            # Count collections
            cursor = conn.execute("SELECT COUNT(DISTINCT collection) as count FROM collections")
            collections_count = cursor.fetchone()["count"]

            # Count items
            cursor = conn.execute("SELECT COUNT(*) as count FROM collections")
            items_count = cursor.fetchone()["count"]

            # Count keys
            cursor = conn.execute("SELECT COUNT(*) as count FROM keyvalue")
            keys_count = cursor.fetchone()["count"]

            # Count counters
            cursor = conn.execute("SELECT COUNT(*) as count FROM counters")
            counters_count = cursor.fetchone()["count"]

            # Count documents
            cursor = conn.execute("SELECT COUNT(*) as count FROM documents")
            documents_count = cursor.fetchone()["count"]

            # Count document collections
            cursor = conn.execute("SELECT COUNT(DISTINCT collection) as count FROM documents")
            doc_collections_count = cursor.fetchone()["count"]

            # Get file size
            db_path = get_db_path()
            size_kb = db_path.stat().st_size / 1024 if db_path.exists() else 0

            stats = {
                "collections": collections_count,
                "items": items_count,
                "keys": keys_count,
                "counters": counters_count,
                "documents": documents_count,
                "document_collections": doc_collections_count,
                "size_kb": round(size_kb, 2)
            }
            return json.dumps(stats, ensure_ascii=False)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run()
