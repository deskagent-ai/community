# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Streaming callbacks and de-anonymization for task execution.

This module provides:
- TaskCancelledException: Exception raised when a task is cancelled
- create_streaming_callback(): Creates callback for streaming updates with de-anonymization
- create_is_cancelled_callback(): Creates callback to check cancellation status
- _publish_sse_completion(): Publishes SSE completion events

CENTRAL de-anonymization point: All streaming content is de-anonymized here
before being stored in task state or published via SSE.
"""

import re
from typing import Callable, Optional, Dict, Any

# Import AI backend for system logging
try:
    import ai_agent
    system_log = ai_agent.system_log
except ImportError:
    system_log = lambda msg: None

# Import shared state - use relative import
from .state import tasks, tasks_lock
from ai_agent import log


class TaskCancelledException(Exception):
    """Raised when a task is cancelled by the user."""
    pass


def create_streaming_callback(task_id: str) -> Callable:
    """Creates a callback function for streaming updates.

    CENTRAL de-anonymization point for streaming content.
    All backends pass anon_mappings, this callback de-anonymizes before storing.

    Uses tasks_lock for thread-safe access to prevent race conditions
    between the streaming backend thread and the HTTP thread handling cancellation.

    Also publishes SSE events for real-time streaming to connected clients.

    Args:
        task_id: The task ID to update

    Returns:
        Callback function that accepts (token, is_thinking, full_response, anon_stats)
    """
    # Track last content for delta calculation (content, not just length!)
    last_content = [""]  # Use list for mutable closure
    system_log(f"[streaming] Creating callback for task {task_id}")

    # Set current task ID for SSE event publishing from AI backends
    try:
        import ai_agent
        ai_agent.set_current_task_id(task_id)
    except ImportError:
        pass

    def on_chunk(token, is_thinking, full_response, anon_stats=None):
        """Called for each streaming token.

        Args:
            token: The new token/text
            is_thinking: Whether this is thinking/tool content
            full_response: The full response so far
            anon_stats: Optional dict with {mappings, total_entities, entity_types, tool_calls_anonymized}
        """
        with tasks_lock:
            if task_id not in tasks:
                return  # Task was removed

            # Check if cancellation was requested FIRST (before updating streaming)
            if tasks[task_id].get("cancel_requested"):
                log(f"[Task {task_id}] Cancellation detected in streaming callback")
                system_log(f"[streaming] Task {task_id} cancellation detected")
                raise TaskCancelledException(f"Task {task_id} cancelled by user")

            # CENTRAL de-anonymization: Replace placeholders with real values
            display_response = full_response
            # Support both new format (full anon_stats) and legacy format (just mappings)
            mappings = anon_stats.get("mappings", {}) if isinstance(anon_stats, dict) and "mappings" in anon_stats else (anon_stats or {})
            if mappings:
                for placeholder, original in mappings.items():
                    display_response = display_response.replace(placeholder, original)

            tasks[task_id]["streaming"] = {
                "content": display_response,  # De-anonymized for display
                "is_thinking": is_thinking,
                "length": len(display_response)
            }

            # Store anonymization stats for live badge updates
            if anon_stats and isinstance(anon_stats, dict) and "mappings" in anon_stats:
                # New format: use full stats from SDK directly
                tasks[task_id]["anonymization"] = {
                    "mappings": anon_stats.get("mappings", {}),
                    "total_entities": anon_stats.get("total_entities", 0),
                    "entity_types": anon_stats.get("entity_types", {}),
                    "tool_calls_anonymized": anon_stats.get("tool_calls_anonymized", 0)
                }
            elif mappings:
                # Legacy format: calculate from mappings
                if "anonymization" not in tasks[task_id]:
                    tasks[task_id]["anonymization"] = {}
                tasks[task_id]["anonymization"]["mappings"] = mappings

                # Calculate live entity counts from mappings for badge display
                entity_types = {}
                for placeholder in mappings.keys():
                    # Extract type from placeholder - supports both [TYPE-N] and <TYPE_N> formats
                    match = re.match(r'[\[<]([A-Z_]+)[-_]\d+[\]>]', placeholder)
                    if match:
                        entity_type = match.group(1)
                        entity_types[entity_type] = entity_types.get(entity_type, 0) + 1

                tasks[task_id]["anonymization"]["total_entities"] = len(mappings)
                tasks[task_id]["anonymization"]["entity_types"] = entity_types

        # === SSE Event Publishing (outside lock for performance) ===
        try:
            from .sse_manager import publish_token, publish_content_sync, publish_anonymization, has_queue

            # Only publish if there's an SSE client connected
            if has_queue(task_id):
                prev_content = last_content[0]
                last_content[0] = display_response

                # Check if content was REPLACED (not just appended)
                # This happens when tool markers are updated: [Tool: name ...] -> [Tool: name | 0.5s]
                if display_response.startswith(prev_content):
                    # Normal append - send delta token
                    delta = display_response[len(prev_content):]
                    if delta:
                        publish_token(task_id, delta, is_thinking, len(display_response))
                elif prev_content and display_response != prev_content:
                    # Content was modified - send full content sync
                    system_log(f"[streaming] Content modified, sending content_sync (len={len(display_response)})")
                    publish_content_sync(task_id, display_response, is_thinking)
                elif not prev_content and display_response:
                    # First content - send as token
                    publish_token(task_id, display_response, is_thinking, len(display_response))

                # Publish anonymization update if stats changed
                # Support both new format (full anon_stats) and legacy format (just mappings)
                if anon_stats and isinstance(anon_stats, dict):
                    if anon_stats.get("total_entities", 0) > 0:
                        # New format: use full stats with mappings
                        publish_anonymization(
                            task_id,
                            anon_stats.get("total_entities", 0),
                            anon_stats.get("entity_types", {}),
                            anon_stats.get("tool_calls_anonymized", 0),
                            anon_stats.get("mappings", {})
                        )
                    elif "mappings" not in anon_stats and len(anon_stats) > 0:
                        # Legacy format: anon_stats IS the mappings dict
                        # Calculate entity types from placeholder keys
                        entity_types = {}
                        for placeholder in anon_stats.keys():
                            # Supports both [TYPE-N] and <TYPE_N> formats
                            match = re.match(r'[\[<]([A-Z_]+)[-_]\d+[\]>]', placeholder)
                            if match:
                                entity_type = match.group(1)
                                entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
                        if entity_types:
                            publish_anonymization(task_id, len(anon_stats), entity_types, 0, anon_stats)
        except ImportError:
            pass  # SSE not available (e.g., running with old http.server)
        except Exception as e:
            # Don't let SSE errors break streaming
            log(f"[SSE] Error publishing event: {e}")

    return on_chunk


def create_is_cancelled_callback(task_id: str) -> Callable[[], bool]:
    """Creates a callback that checks if the task is cancelled.

    Uses tasks_lock for thread-safe access.

    Args:
        task_id: The task ID to check

    Returns:
        Callback function that returns True if task is cancelled
    """
    def is_cancelled() -> bool:
        with tasks_lock:
            if task_id in tasks:
                return tasks[task_id].get("cancel_requested", False)
            return True  # Task removed = treat as cancelled
    return is_cancelled


def publish_sse_completion(task_id: str, status: str, result: str = None,
                           error: str = None, duration: float = None,
                           input_tokens: int = None, output_tokens: int = None,
                           cost_usd: float = None, sub_agent_costs: dict = None,
                           session_id: str = None) -> None:
    """Publish SSE completion event for a task.

    Called after updating task state to notify connected SSE clients.

    Args:
        task_id: The task ID
        status: Completion status ("done", "error", "cancelled")
        result: Optional result content (for "done" status)
        error: Optional error message (for "error" status)
        session_id: Optional session ID to retrieve link_map from registry
        duration: Optional task duration in seconds
        input_tokens: Optional input token count
        output_tokens: Optional output token count
        cost_usd: Optional cost in USD
        sub_agent_costs: Optional aggregated sub-agent costs
    """
    system_log(f"[streaming] publish_sse_completion called: task={task_id}, status={status}")

    # Clear current task ID for SSE event publishing
    try:
        import ai_agent
        ai_agent.set_current_task_id(None)
    except ImportError:
        pass

    try:
        from .sse_manager import (
            publish_task_complete, publish_task_error,
            publish_task_cancelled, has_queue
        )

        queue_exists = has_queue(task_id)
        system_log(f"[streaming] has_queue({task_id})={queue_exists}")

        if not queue_exists:
            system_log(f"[streaming] WARNING: No SSE queue for task {task_id}, cannot publish {status}")
            return  # No SSE client connected

        system_log(f"[streaming] Publishing SSE completion: task={task_id}, status={status}")

        # V2 Link Placeholder System: Get link_map from registry for this session
        link_map = None
        if status == "done" and session_id:
            try:
                from assistant.routes.mcp_api import get_link_map_for_session
                link_map = get_link_map_for_session(session_id)
                if link_map:
                    system_log(f"[streaming] Including link_map with {len(link_map)} entries")
            except ImportError:
                pass
            except Exception as lm_err:
                system_log(f"[streaming] Failed to get link_map: {lm_err}")

        if status == "done":
            publish_task_complete(
                task_id, status="done", result=result,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cost_usd=cost_usd, duration=duration,
                sub_agent_costs=sub_agent_costs,
                link_map=link_map
            )
            system_log(f"[streaming] publish_task_complete returned for task {task_id}")
        elif status == "error":
            publish_task_error(task_id, error or "Unknown error")
            system_log(f"[streaming] publish_task_error returned for task {task_id}")
        elif status == "cancelled":
            publish_task_cancelled(task_id)
            system_log(f"[streaming] publish_task_cancelled returned for task {task_id}")
    except ImportError as ie:
        system_log(f"[streaming] ImportError in publish_sse_completion: {ie}")
    except Exception as e:
        system_log(f"[streaming] ERROR in publish_sse_completion: {e}")
        log(f"[SSE] Error publishing completion: {e}")
