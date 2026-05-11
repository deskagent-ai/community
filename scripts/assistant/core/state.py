# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Global state management for DeskAgent server.

Centralizes all thread-safe state, locks, and accessor functions.
"""

import threading
import time
from typing import Optional, Dict, Any

from ai_agent.response_parser import clean_tool_markers
from ai_agent import log

# Import session_store for persistent history
try:
    from .. import session_store
    SESSION_STORE_AVAILABLE = True
except ImportError:
    SESSION_STORE_AVAILABLE = False


# =============================================================================
# Task State
# =============================================================================

tasks: Dict[str, dict] = {}  # Task tracking: {task_id: {"status": "running/done/error", ...}}
tasks_lock = threading.Lock()  # Lock for thread-safe access to tasks

_task_counter = 0
_task_counter_lock = threading.Lock()  # Lock for thread-safe task ID generation

test_tasks: Dict[str, dict] = {}  # Test runner tasks
test_tasks_lock = threading.Lock()

# Running sessions tracking (for History panel status indicators)
# Dict maps session_id -> task_id (or None if not yet known)
_running_sessions: dict = {}
_running_sessions_lock = threading.Lock()


def add_running_session(session_id: str, task_id: str = None):
    """Mark a session as running (thread-safe).

    Args:
        session_id: The session ID to mark as running.
        task_id: Optional task ID associated with this session.
    """
    with _running_sessions_lock:
        _running_sessions[session_id] = task_id


def remove_running_session(session_id: str):
    """Mark a session as no longer running (thread-safe)."""
    with _running_sessions_lock:
        _running_sessions.pop(session_id, None)


def get_running_sessions() -> list:
    """Get list of currently running session IDs (thread-safe)."""
    with _running_sessions_lock:
        return list(_running_sessions.keys())


def get_session_task_map() -> dict:
    """Get snapshot of session_id -> task_id mapping (thread-safe).

    Returns:
        Dict mapping session IDs to their associated task IDs.
    """
    with _running_sessions_lock:
        return dict(_running_sessions)


def generate_task_id() -> str:
    """Generate a unique task ID in a thread-safe manner."""
    global _task_counter
    with _task_counter_lock:
        _task_counter += 1
        return str(_task_counter)


def update_task(task_id: str, **updates):
    """Update task properties in a thread-safe manner."""
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id].update(updates)


def get_task(task_id: str) -> Optional[dict]:
    """Get a copy of task data in a thread-safe manner."""
    with tasks_lock:
        if task_id in tasks:
            return tasks[task_id].copy()
        return None


def delete_task(task_id: str):
    """Delete a task in a thread-safe manner."""
    with tasks_lock:
        if task_id in tasks:
            del tasks[task_id]


def schedule_task_deletion(task_id: str, delay: float = 10.0):
    """Schedule delayed task deletion to allow sync polling clients to fetch results.

    This prevents race conditions where desk_run_agent_sync polls for results
    but the task is already deleted before it can fetch them.

    The delay is longer than the SSE queue delay (5s) to ensure:
    1. SSE clients receive final events
    2. Sync polling clients (like desk_run_agent_sync) can fetch results

    Args:
        task_id: The task ID to delete
        delay: Seconds to wait before deletion (default: 10.0)
    """
    import asyncio
    from .sse_manager import get_event_loop

    loop = get_event_loop()
    if loop is None:
        # No event loop, fall back to immediate deletion
        log(f"[State] No event loop, immediate task deletion: {task_id}")
        delete_task(task_id)
        return

    async def delayed_delete():
        await asyncio.sleep(delay)
        delete_task(task_id)
        log(f"[State] Delayed task deletion completed: {task_id}")

    try:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(delayed_delete())
        )
        log(f"[State] Scheduled task deletion in {delay}s: {task_id}")
    except RuntimeError:
        # Event loop closed, fall back to immediate deletion
        log(f"[State] Event loop closed, immediate task deletion: {task_id}")
        delete_task(task_id)


def create_task_entry(task_id: str, task_entry: dict):
    """Create a new task entry (thread-safe)."""
    with tasks_lock:
        tasks[task_id] = task_entry


def update_test_task(task_id: str, **updates):
    """Update test task properties in a thread-safe manner."""
    with test_tasks_lock:
        if task_id in test_tasks:
            test_tasks[task_id].update(updates)


# =============================================================================
# Session State
# =============================================================================

current_session = {
    "last_task_id": None,
    "last_task_name": None,
    "last_task_type": None,  # "agent" | "skill" | "prompt"
    "last_ai_backend": None,
    "last_model": None,
    "last_result_summary": None,
    "conversation_active": False,
    "turn_count": 0
}
session_lock = threading.Lock()

# Conversation history for context continuation (no turn limit, cleared on new task)
conversation_history = []  # [{"role": "user"|"assistant", "content": str, "summary": str}, ...]

# Persistent session tracking (SQLite-backed)
_current_session_id: Optional[str] = None
_current_session_agent: Optional[str] = None

# SDK Extended Mode: Session ID for resume capability
_last_sdk_session_id: Optional[str] = None


def get_sdk_session_id() -> Optional[str]:
    """Get stored SDK session ID for resume capability (thread-safe)."""
    with session_lock:
        return _last_sdk_session_id


def set_sdk_session_id(session_id: Optional[str]):
    """Store SDK session ID for resume capability (thread-safe)."""
    global _last_sdk_session_id
    with session_lock:
        _last_sdk_session_id = session_id
        if session_id:
            log(f"[Session] SDK session stored: {session_id[:20]}...")


def clear_sdk_session_id():
    """Clear SDK session ID (on new agent/clear history)."""
    global _last_sdk_session_id
    with session_lock:
        _last_sdk_session_id = None


def get_session_copy() -> dict:
    """Get a thread-safe copy of the current session."""
    with session_lock:
        return current_session.copy()


def get_history_copy() -> list:
    """Get a thread-safe copy of conversation history."""
    with session_lock:
        return conversation_history.copy()


def add_to_history(role: str, content: str, task_name: str = None, task_type: str = None):
    """Add a turn to conversation history (thread-safe)."""
    global conversation_history, current_session

    # Clean tool markers from assistant responses
    if role == "assistant" and content:
        content = clean_tool_markers(content)

    summary = content[:2000] + "..." if len(content) > 2000 else content
    with session_lock:
        conversation_history.append({
            "role": role,
            "content": content,
            "summary": summary,
            "task_name": task_name,
            "task_type": task_type
        })
        current_session["conversation_active"] = True
        current_session["turn_count"] = len(conversation_history)


def _strip_dialog_meta(content: str) -> str:
    """[060] Strip ---DIALOG_META--- block from turn content before sending to AI."""
    if content and "\n---DIALOG_META---\n" in content:
        return content.split("\n---DIALOG_META---\n")[0]
    return content or ""


def build_continuation_prompt(new_prompt: str, use_sdk_resume: bool = False) -> str:
    """Build prompt with conversation history context (thread-safe).

    Args:
        new_prompt: The new user prompt
        use_sdk_resume: If True, skip history (SDK has it via resume)

    Returns:
        Prompt with or without history context
    """
    with session_lock:
        # SDK Extended Mode: When resuming, SDK has history - skip it
        if use_sdk_resume and _last_sdk_session_id:
            log(f"[Session] SDK resume mode - skipping history in prompt")
            return new_prompt

        if not conversation_history:
            return new_prompt

        history_text = "\n\n".join([
            f"**{h['role'].title()}:** {_strip_dialog_meta(h['content'])}"
            for h in conversation_history
        ])

    return f"""## Vorheriger Konversationsverlauf:
{history_text}

