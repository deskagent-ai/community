# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Email Watcher System
====================
Background email monitoring with rule-based actions and optional AI triggers.
Polls for new emails and applies configurable rules (move, flag, delete, trigger_agent).

Token-free actions: move_to_folder, flag, delete
Token-cost actions: trigger_agent (runs AI agent)
"""

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# Path is set up by assistant/__init__.py
from paths import get_data_dir, PROJECT_DIR

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

STATE_FILE = get_data_dir() / "watcher_state.json"

# Thread-safe lock
_lock = threading.Lock()

# Background thread management
_watcher_thread: Optional[threading.Thread] = None
_watcher_stop_event: Optional[threading.Event] = None

# In-memory state cache
_state: Optional[dict] = None


def _ensure_data_dir():
    """Ensure data directory exists."""
    # get_data_dir() already creates the directory
    get_data_dir()


def _load_state() -> dict:
    """Load watcher state from file."""
    global _state
    if _state is not None:
        return _state

    _ensure_data_dir()

    if STATE_FILE.exists():
        try:
            _state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            _state = _default_state()
    else:
        _state = _default_state()

    return _state


def _default_state() -> dict:
    """Default state structure."""
    return {
        "seen_email_ids": [],  # List of email IDs we've already processed
        "processed_count": 0,
        "actions_log": [],  # Recent action log (max 100 entries)
        "stats_by_date": {},
        "last_check": None,
        "errors": []  # Recent errors (max 20)
    }


def _save_state():
    """Save state to file."""
    global _state
    if _state is None:
        return

    _ensure_data_dir()

    try:
        STATE_FILE.write_text(
            json.dumps(_state, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except IOError as e:
        system_log(f"[Watcher] Error saving state: {e}")


def _load_config() -> dict:
    """Load config.json."""
    config_file = PROJECT_DIR / "config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _get_watcher_config() -> dict:
    """Get email_watchers section from config."""
    config = _load_config()
    return config.get("email_watchers", {})


def _log_action(email_subject: str, email_from: str, action: str, params: dict, result: str):
    """Log an action to the state."""
    with _lock:
        state = _load_state()

        entry = {
            "timestamp": datetime.now().isoformat(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "email": email_subject[:50],
            "from": email_from,
            "action": action,
            "params": params,
            "result": result
        }

        state["actions_log"].insert(0, entry)
        # Keep only last 100 entries
        state["actions_log"] = state["actions_log"][:100]

        # Update daily stats
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in state["stats_by_date"]:
            state["stats_by_date"][today] = {
                "processed": 0,
                "actions": 0,
                "by_action": {}
            }
        state["stats_by_date"][today]["actions"] += 1
        action_counts = state["stats_by_date"][today].setdefault("by_action", {})
        action_counts[action] = action_counts.get(action, 0) + 1

        _save_state()


def _log_error(error: str):
    """Log an error to the state."""
    with _lock:
        state = _load_state()

        entry = {
            "timestamp": datetime.now().isoformat(),
            "error": error
        }

        state["errors"].insert(0, entry)
        state["errors"] = state["errors"][:20]  # Keep last 20

        _save_state()
        system_log(f"[Watcher] Error: {error}")


def _mark_email_seen(email_id: str):
    """Mark an email as seen."""
    with _lock:
        state = _load_state()

        if email_id not in state["seen_email_ids"]:
            state["seen_email_ids"].append(email_id)
            # Keep only last 1000 IDs to prevent unbounded growth
            state["seen_email_ids"] = state["seen_email_ids"][-1000:]

        state["processed_count"] += 1

        # Update daily stats
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in state["stats_by_date"]:
            state["stats_by_date"][today] = {
                "processed": 0,
                "actions": 0,
                "by_action": {}
            }
        state["stats_by_date"][today]["processed"] += 1

        _save_state()


def _is_email_seen(email_id: str) -> bool:
    """Check if an email has been seen."""
    with _lock:
        state = _load_state()
        return email_id in state["seen_email_ids"]


def _match_rule(email: dict, rule: dict) -> bool:
    """Check if an email matches a rule's patterns."""
    match = rule.get("match", {})

    # Check from pattern
    from_pattern = match.get("from_pattern")
    if from_pattern:
        email_from = email.get("from", "") or email.get("sender", "")
        if not re.search(from_pattern, email_from, re.IGNORECASE):
            return False

    # Check subject pattern
    subject_pattern = match.get("subject_pattern")
    if subject_pattern:
        subject = email.get("subject", "")
        if not re.search(subject_pattern, subject, re.IGNORECASE):
            return False

    # Check body pattern (optional, expensive)
    body_pattern = match.get("body_pattern")
    if body_pattern:
        body = email.get("body", "") or email.get("preview", "")
        if not re.search(body_pattern, body, re.IGNORECASE):
            return False

    return True


