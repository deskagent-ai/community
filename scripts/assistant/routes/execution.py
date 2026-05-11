# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Routes for Task Execution.

Handles starting agents, skills, and prompts.
Replaces the corresponding endpoints from the old HTTP handler.
"""

import json
import threading
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core import (
    tasks as _tasks,
    tasks_lock as _tasks_lock,
    test_tasks as _test_tasks,
    test_tasks_lock as _test_tasks_lock,
    generate_task_id as _generate_task_id,
    get_task as _get_task,
    update_test_task as _update_test_task,
    get_ai_backend_info as _get_ai_backend_info,
    create_and_start_task as _create_and_start_task,
    get_tray_icon,
    add_to_history,
    build_continuation_prompt,
    clear_conversation_history,
    update_session,
)
from ai_agent import log
from ..skills import load_skill, load_config
from ..agents import load_agent, get_agent_inputs
from ..services.discovery import get_agent_config, check_agent_prerequisites
from ..services.mcp_hints import get_mcp_hint
from .. import interaction

try:
    import ai_agent
except ImportError:
    ai_agent = None

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR, get_config_dir

# Import path constants from core.files (eliminates duplicate definitions)
from ..core import TEMP_UPLOADS_DIR, SCRIPTS_DIR

router = APIRouter()


# =============================================================================
# Input Validation
# =============================================================================

import re
_VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_task_name(name: str, task_type: str = "task") -> None:
    """
    Validate agent/skill name to prevent path traversal and injection.

    Args:
        name: The agent or skill name to validate
        task_type: Type of task for error message ("agent", "skill", etc.)

    Raises:
        HTTPException: If name contains invalid characters
    """
    if not name or not _VALID_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {task_type} name: must contain only letters, numbers, underscores, and hyphens"
        )


# =============================================================================
# Request Models
# =============================================================================

class PromptRequest(BaseModel):
    """Request body for prompt submission."""
    prompt: str
    continue_context: bool = True
    backend: Optional[str] = None
    agent_name: Optional[str] = None  # Chat agent name (e.g., "chat", "chat_claude")
    triggered_by: str = "webui"  # What triggered this: webui, voice, email_watcher, workflow, api
    resume_session_id: Optional[str] = None  # FIX [039]: SDK session ID for resume from History


class AgentInputsRequest(BaseModel):
    """Request body for agent with inputs."""
    inputs: Optional[Dict[str, Any]] = None
    backend: Optional[str] = None  # Override AI backend
    dry_run: bool = False  # Simulate destructive operations
    test_folder: Optional[str] = None  # Test folder for scenarios
    parent_task_id: Optional[str] = None  # Parent task for cost aggregation
    triggered_by: str = "webui"  # What triggered this: webui, voice, email_watcher, workflow, api
    initial_prompt: Optional[str] = None  # Initial prompt for History display
    session_name: Optional[str] = None  # Custom name for History tile (instead of agent_name)
    disable_anon: bool = False  # [044] Expert Mode: Skip anonymization via context menu


# =============================================================================
# Import task runners from core.executor (they contain the core logic)
# =============================================================================

def _get_task_runners():
    """Import task runners lazily to avoid circular imports."""
    from ..core import (
        run_tracked_task,
        run_tracked_agent,
        run_tracked_prompt,
        run_tests,
    )
    return run_tracked_task, run_tracked_agent, run_tracked_prompt, run_tests


# =============================================================================
# Skill Endpoints
# =============================================================================

@router.get("/skill/{skill_name}")
async def start_skill(skill_name: str):
    """
    Start a skill task.

    Returns task_id for SSE streaming connection.
    """
    _validate_task_name(skill_name, "skill")
    run_tracked_task, _, _, _ = _get_task_runners()

    config = load_config()
    skill = load_skill(skill_name)
    user_prompt = skill.get("content", "") if skill else ""

    task_id, response = _create_and_start_task(
        task_type="skill",
        task_name=skill_name,
        runner_func=run_tracked_task,
        runner_args=(skill_name, get_tray_icon()),
        user_prompt=user_prompt
    )

    return response


# =============================================================================
# Agent Endpoints
# =============================================================================

@router.get("/agent/{agent_name}/inputs")
async def get_agent_input_definitions(agent_name: str):
    """
    Get agent input definitions for pre-input dialog.
    """
    _validate_task_name(agent_name, "agent")
    inputs = get_agent_inputs(agent_name)
    log(f"[HTTP] Agent inputs for '{agent_name}': {len(inputs)} input(s) defined")
    if inputs:
        for inp in inputs:
            log(f"  - {inp.get('name')}: {inp.get('type')} ({inp.get('label')})")
    return {"inputs": inputs}


@router.get("/agent/{agent_name}/check-backend")
async def check_agent_backend(agent_name: str):
    """
    Check if agent's configured backend is available.

    Returns:
        - If available: {"available": True, "backend": "name"}
        - If not available: {"available": False, "configured_backend": "name",
          "available_backends": [...], "recommended": "name"}
    """
    _validate_task_name(agent_name, "agent")
    config = load_config()
    ai_backends = config.get("ai_backends", {})

    # Get agent's configured backend
    agent_config = get_agent_config(agent_name) or {}
    configured_backend = agent_config.get("ai", config.get("default_ai", "claude"))

    # Check if backend is available
    is_available = False
    if ai_agent and hasattr(ai_agent, 'is_backend_available'):
        is_available = ai_agent.is_backend_available(configured_backend, config)
    else:
        # Fallback: just check if backend exists in config
        is_available = configured_backend in ai_backends

    if is_available:
        return {"available": True, "backend": configured_backend}

    # Get list of available alternatives
    available_backends = []
    for name, backend_config in ai_backends.items():
        backend_available = False
        if ai_agent and hasattr(ai_agent, 'is_backend_available'):
            backend_available = ai_agent.is_backend_available(name, config)
        else:
            backend_available = True  # Assume available if we can't check

        if backend_available:
            available_backends.append({
                "name": name,
                "display": backend_config.get("display_name", name),
                "model": backend_config.get("model", "")
            })

    log(f"[HTTP] Backend '{configured_backend}' not available for agent '{agent_name}'. "
        f"Alternatives: {[b['name'] for b in available_backends]}")

    return {
        "available": False,
        "configured_backend": configured_backend,
        "available_backends": available_backends,
        "recommended": available_backends[0]["name"] if available_backends else None
    }


@router.get("/agent/{agent_name}/prerequisites")
async def check_agent_prerequisites_endpoint(agent_name: str):
    """
    Check if agent's prerequisites are configured (MCPs + backend).

    Returns:
        - ready: True if all prerequisites are met
        - missing_mcps: List of MCPs that are not configured
        - missing_backend: Name of missing AI backend (or null)
        - hints: Dict of MCP name -> setup hints
    """
    _validate_task_name(agent_name, "agent")

    # Get available backends
    from paths import load_config
    config = load_config()
    ai_backends = config.get("ai_backends", {})

    # Get agent config and check prerequisites
    agent_config = get_agent_config(agent_name) or {}
    prereq_status = check_agent_prerequisites(agent_config, ai_backends)

    # Build hints for missing MCPs
    hints = {}
    for mcp_name in prereq_status.get("missing_mcps", []):
        hint = get_mcp_hint(mcp_name)
        if hint:
            hints[mcp_name] = hint
        else:
            hints[mcp_name] = {
                "name": mcp_name,
                "requirement": "Konfiguration fehlt"
            }

    missing_backend = prereq_status.get("missing_backend")
    fallback_backend = prereq_status.get("fallback_backend")
    log(f"[HTTP] Prerequisites check for '{agent_name}': ready={prereq_status['ready']}, "
        f"missing_mcps={prereq_status.get('missing_mcps', [])}, missing_backend={missing_backend}, "
        f"fallback_backend={fallback_backend}")

    return {
        "ready": prereq_status["ready"],
        "missing_mcps": prereq_status.get("missing_mcps", []),
        "missing_backend": missing_backend,
        "fallback_backend": fallback_backend,
        "hints": hints
    }


@router.get("/agent/{agent_name}")
async def start_agent_get(
    agent_name: str,
    backend: Optional[str] = None,
    dry_run: bool = False,
    test_folder: Optional[str] = None,
    triggered_by: str = "webui",
    disable_anon: bool = False
):
    """
    Start an agent task (GET - no inputs).

    Args:
        agent_name: Name of the agent to run
        backend: Override AI backend (e.g., "gemini", "openai")
        dry_run: If true, simulate destructive operations (no actual moves/deletes)
        test_folder: Optional Outlook folder for test scenarios (e.g., "TestData")
        triggered_by: What triggered this: "webui", "voice", "email_watcher", "workflow", "api"
        disable_anon: If True, skip anonymization (Expert Mode override via context menu)

    Returns task_id for SSE streaming connection.
    """
    _validate_task_name(agent_name, "agent")
    _, run_tracked_agent, _, _ = _get_task_runners()

    config = load_config()
    ai_backends = config.get("ai_backends", {})

    # Validate backend override if provided
    if backend and backend not in ai_backends:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}")

    # Get backend info (global override has highest priority, checked inside _get_ai_backend_info)
    ai_backend, model = _get_ai_backend_info(config, agent_name, "agent")

    # Check for prefetch requirements
    agent_config = get_agent_config(agent_name) or {}
    prefetch_types = agent_config.get("prefetch", [])
    prefetched = {}
    if prefetch_types:
        log(f"[HTTP] Agent {agent_name} has prefetch: {prefetch_types}")
        try:
            from ..services.prefetch import execute_prefetch
            prefetched = await execute_prefetch(prefetch_types)
        except Exception as e:
            log(f"[HTTP] Prefetch error (continuing without): {e}")

    agent = load_agent(agent_name)
    user_prompt = agent.get("content", "") if agent else ""

    # Log dry_run mode
    if dry_run:
        log(f"[HTTP] Agent {agent_name} running in DRY-RUN mode")
    if test_folder:
        log(f"[HTTP] Agent {agent_name} using test folder: {test_folder}")

    # Generate default initial_prompt for History preview
    # Convert "daily_check" -> "Daily Check"
    display_name = agent_name.replace("_", " ").title()
    initial_prompt = f"Agent: {display_name}"

    task_id, response = _create_and_start_task(
        task_type="agent",
        task_name=agent_name,
        runner_func=run_tracked_agent,
        runner_args=(agent_name, get_tray_icon(), None, backend, dry_run, test_folder, triggered_by, initial_prompt, prefetched, disable_anon),
        ai_backend=ai_backend,
        model=model,
        user_prompt=user_prompt,
        dry_run=dry_run,
        triggered_by=triggered_by
    )

    return response


@router.post("/agent/{agent_name}")
async def start_agent_post(agent_name: str, body: AgentInputsRequest):
    """
    Start an agent task with inputs (POST).

    Args:
        agent_name: Name of the agent to run
        body: Request body with inputs and optional backend/dry_run/test_folder

    Returns task_id for SSE streaming connection.
    """
    _validate_task_name(agent_name, "agent")
    _, run_tracked_agent, _, _ = _get_task_runners()

    inputs = body.inputs or {}
    backend = body.backend
    dry_run = body.dry_run
    test_folder = body.test_folder
    parent_task_id = body.parent_task_id
    triggered_by = body.triggered_by
    initial_prompt = body.initial_prompt
    session_name = body.session_name  # Custom name for History tile

    # Generate default initial_prompt if not provided (for History preview)
    if not initial_prompt:
        display_name = (session_name or agent_name).replace("_", " ").title()
        initial_prompt = f"Agent: {display_name}"

        # Include user inputs in initial_prompt for History
        if inputs:
            input_lines = []
            for key, value in inputs.items():
                if key.startswith("_"):  # Skip internal fields
                    continue
                if isinstance(value, list):
                    input_lines.append(f"{key}: [{len(value)} Dateien]")
                elif isinstance(value, str) and value.strip():
                    # Truncate long values
                    preview = value[:200] + "..." if len(value) > 200 else value
                    input_lines.append(f"{key}: {preview}")
            if input_lines:
                initial_prompt += "\n" + "\n".join(input_lines)

    # Log inputs immediately for debugging
    log(f"[HTTP] POST /agent/{agent_name} (triggered_by: {triggered_by})")
    if inputs:
        log(f"[HTTP] Inputs received ({len(inputs)} fields):")
        for key, value in inputs.items():
            if isinstance(value, list):
                log(f"  {key}: [{len(value)} files]")
            elif isinstance(value, str):
                preview = value[:100] + "..." if len(value) > 100 else value
                log(f"  {key}: {preview}")
            else:
                log(f"  {key}: {value}")
    else:
        log(f"[HTTP] No inputs provided")

    # Log dry_run mode
    if dry_run:
        log(f"[HTTP] Agent {agent_name} running in DRY-RUN mode")
    if test_folder:
        log(f"[HTTP] Agent {agent_name} using test folder: {test_folder}")

    config = load_config()
    ai_backends = config.get("ai_backends", {})

    # Validate backend override if provided
    if backend and backend not in ai_backends:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}")

    # Get backend info (global override has highest priority, checked inside _get_ai_backend_info)
    ai_backend, model = _get_ai_backend_info(config, agent_name, "agent")

    # Check for prefetch requirements
    agent_config = get_agent_config(agent_name) or {}
    prefetch_types = agent_config.get("prefetch", [])
    prefetched = {}
    if prefetch_types:
        log(f"[HTTP] Agent {agent_name} has prefetch: {prefetch_types}")
        try:
            from ..services.prefetch import execute_prefetch
            prefetched = await execute_prefetch(prefetch_types)
        except Exception as e:
            log(f"[HTTP] Prefetch error (continuing without): {e}")

    # Load agent WITHOUT inputs for user_prompt display
    # The actual inputs (including _context) are processed in process_agent
    agent = load_agent(agent_name)
    user_prompt = agent.get("content", "") if agent else ""

    # If there's user context, append a note to user_prompt for display
    if inputs and inputs.get("_context"):
        context_preview = inputs["_context"][:100] + "..." if len(inputs.get("_context", "")) > 100 else inputs["_context"]
        user_prompt += f"\n\n[Zusätzlicher Kontext: {context_preview}]"

    # Log parent task for sub-agent tracking
    if parent_task_id:
        log(f"[HTTP] Sub-agent of parent task: {parent_task_id}")

    # [044] Expert Mode: disable_anon from context menu
    disable_anon = body.disable_anon

    task_id, response = _create_and_start_task(
        task_type="agent",
        task_name=session_name or agent_name,  # Use custom session_name if provided
        runner_func=run_tracked_agent,
        runner_args=(agent_name, get_tray_icon(), inputs, backend, dry_run, test_folder, triggered_by, initial_prompt, prefetched, disable_anon),
        ai_backend=ai_backend,
        model=model,
        user_prompt=user_prompt,
        dry_run=dry_run,
        parent_task_id=parent_task_id,  # Store for cost aggregation
        triggered_by=triggered_by
    )

    return response


# =============================================================================
# Prompt Endpoint
# =============================================================================

@router.post("/prompt")
async def submit_prompt(body: PromptRequest):
    """
    Submit a free-form prompt.

    Returns task_id for SSE streaming connection.
    """
    _, _, run_tracked_prompt, _ = _get_task_runners()

    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")

    config = load_config()
    ai_backends = config.get("ai_backends", {})

    # Validate backend if provided
    if body.backend and body.backend not in ai_backends:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {body.backend}")

    # Get backend info (global override has highest priority)
    global_override = config.get("global_ai_override")
    if global_override and global_override != "auto":
        effective_backend = global_override
    else:
        effective_backend = body.backend or config.get("default_ai", "claude")
    ai_config = ai_backends.get(effective_backend, {})
    model = ai_config.get("model", ai_config.get("type", "unknown"))

    task_type = "chat" if body.backend else "prompt"
    task_name = body.agent_name or "prompt"  # Use agent name if provided
    task_id, response = _create_and_start_task(
        task_type=task_type,
        task_name=task_name,
        runner_func=run_tracked_prompt,
        # FIX [039]: Pass resume_session_id to runner
        runner_args=(prompt, get_tray_icon(), body.continue_context, body.backend,
                     body.agent_name, body.triggered_by, body.resume_session_id),
        ai_backend=effective_backend,
        model=model,
        user_prompt=prompt,
        triggered_by=body.triggered_by
    )

    return response


# =============================================================================
# Session Management
# =============================================================================

@router.post("/session/clear")
async def clear_session():
    """Clear old completed sessions from database (current active session stays intact)."""
    from .. import session_store

    # Delete all completed sessions from database
    # Current active session and its history remain untouched
    count = session_store.delete_completed_sessions()
    log(f"[Session] Cleared {count} completed sessions (active session preserved)")
    return {"status": "ok", "message": f"Cleared {count} old sessions", "deleted": count}


@router.post("/session/end")
async def end_session():
    """End current session (called when user closes tile/escapes)."""
    from ..core.state import end_current_session

    # End current session (marks as completed in DB)
    end_current_session()
    log("[Session] Current session ended by user")
    return {"status": "ok", "message": "Session ended"}


# =============================================================================
# File Upload (for Agent Inputs)
# =============================================================================

@router.post("/upload/file")
async def upload_files(request: Request):
    """
    Handle file uploads for agent inputs.

    Saves files to .temp/uploads/ and returns their absolute paths.
    """
    from ..services import save_uploaded_files

    form = await request.form()
    return await save_uploaded_files(form)


# =============================================================================
# Developer Mode: Test Runner
# =============================================================================

@router.get("/tests/run")
async def start_tests(scope: str = "unit"):
    """
    Start test run (developer mode only).

    Args:
        scope: "unit", "integration", or "all"
    """
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    if scope not in ("unit", "integration", "all"):
        raise HTTPException(status_code=400, detail="Invalid scope. Use: unit, integration, all")

    _, _, _, run_tests = _get_task_runners()

    task_id = f"test_{_generate_task_id()}"
    with _test_tasks_lock:
        _test_tasks[task_id] = {"status": "starting", "scope": scope}

    log(f"\n[HTTP] Test Task {task_id}: scope={scope}")
    threading.Thread(target=run_tests, args=(task_id, scope)).start()

    return {"status": "started", "task_id": task_id, "scope": scope}


@router.get("/tests/status/{task_id}")
async def get_test_status(task_id: str):
    """Get test task status."""
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    with _test_tasks_lock:
        if task_id in _test_tasks:
            task_data = _test_tasks[task_id].copy()
        else:
            task_data = None

    if task_data:
        return {"task_id": task_id, **task_data}
    else:
        raise HTTPException(status_code=404, detail="Test task not found")


@router.get("/tests/list")
async def list_tests():
    """List all test tasks."""
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    with _test_tasks_lock:
        task_ids = list(_test_tasks.keys())
    return {"tasks": task_ids}


@router.get("/dev/context")
async def get_dev_context_endpoint(task_id: str = None):
    """Get developer context (developer mode only).

    Args:
        task_id: Optional task ID to get context for specific task.
                 If not provided, returns context for the last active task.
    """
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    if ai_agent:
        ctx = ai_agent.get_dev_context(task_id=task_id)
        return ctx
    return {}


# =============================================================================
# Skill Context Endpoints
# =============================================================================

@router.get("/skill-contexts")
async def get_skill_contexts():
    """Get all active skill contexts."""
    from ..skills import get_active_skill_contexts
    contexts = get_active_skill_contexts()
    return {"contexts": contexts, "timeout_seconds": 600}


@router.post("/skill-contexts/clear")
async def clear_skill_contexts():
    """Clear all skill contexts."""
    from ..skills import clear_all_skill_contexts
    count = clear_all_skill_contexts()
    return {"status": "ok", "cleared": count}


@router.post("/skill-context/{skill_name}/clear")
async def clear_skill_context(skill_name: str):
    """Clear specific skill context."""
    from ..skills import clear_skill_context as _clear_skill_context
    if _clear_skill_context(skill_name):
        return {"status": "ok", "skill": skill_name, "message": "Context cleared"}
    else:
        return {"status": "ok", "skill": skill_name, "message": "No context found"}
