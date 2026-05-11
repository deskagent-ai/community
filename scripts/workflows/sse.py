# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Workflow SSE Utilities
======================
Shared SSE broadcast helper for all workflow modules.
"""

# Import system_log for logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg): pass


def broadcast_sse(event_type: str, data: dict, context: str = "Workflow"):
    """Broadcast SSE event with lazy import to get the correct module instance.

    Args:
        event_type: Type of SSE event (e.g., "workflow_started", "workflow_step")
        data: Event data dictionary
        context: Log message context (default: "Workflow")
    """
    try:
        from assistant.core.sse_manager import broadcast_global_event, get_event_loop
        if get_event_loop() is None:
            system_log(f"[{context}] SSE event loop not set yet: {event_type}")
            return
        broadcast_global_event(event_type, data)
    except ImportError as e:
        system_log(f"[{context}] SSE import failed: {e}")
