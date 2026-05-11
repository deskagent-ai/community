# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Routes for Email and Teams Watchers.

Handles watcher status, control, and action logs.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_agent import log
from ..skills import load_config

router = APIRouter()


class WatcherToggleRequest(BaseModel):
    """Request body for watcher toggle."""
    enabled: Optional[bool] = None


# =============================================================================
# Email Watcher Endpoints
# =============================================================================

@router.get("/watchers")
async def get_watcher_status():
    """Get email watcher status."""
    from .. import watchers
    status = watchers.get_status()
    return status


@router.get("/watchers/log")
async def get_watcher_log(limit: int = 50):
    """Get watcher action log."""
    from .. import watchers
    log_entries = watchers.get_action_log(limit=limit)
    return {"log": log_entries}


@router.post("/watchers/toggle")
async def toggle_watcher(body: WatcherToggleRequest = None):
    """Toggle email watcher on/off."""
    from .. import watchers

    enabled = body.enabled if body else None

    if enabled is None:
        # Toggle current state
        enabled = not watchers.is_enabled()

    if enabled:
        watchers.start_watcher()
    else:
        watchers.stop_watcher()

    return {
        "enabled": enabled,
        "running": watchers.is_running(),
        "status": "ok"
    }


@router.post("/watchers/check-now")
async def check_watcher_now():
    """Force immediate watcher check."""
    from .. import watchers
    result = watchers.check_now()
    return result


# =============================================================================
# Teams Watcher Endpoints
# =============================================================================

@router.get("/teams-watcher")
async def get_teams_watcher_status():
    """Get Teams watcher status."""
    from .. import teams_watcher
    return teams_watcher.get_status()


@router.post("/teams-watcher/start")
async def start_teams_watcher():
    """Start Teams watcher."""
    from .. import teams_watcher
    if teams_watcher.start_watcher():
        return {"status": "ok", "message": "Teams watcher started"}
    else:
        raise HTTPException(status_code=400, detail="Failed to start Teams watcher")


@router.post("/teams-watcher/stop")
async def stop_teams_watcher():
    """Stop Teams watcher."""
    from .. import teams_watcher
    teams_watcher.stop_watcher()
    return {"status": "ok", "message": "Teams watcher stopped"}


@router.post("/teams-watcher/clear")
async def clear_teams_watcher():
    """Clear Teams watcher state."""
    from .. import teams_watcher
    teams_watcher.clear_state()
    return {"status": "ok", "message": "Teams watcher state cleared"}


class TeamsWatcherSetupRequest(BaseModel):
    """Request body for Teams watcher setup."""
    channel_name: str


@router.post("/teams-watcher/setup")
async def setup_teams_watcher(body: TeamsWatcherSetupRequest):
    """Setup Teams watcher for a channel."""
    from .. import teams_watcher
    result = teams_watcher.setup_watcher(body.channel_name)
    return result


# =============================================================================
# Email Auto-Watcher Endpoints (Gmail + Office 365)
# =============================================================================

@router.get("/email-watchers")
async def get_email_watchers_status():
    """Get all email auto-watcher statuses."""
    from .. import email_auto_watcher
    return {"watchers": email_auto_watcher.get_all_statuses()}


@router.get("/email-watchers/{watcher_id}")
async def get_email_watcher_status(watcher_id: str):
    """Get specific email auto-watcher status."""
    from .. import email_auto_watcher
    watcher = email_auto_watcher.get_watcher(watcher_id)
    if watcher:
        return watcher.get_status()
    # Return config-only status
    statuses = email_auto_watcher.get_all_statuses()
    for s in statuses:
        if s.get("id") == watcher_id:
            return s
    raise HTTPException(status_code=404, detail=f"Watcher '{watcher_id}' not found")


@router.post("/email-watchers/{watcher_id}/start")
async def start_email_watcher(watcher_id: str):
    """Start a specific email auto-watcher."""
    from .. import email_auto_watcher
    watcher = email_auto_watcher.get_watcher(watcher_id)
    if watcher:
        if watcher.start():
            return {"status": "ok", "message": f"Watcher '{watcher_id}' started"}
        else:
            raise HTTPException(status_code=400, detail="Watcher already running")
    raise HTTPException(status_code=404, detail=f"Watcher '{watcher_id}' not found")


