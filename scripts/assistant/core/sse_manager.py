# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
SSE (Server-Sent Events) Manager for DeskAgent.

Manages per-task event queues and provides a thread-safe bridge
from synchronous AI backend callbacks to async SSE delivery.
"""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Set

# Import system logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): print(msg)


class SSEEventType(Enum):
    """SSE event types for task streaming."""
    TASK_START = "task_start"
    TOKEN = "token"
    CONTENT_SYNC = "content_sync"  # Full content replacement (when content is modified, not just appended)
    TOOL_CALL = "tool_call"
    ANONYMIZATION = "anonymization"
    DEV_CONTEXT = "dev_context"  # Developer context (token stats, iteration info)
    PENDING_INPUT = "pending_input"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"
    TASK_CANCELLED = "task_cancelled"
    PING = "ping"


@dataclass
class SSEEvent:
    """Represents an SSE event to be sent to clients."""
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None

    def to_sse_format(self) -> str:
        """Format as SSE wire format."""
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data)}")
        lines.append("")  # Empty line terminates event
        return "\n".join(lines)


# =============================================================================
# Queue Management
# =============================================================================

_sse_queues: Dict[str, asyncio.Queue] = {}
_queue_lock = threading.Lock()
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def set_event_loop(loop: asyncio.AbstractEventLoop):
    """Register the FastAPI event loop for thread-safe publishing.

    Called during FastAPI startup.
    """
    global _event_loop
    _event_loop = loop


def get_event_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Get the registered event loop."""
    return _event_loop


def create_queue(task_id: str) -> asyncio.Queue:
    """Create an SSE queue for a task.

    Thread-safe: Can be called from HTTP request threads.
    """
    with _queue_lock:
        if task_id not in _sse_queues:
            # Create queue - will be used from async context
            # We create it here but it belongs to the event loop
            _sse_queues[task_id] = asyncio.Queue()
        return _sse_queues[task_id]


def get_queue(task_id: str) -> Optional[asyncio.Queue]:
    """Get the SSE queue for a task, if it exists.

    Thread-safe: Can be called from any thread.
    """
    with _queue_lock:
        return _sse_queues.get(task_id)


def remove_queue(task_id: str):
    """Remove and cleanup a task's SSE queue.

    Thread-safe: Can be called from any thread.
    """
    with _queue_lock:
        if task_id in _sse_queues:
            del _sse_queues[task_id]


async def remove_queue_delayed(task_id: str, delay: float = 5.0):
    """Remove queue after delay to allow final events to be delivered.

    This prevents race conditions where the queue is removed before
    SSE clients have received the final task_complete/task_error events.

    Thread-safe: Must be called from async context.

    Args:
        task_id: The task ID whose queue should be removed
        delay: Seconds to wait before removal (default: 5.0)
    """
    await asyncio.sleep(delay)
    remove_queue(task_id)
    system_log(f"[SSE] Delayed queue removal for task {task_id}")


def schedule_queue_removal(task_id: str, delay: float = 5.0):
    """Schedule delayed queue removal from synchronous context.

    Thread-safe: Can be called from any thread.
    Uses call_soon_threadsafe to schedule on the event loop.

    Args:
        task_id: The task ID whose queue should be removed
        delay: Seconds to wait before removal (default: 5.0)
    """
    global _event_loop

    if _event_loop is None:
        # No event loop, fall back to immediate removal
        remove_queue(task_id)
        return

    try:
        _event_loop.call_soon_threadsafe(
            lambda: asyncio.create_task(remove_queue_delayed(task_id, delay))
        )
    except RuntimeError:
        # Event loop closed, fall back to immediate removal
        remove_queue(task_id)


def has_queue(task_id: str) -> bool:
    """Check if a task has an SSE queue (client connected).

    Thread-safe: Can be called from any thread.
    """
    with _queue_lock:
        return task_id in _sse_queues


def get_active_queues() -> int:
    """Get count of active SSE queues (for debugging)."""
    with _queue_lock:
        return len(_sse_queues)


# =============================================================================
# Global Broadcast Queues (for running task badges)
# =============================================================================

_global_client_queues: Set[asyncio.Queue] = set()
_global_queue_lock = threading.Lock()


def register_global_client() -> asyncio.Queue:
    """Register a new client for global task events.

    Each client gets their own queue - events are broadcast to ALL queues.
    This solves the multi-client problem where queue.get() removes events.

    Returns:
        New asyncio.Queue for this client
    """
    queue = asyncio.Queue()
    with _global_queue_lock:
        _global_client_queues.add(queue)
    return queue


