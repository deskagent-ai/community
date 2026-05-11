# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Task Routes with SSE Streaming.

Provides endpoints for:
- GET /task/{id}/stream - SSE streaming for real-time updates
- GET /task/{id}/status - Status for reconnection/polling fallback
- POST /task/{id}/cancel - Cancel a running task
- POST /task/{id}/respond - Submit confirmation response
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Response, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..core import (
    get_task,
    update_task,
    tasks as _tasks,
    tasks_lock as _tasks_lock,
    get_queue,
    remove_queue,
    has_queue,
    SSEEvent,
    register_global_client,
    unregister_global_client,
    get_running_sessions,
    get_session_task_map,
)
from .. import interaction
from ai_agent import log
from ..skills import load_config
from ..services.discovery import get_agent_config, get_skill_config

try:
    import ai_agent
except ImportError:
    ai_agent = None

router = APIRouter()


class ConfirmationResponse(BaseModel):
    """Request body for confirmation response."""
    confirmed: bool
    data: Optional[dict] = None


# =============================================================================
# Global Task Events SSE (for running task badges)
# =============================================================================

def get_active_tasks_snapshot() -> dict:
    """Get snapshot of all currently running tasks.

    Returns dict with counts per task name for agents and skills,
    plus list of running session IDs for History panel status.
    """
    with _tasks_lock:
        agents = {}
        skills = {}

        for task_id, task in _tasks.items():
            # Skip completed tasks
            if task.get("status") in ("done", "error", "cancelled"):
                continue

            if task.get("agent"):
                name = task["agent"]
                agents[name] = agents.get(name, 0) + 1
            elif task.get("skill"):
                name = task["skill"]
                skills[name] = skills.get(name, 0) + 1

        return {
            "agents": agents,
            "skills": skills,
            "running_sessions": get_running_sessions(),
            "session_task_map": get_session_task_map()
        }


@router.get("/active")
async def get_active_tasks():
    """Get all currently active tasks (for debugging)."""
    return get_active_tasks_snapshot()


@router.get("/all")
async def get_all_tasks():
    """Get all tasks in memory (for debugging)."""
    with _tasks_lock:
        return {k: v for k, v in _tasks.items()}


@router.get("/events")
async def stream_global_task_events():
    """
    SSE endpoint for global task events (all running tasks).

    Used by WebUI to show pulsating badges on agent tiles when
    tasks are running in the background.

    Events:
    - active_tasks: Initial state with all running tasks (on connect)
    - task_started: A task was started
    - task_ended: A task was completed/failed/cancelled
    - ping: Keepalive (every 30s)
    """
    async def event_generator():
        queue = register_global_client()
        try:
            # Send initial state with all running tasks
            active = get_active_tasks_snapshot()
            yield {
                "event": "active_tasks",
                "data": json.dumps(active)
            }

            # Stream events from broadcast queue
            while True:
                try:
                    # 8s timeout - must be shorter than client health-check interval (10s)
                    # to prevent SSE disconnect during idle phases (e.g. pending_input dialogs)
                    event = await asyncio.wait_for(queue.get(), timeout=8.0)

                    yield {
                        "event": event.event,
                        "data": json.dumps(event.data)
                    }

                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield {
                        "event": "ping",
                        "data": json.dumps({})
                    }

        except asyncio.CancelledError:
            # Client disconnected
            log(f"[SSE] Global events client disconnected")
        finally:
            # Always unregister to prevent memory leaks
            unregister_global_client(queue)

    return EventSourceResponse(event_generator(), ping=0)


# =============================================================================
# SSE Streaming Endpoint (per-task)
# =============================================================================

