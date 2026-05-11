# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Routes for Multi-Backend Testing.

Handles comparing agents across different AI backends for quality/cost analysis.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_agent import log
from ..skills import load_config
from ..agents import load_agent
from ..core import generate_task_id

# Path is set up by assistant/__init__.py
from paths import get_logs_dir

router = APIRouter()


# =============================================================================
# Request Models
# =============================================================================

class CompareRequest(BaseModel):
    """Request body for backend comparison."""
    agent_name: str
    backends: Optional[List[str]] = None  # If empty, uses all enabled backends
    dry_run: bool = True  # Default to dry-run for safety
    test_folder: Optional[str] = None


# =============================================================================
# Backend Comparison
# =============================================================================

async def run_single_backend(
    agent_name: str,
    backend: str,
    dry_run: bool,
    test_folder: str = None,
    config: dict = None
) -> Dict[str, Any]:
    """
    Run an agent against a single backend.

    Each backend runs with its own isolated TaskContext, ensuring:
    - Separate anonymization context per backend
    - Separate simulated actions per backend
    - Separate log files per backend (using task_id)

    Args:
        agent_name: Name of the agent
        backend: Backend to use
        dry_run: Whether to simulate destructive operations
        test_folder: Optional test folder for Outlook
        config: Pre-loaded config dict

    Returns:
        Dict with results including success, duration, tokens, cost, etc.
    """
    import uuid
    import ai_agent
    from ..agents import process_agent

    start_time = time.time()
    result = {
        "backend": backend,
        "success": False,
        "duration_sec": 0,
        "tokens": {"input": 0, "output": 0},
        "cost_usd": 0,
        "response_preview": "",
        "error": None,
        "simulated_actions": []
    }

    # Generate unique task_id for this backend comparison run
    # Format: compare-{backend}-{uuid4[:4]} e.g., "compare-gemini-a1b2"
    task_id = f"compare-{backend}-{str(uuid.uuid4())[:4]}"
    log(f"[Compare] Starting {backend} with task_id={task_id}")

    try:
        # Get backend config
        if config is None:
            config = load_config()

        ai_backends = config.get("ai_backends", {})
        if backend not in ai_backends:
            result["error"] = f"Unknown backend: {backend}"
            return result

        # Load agent
        agent = load_agent(agent_name)
        if not agent:
            result["error"] = f"Agent not found: {agent_name}"
            return result

        # Set up a simple callback to capture the response
        captured_response = []

        def capture_chunk(token: str, is_thinking: bool = False, full_response: str = None, **kwargs):
            if full_response:
                captured_response.clear()
                captured_response.append(full_response)

        # Call agent with the specified backend and unique task_id for isolation
        # The task_id ensures:
        # - Isolated anonymization context via ContextVar
        # - Isolated simulated actions via ContextVar
        response = ai_agent.call_agent(
            agent["content"],
            config,
            use_tools=True,
            agent_name=backend,
            on_chunk=capture_chunk,
            task_name=agent_name,
            task_type="agent",
            dry_run=dry_run,
            test_folder=test_folder,
            task_id=task_id  # Unique task_id for isolation
        )

        duration = time.time() - start_time
        result["duration_sec"] = round(duration, 2)
        result["task_id"] = task_id  # Include task_id in results for debugging

        if response.success:
            result["success"] = True
            result["response"] = response.content or ""  # Full response for export
            result["response_preview"] = response.content[:500] if response.content else ""
            result["tokens"]["input"] = response.input_tokens or 0
            result["tokens"]["output"] = response.output_tokens or 0
            result["cost_usd"] = response.cost_usd or 0

            # Get simulated actions from the response (captured before TaskContext cleanup)
            if dry_run and response.simulated_actions:
                result["simulated_actions"] = response.simulated_actions
        else:
            result["error"] = response.error or "Unknown error"

    except Exception as e:
        result["error"] = str(e)
        result["duration_sec"] = round(time.time() - start_time, 2)

    log(f"[Compare] Finished {backend} (task_id={task_id}): success={result['success']}")
    return result


