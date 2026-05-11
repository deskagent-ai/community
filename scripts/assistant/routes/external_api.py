# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
External API Router
====================
Limited API endpoints safe for external tool access.

Swagger UI: /api/external/docs
OpenAPI JSON: /api/external/openapi.json

Only includes read-only and safe endpoints:
- Discovery (agents, skills, backends)
- Status and health checks
- Cost tracking (read-only)
- Session history (read-only)
- Agent execution (with optional API key)
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..skills import load_config
from ai_agent import log

router = APIRouter()


# =============================================================================
# Optional API Key Authentication
# =============================================================================

def get_api_key_from_config() -> Optional[str]:
    """Get API key from system.json if configured."""
    config = load_config()
    api_config = config.get("api", {})
    return api_config.get("api_key")


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """Verify API key if external access requires it.

    Returns True if:
    - No API key is configured (open access)
    - API key matches configured value

    Raises HTTPException if API key is required but missing/invalid.
    """
    configured_key = get_api_key_from_config()

    # No key configured = open access
    if not configured_key:
        return True

    # Key configured but not provided
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Add X-API-Key header."
        )

    # Key mismatch
    if x_api_key != configured_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )

    return True


# =============================================================================
# Health & Status
# =============================================================================

@router.get("/status", summary="Health check", dependencies=[Depends(verify_api_key)])
async def get_status():
    """
    Health check endpoint.

    Returns server status and readiness state.
    """
    from ..app import is_startup_complete
    return {
        "status": "ok",
        "ready": is_startup_complete()
    }


@router.get("/version", summary="Version info", dependencies=[Depends(verify_api_key)])
async def get_version():
    """Get DeskAgent version information."""
    import updater
    return updater.get_local_version()


# =============================================================================
# Discovery
# =============================================================================

@router.get("/agents", summary="List agents", dependencies=[Depends(verify_api_key)])
async def list_agents():
    """
    List available agents.

    Returns list of agent names that can be executed.
    """
    from paths import get_agents_dir
    agents_dir = get_agents_dir()
    agents = [f.stem for f in agents_dir.glob("*.md")] if agents_dir.exists() else []
    return {"agents": agents}


@router.get("/skills", summary="List skills", dependencies=[Depends(verify_api_key)])
async def list_skills():
    """
    List available skills.

    Returns list of skill names.
    """
    from paths import get_skills_dir
    skills = [f.stem for f in get_skills_dir().glob("*.md")]
    return {"skills": skills}


@router.get("/backends", summary="List AI backends", dependencies=[Depends(verify_api_key)])
async def list_backends():
    """
    List available AI backends.

    Returns enabled backends with basic info (no API keys).
    """
    config = load_config()
    ai_backends = config.get("ai_backends", {})
    default_backend = config.get("default_ai", "claude")

    backends = []
    for name, backend_config in ai_backends.items():
        if backend_config.get("enabled", True):
            backends.append({
                "name": name,
                "type": backend_config.get("type", "unknown"),
                "model": backend_config.get("model", "")
            })

    return {
        "backends": backends,
        "default": default_backend,
        "count": len(backends)
    }


@router.get("/agents/{agent_name}/inputs", summary="Get agent inputs", dependencies=[Depends(verify_api_key)])
async def get_agent_inputs(agent_name: str):
    """
    Get input field definitions for an agent.

    Returns list of required/optional inputs for the agent.
    """
    from ..agents import get_agent_inputs as _get_agent_inputs
    inputs = _get_agent_inputs(agent_name)
    return {"inputs": inputs}


