# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Workflow Manager
================
Discovery, execution, and lifecycle management for workflows.
"""

import importlib.util
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Type

from .base import Workflow
from .state import create_run, get_interrupted_runs, get_run, get_recent_runs

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass

# Import session store for workflow history
try:
    from assistant.session_store import create_session, add_turn, complete_session
except ImportError:
    # Fallback if import fails
    def create_session(*args, **kwargs): return None
    def add_turn(*args, **kwargs): return False
    def complete_session(*args, **kwargs): return False

# Import centralized SSE broadcast
from .sse import broadcast_sse


def _broadcast_sse(event_type: str, data: dict):
    """Broadcast SSE event - delegates to centralized function."""
    broadcast_sse(event_type, data, context="Workflows")

# Try to get PROJECT_DIR from paths module
try:
    from paths import PROJECT_DIR
except ImportError:
    PROJECT_DIR = Path(__file__).parent.parent.parent.parent

# Workflow discovery paths (User > System)
USER_WORKFLOWS = PROJECT_DIR / "workflows"
SYSTEM_WORKFLOWS = PROJECT_DIR / "deskagent" / "workflows"

# Registry of discovered workflows
_workflows: Dict[str, Type[Workflow]] = {}
_discovered = False


def discover() -> int:
    """
    Discover workflows from both user and system directories.

    User workflows override system workflows with the same name.
    Returns count of discovered workflows.
    """
    global _workflows, _discovered
    _workflows.clear()

    found_paths: Dict[str, Path] = {}

    # 1. System workflows (Priority 2)
    if SYSTEM_WORKFLOWS.exists():
        for f in SYSTEM_WORKFLOWS.glob("*.py"):
            if f.name.startswith("_"):
                continue
            found_paths[f.stem] = f
            system_log(f"[Workflows] Found system: {f.stem}")

    # 2. User workflows (Priority 1 - overrides system)
    if USER_WORKFLOWS.exists():
        for f in USER_WORKFLOWS.glob("*.py"):
            if f.name.startswith("_"):
                continue
            if f.stem in found_paths:
                system_log(f"[Workflows] User override: {f.stem}")
            found_paths[f.stem] = f

    # 3. Load modules and extract Workflow classes
    for name, path in found_paths.items():
        try:
            spec = importlib.util.spec_from_file_location(f"workflow_{name}", path)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find Workflow subclasses in module
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                cls = getattr(module, attr_name)
                if (isinstance(cls, type) and
                    issubclass(cls, Workflow) and
                    cls is not Workflow):
                    _workflows[name] = cls
                    system_log(f"[Workflows] Registered: {name} -> {cls.name}")
                    break

        except Exception as e:
            system_log(f"[Workflows] Error loading {name}: {e}")

    _discovered = True
    return len(_workflows)


def list_all() -> List[dict]:
    """List all discovered workflows with metadata."""
    if not _discovered:
        discover()

    return [
        {
            "id": workflow_id,
            "name": cls.name,
            "icon": cls.icon,
            "category": cls.category,
            "description": cls.description,
            "allowed_mcp": cls.allowed_mcp,
            "hidden": cls.hidden
        }
        for workflow_id, cls in _workflows.items()
        if not cls.hidden
    ]


def get_workflow(workflow_id: str) -> Optional[Type[Workflow]]:
    """Get a workflow class by ID."""
    if not _discovered:
        discover()
    return _workflows.get(workflow_id)


def _build_workflow_prompt(inputs: dict) -> str:
    """Build user prompt from workflow inputs for history display."""
    parts = []

    # Email workflow inputs
    if "sender" in inputs or "sender_email" in inputs:
        sender = inputs.get("sender", "")
        sender_email = inputs.get("sender_email", "")
        subject = inputs.get("subject", "")
        body = inputs.get("body", "")

        parts.append(f"Email from: {sender} <{sender_email}>")
        parts.append(f"Subject: {subject}")
        if body:
            # Truncate body for display
            body_preview = body[:2000] + ("..." if len(body) > 2000 else "")
            parts.append(f"\n{body_preview}")

    # Generic inputs fallback
    if not parts:
        for key, value in inputs.items():
            if key.startswith("_"):
                continue
            if isinstance(value, str) and len(value) > 500:
                value = value[:500] + "..."
            parts.append(f"{key}: {value}")

    return "\n".join(parts) if parts else ""


def start(workflow_id: str, **inputs) -> str:
    """
    Start a workflow in a background thread.

    Args:
        workflow_id: ID of the workflow to start
        **inputs: Input parameters for the workflow

    Returns:
        run_id: Unique ID for this workflow run
    """
    if not _discovered:
        discover()

    cls = _workflows.get(workflow_id)
    if cls is None:
        raise ValueError(f"Workflow not found: {workflow_id}")

    run_id = str(uuid.uuid4())

    # Create database record (workflow state)
    create_run(run_id, workflow_id, inputs)

    # Create session for history (like agent sessions)
    session_id = create_session(
        agent_name=cls.name,
        backend="workflow",
        model=None,
        triggered_by="workflow"
    )

    # Build user prompt from inputs for history display
    user_prompt = _build_workflow_prompt(inputs)
    if session_id and user_prompt:
        add_turn(session_id, "user", user_prompt)

    # Instantiate workflow with session_id for saving responses
    workflow = cls(run_id, _session_id=session_id, **inputs)

    # Run in background thread
    def run():
        try:
            result = workflow.execute()
            system_log(f"[Workflows] Completed {workflow_id}: {result}")

            # Complete session in history
            if session_id:
                complete_session(session_id)

            _broadcast_sse("workflow_ended", {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "name": cls.name,
                "status": "completed",
                "result": str(result)[:200],
                "session_id": session_id
            })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            system_log(f"[Workflows] Failed {workflow_id}: {e}")
            system_log(f"[Workflows] Traceback:\n{tb}")

            # Complete session even on failure
            if session_id:
                complete_session(session_id)

            _broadcast_sse("workflow_ended", {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "name": cls.name,
                "status": "failed",
                "error": str(e)[:200],
                "session_id": session_id
            })

    # Get total steps for progress tracking
    total_steps = len(workflow._get_steps())

    # IMPORTANT: Broadcast workflow_started BEFORE starting thread
    # Otherwise the agent session_started event arrives before workflow_started
    # and the frontend doesn't know to show the workflow tile
    system_log(f"[Workflows] Broadcasting workflow_started for {workflow_id}")

    # Prepare input summary for display (truncate body to avoid huge SSE payloads)
    input_summary = {}
    for key, value in inputs.items():
        if key == "body" and isinstance(value, str):
            # Truncate email body to first 1000 chars
            input_summary[key] = value[:1000] + ("..." if len(value) > 1000 else "")
        elif isinstance(value, str) and len(value) > 200:
            input_summary[key] = value[:200] + "..."
        else:
            input_summary[key] = value

    _broadcast_sse("workflow_started", {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "name": cls.name,
        "icon": cls.icon,
        "total_steps": total_steps,
        "inputs": input_summary,
        "session_id": session_id
    })

    # Small delay to ensure frontend receives workflow_started before first step
    time.sleep(0.1)

    # Now start the workflow thread
    thread = threading.Thread(target=run, daemon=True, name=f"Workflow-{workflow_id}")
    thread.start()

    system_log(f"[Workflows] Started {workflow_id} (run_id: {run_id[:8]}...)")
    return run_id


def start_sync(workflow_id: str, **inputs) -> str:
    """
    Start a workflow synchronously (blocking).

    Args:
        workflow_id: ID of the workflow to start
        **inputs: Input parameters for the workflow

    Returns:
        Final status message
    """
    if not _discovered:
        discover()

    cls = _workflows.get(workflow_id)
    if cls is None:
        raise ValueError(f"Workflow not found: {workflow_id}")

    run_id = str(uuid.uuid4())
    create_run(run_id, workflow_id, inputs)

    workflow = cls(run_id, **inputs)
    return workflow.execute()


def resume(run_id: str) -> bool:
    """
    Resume an interrupted workflow run.

    Args:
        run_id: ID of the workflow run to resume

    Returns:
        True if resumed, False if not found or not resumable
    """
    if not _discovered:
        discover()

    run_data = get_run(run_id)
    if not run_data:
        return False

    if not run_data["status"] == "running":
        return False

    cls = _workflows.get(run_data["workflow_name"])
    if cls is None:
        return False

    # Restore workflow state
    workflow = cls(run_id, **run_data["state"])

    # Resume from last step
    from_step = run_data["step_index"]

    def run():
        try:
            result = workflow.execute(from_step=from_step)
            system_log(f"[Workflows] Resumed and completed {run_data['workflow_name']}: {result}")
        except Exception as e:
            system_log(f"[Workflows] Resumed but failed {run_data['workflow_name']}: {e}")

    thread = threading.Thread(target=run, daemon=True, name=f"Workflow-Resume-{run_id[:8]}")
    thread.start()

    system_log(f"[Workflows] Resuming {run_data['workflow_name']} from step {from_step}")
    return True


def resume_all() -> int:
    """
    Resume all interrupted workflows (called on startup).

    Returns:
        Count of resumed workflows
    """
    if not _discovered:
        discover()

    interrupted = get_interrupted_runs()
    resumed = 0

    for run in interrupted:
        if resume(run["id"]):
            resumed += 1

    if resumed > 0:
        system_log(f"[Workflows] Resumed {resumed} interrupted workflow(s)")

    return resumed


def get_status(run_id: str) -> Optional[dict]:
    """Get status of a workflow run."""
    return get_run(run_id)


def get_recent(limit: int = 50) -> List[dict]:
    """Get recent workflow runs."""
    return get_recent_runs(limit)


def get_trigger_status() -> Dict[str, dict]:
    """
    Get trigger status for all workflows.

    Reads triggers.json and finds which workflows have triggers configured.
    Respects hostname filter - triggers configured for other hosts show as disabled.

    Returns:
        Dict mapping workflow_id -> {
            "has_trigger": bool,
            "enabled": bool,
            "trigger_name": str,
            "trigger_type": str
        }
    """
    import json
    import socket

    result: Dict[str, dict] = {}
    current_host = socket.gethostname().lower()

    # Load triggers.json
    config_file = PROJECT_DIR / "config" / "triggers.json"
    if not config_file.exists():
        return result

    try:
        triggers = json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        system_log(f"[Workflows] Error loading triggers.json: {e}")
        return result

    # Scan all triggers for workflow references
    for trigger_id, trigger_config in triggers.items():
        if trigger_id.startswith("_"):
            continue

        trigger_type = trigger_config.get("type", "")
        trigger_name = trigger_config.get("name", trigger_id)
        enabled = trigger_config.get("enabled", False)

        # Hostname filter: if configured for different host, treat as disabled
        required_host = trigger_config.get("hostname", "").lower()
        if required_host and required_host != current_host:
            enabled = False

        # Check rules for workflow actions (email_watcher type)
        rules = trigger_config.get("rules", [])
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            for action in rule.get("actions", []):
                if action.get("type") == "trigger_workflow":
                    workflow_id = action.get("workflow")
                    if workflow_id:
                        # Only update if no trigger exists yet, or if this one is enabled
                        if workflow_id not in result or enabled:
                            result[workflow_id] = {
                                "has_trigger": True,
                                "enabled": enabled,
                                "trigger_name": trigger_name,
                                "trigger_type": trigger_type
                            }

        # Direct workflow reference (schedule type might use this)
        if "workflow" in trigger_config:
            workflow_id = trigger_config["workflow"]
            if workflow_id not in result or enabled:
                result[workflow_id] = {
                    "has_trigger": True,
                    "enabled": enabled,
                    "trigger_name": trigger_name,
                    "trigger_type": trigger_type
                }

    return result
