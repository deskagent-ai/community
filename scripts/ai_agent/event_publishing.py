# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Event Publishing - SSE Event Functions
======================================
Publishes tool and context events via Server-Sent Events (SSE).

Used by AI backends to notify the UI about tool execution and context usage.
"""

from typing import Optional

__all__ = [
    "set_current_task_id",
    "get_current_task_id",
    "publish_tool_event",
    "publish_context_event",
]


def set_current_task_id(task_id: Optional[str]):
    """Set the current task ID for SSE event publishing.

    This is a backwards-compatible wrapper that stores task_id in TaskContext.
    For new code, prefer using create_task_context() directly.
    """
    from .task_context import get_task_context
    ctx = get_task_context()
    ctx.task_id = task_id


def get_current_task_id() -> Optional[str]:
    """Get the current task ID.

    This is a backwards-compatible wrapper that reads from TaskContext.
    For new code, prefer using get_task_context().task_id directly.
    """
    from .task_context import get_task_context_or_none
    ctx = get_task_context_or_none()
    return ctx.task_id if ctx else None


def publish_tool_event(
    tool_name: str,
    status: str = "executing",
    duration: float = None,
    args_preview: str = None,
    result_preview: str = None
):
    """Publish a tool call SSE event if task ID is set.

    Args:
        tool_name: Name of the tool being called
        status: "executing" or "complete"
        duration: Optional duration in seconds (for "complete" status)
        args_preview: Optional short preview of tool arguments
        result_preview: Optional short preview of tool result
    """
    task_id = get_current_task_id()
    if task_id is None:
        return
    try:
        from assistant.core.sse_manager import publish_tool_call, has_queue
        if has_queue(task_id):
            publish_tool_call(
                task_id, tool_name, status, duration,
                args_preview=args_preview,
                result_preview=result_preview
            )
    except ImportError:
        pass  # sse_manager not available (e.g., in tests)
    except Exception as e:
        from .logging import log
        log(f"[SSE] Error publishing tool event: {e}")


def publish_context_event(total_tokens: int = 0, limit: int = 200000,
                          iteration: int = 0, max_iterations: int = 0,
                          tool_count: int = 0, system_tokens: int = 0,
                          prompt_tokens: int = 0, tool_tokens: int = 0):
    """Publish a dev context SSE event if task ID is set.

    Args:
        total_tokens: Total context tokens
        limit: Context limit
        iteration: Current iteration number
        max_iterations: Maximum iterations
        tool_count: Number of tool calls executed
        system_tokens: Tokens used by system prompt (incl. knowledge)
        prompt_tokens: Tokens used by user prompt
        tool_tokens: Tokens used by tool responses
    """
    task_id = get_current_task_id()
    if task_id is None:
        return
    try:
        from assistant.core.sse_manager import publish_dev_context, has_queue
        if has_queue(task_id):
            publish_dev_context(task_id, total_tokens, limit,
                               system_tokens=system_tokens, user_tokens=prompt_tokens,
                               tool_tokens=tool_tokens,
                               iteration=iteration, max_iterations=max_iterations,
                               tool_count=tool_count)
    except ImportError:
        pass
    except Exception as e:
        from .logging import log
        log(f"[SSE] Error publishing context event: {e}")