def unregister_global_client(queue: asyncio.Queue):
    """Remove client queue on disconnect.

    Called in finally block of SSE generator to prevent memory leaks.
    """
    with _global_queue_lock:
        _global_client_queues.discard(queue)


def get_global_client_count() -> int:
    """Get count of connected global SSE clients (for debugging)."""
    with _global_queue_lock:
        return len(_global_client_queues)


def broadcast_global_event(event_type: str, data: Dict[str, Any]):
    """Send event to ALL connected clients.

    Thread-safe: Called from AI backend threads (synchronous context).
    Uses call_soon_threadsafe to bridge to async event loop.

    Args:
        event_type: Event type (e.g., "task_started", "task_ended")
        data: Event payload (will be JSON serialized)
    """
    global _event_loop

    # Try to get event loop - either from global or running loop
    loop = _event_loop
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass  # No running loop in this thread

    if loop is None:
        system_log(f"[SSE] broadcast_global_event({event_type}): No event loop available")
        return  # FastAPI not started yet

    event = SSEEvent(event=event_type, data=data)
    client_count = len(_global_client_queues)
    system_log(f"[SSE] broadcast_global_event({event_type}) to {client_count} clients")

    with _global_queue_lock:
        # Iterate over a copy to avoid modification during iteration
        for queue in list(_global_client_queues):
            try:
                loop.call_soon_threadsafe(
                    lambda q=queue, e=event: asyncio.create_task(q.put(e))
                )
            except RuntimeError:
                pass  # Event loop closed


# =============================================================================
# Event Publishing (Thread-Safe Bridge)
# =============================================================================

def publish_event(task_id: str, event_type: str, data: Dict[str, Any], event_id: str = None):
    """Publish an SSE event for a task.

    Thread-safe: Called from AI backend threads (synchronous context).
    Uses call_soon_threadsafe to bridge to async event loop.

    Args:
        task_id: The task to publish to
        event_type: SSE event type (e.g., "token", "task_complete")
        data: Event payload (will be JSON serialized)
        event_id: Optional event ID for reconnection
    """
    global _event_loop

    # Import system_log for debugging
    try:
        import ai_agent
        system_log = ai_agent.system_log
    except (ImportError, AttributeError):
        system_log = lambda msg: None

    # Debug: Log important events (terminal + pending_input)
    is_terminal = event_type in ("task_complete", "task_error", "task_cancelled")
    is_important = is_terminal or event_type == "pending_input"

    if _event_loop is None:
        system_log(f"[SSE] WARNING: event_loop is None, dropping {event_type} for task {task_id}")
        return  # FastAPI not started yet

    queue = get_queue(task_id)
    if queue is None:
        if is_important:
            system_log(f"[SSE] WARNING: no queue for task {task_id}, dropping {event_type}")
        return  # No client connected

    # [046] Inject task_id centrally in ALL event payloads for frontend validation
    data["task_id"] = task_id

    event = SSEEvent(event=event_type, data=data, id=event_id)

    # Log important events for debugging
    if is_important:
        system_log(f"[SSE] Publishing {event_type} for task {task_id}")

    # Schedule the put operation on the event loop from this thread
    try:
        _event_loop.call_soon_threadsafe(
            lambda e=event: asyncio.create_task(_async_put(queue, e, task_id, event_type))
        )
    except RuntimeError as ex:
        # Event loop closed or not running
        system_log(f"[SSE] ERROR: call_soon_threadsafe failed for {event_type}: {ex}")


async def _async_put(queue: asyncio.Queue, event: SSEEvent,
                     task_id: str = None, event_type: str = None):
    """Async helper to put event in queue."""
    try:
        await queue.put(event)
    except Exception as ex:
        # Log exceptions instead of silently swallowing them
        try:
            import ai_agent
            ai_agent.system_log(f"[SSE] ERROR: queue.put failed for {event_type} (task {task_id}): {ex}")
        except Exception:
            pass


# =============================================================================
# Convenience Functions
# =============================================================================

def publish_task_start(task_id: str, model: str = None, agent: str = None,
                       skill: str = None, backend: str = None):
    """Publish task_start event."""
    publish_event(task_id, SSEEventType.TASK_START.value, {
        "task_id": task_id,
        "model": model,
        "agent": agent,
        "skill": skill,
        "backend": backend
    })