@router.post("/email-watchers/{watcher_id}/stop")
async def stop_email_watcher(watcher_id: str):
    """Stop a specific email auto-watcher."""
    from .. import email_auto_watcher
    watcher = email_auto_watcher.get_watcher(watcher_id)
    if watcher:
        watcher.stop()
        return {"status": "ok", "message": f"Watcher '{watcher_id}' stopped"}
    raise HTTPException(status_code=404, detail=f"Watcher '{watcher_id}' not found")


@router.post("/email-watchers/{watcher_id}/check")
async def check_email_watcher_now(watcher_id: str):
    """Force immediate check for a specific watcher."""
    from .. import email_auto_watcher
    watcher = email_auto_watcher.get_watcher(watcher_id)
    if watcher:
        result = watcher.check_now()
        return result
    raise HTTPException(status_code=404, detail=f"Watcher '{watcher_id}' not found")


@router.post("/email-watchers/{watcher_id}/clear-seen")
async def clear_email_watcher_seen(watcher_id: str):
    """Clear seen email IDs for testing."""
    from .. import email_auto_watcher
    watcher = email_auto_watcher.get_watcher(watcher_id)
    if watcher:
        watcher.clear_seen()
        return {"status": "ok", "message": f"Cleared seen emails for '{watcher_id}'"}
    raise HTTPException(status_code=404, detail=f"Watcher '{watcher_id}' not found")


@router.post("/email-watchers/{watcher_id}/clear-in-progress")
async def clear_email_watcher_in_progress(watcher_id: str):
    """Clear in-progress email IDs (for recovery from orphaned processing)."""
    from .. import email_auto_watcher
    watcher = email_auto_watcher.get_watcher(watcher_id)
    if watcher:
        watcher.clear_in_progress()
        return {"status": "ok", "message": f"Cleared in-progress emails for '{watcher_id}'"}
    raise HTTPException(status_code=404, detail=f"Watcher '{watcher_id}' not found")


@router.post("/email-watchers/reload")
async def reload_email_watchers():
    """Reload email auto-watcher configuration."""
    from .. import email_auto_watcher
    started = email_auto_watcher.reload_config()
    return {"status": "ok", "message": f"Config reloaded, {started} watchers started"}


# =============================================================================
# Scheduler Endpoints (Time-based Agent Execution)
# =============================================================================

@router.get("/schedules")
async def get_all_schedules():
    """Get all scheduler statuses."""
    from .. import scheduler
    return {"schedules": scheduler.get_all_statuses()}


@router.get("/schedules/{schedule_id}")
async def get_schedule_status(schedule_id: str):
    """Get specific schedule status."""
    from .. import scheduler
    schedule = scheduler.get_schedule(schedule_id)
    if schedule:
        return schedule.get_status()
    # Return config-only status
    statuses = scheduler.get_all_statuses()
    for s in statuses:
        if s.get("id") == schedule_id:
            return s
    raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")


@router.post("/schedules/{schedule_id}/start")
async def start_schedule(schedule_id: str):
    """Start a specific schedule."""
    from .. import scheduler
    schedule = scheduler.get_schedule(schedule_id)
    if schedule:
        if schedule.start():
            return {"status": "ok", "message": f"Schedule '{schedule_id}' started"}
        else:
            raise HTTPException(status_code=400, detail="Schedule already running or invalid")
    raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")


@router.post("/schedules/{schedule_id}/stop")
async def stop_schedule(schedule_id: str):
    """Stop a specific schedule."""
    from .. import scheduler
    schedule = scheduler.get_schedule(schedule_id)
    if schedule:
        schedule.stop()
        return {"status": "ok", "message": f"Schedule '{schedule_id}' stopped"}
    raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")


@router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: str):
    """Force immediate execution of a schedule."""
    from .. import scheduler
    schedule = scheduler.get_schedule(schedule_id)
    if schedule:
        result = schedule.run_now()
        return result
    raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")


@router.post("/schedules/reload")
async def reload_schedules():
    """Reload scheduler configuration."""
    from .. import scheduler
    started = scheduler.reload_config()
    return {"status": "ok", "message": f"Config reloaded, {started} schedules started"}