---

## Neue Anfrage:
{new_prompt}

**WICHTIG:** Bei Änderungen am vorherigen Output behalte alle Details bei (Namen, Anreden, E-Mail-Adressen, Daten), außer der User bittet explizit um eine Änderung."""


def clear_conversation_history():
    """Clear conversation history and reset session (thread-safe)."""
    global current_session, _last_sdk_session_id
    with session_lock:
        # Use .clear() instead of = [] to modify in-place
        # This prevents race conditions if another thread holds a reference
        conversation_history.clear()
        _last_sdk_session_id = None  # Clear SDK session on history clear
        current_session = {
            "last_task_id": None,
            "last_task_name": None,
            "last_task_type": None,
            "last_ai_backend": None,
            "last_model": None,
            "last_result_summary": None,
            "conversation_active": False,
            "turn_count": 0
        }


def update_session(task_id: str, task_name: str, task_type: str,
                   ai_backend: str, model: str, result_summary: str = None):
    """Update current session after task completion (thread-safe)."""
    global current_session
    with session_lock:
        current_session.update({
            "last_task_id": task_id,
            "last_task_name": task_name,
            "last_task_type": task_type,
            "last_ai_backend": ai_backend,
            "last_model": model,
            "last_result_summary": result_summary[:200] if result_summary else None,
            "conversation_active": True
        })


# =============================================================================
# Persistent Session Management (SQLite-backed)
# =============================================================================

def start_or_continue_session(agent_name: str, backend: str, model: str,
                               triggered_by: str = "webui",
                               force_new_session: bool = False,
                               anonymization_enabled: bool | None = None) -> Optional[str]:
    """
    Start a new session or continue an existing active session.

    This integrates with session_store for persistent history storage.
    Call this at the start of chat/prompt tasks.

    Args:
        agent_name: Name of the chat agent (e.g., "chat", "chat_claude")
        backend: AI backend type (e.g., "claude_sdk", "gemini")
        model: Model name
        triggered_by: What triggered this session:
            - "webui": User clicked tile/chat in WebUI (can continue existing)
            - "voice": Voice hotkey (can continue existing)
            - "email_watcher": Email auto-watcher (always new session)
            - "workflow": Another agent started this (always new session)
            - "api": Direct API call (always new session)
        force_new_session: If True, always create a new session (e.g., agent tile click)
        anonymization_enabled: Whether PII anonymization is active for this session.
            True = active, False = not active, None = unknown. [043]

    Returns:
        Session ID if session_store is available, None otherwise
    """
    global _current_session_id, _current_session_agent, conversation_history

    if not SESSION_STORE_AVAILABLE:
        return None

    # These triggers always start fresh sessions (no continuation)
    always_new_session = force_new_session or triggered_by in ("workflow", "email_watcher", "api", "auto_chain")

    result_session_id = None

    with session_lock:
        # Check if we can continue an existing session
        # Only for interactive triggers (webui, voice) that don't force new session
        active_session = None
        if not always_new_session:
            active_session = session_store.get_active_session(agent_name)

        if active_session:
            # Continue existing session (ignore _current_session_agent - DB is source of truth)
            _current_session_id = active_session
            _current_session_agent = agent_name  # Sync global state with DB
            result_session_id = active_session
            # [035] Mark continuing session as running too (ensures /task/active returns it
            # and History panel shows running indicator for prompt continuations)
            with _running_sessions_lock:
                _running_sessions[result_session_id] = None
            log(f"[Session] Continuing session {active_session}")

            # Load turns into in-memory history if empty
            if not conversation_history:
                session = session_store.get_session(active_session)
                if session and session.get("turns"):
                    for turn in session["turns"]:
                        # [060] Strip dialog metadata from content before loading into AI history
                        clean_content = _strip_dialog_meta(turn["content"])
                        conversation_history.append({
                            "role": turn["role"],
                            "content": clean_content,
                            "summary": clean_content[:2000] + "..." if len(clean_content) > 2000 else clean_content,
                            "task_name": None,
                            "task_type": "chat"
                        })
                    log(f"[Session] Loaded {len(session['turns'])} turns from history")
        else:
            # Complete any existing active session for this agent before starting new one
            if always_new_session:
                existing_session = session_store.get_active_session(agent_name)
                if existing_session:
                    # Thread-safe check: Don't complete if session is still running (parallel execution)
                    with _running_sessions_lock:
                        is_still_running = existing_session in _running_sessions
                    if is_still_running:
                        log(f"[Session] Keeping {existing_session} active - still running in background")
                    else:
                        session_store.complete_session(existing_session)
                        log(f"[Session] Completed previous session {existing_session} before starting new")

            # Start new session
            _current_session_id = session_store.create_session(
                agent_name, backend, model, triggered_by=triggered_by,
                anonymization_enabled=anonymization_enabled
            )
            result_session_id = _current_session_id
            _current_session_agent = agent_name
            conversation_history = []  # Clear in-memory history for new session
            # Mark session as running immediately (prevents race condition with parallel starts)
            with _running_sessions_lock:
                _running_sessions[result_session_id] = None
            log(f"[Session] Created new session {_current_session_id} (triggered_by: {triggered_by})")

    # Store session_id in TaskContext for parallel execution isolation
    # This ensures add_turn_to_session() uses the correct session even when
    # multiple agents run in parallel and overwrite the global _current_session_id
    try:
        from ai_agent.task_context import get_task_context_or_none
        ctx = get_task_context_or_none()
        if ctx and result_session_id:
            ctx.session_id = result_session_id
            log(f"[Session] Stored session_id in TaskContext: {result_session_id}")
    except ImportError:
        pass

    return result_session_id


def add_turn_to_session(role: str, content: str, tokens: int = 0,
                        cost_usd: float = 0.0, task_id: str = None,
                        session_id: str = None) -> bool:
    """
    Add a turn to the current persistent session.

    This saves to SQLite for Continue/Transfer functionality.
    Also adds to in-memory conversation_history.

    Args:
        role: "user" or "assistant"
        content: The message content
        tokens: Token count
        cost_usd: Cost in USD
        task_id: Optional task ID reference
        session_id: Optional explicit session ID (for parallel execution isolation).
                   If not provided, uses TaskContext.session_id, then falls back to global.

    Returns:
        True if saved successfully, False if no active session or session_store unavailable
    """
    from ai_agent import system_log

    # Determine session ID: explicit > TaskContext > global
    effective_session_id = session_id
    if not effective_session_id:
        # Try to get from TaskContext (for parallel execution isolation)
        try:
            from ai_agent.task_context import get_task_context_or_none
            ctx = get_task_context_or_none()
            if ctx and ctx.session_id:
                effective_session_id = ctx.session_id
        except ImportError:
            pass

    # Fall back to global (legacy behavior) - WARNING: not safe for parallel execution!
    if not effective_session_id:
        effective_session_id = _current_session_id
        if effective_session_id:
            system_log(f"[Session] WARNING: Using global _current_session_id={effective_session_id} - not safe for parallel execution! Set session_id in TaskContext.")

    system_log(f"[Session] add_turn_to_session called: role={role}, content_len={len(content) if content else 0}, SESSION_STORE_AVAILABLE={SESSION_STORE_AVAILABLE}, effective_session_id={effective_session_id}")
    if not SESSION_STORE_AVAILABLE or not effective_session_id:
        system_log(f"[Session] add_turn_to_session early return: SESSION_STORE_AVAILABLE={SESSION_STORE_AVAILABLE}, effective_session_id={effective_session_id}")
        return False

    # Save to SQLite
    success = session_store.add_turn(
        effective_session_id,
        role=role,
        content=content,
        tokens=tokens,
        cost_usd=cost_usd,
        task_id=task_id
    )

    if success:
        log(f"[Session] Added {role} turn to session {effective_session_id}")

    return success


def store_session_log_content(log_content: str, session_id: str = None) -> bool:
    """
    Store execution log content for the current session.

    The log content contains detailed execution info (tool calls, prompts, etc.)
    for debugging and analysis via the improve_agent.

    Args:
        log_content: The execution log content
        session_id: Optional explicit session ID (for parallel execution isolation)

    Returns:
        True if saved successfully, False if no active session
    """
    # Determine session ID: explicit > TaskContext > global
    effective_session_id = session_id
    if not effective_session_id:
        try:
            from ai_agent.task_context import get_task_context_or_none
            ctx = get_task_context_or_none()
            if ctx and ctx.session_id:
                effective_session_id = ctx.session_id
        except ImportError:
            pass

    if not effective_session_id:
        effective_session_id = _current_session_id

    if not SESSION_STORE_AVAILABLE or not effective_session_id or not log_content:
        return False

    success = session_store.store_log_content(effective_session_id, log_content)
    if success:
        log(f"[Session] Stored log_content for session {effective_session_id} ({len(log_content)} chars)")

    return success


def end_current_session():
    """
    End the current session (mark as completed).

    Call this when user clicks "New Chat" or session should be closed.
    """
    global _current_session_id, _current_session_agent

    if not SESSION_STORE_AVAILABLE or not _current_session_id:
        return

    with session_lock:
        # Get link_map from MCP API registry before completing session
        link_map = None
        try:
            from assistant.routes.mcp_api import get_link_map_for_session, clear_link_session
            link_map = get_link_map_for_session(_current_session_id)
            clear_link_session(_current_session_id)  # Cleanup registry
        except ImportError:
            pass
        except Exception as e:
            log(f"[Session] Failed to get link_map: {e}")

        # FIX [039]: Persist SDK session ID for future resume
        session_store.complete_session(
            _current_session_id,
            link_map=link_map,
            sdk_session_id=_last_sdk_session_id
        )
        log(f"[Session] Completed session {_current_session_id} "
            f"(link_map: {len(link_map) if link_map else 0} entries, "
            f"sdk_session: {'yes' if _last_sdk_session_id else 'no'})")
        _current_session_id = None
        _current_session_agent = None


def get_current_session_id() -> Optional[str]:
    """Get the current session ID (thread-safe)."""
    with session_lock:
        return _current_session_id


def load_session_for_continue(session_id: str) -> Optional[str]:
    """
    Load a session for continuing.

    This loads the session's conversation history into memory,
    sets it as the current session, and reactivates it in the database.

    Args:
        session_id: The session ID to continue

    Returns:
        The context string for the prompt, or None if session not found
    """
    global _current_session_id, _current_session_agent, conversation_history

    if not SESSION_STORE_AVAILABLE:
        return None

    session = session_store.get_session(session_id)
    if not session:
        return None

    # Reactivate session in database (completed → active)
    session_store.reactivate_session(session_id)

    with session_lock:
        # Set as current session
        _current_session_id = session_id
        _current_session_agent = session["agent_name"]

        # Load turns into in-memory history
        conversation_history = []
        for turn in session.get("turns", []):
            # [060] Strip dialog metadata from content before loading into AI history
            clean_content = _strip_dialog_meta(turn["content"])
            conversation_history.append({
                "role": turn["role"],
                "content": clean_content,
                "summary": clean_content[:2000] + "..." if len(clean_content) > 2000 else clean_content,
                "task_name": None,
                "task_type": "chat"
            })

        # FIX [039]: Restore SDK session ID for resume capability
        sdk_sid = session.get("sdk_session_id")
        if sdk_sid:
            global _last_sdk_session_id
            _last_sdk_session_id = sdk_sid
            log(f"[Session] Restored SDK session ID: {sdk_sid[:20]}...")

        log(f"[Session] Loaded & reactivated session {session_id} ({len(conversation_history)} turns)")

    # Return context for prompt
    return session_store.get_session_context(session_id)


# =============================================================================
# Server State
# =============================================================================

server_start_time = time.time()  # For uptime calculation
_tray_icon = None  # Tray icon reference for notifications
_http_server = None  # Reference to HTTP server for shutdown

_shutdown_requested = False
_shutdown_lock = threading.Lock()
_server_state_lock = threading.Lock()  # Lock for _tray_icon and _http_server


def get_tray_icon():
    """Get the tray icon reference (thread-safe)."""
    with _server_state_lock:
        return _tray_icon


def set_tray_icon(icon):
    """Set the tray icon reference for notifications (thread-safe)."""
    global _tray_icon
    with _server_state_lock:
        _tray_icon = icon


def set_http_server(server):
    """Set the HTTP server reference (thread-safe)."""
    global _http_server
    with _server_state_lock:
        _http_server = server


def request_shutdown():
    """Request graceful shutdown of the server."""
    global _shutdown_requested
    with _shutdown_lock:
        _shutdown_requested = True
    log("[Shutdown] Graceful shutdown requested")

    # Stop HTTP server if running
    with _server_state_lock:
        http_server = _http_server
    if http_server:
        log("[Shutdown] Stopping HTTP server...")
        threading.Thread(target=http_server.shutdown, daemon=True).start()


def is_shutdown_requested() -> bool:
    """Check if shutdown was requested."""
    with _shutdown_lock:
        return _shutdown_requested


# =============================================================================
# Tray Status Management
# =============================================================================

_tray_default_title = "DeskAgent"  # Default title when idle
_tray_status_lock = threading.RLock()  # RLock to allow nested calls (e.g., update_tray_status from set_tray_busy)
_active_task_name = None  # Track active task for status display
_tray_original_icon = None  # Store original icon for restoration
_tray_recording_icon = None  # Red recording icon (created on demand)
_cursor_state_lock = threading.Lock()  # Lock for _cursor_changed


def set_tray_default_title(title: str):
    """Set the default tray icon title (used when idle)."""
    global _tray_default_title
    with _tray_status_lock:
        _tray_default_title = title


def update_tray_status(status: str, task_name: str = None):
    """
    Update the tray icon tooltip to show current status (thread-safe).

    The tooltip appears when hovering over the tray icon, providing
    continuous visibility of what DeskAgent is doing.

    Args:
        status: Short status text (e.g., "Aufnahme...", "Transkribiere...", "Agent läuft...")
        task_name: Optional task name for context
    """
    global _active_task_name
    with _server_state_lock:
        icon = _tray_icon
    if not icon:
        return

    with _tray_status_lock:
        _active_task_name = task_name

        # Build tooltip text
        if status:
            if task_name:
                tooltip = f"DeskAgent - {task_name}: {status}"
            else:
                tooltip = f"DeskAgent - {status}"
        else:
            tooltip = _tray_default_title

        # Update the icon title (tooltip)
        try:
            icon.title = tooltip
        except Exception as e:
            log(f"[Tray] Error updating title: {e}")


def set_tray_busy(task_name: str, status: str = "läuft..."):
    """
    Set tray to busy state with task info (thread-safe).

    Shows a notification and updates the tooltip.

    Args:
        task_name: Name of the running task
        status: Status text (default: "läuft...")
    """
    with _server_state_lock:
        icon = _tray_icon
    if not icon:
        return

    update_tray_status(status, task_name)

    # Show notification
    try:
        icon.notify(f"{task_name} {status}", "DeskAgent")
    except Exception:
        pass


def set_tray_idle():
    """Reset tray to idle state."""
    update_tray_status(None)


def get_active_task_name() -> Optional[str]:
    """Get the currently active task name."""
    with _tray_status_lock:
        return _active_task_name


def _create_recording_icon():
    """Create a red recording indicator icon (thread-safe)."""
    global _tray_recording_icon
    with _tray_status_lock:
        if _tray_recording_icon:
            return _tray_recording_icon

        try:
            from PIL import Image, ImageDraw

            # Create a red circle icon (64x64)
            size = 64
            image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)

            # Red filled circle
            margin = 4
            draw.ellipse(
                [margin, margin, size - margin, size - margin],
                fill=(220, 53, 69, 255),  # Bootstrap red
                outline=(180, 40, 50, 255),
                width=2
            )

            # Small white microphone indicator in center
            center = size // 2
            mic_height = 16
            mic_width = 8
            draw.rounded_rectangle(
                [center - mic_width//2, center - mic_height//2,
                 center + mic_width//2, center + mic_height//2 - 2],
                radius=4,
                fill=(255, 255, 255, 255)
            )
            # Mic stand
            draw.arc(
                [center - mic_width//2 - 2, center,
                 center + mic_width//2 + 2, center + mic_height//2 + 2],
                start=0, end=180,
                fill=(255, 255, 255, 255),
                width=2
            )
            draw.line(
                [center, center + mic_height//2 + 2, center, center + mic_height//2 + 6],
                fill=(255, 255, 255, 255),
                width=2
            )

            _tray_recording_icon = image
            return image
        except Exception as e:
            log(f"[Tray] Error creating recording icon: {e}")
            return None


def set_tray_recording(is_recording: bool):
    """
    Change tray icon to indicate recording state (thread-safe).

    Args:
        is_recording: True to show red recording icon, False to restore original
    """
    global _tray_original_icon
    with _server_state_lock:
        icon = _tray_icon
    if not icon:
        return

    with _tray_status_lock:
        try:
            if is_recording:
                # Save original icon if not saved yet
                if not _tray_original_icon:
                    _tray_original_icon = icon.icon

                # Create and set recording icon (already protected by _tray_status_lock via RLock)
                recording_icon = _create_recording_icon()
                if recording_icon:
                    icon.icon = recording_icon
                    icon.title = "DeskAgent - Aufnahme..."
                    log("[Tray] Recording icon set")
            else:
                # Restore original icon
                if _tray_original_icon:
                    icon.icon = _tray_original_icon
                    icon.title = _tray_default_title
                    log("[Tray] Original icon restored")
        except Exception as e:
            log(f"[Tray] Error changing icon: {e}")


# =============================================================================
# Mouse Cursor Recording Indicator
# =============================================================================

_cursor_changed = False


def set_recording_cursor(is_recording: bool):
    """
    Change mouse cursor to indicate recording state (thread-safe).

    On Windows, changes cursor to a red/recording indicator.
    Cursor automatically restores when recording stops.

    Args:
        is_recording: True to show recording cursor, False to restore normal
    """
    global _cursor_changed
    import sys

    if sys.platform != 'win32':
        return

    with _cursor_state_lock:
        try:
            import win32api
            import win32con

            if is_recording and not _cursor_changed:
                # Change to "App Starting" cursor (spinning circle) as recording indicator
                # This is a system cursor that's always visible
                win32api.SetSystemCursor(
                    win32api.LoadCursor(0, win32con.IDC_APPSTARTING),
                    win32con.IDC_ARROW
                )
                _cursor_changed = True
                log("[Cursor] Recording cursor set (AppStarting)")

            elif not is_recording and _cursor_changed:
                # Restore default cursor
                # SystemParametersInfo with SPI_SETCURSORS restores all cursors
                import ctypes
                ctypes.windll.user32.SystemParametersInfoW(0x0057, 0, None, 0)  # SPI_SETCURSORS
                _cursor_changed = False
                log("[Cursor] Default cursor restored")

        except ImportError:
            log("[Cursor] win32api not available")
        except Exception as e:
            log(f"[Cursor] Error changing cursor: {e}")


