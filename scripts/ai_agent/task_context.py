# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Task-local context for parallel execution isolation.

This module provides TaskContext, a dataclass that holds all per-task state,
stored in a ContextVar for automatic asyncio task and thread isolation.

Usage:
    # At task start (inside thread/task function)
    ctx = TaskContext(
        task_id="my-task-abc123",
        backend_name="gemini",
        dry_run_mode=True
    )
    set_task_context(ctx)

    # During execution - access current context
    ctx = get_task_context()
    print(ctx.backend_name)  # "gemini"

    # At task end
    clear_task_context()

Note: ContextVar values are NOT automatically inherited by new threads.
      Always call set_task_context() INSIDE the thread function.
"""
from dataclasses import dataclass, field
from contextvars import ContextVar
from typing import Optional, List, Set, Dict, Any
from datetime import datetime


@dataclass
class TaskContext:
    """
    Holds all per-task state for isolated parallel execution.

    This replaces the previous global variables in tool_bridge.py:
    - _anonymization_context
    - _dry_run_mode
    - _test_folder
    - _allowed_tools
    - _blocked_tools
    - _simulated_actions
    """

    # Anonymization
    anon_context: Any = None  # AnonymizationContext instance

    # Dry-run mode
    dry_run_mode: bool = False
    simulated_actions: List[Dict] = field(default_factory=list)

    # Test isolation
    test_folder: Optional[str] = None

    # Tool filtering
    allowed_tools: Optional[Set[str]] = None
    blocked_tools: Optional[Set[str]] = None

    # Filesystem restrictions (per-agent write path whitelist)
    # List of glob patterns for allowed write paths, e.g., ["workspace/exports/**"]
    filesystem_write_paths: Optional[List[str]] = None

    # MCP filter (per-task isolation for parallel execution)
    mcp_filter: Optional[str] = None

    # Task metadata
    task_id: Optional[str] = None
    backend_name: Optional[str] = None
    session_id: Optional[str] = None  # SQLite session ID for parallel execution isolation

    # Logging buffer (optional - for collecting logs per task)
    log_buffer: List[Dict] = field(default_factory=list)

    def log(self, category: str, message: str, content: str = None) -> None:
        """
        Add log entry to task buffer.

        Args:
            category: Log category (e.g., "PROMPT", "RESPONSE", "TOOL_CALL")
            message: Short log message
            content: Optional detailed content
        """
        self.log_buffer.append({
            "timestamp": datetime.now().isoformat(),
            "task_id": self.task_id,
            "backend": self.backend_name,
            "category": category,
            "message": message,
            "content": content
        })

    def reset_simulated_actions(self) -> None:
        """Clear simulated actions list (for dry-run mode)."""
        self.simulated_actions = []

    def add_simulated_action(self, tool: str, args: dict, result: str) -> None:
        """
        Record a simulated action in dry-run mode.

        Args:
            tool: Tool name
            args: Tool arguments
            result: Simulated result
        """
        self.simulated_actions.append({
            "tool": tool,
            "args": args,
            "simulated_result": result
        })


# ContextVar for automatic task isolation
# Each asyncio task and thread gets its own value
_task_context: ContextVar[Optional[TaskContext]] = ContextVar(
    'task_context',
    default=None
)


def get_task_context() -> TaskContext:
    """
    Get current task context, creating default if needed.

    Returns:
        TaskContext: The current task's context

    Note:
        If no context is set, creates a new empty TaskContext.
        This ensures backward compatibility with code that doesn't
        explicitly set a context.
    """
    ctx = _task_context.get()
    if ctx is None:
        ctx = TaskContext()
        _task_context.set(ctx)
    return ctx


def get_task_context_or_none() -> Optional[TaskContext]:
    """
    Get current task context without creating default.

    Returns:
        Optional[TaskContext]: The current context or None

    Use this when you need to check if a context exists without
    creating one (e.g., for optional per-task logging).
    """
    return _task_context.get()


def set_task_context(ctx: TaskContext) -> None:
    """
    Set task context for current asyncio task or thread.

    Args:
        ctx: TaskContext to set

    Important:
        Call this INSIDE the thread/task function, not before starting.
        ContextVar values are NOT inherited by new threads.
    """
    _task_context.set(ctx)


def clear_task_context() -> None:
    """
    Clear task context (reset to None).

    Call this when a task completes to ensure clean state
    for any subsequent tasks in the same thread.
    """
    _task_context.set(None)


def create_task_context(
    task_id: str,
    backend_name: str = None,
    dry_run_mode: bool = False,
    test_folder: str = None,
    allowed_tools: Set[str] = None,
    blocked_tools: Set[str] = None,
    mcp_filter: str = None,
    session_id: str = None,
    filesystem_write_paths: List[str] = None
) -> TaskContext:
    """
    Factory function to create and set a new TaskContext.

    Args:
        task_id: Unique identifier for this task
        backend_name: AI backend name (e.g., "gemini", "openai")
        dry_run_mode: If True, simulate destructive actions
        test_folder: Outlook test folder name (for testing)
        allowed_tools: Optional whitelist of allowed tool names
        blocked_tools: Optional blacklist of blocked tool names
        mcp_filter: Optional MCP server filter pattern (e.g., "outlook|gmail")
        session_id: Optional SQLite session ID for parallel execution isolation
        filesystem_write_paths: Optional list of glob patterns for allowed write paths

    Returns:
        TaskContext: The newly created and set context
    """
    ctx = TaskContext(
        task_id=task_id,
        backend_name=backend_name,
        dry_run_mode=dry_run_mode,
        test_folder=test_folder,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        mcp_filter=mcp_filter,
        session_id=session_id,
        filesystem_write_paths=filesystem_write_paths
    )
    set_task_context(ctx)
    return ctx
