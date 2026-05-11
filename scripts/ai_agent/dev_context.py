# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Developer Context Capture
=========================
Stores context data for debugging in Developer Mode.

This module tracks:
- System/user prompts sent to AI
- Tool call results
- Iteration progress
- Anonymization mappings

Used by the WebUI Developer Panel to inspect what was sent to the AI.

IMPORTANT: This module imports from logging.py only (no other ai_agent modules)
to avoid circular imports.

Task Isolation (planfeature-034):
DevContext is stored in a task-keyed dict (_dev_contexts) instead of a global
singleton. Task-ID is read from TaskContext (ContextVar). This ensures parallel
agents get isolated DevContexts while still allowing cross-thread reads from
HTTP endpoints (which can pass task_id explicitly).
"""

import time
import threading
from typing import Optional, Callable

__all__ = [
    "reset_dev_context",
    "capture_dev_context",
    "get_dev_context",
    "add_dev_tool_result",
    "set_dev_anonymization",
    "update_dev_iteration",
    "set_log_func",
    "clear_dev_context",
]

# =============================================================================
# DEVELOPER CONTEXT CAPTURE
# Task-keyed storage for parallel execution isolation
# =============================================================================

# Task-keyed dict: {task_id: dev_context_dict}
_dev_contexts: dict[str, dict] = {}

# Lock for thread-safe access to _dev_contexts dict itself
# (individual dict mutations are GIL-protected, but dict creation/deletion needs this)
_dev_contexts_lock = threading.Lock()

# Last active task_id for fallback access (e.g., HTTP endpoints without explicit task_id)
_last_task_id: str = "_default"

# Optional logging function (set by base.py or logging.py)
_log_func: Optional[Callable[[str], None]] = None


def _log(message: str):
    """Internal log helper - uses external log function if set."""
    if _log_func:
        _log_func(message)


def set_log_func(func: Callable[[str], None]):
    """Set the logging function.

    Called from base.py to wire up logging after the logging module is loaded.
    This avoids circular imports while still providing logging capability.

    Args:
        func: Logging function that accepts a string message
    """
    global _log_func
    _log_func = func


def _make_empty_context() -> dict:
    """Create a fresh empty dev context dict.

    Returns:
        Dict with all dev context fields initialized to defaults.
    """
    return {
        "system_prompt": "",
        "user_prompt": "",
        "tool_results": [],
        "model": "",
        "timestamp": None,
        "iteration": 0,
        "max_iterations": 0,
        "anonymization": {}
    }


def _get_task_id() -> str:
    """Get current task ID from TaskContext, fallback to _last_task_id.

    For write operations (called from agent thread), this reads the task_id
    from the ContextVar-based TaskContext. If no TaskContext is set (e.g.,
    tests, single-agent usage), falls back to _last_task_id.

    Returns:
        Task ID string
    """
    try:
        from .task_context import get_task_context_or_none
        ctx = get_task_context_or_none()
        if ctx and ctx.task_id:
            return str(ctx.task_id)
    except ImportError:
        pass
    return _last_task_id


def _get_context(task_id: str | None = None) -> dict:
    """Get or create dev context for given task.

    Args:
        task_id: Explicit task ID. If None, reads from TaskContext.

    Returns:
        Dev context dict for the task.
    """
    global _last_task_id

    if task_id is None:
        task_id = _get_task_id()

    _last_task_id = task_id

    with _dev_contexts_lock:
        if task_id not in _dev_contexts:
            _dev_contexts[task_id] = _make_empty_context()
        return _dev_contexts[task_id]


def reset_dev_context():
    """
    Reset dev context for a new task.

    Called once at start of call_agent() to clear previous task's data.
    Creates a fresh context for the current task (identified via TaskContext).
    """
    global _last_task_id

    task_id = _get_task_id()
    _last_task_id = task_id

    with _dev_contexts_lock:
        _dev_contexts[task_id] = _make_empty_context()
        _dev_contexts[task_id]["timestamp"] = time.time()

    _log(f"[DevContext] Reset for new task (task_id={task_id})")


def set_dev_anonymization(mappings: dict):
    """
    Set anonymization mappings in dev context.

    These mappings show which placeholders map to which original values,
    useful for debugging anonymization issues.

    Args:
        mappings: Dict of {placeholder: original_value}
    """
    ctx = _get_context()
    ctx["anonymization"] = mappings or {}
    _log(f"[DevContext] Anonymization set: {len(mappings or {})} mappings")


def capture_dev_context(
    system_prompt: str = None,
    user_prompt: str = None,
    model: str = None
):
    """
    Update context fields.

    Does NOT clear tool_results - use reset_dev_context() for that.
    Updates timestamp on each capture.

    Args:
        system_prompt: The system prompt sent to AI (optional)
        user_prompt: The user prompt sent to AI (optional)
        model: The model name/identifier (optional)
    """
    ctx = _get_context()
    if system_prompt is not None:
        ctx["system_prompt"] = system_prompt
    if user_prompt is not None:
        ctx["user_prompt"] = user_prompt
    if model is not None:
        ctx["model"] = model
    ctx["timestamp"] = time.time()


def add_dev_tool_result(
    tool_name: str,
    result: str,
    anon_count: int = 0,
    args: dict = None
):
    """
    Add tool result to developer context.

    Tool results are accumulated across the agent run.
    Results are truncated to 10000 chars to prevent memory issues.

    Args:
        tool_name: Name of the tool
        result: Tool result string
        anon_count: Number of PII entities anonymized in result
        args: Tool arguments (for debugging)
    """
    ctx = _get_context()

    ctx["tool_results"].append({
        "tool": tool_name,
        "args": args or {},
        "result": result[:10000] if result else "",  # Limit size for display
        "anon_count": anon_count
    })
    _log(
        f"[DevContext] Added tool result: {tool_name} "
        f"({len(result) if result else 0} chars) - "
        f"Total: {len(ctx['tool_results'])} tools"
    )


def update_dev_iteration(iteration: int, max_iterations: int):
    """
    Update iteration progress in developer context.

    Shows how many AI turns have occurred and the configured limit.

    Args:
        iteration: Current iteration number (1-based)
        max_iterations: Maximum iterations configured for agent
    """
    ctx = _get_context()
    ctx["iteration"] = iteration
    ctx["max_iterations"] = max_iterations


def get_dev_context(task_id: str | None = None) -> dict:
    """
    Get the captured context for developer debugging.

    Returns a copy of the context to prevent external modification.

    Args:
        task_id: Explicit task ID. If None, reads from TaskContext or
                 falls back to the last active task.

    Returns:
        Dict with:
        - system_prompt: str
        - user_prompt: str
        - tool_results: list of {tool, args, result, anon_count}
        - model: str
        - timestamp: float (Unix timestamp)
        - iteration: int
        - max_iterations: int
        - anonymization: dict of {placeholder: original}
    """
    ctx = _get_context(task_id)
    return ctx.copy()


def clear_dev_context(task_id: str | None = None):
    """
    Remove dev context for a completed task (memory cleanup).

    Called after task completion and logging to free memory.

    Args:
        task_id: Task ID to clear. If None, reads from TaskContext.
    """
    if task_id is None:
        task_id = _get_task_id()

    with _dev_contexts_lock:
        if task_id in _dev_contexts:
            del _dev_contexts[task_id]
            _log(f"[DevContext] Cleared context for task_id={task_id}")
