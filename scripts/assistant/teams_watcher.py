# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Teams Watcher System
====================
Background Teams channel monitoring with AI-triggered responses.
Polls for new messages via Graph API and triggers configured agent to respond.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Path is set up by assistant/__init__.py
from paths import get_data_dir, get_config_dir, PROJECT_DIR

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

STATE_FILE = get_data_dir() / "teams_watcher_state.json"
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

# Thread-safe lock
_lock = threading.Lock()

# Cached template
_prompt_template: Optional[str] = None

# Default template (fallback if file not found)
DEFAULT_PROMPT_TEMPLATE = """[Teams Message from {{SENDER}}]
{{CONTENT}}

---
Respond to this Teams message. Use teams_post_to_configured_channel('{{WEBHOOK}}', your_response) to reply."""


def _load_prompt_template() -> str:
    """Load prompt template from file or use default."""
    global _prompt_template
    if _prompt_template is not None:
        return _prompt_template

    template_file = TEMPLATES_DIR / "teams_watcher.template"
    if template_file.exists():
        try:
            content = template_file.read_text(encoding="utf-8")
            # Extract template from markdown code block
            import re
            match = re.search(r'```\n(.*?)\n```', content, re.DOTALL)
            if match:
                _prompt_template = match.group(1).strip()
            else:
                _prompt_template = DEFAULT_PROMPT_TEMPLATE
        except Exception:
            _prompt_template = DEFAULT_PROMPT_TEMPLATE
    else:
        _prompt_template = DEFAULT_PROMPT_TEMPLATE

    return _prompt_template


# Background thread management
_watcher_thread: Optional[threading.Thread] = None
_watcher_stop_event: Optional[threading.Event] = None

# In-memory state cache
_state: Optional[dict] = None


def _ensure_data_dir():
    """Ensure data directory exists."""
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
        "last_message_timestamp": None,  # ISO timestamp of last processed message
        "processed_count": 0,
        "messages_log": [],  # Recent messages log (max 50 entries)
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
        system_log(f"[TeamsWatcher] Error saving state: {e}")


