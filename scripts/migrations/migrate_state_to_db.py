#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Migration Script: State Files to datastore.db
==============================================
Migrates data from:
- workflows.db -> datastore.db (workflow_runs table)
- api_costs.json -> datastore.db (api_costs_* tables)

Run once after updating to the new unified database structure.
"""

import json
import sqlite3
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from paths import get_data_dir


def migrate_workflows_db():
    """Migrate workflow_runs from workflows.db to datastore.db."""
    data_dir = get_data_dir()
    old_db = data_dir / "workflows.db"
    new_db = data_dir / "datastore.db"

    if not old_db.exists():
        print(f"[workflows.db] Not found at {old_db}, skipping")
        return 0

    print(f"[workflows.db] Migrating from {old_db}")

    # Connect to both databases
    old_conn = sqlite3.connect(str(old_db))
    old_conn.row_factory = sqlite3.Row
    new_conn = sqlite3.connect(str(new_db))

    # Ensure table exists in new DB
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

    # Copy data
    cursor = old_conn.execute("SELECT * FROM workflow_runs")
    rows = cursor.fetchall()

    migrated = 0
    for row in rows:
        try:
            new_conn.execute("""
                INSERT OR REPLACE INTO workflow_runs
                (id, workflow_name, step_index, state, status, created_at, updated_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"],
                row["workflow_name"],
                row["step_index"],
                row["state"],
                row["status"],
                row["created_at"],
                row["updated_at"],
                row["error"]
            ))
            migrated += 1
        except Exception as e:
            print(f"  Error migrating row {row['id']}: {e}")

    new_conn.commit()
    old_conn.close()
    new_conn.close()

    print(f"[workflows.db] Migrated {migrated} workflow runs")
    return migrated


def migrate_api_costs_json():
    """Migrate api_costs.json to datastore.db tables."""
    data_dir = get_data_dir()
    json_file = data_dir / "api_costs.json"
    new_db = data_dir / "datastore.db"

    if not json_file.exists():
        print(f"[api_costs.json] Not found at {json_file}, skipping")
        return False

    print(f"[api_costs.json] Migrating from {json_file}")

    # Load JSON data
    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        print(f"[api_costs.json] Error reading file: {e}")
        return False

    # Connect to database
    conn = sqlite3.connect(str(new_db))

    # Ensure tables exist
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

    # Migrate totals
    conn.execute("DELETE FROM api_costs")  # Clear existing
    conn.execute("""
        INSERT INTO api_costs (id, total_usd, total_input_tokens, total_output_tokens,
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
    print(f"  Totals: ${data.get('total_usd', 0):.4f}, {data.get('task_count', 0)} tasks")

    # Migrate by_model
    conn.execute("DELETE FROM api_costs_by_model")
    by_model = data.get("by_model", {})
    for model, stats in by_model.items():
        conn.execute("""
            INSERT INTO api_costs_by_model (model, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            model,
            stats.get("cost_usd", 0),
            stats.get("input_tokens", 0),
            stats.get("output_tokens", 0),
            stats.get("audio_seconds", 0),
            stats.get("task_count", 0)
        ))
    print(f"  by_model: {len(by_model)} models")

    # Migrate by_backend
    conn.execute("DELETE FROM api_costs_by_backend")
    by_backend = data.get("by_backend", {})
    for backend, stats in by_backend.items():
        conn.execute("""
            INSERT INTO api_costs_by_backend (backend, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            backend,
            stats.get("cost_usd", 0),
            stats.get("input_tokens", 0),
            stats.get("output_tokens", 0),
            stats.get("audio_seconds", 0),
            stats.get("task_count", 0)
        ))
    print(f"  by_backend: {len(by_backend)} backends")

    # Migrate by_date
    conn.execute("DELETE FROM api_costs_by_date")
    by_date = data.get("by_date", {})
    for date, stats in by_date.items():
        conn.execute("""
            INSERT INTO api_costs_by_date (date, cost_usd, input_tokens, output_tokens, audio_seconds, task_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            date,
            stats.get("cost_usd", 0),
            stats.get("input_tokens", 0),
            stats.get("output_tokens", 0),
            stats.get("audio_seconds", 0),
            stats.get("task_count", 0)
        ))
    print(f"  by_date: {len(by_date)} days")

    conn.commit()
    conn.close()

    print(f"[api_costs.json] Migration complete")
    return True


def cleanup_old_files(dry_run: bool = True):
    """Remove old state files after successful migration."""
    data_dir = get_data_dir()

    files_to_remove = [
        data_dir / "workflows.db",
        data_dir / "api_costs.json"
    ]

    for f in files_to_remove:
        if f.exists():
            if dry_run:
                print(f"[Cleanup] Would delete: {f}")
            else:
                f.unlink()
                print(f"[Cleanup] Deleted: {f}")


def main():
    """Run all migrations."""
    print("=" * 60)
    print("State Files Migration to datastore.db")
    print("=" * 60)
    print()

    data_dir = get_data_dir()
    print(f"Data directory: {data_dir}")
    print()

    # Check if datastore.db exists
    datastore_db = data_dir / "datastore.db"
    if not datastore_db.exists():
        print(f"[Warning] datastore.db not found at {datastore_db}")
        print("Creating new database...")
        conn = sqlite3.connect(str(datastore_db))
        conn.close()
    print()

    # Run migrations
    workflows_migrated = migrate_workflows_db()
    print()

    costs_migrated = migrate_api_costs_json()
    print()

    # Cleanup prompt
    print("=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"  Workflows: {workflows_migrated} runs migrated")
    print(f"  API Costs: {'Yes' if costs_migrated else 'No'}")
    print()

    # Show what would be cleaned up
    cleanup_old_files(dry_run=True)
    print()

    # Ask for confirmation
    response = input("Delete old files? [y/N]: ").strip().lower()
    if response == "y":
        cleanup_old_files(dry_run=False)
        print("Done!")
    else:
        print("Skipped cleanup. Old files preserved.")


if __name__ == "__main__":
    main()