@router.get("/mcp/status", summary="MCP server status", dependencies=[Depends(verify_api_key)])
async def get_mcp_status():
    """
    Get status of installed MCP servers.

    Returns list of MCPs with installed/configured status.
    """
    from ..routes.system import _get_mcp_info
    from paths import DESKAGENT_DIR

    mcps = []
    mcp_dir = DESKAGENT_DIR / "mcp"

    if mcp_dir.exists():
        for item in sorted(mcp_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("_"):
                init_file = item / "__init__.py"
                installed = init_file.exists()
                mcp_info = _get_mcp_info(item.name) if installed else {"configured": False}

                mcps.append({
                    "name": item.name,
                    "installed": installed,
                    "configured": mcp_info.get("configured", False)
                })

    return {"mcps": mcps}


# =============================================================================
# Costs (Read-only)
# =============================================================================

@router.get("/costs", summary="Cost summary", dependencies=[Depends(verify_api_key)])
async def get_costs():
    """
    Get daily/monthly cost summary.

    Returns aggregated costs by day and month.
    """
    from .. import cost_tracker
    return cost_tracker.get_summary()


@router.get("/costs/full", summary="Detailed costs", dependencies=[Depends(verify_api_key)])
async def get_costs_full():
    """
    Get detailed cost breakdown by backend.

    Returns full cost history with per-backend breakdown.
    """
    from .. import cost_tracker
    return cost_tracker.get_costs()


# =============================================================================
# History (Read-only)
# =============================================================================

@router.get("/history/sessions", summary="List sessions", dependencies=[Depends(verify_api_key)])
async def get_sessions(
    limit: int = 20,
    offset: int = 0,
    agent: Optional[str] = None,
    status: Optional[str] = None
):
    """
    List chat sessions (paginated).

    - **limit**: Max sessions to return (default 20)
    - **offset**: Pagination offset
    - **agent**: Filter by agent name
    - **status**: Filter by "active" or "completed"
    """
    try:
        from .. import session_store
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
            "limit": limit,
            "offset": offset
        }
    except ImportError:
        return {"sessions": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/history/sessions/{session_id}", summary="Get session", dependencies=[Depends(verify_api_key)])
async def get_session(session_id: str):
    """
    Get session with all turns.

    Returns full session object including conversation history.
    """
    try:
        from .. import session_store
        session = session_store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except ImportError:
        raise HTTPException(status_code=404, detail="Session store not available")


@router.get("/history/stats", summary="Session statistics", dependencies=[Depends(verify_api_key)])
async def get_history_stats():
    """
    Get session statistics.

    Returns aggregate stats: total sessions, turns, tokens, costs.
    """
    try:
        from .. import session_store
        return session_store.get_stats()
    except ImportError:
        return {"total_sessions": 0, "total_turns": 0, "total_tokens": 0, "total_cost_usd": 0.0}


# =============================================================================
# Agent Execution (Protected)
# =============================================================================

class AgentRequest(BaseModel):
    """Request body for agent execution."""
    inputs: Optional[dict] = None
    backend: Optional[str] = None
    dry_run: bool = False
    triggered_by: str = "api"


@router.post("/agent/{agent_name}", summary="Start agent", dependencies=[Depends(verify_api_key)])
async def start_agent(agent_name: str, body: AgentRequest):
    """
    Start an agent task.

    **Requires API key** if configured in system.json.

    Returns task_id for streaming results via `/task/{task_id}/stream`.
    """
    # Import the actual execution logic
    from ..routes.execution import start_agent_post, AgentInputsRequest

    # Convert to internal request format
    internal_body = AgentInputsRequest(
        inputs=body.inputs,
        backend=body.backend,
        dry_run=body.dry_run,
        triggered_by=body.triggered_by
    )

    return await start_agent_post(agent_name, internal_body)


@router.get("/task/{task_id}/status", summary="Task status", dependencies=[Depends(verify_api_key)])
async def get_task_status(task_id: str):
    """
    Get current task status.

    Use this for polling. For real-time updates, use SSE streaming.
    """
    from ..core import get_task
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, **task}


@router.post("/task/{task_id}/cancel", summary="Cancel task", dependencies=[Depends(verify_api_key)])
async def cancel_task(task_id: str):
    """
    Cancel a running task.

    **Requires API key** if configured.
    """
    from ..routes.tasks import cancel_task as _cancel_task
    return await _cancel_task(task_id)