def _execute_action(email: dict, action: dict) -> str:
    """Execute a single action on an email."""
    action_type = action.get("type")
    subject = email.get("subject", "")
    email_from = email.get("from", "") or email.get("sender", "")

    # Import tool_bridge for direct MCP calls (use relative import)
    from ..ai_agent.tool_bridge import execute_tool

    if action_type == "move_to_folder":
        folder = action.get("folder", "ToDelete")
        result = execute_tool("move_email", {
            "query": subject,
            "folder_name": folder,
            "index": 0
        }, skip_logging=True)
        _log_action(subject, email_from, "move_to_folder", {"folder": folder}, result[:100])
        return result

    elif action_type == "flag":
        flag_type = action.get("flag_type", "followup")
        result = execute_tool("flag_email", {
            "query": subject,
            "flag_type": flag_type,
            "index": 0
        }, skip_logging=True)
        _log_action(subject, email_from, "flag", {"flag_type": flag_type}, result[:100])
        return result

    elif action_type == "delete":
        result = execute_tool("move_email", {
            "query": subject,
            "folder_name": "Deleted Items",
            "index": 0
        }, skip_logging=True)
        _log_action(subject, email_from, "delete", {}, result[:100])
        return result

    elif action_type == "trigger_agent":
        agent_name = action.get("agent")
        if not agent_name:
            return "Error: No agent specified"

        # Import agents module (use relative import)
        from .agents import process_agent

        # Build context from email
        context = f"Email from: {email_from}\nSubject: {subject}\n"
        if email.get("body"):
            context += f"Body:\n{email.get('body', '')[:500]}"

        # Run agent in background thread
        def run_agent():
            try:
                result = process_agent(agent_name, context)
                _log_action(subject, email_from, "trigger_agent", {"agent": agent_name}, "completed")
            except Exception as e:
                _log_error(f"Agent {agent_name} failed: {e}")

        threading.Thread(target=run_agent, daemon=True).start()
        _log_action(subject, email_from, "trigger_agent", {"agent": agent_name}, "started")
        return f"Agent {agent_name} triggered"

    else:
        return f"Unknown action type: {action_type}"


def _check_emails(config: dict):
    """Check for new emails and apply rules."""
    # Import tool_bridge for MCP calls (use relative import)
    from ..ai_agent.tool_bridge import execute_tool

    max_emails = config.get("max_emails_per_check", 20)
    rules = config.get("rules", [])

    if not rules:
        return

    # Get unread emails as JSON (with EntryID for reliable deduplication)
    # skip_logging=True to prevent anon_messages.log bloat from polling
    try:
        result = execute_tool("get_unread_emails_json", {"limit": max_emails}, skip_logging=True)

        if not result:
            return

        # Check for ERROR prefix (MCP tools return "ERROR: ..." on failure)
        if isinstance(result, str) and result.startswith("ERROR:"):
            _log_error(f"MCP tool error: {result}")
            return

        # Parse JSON result
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            _log_error(f"Failed to parse emails JSON: {result[:100]}")
            return

        # Check for error response
        if isinstance(data, dict) and "error" in data:
            _log_error(f"Failed to get unread emails: {data['error']}")
            return

        emails = data if isinstance(data, list) else []

        if not emails:
            return

        # Process each email
        for email in emails:
            # Use EntryID for reliable deduplication
            email_id = email.get("entry_id")
            if not email_id:
                # Fallback to synthetic ID if EntryID missing
                email_id = f"{email.get('subject', '')[:30]}_{email.get('from', '')[:30]}"

            # Skip if already seen
            if _is_email_seen(email_id):
                continue

            # Check against rules
            for rule in rules:
                if not rule.get("enabled", True):
                    continue

                if _match_rule(email, rule):
                    rule_name = rule.get("name", "Unknown")
                    system_log(f"[Watcher] Rule '{rule_name}' matched: {email.get('subject', '')[:40]}")

                    # Execute all actions for this rule
                    for action in rule.get("actions", []):
                        try:
                            _execute_action(email, action)
                        except Exception as e:
                            _log_error(f"Action failed: {action.get('type')} - {e}")

                    # Stop checking rules after first match (unless configured otherwise)
                    break

            # Mark as seen regardless of match
            _mark_email_seen(email_id)

    except Exception as e:
        _log_error(f"Check emails failed: {e}")


