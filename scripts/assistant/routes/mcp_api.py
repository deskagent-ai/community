# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI MCP API Routes
======================
API endpoints for MCP servers running in separate subprocesses (Nuitka builds).

These endpoints provide access to compiled functionality that MCPs cannot import directly:
- Config loading (apis.json + system.json)
- Path resolution (workspace, config, temp, exports, data, logs)
- Logging (system.log)
- Task context (for nested agent calls)
- Session-based anonymization (for parallel agents)

Architecture:
    DeskAgent.exe (compiled) <-- HTTP --> MCP Subprocess (embedded Python)

    The compiled EXE contains all business logic. MCPs call these API endpoints
    through the _mcp_api.py stub module, which contains no business logic.
"""

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

# Session TTL configuration (24 hours in seconds)
SESSION_TTL = 86400

# Module-level session storage for anonymization contexts
# Each session_id gets its own AnonymizationContext for parallel agent isolation
_anon_sessions: dict = {}

# Module-level session storage for link registrations (V2 Link Placeholder System)
# Each session_id gets its own link_ref -> web_link mapping
_link_sessions: dict[str, dict[str, str]] = {}

# Track session creation timestamps for TTL-based cleanup
_session_timestamps: dict[str, float] = {}


def _cleanup_old_sessions():
    """Remove sessions older than SESSION_TTL (24 hours).

    Called automatically when new sessions are created to prevent memory leaks.
    """
    now = time.time()
    expired = [sid for sid, ts in _session_timestamps.items()
               if now - ts > SESSION_TTL]

    for sid in expired:
        _anon_sessions.pop(sid, None)
        _link_sessions.pop(sid, None)
        _session_timestamps.pop(sid, None)

    if expired:
        try:
            from ai_agent.base import system_log
            system_log(f"[MCP API] Cleaned up {len(expired)} expired sessions")
        except ImportError:
            pass

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class LogRequest(BaseModel):
    """Request body for POST /api/mcp/log."""
    message: str
    level: str = "info"


class AnonymizeRequest(BaseModel):
    """Request body for POST /api/mcp/anonymize."""
    session_id: str
    text: str
    lang: str = "de"


class AnonymizeResponse(BaseModel):
    """Response body for POST /api/mcp/anonymize."""
    anonymized: str
    session_id: str


class DeanonymizeRequest(BaseModel):
    """Request body for POST /api/mcp/deanonymize."""
    session_id: str
    text: str


class DeanonymizeResponse(BaseModel):
    """Response body for POST /api/mcp/deanonymize."""
    text: str
    session_id: str


class AnonymizerStatusResponse(BaseModel):
    """Response body for GET /api/mcp/anonymizer/status."""
    available: bool
    reason: Optional[str] = None


class TaskContextResponse(BaseModel):
    """Response body for GET /api/mcp/task_context."""
    task_id: Optional[str] = None
    parent_task_id: Optional[str] = None


class PathsResponse(BaseModel):
    """Response body for GET /api/mcp/paths."""
    workspace_dir: str
    config_dir: str
    temp_dir: str
    exports_dir: str
    data_dir: str
    logs_dir: str


class ToolCallLogRequest(BaseModel):
    """Request body for POST /api/mcp/log_tool_call."""
    tool_name: str
    direction: str  # "CALL" or "RESULT"
    content: str
    is_anonymized: bool = True


class RegisterLinkRequest(BaseModel):
    """Request body for POST /api/mcp/register-link."""
    session_id: str
    link_ref: str
    web_link: str


class RegisterLinkResponse(BaseModel):
    """Response body for POST /api/mcp/register-link."""
    status: str
    link_ref: str


class LinkMapResponse(BaseModel):
    """Response body for GET /api/mcp/links/{session_id}."""
    session_id: str
    link_map: dict[str, str]


# =============================================================================
# GET /api/mcp/config
# =============================================================================

@router.get("/config")
async def get_mcp_config() -> dict:
    """
    Get merged configuration (apis.json + system.json).

    Returns the complete config dict that MCPs need for API keys,
    service settings, and feature flags.

    Returns:
        Dict containing merged configuration from all config files.
    """
    try:
        from paths import load_config
        config = load_config()
        return config
    except Exception as e:
        # Return empty dict on error - MCPs should handle missing config gracefully
        from ai_agent.base import system_log
        system_log(f"[MCP API] Error loading config: {e}")
        return {}


# =============================================================================
# GET /api/mcp/paths
# =============================================================================

@router.get("/paths", response_model=PathsResponse)
async def get_mcp_paths() -> PathsResponse:
    """
    Get base paths for workspace, config, temp, exports, data, and logs.

    These paths are resolved at runtime based on DESKAGENT_* environment
    variables and platform-specific defaults.

    Returns:
        PathsResponse with all directory paths as strings.
    """
    try:
        from paths import (
            get_workspace_dir,
            get_config_dir,
            get_temp_dir,
            get_exports_dir,
            get_data_dir,
            get_logs_dir,
        )

        return PathsResponse(
            workspace_dir=str(get_workspace_dir()),
            config_dir=str(get_config_dir()),
            temp_dir=str(get_temp_dir()),
            exports_dir=str(get_exports_dir()),
            data_dir=str(get_data_dir()),
            logs_dir=str(get_logs_dir()),
        )
    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] Error getting paths: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# POST /api/mcp/log
# =============================================================================

@router.post("/log")
async def post_mcp_log(body: LogRequest) -> dict:
    """
    Write log message to system.log.

    Used by MCP servers to log without importing ai_agent module.

    Args:
        body: LogRequest with message and optional level.

    Returns:
        Status dict indicating success.
    """
    try:
        from ai_agent.base import system_log

        # Format message with level prefix if not info
        message = body.message
        if body.level != "info":
            message = f"[{body.level.upper()}] {message}"

        system_log(message)
        return {"status": "ok"}
    except Exception as e:
        # Logging should never fail visibly - swallow errors
        return {"status": "error", "message": str(e)}


# =============================================================================
# GET /api/mcp/task_context
# =============================================================================

@router.get("/task_context", response_model=TaskContextResponse)
async def get_mcp_task_context() -> TaskContextResponse:
    """
    Get current task context (for nested agent calls).

    When an agent calls desk_run_agent() to start a nested agent,
    this endpoint provides the parent task_id for workflow tracking.

    Returns:
        TaskContextResponse with task_id (or null if no task running).
    """
    try:
        from ai_agent.task_context import get_task_context_or_none

        ctx = get_task_context_or_none()
        if ctx and ctx.task_id:
            return TaskContextResponse(
                task_id=ctx.task_id,
                parent_task_id=None  # Could be extended for deeper nesting
            )
        return TaskContextResponse(task_id=None)
    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] Error getting task context: {e}")
        return TaskContextResponse(task_id=None)


# =============================================================================
# POST /api/mcp/anonymize
# =============================================================================

@router.post("/anonymize", response_model=AnonymizeResponse)
async def post_mcp_anonymize(body: AnonymizeRequest) -> AnonymizeResponse:
    """
    Anonymize text with session-based context.

    Each session_id gets its own AnonymizationContext, ensuring:
    - Parallel agents have isolated mappings
    - Multiple tool calls within an agent use consistent placeholders
    - "Max Mustermann" becomes <PERSON_1> consistently within a session

    The response includes metadata in the format:
    <!--ANON:total|new|PERSON:2,EMAIL:1|base64_mappings-->

    This metadata is parsed by claude_agent_sdk.py to track tool_calls_anonymized.

    Args:
        body: AnonymizeRequest with session_id, text, and lang.

    Returns:
        AnonymizeResponse with anonymized text (including metadata) and session_id.
    """
    import base64
    import json

    try:
        from ai_agent.anonymizer import (
            AnonymizationContext,
            anonymize_with_context,
            is_available,
        )
        from paths import load_config

        # Check if anonymization is available
        if not is_available():
            # Return original text if anonymizer not available
            return AnonymizeResponse(
                anonymized=body.text,
                session_id=body.session_id
            )

        # Get or create session context
        if body.session_id not in _anon_sessions:
            # Cleanup old sessions before creating new one
            _cleanup_old_sessions()
            _anon_sessions[body.session_id] = AnonymizationContext()
            _session_timestamps[body.session_id] = time.time()

        context = _anon_sessions[body.session_id]
        config = load_config()

        # Track existing mappings count BEFORE anonymization
        existing_count = len(context.mappings)
        existing_mappings = set(context.mappings.keys())

        # Update language in config for this call
        anon_config = config.get("anonymization", {})
        anon_config["language"] = body.lang
        config["anonymization"] = anon_config

        # Anonymize with session context
        anonymized_text, updated_context = anonymize_with_context(
            body.text, config, context
        )

        # Store updated context
        _anon_sessions[body.session_id] = updated_context

        # Calculate stats for metadata
        total_entities = len(updated_context.mappings)
        new_entities = total_entities - existing_count

        # Build entity type summary from counters (e.g., "PERSON:2,EMAIL:1")
        entity_parts = []
        for entity_type, count in sorted(updated_context.counters.items()):
            entity_parts.append(f"{entity_type}:{count}")
        entity_summary = ",".join(entity_parts)

        # Get only NEW mappings for this call (for de-anonymization)
        new_mappings = {
            k: v for k, v in updated_context.mappings.items()
            if k not in existing_mappings
        }

        # Base64-encode the new mappings
        mappings_json = json.dumps(new_mappings, ensure_ascii=False)
        mappings_b64 = base64.b64encode(mappings_json.encode('utf-8')).decode('ascii')

        # Append metadata comment if any entities were found
        # Format: <!--ANON:total|new|entity_summary|base64_mappings-->
        if total_entities > 0:
            metadata = f"\n<!--ANON:{total_entities}|{new_entities}|{entity_summary}|{mappings_b64}-->"
            anonymized_text += metadata

        return AnonymizeResponse(
            anonymized=anonymized_text,
            session_id=body.session_id
        )

    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] Anonymization error: {e}")
        # Return original text on error
        return AnonymizeResponse(
            anonymized=body.text,
            session_id=body.session_id
        )


# =============================================================================
# POST /api/mcp/deanonymize
# =============================================================================

@router.post("/deanonymize", response_model=DeanonymizeResponse)
async def post_mcp_deanonymize(body: DeanonymizeRequest) -> DeanonymizeResponse:
    """
    De-anonymize text using session-based context.

    Restores original PII values using the mappings stored in the session.

    Args:
        body: DeanonymizeRequest with session_id and text.

    Returns:
        DeanonymizeResponse with restored text and session_id.
    """
    try:
        from ai_agent.anonymizer import deanonymize

        # Get session context
        if body.session_id not in _anon_sessions:
            # No session found - return text as-is
            return DeanonymizeResponse(
                text=body.text,
                session_id=body.session_id
            )

        context = _anon_sessions[body.session_id]

        # De-anonymize using session mappings
        restored_text = deanonymize(body.text, context)

        return DeanonymizeResponse(
            text=restored_text,
            session_id=body.session_id
        )

    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] De-anonymization error: {e}")
        # Return original text on error
        return DeanonymizeResponse(
            text=body.text,
            session_id=body.session_id
        )


# =============================================================================
# DELETE /api/mcp/session/{session_id}
# =============================================================================

@router.delete("/session/{session_id}")
async def delete_mcp_session(session_id: str) -> dict:
    """
    Delete session data (cleanup after agent completes).

    Should be called when an agent finishes to free memory.

    Args:
        session_id: The session ID to clean up.

    Returns:
        Status dict indicating success.
    """
    try:
        deleted = False
        if session_id in _anon_sessions:
            del _anon_sessions[session_id]
            deleted = True
        if session_id in _link_sessions:
            del _link_sessions[session_id]
            deleted = True
        if session_id in _session_timestamps:
            del _session_timestamps[session_id]
            deleted = True

        if deleted:
            return {"status": "ok", "message": f"Session {session_id} deleted"}
        return {"status": "ok", "message": f"Session {session_id} not found (already cleaned up)"}
    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] Session cleanup error: {e}")
        return {"status": "error", "message": str(e)}


# =============================================================================
# GET /api/mcp/anonymizer/status
# =============================================================================

@router.get("/anonymizer/status", response_model=AnonymizerStatusResponse)
async def get_anonymizer_status() -> AnonymizerStatusResponse:
    """
    Check if anonymization service is available.

    Returns availability status and reason if unavailable.

    Returns:
        AnonymizerStatusResponse with available flag and optional reason.
    """
    try:
        from ai_agent.anonymizer import is_available

        available = is_available()
        if available:
            return AnonymizerStatusResponse(available=True)
        else:
            return AnonymizerStatusResponse(
                available=False,
                reason="Presidio/spaCy not available"
            )
    except ImportError as e:
        return AnonymizerStatusResponse(
            available=False,
            reason=f"Import error: {e}"
        )
    except Exception as e:
        return AnonymizerStatusResponse(
            available=False,
            reason=f"Error: {e}"
        )


# =============================================================================
# POST /api/mcp/log_tool_call
# =============================================================================

@router.post("/log_tool_call")
async def post_mcp_log_tool_call(body: ToolCallLogRequest) -> dict:
    """
    Log a tool call to anon_messages.log.

    Used by MCP proxy to log tool calls and results in the anonymization log.

    Args:
        body: ToolCallLogRequest with tool_name, direction, content, and is_anonymized.

    Returns:
        Status dict indicating success.
    """
    try:
        from ai_agent.base import log_tool_call

        log_tool_call(
            tool_name=body.tool_name,
            direction=body.direction,
            content=body.content,
            is_anonymized=body.is_anonymized
        )
        return {"status": "ok"}
    except Exception as e:
        # Logging should never fail visibly - swallow errors
        return {"status": "error", "message": str(e)}


# =============================================================================
# POST /api/mcp/register-link
# =============================================================================

@router.post("/register-link", response_model=RegisterLinkResponse)
async def post_register_link(body: RegisterLinkRequest) -> RegisterLinkResponse:
    """
    Register a link_ref -> web_link mapping for a session.

    Part of the V2 Link Placeholder System. MCPs call this to register URLs
    without exposing them to the AI. The AI only sees {{LINK:ref}} placeholders.
    URLs are resolved at display time.

    Args:
        body: RegisterLinkRequest with session_id, link_ref, and web_link.

    Returns:
        RegisterLinkResponse confirming registration.
    """
    try:
        from ai_agent.base import system_log

        # Initialize session if needed
        if body.session_id not in _link_sessions:
            _link_sessions[body.session_id] = {}
            system_log(f"[LinkRegistry API] New session: {body.session_id}")

        # Register the link (idempotent - same ref overwrites)
        _link_sessions[body.session_id][body.link_ref] = body.web_link
        system_log(f"[LinkRegistry API] Registered {body.link_ref} for session {body.session_id} (total: {len(_link_sessions[body.session_id])})")

        return RegisterLinkResponse(
            status="ok",
            link_ref=body.link_ref
        )
    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] Register link error: {e}")
        return RegisterLinkResponse(
            status="error",
            link_ref=body.link_ref
        )


# =============================================================================
# GET /api/mcp/links/{session_id}
# =============================================================================

@router.get("/links/{session_id}", response_model=LinkMapResponse)
async def get_session_links(session_id: str) -> LinkMapResponse:
    """
    Get all registered links for a session.

    Used by the display layer to resolve {{LINK:ref}} placeholders to URLs.

    Args:
        session_id: The session ID to get links for.

    Returns:
        LinkMapResponse with the link_map dict.
    """
    link_map = _link_sessions.get(session_id, {})
    return LinkMapResponse(
        session_id=session_id,
        link_map=link_map
    )


# =============================================================================
# Helper functions for internal use
# =============================================================================

def get_link_map_for_session(session_id: str) -> dict[str, str]:
    """
    Get link map for a session (internal API for agent runner).

    Called when saving session to include link_map in stored data.
    """
    from ai_agent.base import system_log
    link_map = _link_sessions.get(session_id, {})
    system_log(f"[LinkRegistry] get_link_map_for_session({session_id}): {len(link_map)} entries, sessions={list(_link_sessions.keys())}")
    return link_map


def clear_link_session(session_id: str) -> None:
    """
    Clear links for a session (internal API for cleanup).

    Called when agent completes to free memory.
    """
    _link_sessions.pop(session_id, None)


# =============================================================================
# POST /api/mcp/refresh-prerequisites
# =============================================================================

@router.post("/refresh-prerequisites")
async def refresh_prerequisites_cache() -> dict:
    """
    Refresh the MCP prerequisites cache.

    Invalidates the cached is_configured() results for all MCPs,
    forcing a fresh check on the next prerequisites query.

    Use this when:
    - User completes OAuth authentication
    - User updates configuration
    - Prerequisites check shows stale results

    Returns:
        Status dict with refresh result.
    """
    try:
        from ai_agent.base import system_log
        from assistant.services.discovery import invalidate_mcp_config_cache

        # Clear all cached results
        invalidate_mcp_config_cache()
        system_log("[MCP API] Prerequisites cache refreshed")

        return {"status": "ok", "message": "Prerequisites cache cleared"}
    except Exception as e:
        from ai_agent.base import system_log
        system_log(f"[MCP API] Error refreshing prerequisites cache: {e}")
        return {"status": "error", "message": str(e)}
