# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Workflow API routes for DeskAgent.

Provides endpoints for listing and starting workflows.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

# Import workflow manager (fallback for different run contexts)
manager = None
try:
    from workflows import manager
except ImportError:
    try:
        from scripts.workflows import manager
    except ImportError as e:
        try:
            from ai_agent import system_log
            system_log(f"[WorkflowRoutes] Could not import workflows: {e}")
        except Exception:
            pass

router = APIRouter(tags=["workflows"])


class WorkflowStartRequest(BaseModel):
    """Request body for starting a workflow."""
    inputs: Optional[Dict[str, Any]] = {}


@router.get("/workflows")
def list_workflows():
    """List all available workflows.

    Returns:
        List of workflow metadata (id, name, icon, description, category)
    """
    if manager is None:
        return []
    manager.discover()
    return manager.list_all()


@router.post("/workflows/{workflow_id}/start")
def start_workflow(workflow_id: str, request: WorkflowStartRequest = None):
    """Start a workflow by ID.

    Args:
        workflow_id: The workflow identifier (filename without .py)
        request: Optional inputs to pass to the workflow

    Returns:
        run_id: Unique identifier for this workflow run
    """
    if manager is None:
        raise HTTPException(status_code=503, detail="Workflow system not available")

    manager.discover()

    inputs = request.inputs if request else {}

    try:
        run_id = manager.start(workflow_id, **inputs)
        return {"run_id": run_id, "workflow_id": workflow_id, "status": "started"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    """Get details about a specific workflow.

    Args:
        workflow_id: The workflow identifier

    Returns:
        Workflow metadata including name, icon, description, steps
    """
    if manager is None:
        raise HTTPException(status_code=503, detail="Workflow system not available")

    manager.discover()

    workflows = {w["id"]: w for w in manager.list_all()}
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")

    return workflows[workflow_id]
