# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
AI Agent Logging Module
=======================
Centralized logging for all AI agent implementations.

This module provides:
- Console logging with buffer support
- System log (persistent debug log in system.log)
- Anonymization message log (shows what goes to AI backends)
- Tool call logging

IMPORTANT: This module must NOT import from other ai_agent modules
to avoid circular imports. It only imports from `paths`.

Functions:
- log() - General console log (with optional file output)
- system_log() - Write to system.log with timestamp
- init_system_log() - Initialize system.log (call once at startup)
- set_logger() - Set external logger function
- set_console_logging() - Enable/disable console output
- start_log_buffer() / stop_log_buffer() - Capture logs to buffer
- anon_message_log() - Log anonymized messages for visibility
- log_tool_call() - Log tool calls to anon log
"""

import sys
import threading
import traceback
from pathlib import Path
from typing import Optional, Callable

# Handle imports for both package and direct execution
# Path is set up by ai_agent/__init__.py
from paths import get_logs_dir

# Centralized timestamp utilities
try:
    from utils.timestamp import (
        get_timestamp_datetime,
        get_timestamp_time,
        get_timestamp_time_ms,
    )
except ImportError:
    # Fallback for standalone execution
    from datetime import datetime
    def get_timestamp_datetime(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def get_timestamp_time(): return datetime.now().strftime("%H:%M:%S")
    def get_timestamp_time_ms(): return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# =============================================================================
# Global State
# =============================================================================

# Console logging
_log_func: Optional[Callable[[str], None]] = None
_console_logging: bool = True

# Log buffer for capturing during agent calls
_log_buffer: list = []
_log_buffer_enabled: bool = False

# System log state
_system_log_path: Optional[Path] = None
_SYSTEM_LOG_MAX_SIZE = 5 * 1024 * 1024  # 5 MB max size
_system_log_check_counter = 0  # Only check size every N writes


# =============================================================================
# Unicode Safe Output
# =============================================================================

def safe_output(message: str, output_func: Callable[[str], None] = print) -> None:
    """Output message with Unicode error handling for Windows console.

    On Windows, the console may not support all Unicode characters.
    This function falls back to ASCII replacement if encoding fails.

    Args:
        message: Message to output
        output_func: Function to output the message (default: print)
    """
    try:
        output_func(message)
    except UnicodeEncodeError:
        # Replace problematic characters for Windows console
        safe_message = message.encode('ascii', 'replace').decode('ascii')
        output_func(safe_message)


# =============================================================================
# Console Logging
# =============================================================================

def set_logger(log_func: Callable[[str], None]):
    """Sets the logging function for console output.

    Args:
        log_func: Function that accepts a string message
    """
    global _log_func
    _log_func = log_func


def set_console_logging(enabled: bool):
    """Enables/disables console logging output.

    Args:
        enabled: True to enable, False to disable
    """
    global _console_logging
    _console_logging = enabled


def start_log_buffer():
    """Start capturing log messages to buffer.

    Call this before agent execution to capture all log messages.
    Retrieve captured messages with stop_log_buffer().
    """
    global _log_buffer, _log_buffer_enabled
    _log_buffer = []
    _log_buffer_enabled = True


def stop_log_buffer() -> list:
    """Stop capturing and return buffered messages.

    Returns:
        List of captured log messages since start_log_buffer()
    """
    global _log_buffer, _log_buffer_enabled
    _log_buffer_enabled = False
    result = _log_buffer.copy()
    _log_buffer = []
    return result


def log(message: str):
    """Logs message if logger is set and console_logging is active.

    Also:
    - Captures to buffer if buffering is enabled
    - Writes to system.log if initialized

    Args:
        message: Message to log
    """
    # Capture to buffer if enabled
    if _log_buffer_enabled:
        _log_buffer.append(message)

    # Output to console (with encoding error handling for Windows)
    if _log_func and _console_logging:
        safe_output(message, _log_func)

    # Also write to system.log (if initialized)
    if _system_log_path is not None:
        _write_to_system_log(message)


# =============================================================================
# System Log (Persistent Debug Log)
# =============================================================================

def init_system_log() -> Path:
    """
    Initialize system.log - deletes old log and creates new one.
    Call this once at application startup.

    Safe to call multiple times - only initializes on first call.

    Also installs global exception hooks to log unhandled errors.

    Returns:
        Path to the system.log file
    """
    global _system_log_path

    # Already initialized - return existing path
    if _system_log_path is not None:
        return _system_log_path

    _system_log_path = get_logs_dir() / "system.log"

    # Delete old log if exists
    if _system_log_path.exists():
        try:
            _system_log_path.unlink()
        except (OSError, PermissionError):
            pass  # Log file may be locked by another process

    # Also delete mcp_discovery.log on startup (MCP subprocess debug log)
    mcp_log = get_logs_dir() / "mcp_discovery.log"
    if mcp_log.exists():
        try:
            mcp_log.unlink()
        except (OSError, PermissionError):
            pass  # Log file may be locked by another process

    # Delete anon_messages.log on startup (fresh start each session)
    anon_log = get_logs_dir() / "anon_messages.log"
    if anon_log.exists():
        try:
            anon_log.unlink()
        except (OSError, PermissionError):
            pass  # Log file may be locked by another process

    # Cleanup old per-task anon logs (legacy files from previous version)
    logs_dir = get_logs_dir()
    for old_anon in logs_dir.glob("anon_messages_*.log"):
        try:
            old_anon.unlink()
        except (OSError, PermissionError):
            pass  # Skip files that can't be deleted

    # Create new log with startup header
    try:
        with open(_system_log_path, "w", encoding="utf-8") as f:
            f.write(f"=== DeskAgent System Log ===\n")
            f.write(f"Started: {get_timestamp_datetime()}\n")
            f.write(f"{'=' * 40}\n\n")
    except (OSError, PermissionError, IOError):
        pass  # Cannot create log file - continue without logging

    # Install global exception hook to log Python errors
    _original_excepthook = sys.excepthook

    def _exception_hook(exc_type, exc_value, exc_tb):
        """Log unhandled exceptions to system.log."""
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        system_log(f"[ERROR] Unhandled exception:\n{error_msg}")
        # Also call original hook (prints to console)
        _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _exception_hook

    # Also install threading exception hook for errors in threads
    def _threading_exception_hook(args):
        """Log unhandled exceptions in threads to system.log."""
        error_msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        system_log(f"[ERROR] Thread exception in {args.thread.name}:\n{error_msg}")

    threading.excepthook = _threading_exception_hook

    return _system_log_path


def _check_system_log_size():
    """Check if system.log exceeds max size, truncate if needed."""
    global _system_log_check_counter
    _system_log_check_counter += 1

    # Only check every 100 writes to avoid performance impact
    if _system_log_check_counter < 100:
        return
    _system_log_check_counter = 0

    if _system_log_path is None or not _system_log_path.exists():
        return

    try:
        size = _system_log_path.stat().st_size
        if size > _SYSTEM_LOG_MAX_SIZE:
            # Read last 2MB of content and rewrite
            with open(_system_log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(max(0, size - 2 * 1024 * 1024))
                content = f.read()
            # Find first newline to start at a complete line
            first_newline = content.find("\n")
            if first_newline > 0:
                content = content[first_newline + 1:]
            with open(_system_log_path, "w", encoding="utf-8") as f:
                f.write(f"[...truncated - log exceeded {_SYSTEM_LOG_MAX_SIZE // (1024*1024)}MB...]\n")
                f.write(content)
    except (OSError, PermissionError, IOError):
        pass  # Log truncation failed - continue with existing log


def _write_to_system_log(message: str):
    """Internal helper - write to system.log without auto-init (for use from log()).

    Args:
        message: Message to write
    """
    if _system_log_path is None:
        return
    try:
        with open(_system_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{get_timestamp_time_ms()}] {message}\n")
        _check_system_log_size()
    except (OSError, PermissionError, IOError):
        pass  # Cannot write to log - continue silently


def system_log(message: str):
    """
    Write message to system.log with timestamp.
    If init_system_log() hasn't been called, creates the log file automatically.
    Automatically truncates if file exceeds 5MB.

    Args:
        message: Message to log (can include category prefix like [HTTP], [Task], etc.)
    """
    global _system_log_path

    if _system_log_path is None:
        _system_log_path = get_logs_dir() / "system.log"

    try:
        with open(_system_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{get_timestamp_time_ms()}] {message}\n")
        _check_system_log_size()
    except (OSError, PermissionError, IOError):
        pass  # Cannot write to log - continue silently


# =============================================================================
# Anonymization Message Log
# =============================================================================
# Simple log showing what goes IN and OUT of AI backends (for verifying anonymization)
# Single file (anon_messages.log) - deleted on startup, replaced on each agent run

def _get_anon_log_path() -> Path:
    """
    Get the anon_messages log path.

    Returns single file that's overwritten on each new agent run.
    Deleted on startup in init_system_log().

    Returns:
        Path to the log file (always anon_messages.log)
    """
    return get_logs_dir() / "anon_messages.log"


def anon_message_log(direction: str, content: str, task_name: str = "", pii_count: int = 0, backend: str = "", mappings: dict = None):
    """
    Log anonymized messages to dedicated file for visibility.
    File is overwritten on each new agent run (when PROMPT is logged).
    Shows ONLY what goes over the internet (anonymized content).

    Single file (anon_messages.log) - deleted on startup, replaced per run.

    Args:
        direction: "PROMPT" (going to AI) or "RESPONSE" (coming from AI)
        content: The message content (should be anonymized)
        task_name: Name of the task/agent
        pii_count: Number of PII entities replaced (for PROMPT only)
        backend: Name of the AI backend being used (e.g., "gemini", "openai", "claude_sdk")
        mappings: Dict of placeholder -> original value (shown at end for RESPONSE)
    """
    # Import here to avoid circular dependency
    try:
        from .task_context import get_task_context_or_none
        ctx = get_task_context_or_none()
        task_id = ctx.task_id if ctx else None
    except ImportError:
        task_id = None

    log_path = _get_anon_log_path()
    timestamp = get_timestamp_datetime()
    separator = "-" * 70

    try:
        # PROMPT = new agent run, overwrite file; RESPONSE = append
        mode = "w" if direction == "PROMPT" else "a"
        with open(log_path, mode, encoding="utf-8") as f:
            if direction == "PROMPT":
                backend_info = f" | Backend: {backend}" if backend else ""
                task_id_info = f" | TaskID: {task_id}" if task_id else ""
                f.write(f"# ANONYMIZATION LOG - {timestamp} - {task_name}{backend_info}{task_id_info}\n")
                f.write(f"# Look for: [PERSON-1], [EMAIL-1], [ORG-1] = anonymized OK\n")
                f.write(f"# {pii_count} PII entities replaced in prompt\n")
                f.write(f"{separator}\n\n")
                f.write(f"> OUT PROMPT TO AI ({len(content)} chars):\n")
                f.write(f"{content}\n")
                f.write(f"\n{separator}\n")
            else:
                f.write(f"\n< IN RESPONSE FROM AI ({len(content)} chars):\n")
                f.write(f"{content}\n")
                f.write(f"\n{separator}\n")

                # Show mappings at the end
                if mappings:
                    f.write(f"\n# ANONYMIZATION MAPPINGS ({len(mappings)} total):\n")
                    for placeholder, original in mappings.items():
                        f.write(f"#   {placeholder} = {original}\n")
                    f.write(f"{separator}\n")
    except (OSError, PermissionError, IOError):
        pass  # Cannot write to anon log - continue silently


def log_tool_call(tool_name: str, direction: str, content: str, is_anonymized: bool = True):
    """
    Log tool calls to anon_messages log for visibility.
    Appends to the existing log file.
    Shows ONLY anonymized content (what goes over the internet).

    Args:
        tool_name: Name of the tool being called
        direction: "CALL" (AI sends to tool) or "RESULT" (tool returns to AI)
        content: Arguments or result content (must be anonymized)
        is_anonymized: Whether the content has been anonymized (for logging purposes)
    """
    log_path = _get_anon_log_path()
    separator = "-" * 70

    try:
        timestamp = get_timestamp_time()
        if direction == "CALL":
            prefix = f"> OUT {timestamp} TOOL CALL: {tool_name}"
        else:
            prefix = f"< IN  {timestamp} TOOL RESULT: {tool_name}"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{prefix}\n")
            f.write(f"{content}\n")
            f.write(f"{separator}\n")
    except (OSError, PermissionError, IOError):
        pass  # Cannot write to tool log - continue silently


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Unicode safe output
    "safe_output",
    # Console logging
    "log",
    "set_logger",
    "set_console_logging",
    "start_log_buffer",
    "stop_log_buffer",
    # System log
    "system_log",
    "init_system_log",
    # Anonymization log
    "anon_message_log",
    "log_tool_call",
]