def _load_triggers_config() -> dict:
    """Load triggers.json config."""
    # Try user config first, then deskagent default config
    user_config = get_config_dir() / "triggers.json"
    deskagent_config = Path(__file__).parent.parent.parent / "config" / "triggers.json"

    for config_file in [user_config, deskagent_config]:
        if config_file.exists():
            try:
                return json.loads(config_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                continue
    return {"triggers": []}


def _get_watcher_config() -> dict:
    """Get first enabled teams_channel trigger from triggers.json."""
    config = _load_triggers_config()
    for trigger in config.get("triggers", []):
        if trigger.get("type") == "teams_channel":
            return trigger
    return {}


def _log_message(sender: str, content: str, response: str):
    """Log a processed message to the state."""
    with _lock:
        state = _load_state()

        entry = {
            "timestamp": datetime.now().isoformat(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "sender": sender,
            "content": content[:100],
            "response": response[:100] if response else None
        }

        state["messages_log"].insert(0, entry)
        state["messages_log"] = state["messages_log"][:50]  # Keep last 50

        # Update daily stats
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in state["stats_by_date"]:
            state["stats_by_date"][today] = {
                "messages": 0,
                "responses": 0
            }
        state["stats_by_date"][today]["messages"] += 1
        if response:
            state["stats_by_date"][today]["responses"] += 1

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
        state["errors"] = state["errors"][:20]

        _save_state()
        system_log(f"[TeamsWatcher] Error: {error}")


def _process_message(message: dict, config: dict):
    """Process a new message - trigger agent and respond."""
    import ai_agent

    sender = message.get("sender", "Unknown")
    content = message.get("content", "")
    agent_name = config.get("agent", "chat")
    response_webhook = config.get("response_webhook", "deskagent")

    system_log(f"[TeamsWatcher] New message from {sender}: {content[:50]}...")
    ai_agent.system_log(f"[TeamsWatcher] Processing message from {sender}")

    try:
        # Build prompt from template
        template = _load_prompt_template()
        prompt = template.replace("{{SENDER}}", sender)
        prompt = prompt.replace("{{CONTENT}}", content)
        prompt = prompt.replace("{{WEBHOOK}}", response_webhook)

        # Run the agent (ai_backend comes from agent config)
        response = ai_agent.run_agent(
            agent_name=agent_name,
            user_prompt=prompt
        )

        _log_message(sender, content, response)
        ai_agent.system_log(f"[TeamsWatcher] Response sent for message from {sender}")

    except Exception as e:
        _log_error(f"Failed to process message from {sender}: {e}")
        _log_message(sender, content, None)


def _check_messages(config: dict):
    """Check for new messages in the Teams channel."""
    import sys

    # Import msgraph_mcp for polling
    mcp_dir = PROJECT_DIR / "mcp"
    if str(mcp_dir) not in sys.path:
        sys.path.insert(0, str(mcp_dir))

    try:
        import msgraph_mcp
    except ImportError as e:
        _log_error(f"Failed to import msgraph_mcp: {e}")
        return

    team_id = config.get("team_id")
    channel_id = config.get("channel_id")

    if not team_id or not channel_id:
        _log_error("team_id and channel_id not configured. Run teams_setup_watcher() first.")
        return

    # Get last processed timestamp
    with _lock:
        state = _load_state()
        since_timestamp = state.get("last_message_timestamp")

    # Poll for new messages
    messages = msgraph_mcp.teams_poll_messages(team_id, channel_id, since_timestamp)

    if not messages:
        return

    # Process each new message (oldest first to maintain order)
    for msg in reversed(messages):
        msg_timestamp = msg.get("timestamp")

        # Process the message
        _process_message(msg, config)

        # Update last processed timestamp
        with _lock:
            state = _load_state()
            if not state["last_message_timestamp"] or msg_timestamp > state["last_message_timestamp"]:
                state["last_message_timestamp"] = msg_timestamp
            state["processed_count"] += 1
            _save_state()


def _watcher_loop():
    """Main watcher loop - runs in background thread."""
    import ai_agent
    system_log("[TeamsWatcher] Background thread started")
    ai_agent.system_log("[TeamsWatcher] Background polling started")

    while not _watcher_stop_event.is_set():
        config = _get_watcher_config()
        interval = config.get("poll_interval", 10)

        if config.get("enabled", False):
            try:
                # Update last check time
                with _lock:
                    state = _load_state()
                    state["last_check"] = datetime.now().isoformat()
                    _save_state()

                _check_messages(config)

            except Exception as e:
                _log_error(str(e))

        # Sleep with interruptible wait
        _watcher_stop_event.wait(timeout=interval)

    system_log("[TeamsWatcher] Background thread stopped")


def start_watcher() -> bool:
    """Start the Teams watcher background thread."""
    global _watcher_thread, _watcher_stop_event

    if _watcher_thread and _watcher_thread.is_alive():
        system_log("[TeamsWatcher] Already running")
        return False

    config = _get_watcher_config()
    if not config.get("enabled", False):
        system_log("[TeamsWatcher] Not enabled in config")
        return False

    if not config.get("team_id") or not config.get("channel_id"):
        system_log("[TeamsWatcher] team_id/channel_id not configured")
        return False

    _watcher_stop_event = threading.Event()
    _watcher_thread = threading.Thread(
        target=_watcher_loop,
        daemon=True,
        name="TeamsWatcher"
    )
    _watcher_thread.start()
    system_log("[TeamsWatcher] Started")
    return True


def stop_watcher() -> bool:
    """Stop the Teams watcher thread."""
    global _watcher_thread, _watcher_stop_event

    if _watcher_stop_event:
        _watcher_stop_event.set()
        system_log("[TeamsWatcher] Stop signal sent")
        return True
    return False


def is_running() -> bool:
    """Check if watcher thread is running."""
    return _watcher_thread is not None and _watcher_thread.is_alive()


def is_enabled() -> bool:
    """Check if watcher is enabled in config."""
    config = _get_watcher_config()
    return config.get("enabled", False)


def get_status() -> dict:
    """Get current watcher status for API/UI."""
    config = _get_watcher_config()

    with _lock:
        state = _load_state()
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = state["stats_by_date"].get(today, {
            "messages": 0,
            "responses": 0
        })

        # Calculate next check time
        next_check_in = None
        if state["last_check"] and is_running():
            last = datetime.fromisoformat(state["last_check"])
            interval = config.get("poll_interval", 10)
            elapsed = (datetime.now() - last).total_seconds()
            next_check_in = max(0, int(interval - elapsed))

        return {
            "enabled": config.get("enabled", False),
            "running": is_running(),
            "last_check": state["last_check"],
            "next_check_in": next_check_in,
            "poll_interval": config.get("poll_interval", 10),
            "team_id": config.get("team_id", "")[:20] + "..." if config.get("team_id") else None,
            "channel_id": config.get("channel_id", "")[:20] + "..." if config.get("channel_id") else None,
            "response_webhook": config.get("response_webhook", "deskagent"),
            "agent": config.get("agent", "chat"),
            "stats": {
                "messages_today": today_stats.get("messages", 0),
                "responses_today": today_stats.get("responses", 0),
                "total_processed": state["processed_count"]
            },
            "recent_messages": state["messages_log"][:10],
            "errors": state["errors"][:5]
        }


def clear_state():
    """Clear the state (for testing/reset)."""
    global _state
    with _lock:
        _state = _default_state()
        _save_state()
    system_log("[TeamsWatcher] State cleared")