def publish_token(task_id: str, token: str, is_thinking: bool = False,
                  accumulated_length: int = 0):
    """Publish a streaming token event."""
    publish_event(task_id, SSEEventType.TOKEN.value, {
        "token": token,
        "is_thinking": is_thinking,
        "accumulated_length": accumulated_length
    })


def publish_content_sync(task_id: str, content: str, is_thinking: bool = False):
    """Publish a full content sync event (when content was modified, not just appended).

    This is used when tool markers are replaced (e.g., [Tool: name ...] -> [Tool: name | 0.5s])
    because delta streaming would produce incorrect results.
    """
    publish_event(task_id, SSEEventType.CONTENT_SYNC.value, {
        "content": content,
        "is_thinking": is_thinking,
        "length": len(content)
    })


def publish_tool_call(task_id: str, tool_name: str, status: str = "executing",
                      duration: float = None, args_preview: str = None,
                      result_preview: str = None):
    """Publish tool call status with optional details.

    Args:
        task_id: Task identifier
        tool_name: Name of the tool being called
        status: "executing" or "complete"
        duration: Optional duration in seconds
        args_preview: Optional short preview of arguments (max 100 chars)
        result_preview: Optional short preview of result (max 100 chars)
    """
    data = {"tool_name": tool_name, "status": status}
    if duration is not None:
        data["duration"] = round(duration, 2)
    if args_preview:
        data["args_preview"] = args_preview[:100]  # Limit length
    if result_preview:
        data["result_preview"] = result_preview[:100]  # Limit length
    publish_event(task_id, SSEEventType.TOOL_CALL.value, data)


def publish_anonymization(task_id: str, total_entities: int,
                          entity_types: Dict[str, int] = None,
                          tool_calls_anonymized: int = 0,
                          mappings: Dict[str, str] = None):
    """Publish anonymization stats update.

    Args:
        task_id: Task identifier
        total_entities: Total number of PII entities anonymized
        entity_types: Dict of entity type -> count
        tool_calls_anonymized: Number of tool calls with anonymized results
        mappings: Dict of placeholder -> original value (truncated for display)
    """
    # Truncate mapping values for display (don't expose full PII in logs)
    display_mappings = {}
    if mappings:
        for placeholder, value in mappings.items():
            if isinstance(value, str):
                display_mappings[placeholder] = value[:40] + "..." if len(value) > 40 else value
            else:
                display_mappings[placeholder] = str(value)[:40]

    publish_event(task_id, SSEEventType.ANONYMIZATION.value, {
        "total_entities": total_entities,
        "entity_types": entity_types or {},
        "tool_calls_anonymized": tool_calls_anonymized,
        "mappings": display_mappings
    })


def publish_pending_input(task_id: str, question: str, options: list = None,
                          data: dict = None, editable_fields: list = None):
    """Publish pending input dialog request."""
    publish_event(task_id, SSEEventType.PENDING_INPUT.value, {
        "question": question,
        "options": options,
        "data": data,
        "editable_fields": editable_fields
    })


def publish_task_complete(task_id: str, status: str = "done", result: str = None,
                          input_tokens: int = None, output_tokens: int = None,
                          cost_usd: float = None, duration: float = None,
                          sub_agent_costs: dict = None, link_map: dict = None):
    """Publish task completion event."""
    publish_event(task_id, SSEEventType.TASK_COMPLETE.value, {
        "status": status,
        "result": result,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 4) if cost_usd else None,
        "duration": round(duration, 2) if duration else None,
        "sub_agent_costs": sub_agent_costs,
        "link_map": link_map  # V2 Link Placeholder System
    })


def publish_task_error(task_id: str, error: str):
    """Publish task error event."""
    publish_event(task_id, SSEEventType.TASK_ERROR.value, {
        "error": error
    })


def publish_task_cancelled(task_id: str):
    """Publish task cancelled event."""
    publish_event(task_id, SSEEventType.TASK_CANCELLED.value, {})


def publish_dev_context(task_id: str, total_tokens: int = 0, limit: int = 200000,
                        system_tokens: int = 0, user_tokens: int = 0, tool_tokens: int = 0,
                        iteration: int = 0, max_iterations: int = 0, tool_count: int = 0):
    """Publish developer context update (token stats, iteration info, tool count)."""
    publish_event(task_id, SSEEventType.DEV_CONTEXT.value, {
        "total_tokens": total_tokens,
        "limit": limit,
        "system_tokens": system_tokens,
        "user_tokens": user_tokens,
        "tool_tokens": tool_tokens,
        "iteration": iteration,
        "max_iterations": max_iterations,
        "tool_count": tool_count
    })