def _watcher_loop():
    """Main watcher loop - runs in background thread."""
    system_log("[Watcher] Background thread started")

    while not _watcher_stop_event.is_set():
        config = _get_watcher_config()
        interval = config.get("check_interval", 60)

        if config.get("enabled", False):
            try:
                # Update last check time
                with _lock:
                    state = _load_state()
                    state["last_check"] = datetime.now().isoformat()
                    _save_state()

                _check_emails(config)

            except Exception as e:
                _log_error(str(e))

        # Sleep with interruptible wait
        _watcher_stop_event.wait(timeout=interval)

    system_log("[Watcher] Background thread stopped")


def start_watcher() -> bool:
    """Start the email watcher background thread."""
    global _watcher_thread, _watcher_stop_event

    if _watcher_thread and _watcher_thread.is_alive():
        system_log("[Watcher] Already running")
        return False

    _watcher_stop_event = threading.Event()
    _watcher_thread = threading.Thread(
        target=_watcher_loop,
        daemon=True,
        name="EmailWatcher"
    )
    _watcher_thread.start()
    system_log("[Watcher] Started")
    return True


def stop_watcher() -> bool:
    """Stop the email watcher thread."""
    global _watcher_thread, _watcher_stop_event

    if _watcher_stop_event:
        _watcher_stop_event.set()
        system_log("[Watcher] Stop signal sent")
        return True
    return False


def is_running() -> bool:
    """Check if watcher thread is running."""
    return _watcher_thread is not None and _watcher_thread.is_alive()


def is_enabled() -> bool:
    """Check if watcher is enabled in config."""
    config = _get_watcher_config()
    return config.get("enabled", False)


def check_now() -> dict:
    """Force an immediate check (for manual trigger)."""
    config = _get_watcher_config()

    try:
        _check_emails(config)
        return {"status": "ok", "message": "Check completed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_status() -> dict:
    """Get current watcher status for API/UI."""
    config = _get_watcher_config()

    with _lock:
        state = _load_state()
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = state["stats_by_date"].get(today, {
            "processed": 0,
            "actions": 0,
            "by_action": {}
        })

        # Calculate next check time
        next_check_in = None
        if state["last_check"] and is_running():
            last = datetime.fromisoformat(state["last_check"])
            interval = config.get("check_interval", 60)
            elapsed = (datetime.now() - last).total_seconds()
            next_check_in = max(0, int(interval - elapsed))

        # Get recent actions (last 10)
        recent_actions = state["actions_log"][:10]

        return {
            "enabled": config.get("enabled", False),
            "running": is_running(),
            "last_check": state["last_check"],
            "next_check_in": next_check_in,
            "check_interval": config.get("check_interval", 60),
            "stats": {
                "processed_today": today_stats.get("processed", 0),
                "actions_today": today_stats.get("actions", 0),
                "total_processed": state["processed_count"],
                "by_action": today_stats.get("by_action", {})
            },
            "recent_actions": recent_actions,
            "rules_count": len(config.get("rules", [])),
            "errors": state["errors"][:5]  # Last 5 errors
        }


def get_action_log(limit: int = 50) -> list:
    """Get recent action log."""
    with _lock:
        state = _load_state()
        return state["actions_log"][:limit]


def clear_seen_emails():
    """Clear the seen emails list (for testing/reset)."""
    with _lock:
        state = _load_state()
        state["seen_email_ids"] = []
        _save_state()
    system_log("[Watcher] Seen emails cleared")
