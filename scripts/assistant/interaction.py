# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
User Interaction Handler
========================
Manages pending user confirmations for multi-turn agent workflows.

Usage:
1. Agent detects CONFIRMATION_NEEDED in output
2. Backend calls request_confirmation() - blocks until user responds
3. WebUI polls task, sees pending_input, shows dialog
4. User confirms/edits -> POST /task/{id}/respond
5. submit_response() unblocks the waiting request_confirmation()
6. Agent continues with confirmed data
"""

import threading
import time
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from ai_agent import log
from .skills import load_config


@dataclass
class PendingConfirmation:
    """A pending user confirmation request."""
    task_id: str
    question: str
    data: Dict[str, Any]
    session_id: str = None  # [046] Thread-safe session_id from Agent-Thread for parallel isolation
    editable_fields: list = field(default_factory=list)
    anon_mappings: Dict[str, str] = field(default_factory=dict)  # For de-anonymization
    on_cancel: str = "abort"  # "abort" = stop entirely, "continue" = continue without change
    on_cancel_message: str = ""  # Message to send to agent when user cancels (if on_cancel="continue")
    dialog_type: str = ""  # "question" for simple yes/no dialogs
    options: list = field(default_factory=list)  # Button options for question dialogs
    response: Optional[Dict[str, Any]] = None
    response_event: threading.Event = field(default_factory=threading.Event)  # Event-based signaling
    timestamp: float = field(default_factory=time.time)


# Global state
_pending: Dict[str, PendingConfirmation] = {}
_lock = threading.Lock()

# [063] Round-ready handshake for multi-round confirmation dialogs
# After a confirmation, the backend waits for the frontend to signal
# that its SSE connection is re-established before starting Round 2.
_round_ready: Dict[str, threading.Event] = {}
_round_ready_lock = threading.Lock()
# IMPORTANT: Lock hierarchy (deadlock prevention!)
# ALWAYS acquire in this order: _lock -> _round_ready_lock
# NEVER the other way around!


def prepare_round_ready(task_id: str):
    """Prepare a round-ready event for the next confirmation round.

    Called by submit_response() BEFORE response_event.set() unblocks
    the agent thread, so the event is ready when the agent continues.
    """
    with _round_ready_lock:
        _round_ready[task_id] = threading.Event()
        log(f"[Interaction] Round-ready event prepared for task {task_id}")


def wait_for_round_ready(task_id: str, timeout: float = 10.0) -> bool:
    """Wait for frontend to signal round-ready after SSE reconnect.

    Called by agents.py after confirmation received, before starting Round 2.
    Returns True if signal received, False on timeout.
    Uses try-finally to guarantee cleanup even on exceptions.

    Args:
        task_id: The task ID to wait for
        timeout: Maximum seconds to wait (default 10s)

    Returns:
        True if round-ready signal received, False on timeout
    """
    with _round_ready_lock:
        event = _round_ready.get(task_id)

    if not event:
        log(f"[Interaction] No round-ready event for task {task_id}, proceeding immediately")
        return True

    try:
        log(f"[Interaction] Waiting for round-ready signal (timeout={timeout}s)...")
        result = event.wait(timeout=timeout)

        if result:
            log(f"[Interaction] Round-ready signal received for task {task_id}")
        else:
            log(f"[Interaction] Round-ready TIMEOUT for task {task_id} - proceeding anyway")

        return result
    finally:
        # Cleanup even on exception (Memory Leak Prevention)
        with _round_ready_lock:
            _round_ready.pop(task_id, None)


def signal_round_ready(task_id: str) -> bool:
    """Signal that frontend is ready for the next round.

    Called by POST /task/{id}/round-ready endpoint after SSE reconnect.
    Returns True if there was a waiting event, False otherwise.

    Args:
        task_id: The task ID to signal

    Returns:
        True if a waiting event was found and signaled, False otherwise
    """
    with _round_ready_lock:
        event = _round_ready.get(task_id)

    if event:
        event.set()
        log(f"[Interaction] Round-ready signaled for task {task_id}")
        return True

    log(f"[Interaction] No round-ready event waiting for task {task_id}")
    return False


def _get_confirmation_timeout() -> int:
    """Get confirmation timeout from config, default 1 hour."""
    try:
        config = load_config()
        return config.get("interaction", {}).get("confirmation_timeout", 3600)
    except Exception:
        return 3600  # Default: 1 hour


def request_confirmation(task_id: str, question: str, data: dict,
                         editable_fields: list = None, timeout: int = None,
                         anon_mappings: dict = None, on_cancel: str = "abort",
                         on_cancel_message: str = "", dialog_type: str = "",
                         options: list = None) -> dict:
    """
    Request user confirmation. Blocks until user responds or timeout.

    Args:
        task_id: The task requesting confirmation
        question: Question to display to user
        data: Data to show (can be edited by user)
        editable_fields: Which fields the user can edit (default: all)
        timeout: Max seconds to wait (default: from config, fallback 1 hour)
        anon_mappings: Anonymization mappings {placeholder: original} for de-anonymization
        on_cancel: What to do when user cancels: "abort" (stop agent) or "continue" (skip this step)
        on_cancel_message: Message to pass to agent when user cancels and on_cancel="continue"
        dialog_type: "question" for simple yes/no dialogs, "" for confirmation with form
        options: Button options for question dialogs [{"value": "yes", "label": "Ja"}, ...]

    Returns:
        {"confirmed": True, "data": {...}} on success
        {"confirmed": False, "on_cancel": "...", "on_cancel_message": "..."} on cancel/timeout
    """
    # Use configured timeout if not explicitly provided
    if timeout is None:
        timeout = _get_confirmation_timeout()

    log(f"[Interaction] Requesting confirmation for task {task_id} (timeout: {timeout}s)")
    log(f"[Interaction] Question: {question}")
    log(f"[Interaction] Data: {json.dumps(data, ensure_ascii=False)}")
    log(f"[Interaction] On cancel: {on_cancel}")
    if dialog_type:
        log(f"[Interaction] Dialog type: {dialog_type}")
    if on_cancel_message:
        log(f"[Interaction] On cancel message: {on_cancel_message[:100]}...")
    if anon_mappings:
        log(f"[Interaction] Anonymization mappings available: {len(anon_mappings)} entries")

    # [046] Extract session_id from TaskContext (available in Agent-Thread)
    _session_id = None
    try:
        from ai_agent.task_context import get_task_context_or_none
        ctx = get_task_context_or_none()
        _session_id = ctx.session_id if ctx else None
        if _session_id:
            log(f"[Interaction] session_id from TaskContext: {_session_id}")
    except ImportError:
        pass

    with _lock:
        _pending[task_id] = PendingConfirmation(
            task_id=task_id,
            question=question,
            data=data,
            session_id=_session_id,  # [046] Store for submit_response() in HTTP-Thread
            editable_fields=editable_fields or list(data.keys()),
            anon_mappings=anon_mappings or {},
            on_cancel=on_cancel,
            on_cancel_message=on_cancel_message,
            dialog_type=dialog_type,
            options=options or []
        )

    # FIX [051]: Set task status to "pending_input" so sync polling clients
    # (desk_run_agent_sync, desk_send_prompt) detect the dialog instead of timing out
    try:
        from assistant.core.state import update_task
        update_task(task_id, status="pending_input", pending_input={
            "question": question,
            "dialog_type": dialog_type,
            "options": options or []
        })
        log(f"[Interaction] Set task {task_id} status to pending_input")
    except Exception as e:
        log(f"[Interaction] Could not set pending_input status: {e}")

    # Store question as assistant turn for history (with dialog metadata for [060])
    # Use lazy import to avoid circular imports
    try:
        from assistant.core.state import add_turn_to_session
        question_text = f"❓ {question}"
        # [060] Append dialog metadata for rich history rendering
        dialog_meta = {
            "type": dialog_type or "confirmation",
            "question": question,
            "data": data,
            "options": options or [],
            "editable_fields": editable_fields or list(data.keys())
        }
        question_text += f"\n---DIALOG_META---\n{json.dumps(dialog_meta, ensure_ascii=False)}"
        add_turn_to_session("assistant", question_text, task_id=task_id, session_id=_session_id)  # [046]
        log(f"[Interaction] Stored question as assistant turn (with dialog metadata)")
    except Exception as e:
        log(f"[Interaction] Could not store question turn: {e}")

    # Wait for response using Event (no polling)
    with _lock:
        pending = _pending.get(task_id)
        response_event = pending.response_event if pending else None

    if response_event and response_event.wait(timeout=timeout):
        # Event was set - response received
        # FIX [051]: Restore task status to "running" after user responds
        try:
            from assistant.core.state import update_task
            update_task(task_id, status="running")
            log(f"[Interaction] Restored task {task_id} status to running")
        except Exception as e:
            log(f"[Interaction] Could not restore running status: {e}")

        with _lock:
            if task_id in _pending:
                pending = _pending[task_id]
                response = pending.response.copy() if pending.response else {"confirmed": False}

                # Add on_cancel info when user cancels
                if not response.get("confirmed"):
                    response["on_cancel"] = pending.on_cancel
                    response["on_cancel_message"] = pending.on_cancel_message

                del _pending[task_id]
                log(f"[Interaction] Got response: confirmed={response.get('confirmed')}, on_cancel={response.get('on_cancel')}")
                return response

    # Timeout or no pending - clean up
    log(f"[Interaction] Timeout waiting for user response")
    with _lock:
        on_cancel = "abort"
        on_cancel_message = ""
        if task_id in _pending:
            on_cancel = _pending[task_id].on_cancel
            on_cancel_message = _pending[task_id].on_cancel_message
            del _pending[task_id]

    timeout_mins = timeout // 60
    return {
        "confirmed": False,
        "error": f"Timeout - keine Antwort vom User ({timeout_mins} Minuten)",
        "on_cancel": on_cancel,
        "on_cancel_message": on_cancel_message
    }


def _deanonymize_value(value: str, mappings: dict) -> str:
    """De-anonymize a single string value using the mappings."""
    if not isinstance(value, str) or not mappings:
        return value

    result = value
    for placeholder, original in mappings.items():
        if placeholder in result:
            result = result.replace(placeholder, original)
    return result


def _deanonymize_data(data: dict, mappings: dict) -> dict:
    """De-anonymize all string values in a dict using the mappings."""
    if not mappings:
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _deanonymize_value(value, mappings)
        elif isinstance(value, dict):
            result[key] = _deanonymize_data(value, mappings)
        else:
            result[key] = value
    return result


def get_pending(task_id: str) -> Optional[dict]:
    """
    Get pending confirmation for a task.

    Called by server.py when WebUI polls task status.
    Returns confirmation data if waiting, None otherwise.
    Data is de-anonymized before returning so user sees real values.
    """
    with _lock:
        if task_id in _pending:
            p = _pending[task_id]

            # [064] Guard: Don't return already-answered confirmations
            # Between submit_response() and request_confirmation() cleanup,
            # the entry still exists but response is already set → ghost dialog
            if p.response_event.is_set():
                log(f"[Interaction] Suppressing ghost-dialog for {task_id} (already answered)")
                return None

            # De-anonymize data for display to user
            display_data = _deanonymize_data(p.data, p.anon_mappings)
            display_question = _deanonymize_value(p.question, p.anon_mappings)

            if p.anon_mappings and display_data != p.data:
                log(f"[Interaction] De-anonymized {len(p.anon_mappings)} placeholders for display")

            result = {
                "question": display_question,
                "data": display_data,
                "editable_fields": p.editable_fields,
                "on_cancel": p.on_cancel  # "abort" or "continue"
            }

            # Include type and options for question dialogs
            if hasattr(p, 'dialog_type') and p.dialog_type:
                result["type"] = p.dialog_type
            if hasattr(p, 'options') and p.options:
                result["options"] = p.options

            return result
    return None


def get_anon_mappings(task_id: str) -> dict:
    """
    Get anonymization mappings for a task.

    Called by server.py to de-anonymize streaming content.
    Returns mappings dict or empty dict if none.
    """
    with _lock:
        if task_id in _pending:
            return _pending[task_id].anon_mappings or {}
    return {}


def submit_response(task_id: str, confirmed: bool, data: dict) -> bool:
    """
    Submit user response to a pending confirmation.

    Called by server.py when user clicks confirm/cancel in WebUI.
    Returns True if response was accepted, False if no pending request.
    """
    with _lock:
        if task_id in _pending:
            # [046] Read session_id from PendingConfirmation (HTTP-Thread has no TaskContext!)
            _session_id = _pending[task_id].session_id

            _pending[task_id].response = {
                "confirmed": confirmed,
                "data": data
            }

            # [063] Prepare round-ready event BEFORE set() wakes agent thread!
            # Only for confirmed responses (cancelled responses don't need Round 2)
            if confirmed:
                prepare_round_ready(task_id)

            _pending[task_id].response_event.set()  # Wake up waiting thread
            log(f"[Interaction] Response submitted: confirmed={confirmed}")

            # [060] Store user response as turn for history (ALL dialog types)
            try:
                from assistant.core.state import add_turn_to_session
                if data.get("response"):
                    # QUESTION_NEEDED: User hat Option gewählt
                    response_text = f"✓ {data['response']}"
                    response_meta = {"type": "question_response", "selected": data["response"]}
                elif confirmed:
                    # CONFIRMATION_NEEDED: User hat Daten bestätigt
                    response_text = "✓ Bestätigt"
                    response_meta = {"type": "confirmation_response", "confirmed": True,
                                    "data": {k: v for k, v in data.items() if not k.startswith('_')}}
                else:
                    # Abgebrochen
                    response_text = "✗ Abgebrochen"
                    response_meta = {"type": "confirmation_response", "confirmed": False}
                response_text += f"\n---DIALOG_META---\n{json.dumps(response_meta, ensure_ascii=False)}"
                add_turn_to_session("user", response_text, task_id=task_id, session_id=_session_id)  # [046]
                log(f"[Interaction] Stored response as user turn (session: {_session_id})")
            except Exception as e:
                log(f"[Interaction] Could not store response turn: {e}")

            return True

    log(f"[Interaction] No pending confirmation for task {task_id}")
    return False


def parse_confirmation_request(content: str) -> Optional[dict]:
    """
    Parse CONFIRMATION_NEEDED or QUESTION_NEEDED block from agent output.

    Expected formats:

    CONFIRMATION_NEEDED: (with form fields)
    {
      "question": "...",
      "data": {...},
      "editable_fields": [...]
    }

    QUESTION_NEEDED: (simple yes/no question)
    {
      "question": "...",
      "options": [{"value": "yes", "label": "Ja"}, {"value": "no", "label": "Nein"}]
    }

    Returns parsed dict or None if not found/invalid.
    """
    # Check for either marker
    is_question = "QUESTION_NEEDED" in content
    is_confirmation = "CONFIRMATION_NEEDED" in content

    if not is_question and not is_confirmation:
        return None

    marker = "QUESTION_NEEDED" if is_question else "CONFIRMATION_NEEDED"
    log(f"[Interaction] Found {marker} in content, attempting to parse...")

    try:
        # Find the start of the block
        idx = content.find(marker)
        if idx < 0:
            return None

        # Extract text before the marker (preamble/preprompt)
        preamble = content[:idx].strip() if idx > 0 else ""

        # Skip past the marker and any following colon/whitespace
        rest = content[idx + len(marker):]
        rest = rest.lstrip(":").lstrip()

        log(f"[Interaction] Rest starts with: {rest[:50]}...")

        # Find the opening brace
        brace_start = rest.find("{")
        if brace_start < 0:
            log("[Interaction] No opening brace found")
            return None

        rest = rest[brace_start:]

        # Find matching closing brace using depth counting
        depth = 0
        in_string = False
        escape = False
        json_end = -1

        for i, c in enumerate(rest):
            if escape:
                escape = False
                continue

            if c == "\\":
                escape = True
                continue

            if c == '"' and not escape:
                in_string = not in_string
                continue

            if in_string:
                continue

            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break

        if json_end < 0:
            log("[Interaction] No matching closing brace found")
            return None

        json_str = rest[:json_end]
        log(f"[Interaction] Extracted JSON ({len(json_str)} chars): {json_str[:100]}...")

        data = json.loads(json_str)

        # Validate and normalize
        if "question" not in data:
            log(f"[Interaction] Missing required field: question")
            return None

        # For QUESTION_NEEDED: set type and ensure empty data
        if is_question:
            data["type"] = "question"
            if "data" not in data:
                data["data"] = {}
            # Default options if not provided
            if "options" not in data:
                data["options"] = [
                    {"value": "yes", "label": "✅ Ja", "class": "btn-confirm"},
                    {"value": "no", "label": "❌ Nein", "class": "btn-cancel"}
                ]
            # Include preamble (text before the marker) for history
            if preamble:
                data["preamble"] = preamble
            log(f"[Interaction] Successfully parsed QUESTION_NEEDED request (preamble: {len(preamble)} chars)")
            return data

        # For CONFIRMATION_NEEDED: require data field
        if "data" in data:
            # Include preamble (text before the marker) for history
            if preamble:
                data["preamble"] = preamble
            log(f"[Interaction] Successfully parsed CONFIRMATION_NEEDED request (preamble: {len(preamble)} chars)")
            return data
        else:
            log(f"[Interaction] Missing required field: data")
            return None

    except json.JSONDecodeError as e:
        log(f"[Interaction] Failed to parse confirmation JSON: {e}")
    except Exception as e:
        log(f"[Interaction] Error parsing confirmation: {e}")
        import traceback
        log(f"[Interaction] Traceback: {traceback.format_exc()}")

    return None


def has_pending_confirmations() -> bool:
    """Check if there are any pending confirmations."""
    with _lock:
        return len(_pending) > 0


def cleanup_stale(max_age: int = 600):
    """Remove confirmations older than max_age seconds.

    Also cleans up orphaned round-ready events (e.g. after agent crash).
    """
    now = time.time()
    with _lock:
        stale = [tid for tid, p in _pending.items() if now - p.timestamp > max_age]
        for tid in stale:
            log(f"[Interaction] Cleaning up stale confirmation for task {tid}")
            del _pending[tid]

    # [063] Clean up orphaned round-ready events
    # Events that are not yet set after 60s cannot be valid anymore
    # (normal timeout is 10s, 60s is very generous)
    with _round_ready_lock:
        stale_rr = [tid for tid in _round_ready
                    if not _round_ready[tid].is_set()]
        for tid in stale_rr:
            log(f"[Interaction] Cleaning up stale round-ready event for {tid}")
            del _round_ready[tid]


def parse_continuation_request(content: str) -> Optional[dict]:
    """
    Parse CONTINUATION_NEEDED block from agent output.

    Expected format:
    CONTINUATION_NEEDED: {
      "message": "10 von 83 Dokumenten verarbeitet",
      "remaining": 73,
      "processed": 10
    }

    Args:
        content: The agent's response text

    Returns:
        Parsed dict with message (required), remaining (optional int), processed (optional int)
        or None if not found/invalid.
    """
    if "CONTINUATION_NEEDED" not in content:
        return None

    log(f"[Interaction] Found CONTINUATION_NEEDED in content, attempting to parse...")

    try:
        # Find the start of the block
        idx = content.find("CONTINUATION_NEEDED")
        if idx < 0:
            return None

        # Skip past the marker and any following colon/whitespace
        rest = content[idx + len("CONTINUATION_NEEDED"):]
        rest = rest.lstrip(":").lstrip()

        log(f"[Interaction] Rest starts with: {rest[:50]}...")

        # Find the opening brace
        brace_start = rest.find("{")
        if brace_start < 0:
            log("[Interaction] No opening brace found")
            return None

        rest = rest[brace_start:]

        # Find matching closing brace using depth counting
        depth = 0
        in_string = False
        escape = False
        json_end = -1

        for i, c in enumerate(rest):
            if escape:
                escape = False
                continue

            if c == "\\":
                escape = True
                continue

            if c == '"' and not escape:
                in_string = not in_string
                continue

            if in_string:
                continue

            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break

        if json_end < 0:
            log("[Interaction] No matching closing brace found")
            return None

        json_str = rest[:json_end]
        log(f"[Interaction] Extracted JSON ({len(json_str)} chars): {json_str[:100]}...")

        data = json.loads(json_str)

        # Validate: message is required
        if "message" not in data:
            log(f"[Interaction] Missing required field: message")
            return None

        # Ensure types are correct
        result = {
            "message": str(data["message"])
        }

        # Optional fields
        if "remaining" in data:
            try:
                result["remaining"] = int(data["remaining"])
            except (ValueError, TypeError):
                result["remaining"] = data["remaining"]

        if "processed" in data:
            try:
                result["processed"] = int(data["processed"])
            except (ValueError, TypeError):
                result["processed"] = data["processed"]

        log(f"[Interaction] Successfully parsed CONTINUATION_NEEDED: {result}")
        return result

    except json.JSONDecodeError as e:
        log(f"[Interaction] Failed to parse continuation JSON: {e}")
    except Exception as e:
        log(f"[Interaction] Error parsing continuation: {e}")
        import traceback
        log(f"[Interaction] Traceback: {traceback.format_exc()}")

    return None