@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    """
    SSE endpoint for real-time task updates.

    Events:
    - task_start: Initial task info
    - token: Streaming tokens (delta)
    - tool_call: Tool execution status
    - anonymization: PII stats update
    - pending_input: Confirmation dialog needed
    - task_complete: Task finished successfully
    - task_error: Task failed
    - task_cancelled: Task was cancelled
    - ping: Keepalive (every 30s)
    """
    async def event_generator():
        queue = get_queue(task_id)

        # If no queue exists, task might have completed before client connected
        if queue is None:
            task = get_task(task_id)
            if task is None:
                yield {
                    "event": "task_error",
                    "data": json.dumps({"error": "Task not found"})
                }
                return

            # Task exists but no queue - send final state
            yield {
                "event": "task_complete",
                "data": json.dumps({
                    "status": task.get("status", "done"),
                    "result": task.get("result"),
                    "input_tokens": task.get("input_tokens"),
                    "output_tokens": task.get("output_tokens"),
                    "cost_usd": task.get("cost_usd"),
                    "duration": task.get("duration"),
                    "sub_agent_costs": task.get("sub_agent_costs")
                })
            }
            return

        try:
            # Send initial task state
            task = get_task(task_id)
            if task:
                # Check if anonymization is enabled for this task
                # Use central decision function from anonymizer module
                config = load_config()
                anon_enabled = False

                task_name = task.get("agent") or task.get("skill") or ""
                task_type = "agent" if task.get("agent") else "skill"
                backend_name = task.get("ai_backend") or ""

                if task_name:
                    # Get configs for central decision
                    backends = config.get("ai_backends", {})
                    backend_config = backends.get(backend_name, {})

                    if task_type == "agent":
                        task_config = get_agent_config(task_name) or {}
                    else:
                        task_config = get_skill_config(task_name) or {}

                    # Use central anonymization decision
                    try:
                        from ai_agent.anonymizer import resolve_anonymization_setting
                        anon_enabled, _source = resolve_anonymization_setting(
                            config, backend_config, task_config, task_name, task_type, backend_name
                        )
                    except ImportError:
                        # Fallback if import fails
                        anon_enabled = config.get("anonymization", {}).get("enabled", False)

                yield {
                    "event": "task_start",
                    "data": json.dumps({
                        "task_id": task_id,
                        "model": task.get("model"),
                        "agent": task.get("agent"),
                        "skill": task.get("skill"),
                        "backend": task.get("ai_backend"),
                        "status": task.get("status"),
                        "anon_enabled": anon_enabled
                    })
                }

                # If task already has streaming content, send it
                if task.get("streaming"):
                    yield {
                        "event": "token",
                        "data": json.dumps({
                            "token": task["streaming"].get("content", ""),
                            "is_thinking": task["streaming"].get("is_thinking", False),
                            "accumulated_length": task["streaming"].get("length", 0)
                        })
                    }

            # Stream events from queue
            while True:
                try:
                    # 8s timeout - must be shorter than client health-check interval (10s)
                    # to prevent SSE disconnect during idle phases (e.g. pending_input dialogs)
                    event = await asyncio.wait_for(queue.get(), timeout=8.0)

                    if event.event == "pending_input":
                        log(f"[SSE] Yielding pending_input event for task {task_id}")

                    yield {
                        "event": event.event,
                        "data": json.dumps(event.data)
                    }

                    if event.event == "pending_input":
                        log(f"[SSE] pending_input yielded OK, continuing stream for task {task_id}")

                    # Stop streaming on terminal events
                    if event.event in ("task_complete", "task_error", "task_cancelled"):
                        log(f"[SSE] Task {task_id} stream ended: {event.event}")
                        break

                except asyncio.TimeoutError:
                    # Send keepalive ping
                    log(f"[SSE] Sending keepalive ping for task {task_id}")
                    yield {
                        "event": "ping",
                        "data": json.dumps({})
                    }

                    # Check if task is still running
                    task = get_task(task_id)
                    if task is None:
                        yield {
                            "event": "task_error",
                            "data": json.dumps({"error": "Task disappeared"})
                        }
                        break
                    elif task.get("status") in ("done", "error", "cancelled"):
                        # Task completed while we were waiting
                        yield {
                            "event": "task_complete",
                            "data": json.dumps({
                                "status": task.get("status"),
                                "result": task.get("result"),
                                "input_tokens": task.get("input_tokens"),
                                "output_tokens": task.get("output_tokens"),
                                "cost_usd": task.get("cost_usd"),
                                "duration": task.get("duration"),
                                "sub_agent_costs": task.get("sub_agent_costs")
                            })
                        }
                        break

        except asyncio.CancelledError:
            # Client disconnected
            log(f"[SSE] Client disconnected from task {task_id}")
        finally:
            # Cleanup queue if we were the only consumer
            # Note: Keep queue for a bit in case client reconnects
            pass

    return EventSourceResponse(event_generator(), ping=0)