@router.post("/test/compare")
async def compare_backends(request: CompareRequest):
    """
    Run agent against multiple backends in parallel and compare results.

    Returns comparison data including:
    - Per-backend results (success, duration, tokens, cost)
    - Winner analysis (fastest, cheapest, most tokens)
    - Saved file path for JSON export
    """
    config = load_config()

    # Check developer mode (comparison is a dev feature)
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    ai_backends = config.get("ai_backends", {})

    # Determine which backends to test
    if request.backends:
        backends = [b for b in request.backends if b in ai_backends]
        if not backends:
            raise HTTPException(status_code=400, detail="No valid backends specified")
    else:
        # Use all enabled backends
        backends = [
            name for name, cfg in ai_backends.items()
            if cfg.get("enabled", True)
        ]

    if len(backends) < 1:
        raise HTTPException(status_code=400, detail="No backends available for comparison")

    log(f"[Compare] Starting comparison for {request.agent_name} across {len(backends)} backends: {backends}")

    # Run all backends in parallel
    tasks = [
        run_single_backend(
            request.agent_name,
            backend,
            request.dry_run,
            request.test_folder,
            config
        )
        for backend in backends
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    backend_results = {}
    for i, result in enumerate(results):
        backend_name = backends[i]
        if isinstance(result, Exception):
            backend_results[backend_name] = {
                "success": False,
                "error": str(result),
                "duration_sec": 0,
                "tokens": {"input": 0, "output": 0},
                "cost_usd": 0
            }
        else:
            backend_results[backend_name] = result

    # Determine winners
    successful = {k: v for k, v in backend_results.items() if v.get("success")}

    winner = {
        "fastest": None,
        "cheapest": None,
        "most_tokens": None
    }

    if successful:
        # Fastest (lowest duration)
        fastest = min(successful.items(), key=lambda x: x[1].get("duration_sec", float("inf")))
        winner["fastest"] = fastest[0]

        # Cheapest (lowest cost, excluding free)
        with_cost = {k: v for k, v in successful.items() if v.get("cost_usd", 0) > 0}
        if with_cost:
            cheapest = min(with_cost.items(), key=lambda x: x[1].get("cost_usd", float("inf")))
            winner["cheapest"] = cheapest[0]
        else:
            # All free - first one wins
            winner["cheapest"] = list(successful.keys())[0] if successful else None

        # Most output tokens
        most_tokens = max(successful.items(), key=lambda x: x[1].get("tokens", {}).get("output", 0))
        winner["most_tokens"] = most_tokens[0]

    # Build comparison result
    timestamp = datetime.now()
    comparison = {
        "agent": request.agent_name,
        "timestamp": timestamp.isoformat(),
        "dry_run": request.dry_run,
        "test_folder": request.test_folder,
        "backends": backend_results,
        "winner": winner,
        "summary": {
            "total_backends": len(backends),
            "successful": len(successful),
            "failed": len(backends) - len(successful)
        }
    }

    # Save to JSON file
    comparisons_dir = get_logs_dir() / "comparisons"
    comparisons_dir.mkdir(exist_ok=True)

    filename = f"compare_{request.agent_name}_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
    file_path = comparisons_dir / filename

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        comparison["file"] = str(file_path)
        log(f"[Compare] Results saved to {filename}")
    except Exception as e:
        log(f"[Compare] Failed to save results: {e}")
        comparison["file"] = None

    log(f"[Compare] Comparison complete: {len(successful)}/{len(backends)} successful")
    return comparison


@router.get("/test/comparisons")
async def list_comparisons():
    """List all saved comparison files."""
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    comparisons_dir = get_logs_dir() / "comparisons"
    if not comparisons_dir.exists():
        return {"comparisons": []}

    files = sorted(comparisons_dir.glob("compare_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

    comparisons = []
    for f in files[:50]:  # Limit to 50 most recent
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                comparisons.append({
                    "file": f.name,
                    "agent": data.get("agent"),
                    "timestamp": data.get("timestamp"),
                    "backends": list(data.get("backends", {}).keys()),
                    "winner": data.get("winner", {})
                })
        except Exception:
            pass

    return {"comparisons": comparisons}


@router.get("/test/comparison/{filename}")
async def get_comparison(filename: str):
    """Get a specific comparison result."""
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    comparisons_dir = get_logs_dir() / "comparisons"
    file_path = comparisons_dir / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Comparison not found")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading comparison: {e}")


@router.delete("/test/comparisons")
async def clear_comparisons():
    """Clear all comparison files."""
    config = load_config()
    if not config.get("developer_mode", False):
        raise HTTPException(status_code=403, detail="Developer mode not enabled")

    comparisons_dir = get_logs_dir() / "comparisons"
    if not comparisons_dir.exists():
        return {"status": "ok", "deleted": 0}

    deleted = 0
    for f in comparisons_dir.glob("compare_*.json"):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass

    return {"status": "ok", "deleted": deleted}
