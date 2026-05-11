# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI History Routes
======================
Provides endpoints for chat session history management:
- GET /history/sessions - List sessions (paginated)
- GET /history/sessions/{id} - Get session with all turns
- POST /history/sessions/{id}/continue - Continue session
- POST /history/sessions/{id}/transfer - Transfer to different agent
- DELETE /history/sessions/{id} - Delete session
- POST /history/cleanup - Trigger cleanup of old sessions
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_agent import log

# Import session_store (will be created by parallel agent)
try:
    from .. import session_store
except ImportError:
    session_store = None

# Import state functions for session continuation
try:
    from ..core.state import load_session_for_continue
except ImportError:
    load_session_for_continue = None

router = APIRouter(prefix="/history", tags=["history"])


# =============================================================================
# Request/Response Models
# =============================================================================

class TransferRequest(BaseModel):
    """Request body for session transfer."""
    target_agent: str


# =============================================================================
# Session List & Details
# =============================================================================

@router.get("/sessions")
async def get_sessions(
    limit: int = 20,
    offset: int = 0,
    agent: Optional[str] = None,
    status: Optional[str] = None
):
    """
    List sessions (paginated).

    Args:
        limit: Maximum number of sessions to return (default: 20)
        offset: Number of sessions to skip (default: 0)
        agent: Filter by agent name (optional)
        status: Filter by status: 'active' or 'completed' (optional)

    Returns:
        sessions: List of session objects (without turns)
        total: Total number of sessions matching filter
        limit: Applied limit
        offset: Applied offset
    """
    if session_store is None:
        return {"sessions": [], "total": 0, "limit": limit, "offset": offset}

    sessions = session_store.get_sessions(
        limit=limit,
        offset=offset,
        agent_name=agent,
        status=status
    )
    stats = session_store.get_stats()

    return {
        "sessions": sessions,
        "total": stats.get("total_sessions", 0),
        "total_turns": stats.get("total_turns", 0),
        "total_tokens": stats.get("total_tokens", 0),
        "total_cost_usd": stats.get("total_cost_usd", 0.0),
        "limit": limit,
        "offset": offset
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Get session with all turns.

    Args:
        session_id: The session ID to retrieve

    Returns:
        Full session object including all turns

    Raises:
        404: Session not found
    """
    if session_store is None:
        raise HTTPException(status_code=404, detail="Session store not available")

    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


# =============================================================================
# Session Actions
# =============================================================================

@router.post("/sessions/{session_id}/continue")
async def continue_session(session_id: str):
    """
    Continue session - loads session into state and returns context for frontend.

    Sets the session as active in server state and returns context
    for injecting into prompts.

    Args:
        session_id: The session ID to continue

    Returns:
        agent_name: Original agent name
        backend: Original backend
        context: Formatted conversation context for injection
        original_session_id: Reference to original session

    Raises:
        404: Session not found
    """
    if session_store is None:
        raise HTTPException(status_code=404, detail="Session store not available")

    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Load session into server state (sets _current_session_id, loads history)
    context = None
    if load_session_for_continue:
        context = load_session_for_continue(session_id)
    else:
        # Fallback: just get context without setting state
        context = session_store.get_session_context(session_id)

    log(f"[History] Continue session {session_id} ({session['agent_name']})")

    return {
        "agent_name": session["agent_name"],
        "backend": session["backend"],
        "model": session.get("model"),
        "context": context,
        "original_session_id": session_id,
        "sdk_session_id": session.get("sdk_session_id")  # FIX [039]: Include for resume
    }


@router.post("/sessions/{session_id}/transfer")
async def transfer_session(session_id: str, body: TransferRequest):
    """
    Transfer session context to different agent.

    Allows switching AI backend while preserving conversation context.
    Example: Transfer from Gemini "chat" to Claude "chat_claude".

    Args:
        session_id: The session ID to transfer
        body: TransferRequest with target_agent name

    Returns:
        agent_name: New agent name (from request)
        context: Formatted conversation context for injection
        original_session_id: Reference to original session
        original_agent: Original agent name

    Raises:
        404: Session not found
    """
    if session_store is None:
        raise HTTPException(status_code=404, detail="Session store not available")

    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build context from previous turns
    context = session_store.get_session_context(session_id)

    log(f"[History] Transfer session {session_id} from {session['agent_name']} to {body.target_agent}")

    return {
        "agent_name": body.target_agent,
        "context": context,
        "original_session_id": session_id,
        "original_agent": session["agent_name"]
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """
    Delete session and all its turns.

    Args:
        session_id: The session ID to delete

    Returns:
        success: Whether deletion was successful
    """
    if session_store is None:
        return {"success": False, "error": "Session store not available"}

    success = session_store.delete_session(session_id)

    if success:
        log(f"[History] Deleted session {session_id}")

    return {"success": success}


@router.delete("/sessions")
async def delete_all_sessions():
    """
    Delete ALL sessions and turns.

    Returns:
        success: Whether deletion was successful
        deleted: Number of sessions deleted
    """
    if session_store is None:
        return {"success": False, "error": "Session store not available", "deleted": 0}

    deleted = session_store.delete_all_sessions()
    log(f"[History] Deleted all sessions ({deleted} total)")

    return {"success": True, "deleted": deleted}


# =============================================================================
# Maintenance
# =============================================================================

@router.post("/cleanup")
async def cleanup():
    """
    Trigger cleanup of old sessions.

    Performs two operations:
    1. Auto-completes stale sessions (inactive > timeout)
    2. Deletes oldest sessions if count exceeds max_sessions

    Returns:
        deleted_sessions: Number of sessions deleted
        completed_sessions: Number of sessions marked as completed
    """
    if session_store is None:
        return {"deleted_sessions": 0, "completed_sessions": 0}

    # Auto-complete stale sessions
    completed = session_store.auto_complete_stale_sessions()

    # Delete oldest if over limit
    deleted = session_store.cleanup_old_sessions()

    log(f"[History] Cleanup: {completed} completed, {deleted} deleted")

    return {
        "deleted_sessions": deleted,
        "completed_sessions": completed
    }


@router.get("/stats")
async def get_stats():
    """
    Get session statistics.

    Returns:
        total_sessions: Total number of sessions
        active_sessions: Number of active sessions
        total_turns: Total number of turns across all sessions
        total_tokens: Total tokens used
        total_cost_usd: Total cost in USD
    """
    if session_store is None:
        return {
            "total_sessions": 0,
            "active_sessions": 0,
            "total_turns": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0
        }

    return session_store.get_stats()