# =============================================================================
# Status Endpoint (Polling Fallback)
# =============================================================================

@router.get("/{task_id}/status")
async def get_task_status(task_id: str):
    """
    Get current task status.

    Used for:
    - Initial state fetch when SSE connects
    - Reconnection after network drop
    - Simple health checks

    Returns full task state including streaming content.
    """
    task = get_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # De-anonymize streaming content if we have mappings
    if task.get("streaming") and task["streaming"].get("content"):
        mappings = {}
        if task.get("anonymization"):
            mappings = task["anonymization"].get("mappings", {})
        if not mappings:
            mappings = interaction.get_anon_mappings(task_id)

        if mappings:
            content = task["streaming"]["content"]
            for placeholder, original in mappings.items():
                content = content.replace(placeholder, original)
            task["streaming"] = {**task["streaming"], "content": content}

    # Check for pending user confirmation
    pending = interaction.get_pending(task_id)
    if pending:
        task["pending_input"] = pending
        log(f"[Task {task_id}] Has pending confirmation")
    else:
        # Clear stale pending_input from task state (was stored by request_confirmation
        # but already consumed by submit_response)
        task.pop("pending_input", None)

    # Always include basic context info (iteration progress)
    # Full dev_context (prompts, tool_results) only in developer mode
    config = load_config()
    if ai_agent:
        dev_ctx = ai_agent.get_dev_context(task_id=str(task_id))
        if config.get("developer_mode", False):
            # Full context for developers
            task["dev_context"] = dev_ctx
        else:
            # Basic info for all users (iteration progress)
            task["dev_context"] = {
                "iteration": dev_ctx.get("iteration", 0),
                "max_iterations": dev_ctx.get("max_iterations", 0),
                "model": dev_ctx.get("model", "")
            }

    return {"task_id": task_id, **task}


# =============================================================================
# Task Control Endpoints
# =============================================================================

@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """
    Cancel a running task.

    Sets cancel_requested flag which is checked by streaming callbacks.
    """
    with _tasks_lock:
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="Task not found")

        _tasks[task_id]["cancel_requested"] = True
        log(f"[Task {task_id}] Cancellation requested")

    # Publish SSE event if queue exists
    from ..core import publish_task_cancelled
    publish_task_cancelled(task_id)

    return {"status": "ok", "cancelled": True}


@router.post("/{task_id}/round-ready")
async def round_ready(task_id: str):
    """
    Signal that the frontend SSE connection is ready for the next round.

    Called by the frontend after reconnecting SSE following a confirmation response.
    Unblocks the agent thread which is waiting in wait_for_round_ready().
    """
    # [063] T-R2: Validate task existence (consistent with other endpoints)
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    log(f"[Task {task_id}] Round-ready signal received from frontend")

    result = interaction.signal_round_ready(task_id)
    return {"status": "ok", "was_waiting": result}


@router.post("/{task_id}/respond")
async def respond_to_confirmation(task_id: str, body: ConfirmationResponse):
    """
    Submit response to a pending confirmation dialog.

    Args:
        confirmed: Whether user confirmed (True) or cancelled (False)
        data: Optional edited data from user
    """
    log(f"[Task {task_id}] Confirmation response: confirmed={body.confirmed}")

    if not body.confirmed:
        # User cancelled - also set cancel flag for task
        with _tasks_lock:
            if task_id in _tasks:
                _tasks[task_id]["cancel_requested"] = True

    if interaction.submit_response(task_id, body.confirmed, body.data or {}):
        # [058] Clear streaming content to prevent duplicate display on SSE reconnect
        # When client reconnects SSE after dialog, catch-up would re-send Round-1 content
        with _tasks_lock:
            if task_id in _tasks:
                _tasks[task_id]["streaming"] = None
                log(f"[Task {task_id}] Cleared streaming state for next round")
        return {"status": "ok", "confirmed": body.confirmed}
    else:
        raise HTTPException(status_code=400, detail="No pending confirmation")


# =============================================================================
# Legacy Polling Endpoint (for backward compatibility)
# =============================================================================

@router.get("/{task_id}")
async def get_task_legacy(task_id: str):
    """
    Legacy task polling endpoint.

    Maintains backward compatibility with existing frontend.
    Redirects to /status behavior.
    """
    return await get_task_status(task_id)
