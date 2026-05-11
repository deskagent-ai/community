# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI System Routes
=====================
Handles status, version, costs, logs, and system info endpoints.
"""

import platform
import sys
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from ai_agent import log
from ..skills import load_config
from .. import cost_tracker
from .. import usage_tracker
from ..core.sse_manager import broadcast_global_event

# Path is set up by assistant/__init__.py
from paths import (
    PROJECT_DIR,
    DESKAGENT_DIR,
    get_skills_dir,
    get_agents_dir,
    get_config_dir,
    get_logs_dir,
    get_content_mode,
    _get_workspace_dir,
    _get_shared_dir,
)

# Alias private functions for use in this module
get_workspace_dir = _get_workspace_dir
get_shared_dir = _get_shared_dir

from ..core import (
    current_session,
    session_lock,
    conversation_history,
    server_start_time,
)

router = APIRouter()

# Import system_log for frontend logging
try:
    import ai_agent
    system_log = ai_agent.system_log
except (ImportError, AttributeError):
    system_log = lambda msg: print(msg)


# =============================================================================
# Frontend Logging
# =============================================================================

@router.post("/log")
async def frontend_log(data: dict):
    """Log messages from the frontend to system.log."""
    message = data.get("message", "")
    if message:
        system_log(message)
    return {"status": "ok"}


@router.post("/ui/heartbeat")
async def ui_heartbeat(data: dict = None):
    """Record a heartbeat from a UI client (browser tab).

    Called periodically by the WebUI to indicate the tab is still open.
    Used to prevent opening duplicate browser tabs on restart.
    """
    from ..state import record_ui_heartbeat
    client_id = data.get("client_id") if data else None
    record_ui_heartbeat(client_id)
    return {"status": "ok"}


@router.post("/shutdown-notify")
async def shutdown_notify():
    """Notify all connected clients that the server is restarting.

    Called by a new DeskAgent instance before killing this one.
    Broadcasts a 'server_restarting' event to all SSE clients.
    """
    system_log("[Shutdown] Received restart notification, notifying clients...")
    broadcast_global_event("server_restarting", {"reason": "restart"})
    return {"status": "ok"}


# =============================================================================
# Health & Status
# =============================================================================

@router.get("/status")
async def get_status():
    """Health check endpoint with startup status."""
    from ..app import is_startup_complete
    return {
        "status": "ok",
        "ready": is_startup_complete()
    }


@router.get("/content-mode")
async def get_content_mode_endpoint():
    """Get current content mode setting."""
    config = load_config()
    return {
        "mode": get_content_mode(),
        "show_selector": config.get("ui", {}).get("show_content_mode_selector", True)
    }


# =============================================================================
# Skills & Agents
# =============================================================================

@router.get("/skills")
async def list_skills():
    """List available skills."""
    skills = [f.stem for f in get_skills_dir().glob("*.md")]
    return {"skills": skills}


@router.get("/agents")
async def list_agents():
    """List available agents."""
    agents_dir = get_agents_dir()
    agents = [f.stem for f in agents_dir.glob("*.md")] if agents_dir.exists() else []
    return {"agents": agents}


@router.post("/agents/refresh")
async def refresh_agents():
    """Clear agent discovery cache and reload agents."""
    try:
        from ..services.discovery import clear_cache
        clear_cache(broadcast=True)
        return {"status": "ok", "message": "Agent cache cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/agents/{agent_name}/content")
async def get_agent_content(agent_name: str):
    """Get agent file content for editing."""
    # Check user agents first (editable)
    user_agents_dir = PROJECT_DIR / "agents"
    user_file = user_agents_dir / f"{agent_name}.md"
    if user_file.exists():
        content = user_file.read_text(encoding="utf-8")
        return {
            "name": agent_name,
            "content": content,
            "file_path": str(user_file),
            "source": "user",
            "editable": True
        }

    # Check system agents (read-only)
    system_agents_dir = DESKAGENT_DIR / "agents"
    system_file = system_agents_dir / f"{agent_name}.md"
    if system_file.exists():
        content = system_file.read_text(encoding="utf-8")
        return {
            "name": agent_name,
            "content": content,
            "file_path": str(system_file),
            "source": "system",
            "editable": False
        }

    raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")


@router.put("/agents/{agent_name}/content")
async def save_agent_content(agent_name: str, request: Request):
    """Save agent file content (user agents only)."""
    from ..services.discovery import clear_cache

    body = await request.json()
    content = body.get("content", "")

    user_agents_dir = PROJECT_DIR / "agents"
    user_file = user_agents_dir / f"{agent_name}.md"

    if not user_file.exists():
        system_file = DESKAGENT_DIR / "agents" / f"{agent_name}.md"
        if system_file.exists():
            raise HTTPException(status_code=403, detail="System agents cannot be edited")
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    try:
        user_file.write_text(content, encoding="utf-8")
        system_log(f"[Agents] Saved content for '{agent_name}'")
        clear_cache(broadcast=True)
        return {"status": "ok", "message": f"Agent '{agent_name}' saved"}
    except Exception as e:
        system_log(f"[Agents] Error saving '{agent_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_name}/toggle-hidden")
async def toggle_agent_hidden(agent_name: str):
    """Toggle hidden state for an agent (stored in user config/agents.json)."""
    import json

    try:
        # Load user agents.json (or create empty)
        agents_json_path = get_config_dir() / "agents.json"
        if agents_json_path.exists():
            with open(agents_json_path, "r", encoding="utf-8") as f:
                agents_config = json.load(f)
        else:
            agents_config = {}

        # Get current hidden state (default False)
        agent_config = agents_config.get(agent_name, {})
        current_hidden = agent_config.get("hidden", False)

        # Toggle the state
        new_hidden = not current_hidden

        # Update config
        if agent_name not in agents_config:
            agents_config[agent_name] = {}
        agents_config[agent_name]["hidden"] = new_hidden

        # Save
        with open(agents_json_path, "w", encoding="utf-8") as f:
            json.dump(agents_config, f, indent=2, ensure_ascii=False)

        system_log(f"[Agents] Toggled hidden for '{agent_name}': {new_hidden}")

        # Clear cache and broadcast change
        from ..services.discovery import clear_cache
        clear_cache(broadcast=True)

        return {
            "status": "ok",
            "agent": agent_name,
            "hidden": new_hidden
        }
    except Exception as e:
        system_log(f"[Agents] Error toggling hidden for '{agent_name}': {e}")
        return {"status": "error", "message": str(e)}


@router.get("/backends")
async def list_backends():
    """
    List all available AI backends (enabled AND properly configured).

    Returns:
        - enabled: List of available backend names (enabled + configured)
        - default: The default backend name
        - details: Dict with backend configs (without sensitive data)
        - all_backends: Dict of all backends with their availability status
    """
    config = load_config()
    ai_backends = config.get("ai_backends", {})
    default_backend = config.get("default_ai", "claude")

    enabled = []
    details = {}
    all_backends = {}

    for name, backend_config in ai_backends.items():
        backend_type = backend_config.get("type", "unknown")
        is_enabled = backend_config.get("enabled", True)

        # Check if backend is properly configured
        is_configured, config_issue = _check_backend_configured(backend_type, backend_config)

        # Build safe config (no API keys)
        safe_config = {
            "type": backend_type,
            "model": backend_config.get("model", backend_type),
            "configured": is_configured,
            "enabled": is_enabled,
        }

        # Add config issue if present
        if config_issue:
            safe_config["issue"] = config_issue

        # Add pricing if available
        if "pricing" in backend_config:
            safe_config["pricing"] = backend_config["pricing"]

        all_backends[name] = safe_config

        # Only add to enabled list if both enabled AND configured
        if is_enabled and is_configured:
            enabled.append(name)
            details[name] = safe_config

    # Build backends list for backward compatibility (webui-settings.js)
    backends_list = [
        {
            "id": name,
            "type": cfg.get("type", "unknown"),
            "model": cfg.get("model", ""),
            "enabled": cfg.get("enabled", True)
        }
        for name, cfg in ai_backends.items()
    ]

    return {
        "enabled": enabled,
        "default": default_backend,
        "count": len(enabled),
        "details": details,
        "all_backends": all_backends,
        "backends": backends_list  # Backward compat for webui-settings.js
    }


def _check_backend_configured(backend_type: str, backend_config: dict) -> tuple:
    """
    Check if a backend is properly configured by calling its own check_configured().

    Each backend module implements its own validation logic:
    - API backends check for valid API keys
    - CLI backends check if the CLI is installed
    - Ollama backends check if the server is reachable

    Args:
        backend_type: The type of backend (e.g., "claude_agent_sdk", "gemini_adk")
        backend_config: The backend configuration dict

    Returns:
        Tuple of (is_configured: bool, issue: str or None)
    """
    # Map backend types to their module names
    backend_modules = {
        "claude_agent_sdk": "claude_agent_sdk",
        "claude_api": "claude_api",
        "claude_cli": "claude_cli",
        "gemini_adk": "gemini_adk",
        "openai_api": "openai_api",
        "qwen_agent": "qwen_agent",
        "ollama_native": "ollama_native",
    }

    module_name = backend_modules.get(backend_type)
    if not module_name:
        # Unknown backend type - assume configured
        return True, None

    try:
        # Dynamically import the backend module
        import importlib
        module = importlib.import_module(f"ai_agent.{module_name}")

        # Call the backend's own check_configured function
        if hasattr(module, "check_configured"):
            return module.check_configured(backend_config)
        else:
            # Backend doesn't have check_configured - assume configured
            return True, None

    except ImportError as e:
        return False, f"Module not found: {e}"
    except Exception as e:
        return False, f"Check failed: {str(e)}"


# =============================================================================
# Pricing & Costs
# =============================================================================

@router.get("/pricing")
async def get_pricing():
    """Get pricing configuration for all backends including billable status."""
    config = load_config()
    pricing = config.get("pricing", {})
    backends_pricing = {}
    ai_backends = config.get("ai_backends", {})
    for backend_name, backend_config in ai_backends.items():
        backend_pricing = {}
        if "pricing" in backend_config:
            backend_pricing = backend_config["pricing"].copy()
        # Include billable status (default True for backwards compatibility)
        backend_pricing["billable"] = backend_config.get("billable", True)
        backends_pricing[backend_name] = backend_pricing
    pricing["backends"] = backends_pricing
    return pricing


@router.get("/costs")
async def get_costs_summary():
    """Get daily/monthly cost summary (with Anthropic data if available)."""
    summary = cost_tracker.get_summary()
    config = load_config()

    # Calculate billable costs (only backends with billable: true)
    ai_backends = config.get("ai_backends", {})
    full_costs = cost_tracker.get_costs()
    billable_total = 0.0
    by_backend = full_costs.get("by_backend", {})

    for backend_name, backend_costs in by_backend.items():
        # Check if this backend is billable (default True for backwards compat)
        is_billable = ai_backends.get(backend_name, {}).get("billable", True)
        if is_billable:
            billable_total += backend_costs.get("cost_usd", 0)

    summary["billable_total_usd"] = round(billable_total, 4)

    # Try to add Anthropic data if configured
    try:
        from .. import anthropic_admin
        if anthropic_admin.is_configured(config):
            cost_data = anthropic_admin.get_cost_report(config, use_cache=True)
            if "error" not in cost_data:
                transformed = anthropic_admin._transform_cost_data(cost_data)
                summary["anthropic_available"] = True
                summary["anthropic_total_usd"] = round(transformed.get("total_usd", 0), 4)
                summary["source"] = "anthropic"
            else:
                summary["anthropic_available"] = False
                summary["anthropic_error"] = cost_data["error"]
                summary["source"] = "local"
        else:
            summary["anthropic_available"] = False
            summary["source"] = "local"
    except ImportError:
        summary["anthropic_available"] = False
        summary["source"] = "local"
    except Exception as e:
        summary["anthropic_available"] = False
        summary["anthropic_error"] = str(e)
        summary["source"] = "local"

    return summary


@router.get("/costs/full")
async def get_costs_full():
    """Get detailed cost history with billable status per backend."""
    costs = cost_tracker.get_costs()
    config = load_config()
    ai_backends = config.get("ai_backends", {})

    # Add billable flag to each backend in by_backend
    for backend_name in costs.get("by_backend", {}):
        is_billable = ai_backends.get(backend_name, {}).get("billable", True)
        costs["by_backend"][backend_name]["billable"] = is_billable

    # Calculate billable totals
    billable_total = sum(
        data.get("cost_usd", 0)
        for name, data in costs.get("by_backend", {}).items()
        if data.get("billable", True)
    )
    costs["billable_total_usd"] = round(billable_total, 4)

    return costs


@router.get("/costs/anthropic")
async def get_anthropic_costs():
    """Get costs from Anthropic Admin API (if configured)."""
    try:
        from .. import anthropic_admin
        config = load_config()

        if not anthropic_admin.is_configured(config):
            return {"available": False, "message": "No admin_api_key configured in backends.json"}

        cost_report = anthropic_admin.get_cost_report(config)
        usage_report = anthropic_admin.get_usage_report(config, group_by=["model"])
        cache_status = anthropic_admin.get_cache_status()

        return {
            "available": True,
            "costs": cost_report,
            "usage": usage_report,
            "cache": cache_status
        }
    except ImportError:
        return {"available": False, "message": "anthropic_admin module not found"}
    except Exception as e:
        log(f"[Costs] Error fetching Anthropic data: {e}")
        return {"available": False, "error": str(e)}


@router.get("/costs/comparison")
async def get_costs_comparison():
    """Get costs comparison: local tracking vs Anthropic API."""
    config = load_config()
    comparison = cost_tracker.get_costs_with_anthropic(config)
    return comparison


@router.post("/costs/anthropic/refresh")
async def refresh_anthropic_costs():
    """Force refresh Anthropic costs (invalidate cache)."""
    try:
        from .. import anthropic_admin
        anthropic_admin.invalidate_cache()
        log("[Costs] Anthropic cache invalidated")
        return {"status": "ok", "message": "Cache invalidated - next request will fetch fresh data"}
    except ImportError:
        return {"error": "anthropic_admin module not available"}


# =============================================================================
# Usage Statistics
# =============================================================================

@router.get("/statistics/usage")
async def get_usage_statistics():
    """Get agent usage statistics (execution counts)."""
    return usage_tracker.get_agent_stats()


# =============================================================================
# Session
# =============================================================================

@router.get("/session")
async def get_session():
    """Get current session state."""
    with session_lock:
        session_data = current_session.copy()
        session_data["history_count"] = len(conversation_history)
    return session_data


# =============================================================================
# Version & Updates
# =============================================================================

@router.get("/version")
async def get_version():
    """Get local version info."""
    import updater
    version_info = updater.get_local_version()
    return version_info


@router.get("/version/check")
async def check_version():
    """Check for updates."""
    import updater
    result = updater.check_for_updates()
    return result


@router.get("/version/list")
async def list_versions():
    """List available versions."""
    import updater
    versions = updater.get_available_versions()
    return {"versions": versions}


@router.get("/update/check")
async def check_update():
    """Check if update is available."""
    try:
        import updater
        result = updater.check_for_updates()
        return {
            "update_available": result.get("update_available", False),
            "current_version": result.get("local_version", "unknown"),
            "latest_version": result.get("remote_version", "unknown"),
            "error": result.get("error")
        }
    except Exception as e:
        log(f"[Update Check] Error: {e}")
        return {"error": str(e)}


@router.get("/release/notes")
async def get_release_notes(version: Optional[str] = Query(None)):
    """Get release notes for a version."""
    try:
        import updater
        result = updater.get_release_notes(version)
        return result
    except Exception as e:
        log(f"[Release Notes] Error: {e}")
        return {"error": str(e)}


@router.get("/release/notes/{version}")
async def get_release_notes_by_path(version: str):
    """Get release notes for a specific version (path parameter)."""
    try:
        import updater
        result = updater.get_release_notes(version)
        return result
    except Exception as e:
        log(f"[Release Notes] Error: {e}")
        return {"error": str(e)}


# =============================================================================
# System Info & Logs
# =============================================================================

@router.get("/system/info")
async def get_system_info():
    """Get system information including ports, MCP status, and public API.

    Returns extended system info for Settings -> System tab:
    - version, build, python, platform, uptime
    - paths: all configured directories
    - ports: HTTP server, MCP proxy, FastMCP ports with status
    - mcp: current transport mode (sse/streamable-http)
    - public_api: URL and Swagger docs link for external integrations
    """
    import updater
    from ..state import get_active_port

    version_info = updater.get_local_version()

    # Calculate uptime
    uptime_seconds = int(time.time() - server_start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s"

    # Get port information
    http_port = get_active_port()

    # Get MCP proxy status
    try:
        from ..services.mcp_proxy_manager import (
            PROXY_PORT, _get_fastmcp_port, get_mcp_transport, is_proxy_running, get_proxy_status
        )
        mcp_status = get_proxy_status()
        mcp_proxy_port = PROXY_PORT
        fastmcp_port = _get_fastmcp_port()
        mcp_transport = get_mcp_transport()
        fastmcp_running = mcp_status.get("fastmcp", {}).get("port_open", False)
        mcp_proxy_running = mcp_status.get("filter_proxy", {}).get("port_open", False)
    except ImportError:
        mcp_proxy_port = 8766
        fastmcp_port = 19001
        mcp_transport = "sse"
        fastmcp_running = False
        mcp_proxy_running = False

    return {
        "version": version_info.get("version", "unknown"),
        "build": version_info.get("build", 0),
        "python": platform.python_version(),
        "platform": platform.system() + " " + platform.release(),
        "uptime": uptime_str,
        "paths": {
            "executable": str(Path(sys.executable).resolve().parent),
            "project": str(PROJECT_DIR),
            "deskagent": str(DESKAGENT_DIR),
            "workspace": str(get_workspace_dir()),
            "shared": str(get_shared_dir()),
            "config": str(get_config_dir()),
            "logs": str(get_logs_dir()),
            "agents": str(get_agents_dir()),
            "skills": str(get_skills_dir()),
            "plugins": str(PROJECT_DIR / "plugins")
        },
        # New fields for [014] System-Info Expansion
        "ports": {
            "http": http_port,
            "http_running": True,  # If we're responding, HTTP is running
            "mcp_proxy": mcp_proxy_port,
            "mcp_proxy_running": mcp_proxy_running,
            "fastmcp": fastmcp_port,
            "fastmcp_running": fastmcp_running
        },
        "mcp": {
            "transport": mcp_transport
        },
        "public_api": {
            "url": f"http://localhost:{http_port}/api/external",
            "docs": f"http://localhost:{http_port}/api/external/docs"
        }
    }


@router.get("/system/logs")
async def get_system_logs():
    """Get system, agent, and anonymization logs."""
    try:
        logs_dir = get_logs_dir()
        result = {}

        # System log (last 500 lines)
        system_log = logs_dir / "system.log"
        if system_log.exists():
            with open(system_log, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                last_lines = lines[-500:] if len(lines) > 500 else lines
                result["system"] = "".join(last_lines)
        else:
            result["system"] = "No system log found."

        # Agent log (full file)
        agent_log = logs_dir / "agent_latest.txt"
        if agent_log.exists():
            with open(agent_log, "r", encoding="utf-8", errors="replace") as f:
                result["agent"] = f.read()
        else:
            result["agent"] = "No agent log found."

        # Anonymization log (full file)
        anon_log = logs_dir / "anon_messages.log"
        if anon_log.exists():
            with open(anon_log, "r", encoding="utf-8", errors="replace") as f:
                result["anon"] = f.read()
        else:
            result["anon"] = "No anonymization log found.\n\nEnable 'use_anonymization_proxy: true' in backend config to see anonymization details."

        return result
    except Exception as e:
        return {"system": f"Error reading logs: {e}", "agent": "", "anon": ""}


# =============================================================================
# System Control (POST endpoints)
# =============================================================================

from pydantic import BaseModel
from fastapi import HTTPException
import subprocess
import threading


class ContentModeRequest(BaseModel):
    """Request body for content mode."""
    mode: str
    save: bool = True


class VersionInstallRequest(BaseModel):
    """Request body for version install."""
    version: str


@router.post("/costs/reset")
async def reset_costs():
    """Reset API costs to zero."""
    cost_tracker.reset_costs()
    log("[Costs] API costs reset to zero")
    return {"status": "ok", "message": "API costs reset"}


@router.post("/content-mode")
async def set_content_mode(body: ContentModeRequest):
    """Set content mode (custom, both, standard)."""
    try:
        from paths import set_content_mode as _set_content_mode, save_system_setting
    except ImportError:
        from paths import set_content_mode as _set_content_mode, save_system_setting

    if body.mode not in ("custom", "both", "standard"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {body.mode}")

    # Set runtime mode
    _set_content_mode(body.mode)

    # Persist to system.json if requested
    if body.save:
        save_system_setting("content_mode", body.mode)
        log(f"[Content Mode] Saved to system.json: {body.mode}")
    else:
        log(f"[Content Mode] Set runtime mode: {body.mode}")

    return {"status": "ok", "mode": body.mode}


class OpenUrlRequest(BaseModel):
    url: str


@router.post("/open-url")
async def open_url_in_browser(body: OpenUrlRequest):
    """Open URL in system browser."""
    import webbrowser

    url = body.url
    # Security: Only allow http/https URLs
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http/https URLs allowed")

    log(f"[Browser] Opening URL: {url}")
    webbrowser.open(url)
    return {"status": "ok", "url": url}


@router.post("/shutdown")
async def shutdown_server():
    """Shutdown the server."""
    from ..server import perform_cleanup, request_shutdown

    log("[HTTP] Shutdown requested via API")
    perform_cleanup()
    request_shutdown()
    return {"status": "ok", "message": "Shutdown initiated"}


@router.post("/update")
async def run_update():
    """Run update process."""
    import updater
    log("[Update] Starting update process...")
    result = updater.run_update()
    log(f"[Update] Result: {result}")
    return result


@router.post("/restart")
async def restart_server():
    """Restart the application."""
    import updater
    from ..server import request_shutdown

    log("[Restart] Restarting application...")

    # Schedule restart after response is sent
    def do_restart():
        import time
        time.sleep(1)
        updater.restart_app()
        request_shutdown()

    threading.Thread(target=do_restart, daemon=True).start()
    return {"success": True, "message": "Restarting..."}


@router.post("/version/install")
async def install_version(body: VersionInstallRequest):
    """Install a specific version (upgrade or downgrade)."""
    import updater
    log(f"[Update] Installing version {body.version}...")
    result = updater.install_version(body.version)
    log(f"[Update] Result: {result}")
    return result


@router.post("/system/open-logs")
async def open_logs_folder():
    """Open logs folder in file explorer (platform-specific)."""
    logs_dir = get_logs_dir()
    if logs_dir.exists():
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', str(logs_dir)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(logs_dir)])
        else:
            subprocess.Popen(['xdg-open', str(logs_dir)])
        return {"status": "ok"}
    else:
        raise HTTPException(status_code=404, detail="Logs directory not found")


@router.post("/system/open-log/{log_type}")
async def open_specific_log(log_type: str):
    """Open a specific log file in default editor."""
    logs_dir = get_logs_dir()

    # Map log type to filename
    log_files = {
        "system": "system.log",
        "agent": "agent_latest.txt",
        "anon": "anon_messages.log"
    }

    if log_type not in log_files:
        raise HTTPException(status_code=400, detail=f"Unknown log type: {log_type}")

    log_path = logs_dir / log_files[log_type]
    if log_path.exists():
        if sys.platform == 'win32':
            subprocess.Popen(['notepad', str(log_path)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(log_path)])
        else:
            subprocess.Popen(['xdg-open', str(log_path)])
        return {"status": "ok", "file": str(log_path)}
    else:
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_files[log_type]}")


@router.post("/logs/send")
async def send_logs_email():
    """Send system.log via email to support (Windows only, requires Outlook)."""
    from datetime import datetime
    import sys as _sys

    if _sys.platform != 'win32':
        raise HTTPException(status_code=501, detail="Log email sending requires Windows (Outlook)")

    config = load_config()
    app_config = config.get("app", {})
    support_email = app_config.get("support_email", config.get("support_email", "ask@deskagent.de"))

    log_path = get_logs_dir() / "system.log"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="System log file not found")

    # Import outlook_mcp
    mcp_dir = DESKAGENT_DIR / "mcp"
    if str(mcp_dir) not in _sys.path:
        _sys.path.insert(0, str(mcp_dir))

    import outlook_mcp

    subject = f"DeskAgent System Log - {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    body = "System Log im Anhang."

    result = outlook_mcp.create_new_email_with_attachment(
        to=support_email,
        subject=subject,
        body=body,
        attachment_path=str(log_path)
    )

    log(f"[Send Log] Created email draft to {support_email}")
    return {"status": "ok", "message": result}


# =============================================================================
# Developer Mode
# =============================================================================

@router.get("/config/developer_mode")
async def get_developer_mode():
    """Get developer mode status."""
    config = load_config()
    return {"enabled": config.get("developer_mode", False)}


class DevModeRequest(BaseModel):
    enabled: bool


@router.post("/config/developer_mode")
async def set_developer_mode(body: DevModeRequest):
    """Toggle developer mode in system.json."""
    from paths import save_system_setting

    # Save to system.json
    save_system_setting("developer_mode", body.enabled)
    log(f"[Config] Developer mode: {'enabled' if body.enabled else 'disabled'}")

    return {"status": "ok", "enabled": body.enabled}


# =============================================================================
# Global AI Backend Override
# =============================================================================

@router.get("/config/backend_override")
async def get_backend_override():
    """Get current global AI backend override and available backends.

    Returns:
        - backend: Current override value ("auto" if not set)
        - available_backends: List of configured backend IDs with display info
    """
    config = load_config()
    override = config.get("global_ai_override")
    ai_backends = config.get("ai_backends", {})

    # Build available backends list (only enabled + configured)
    available = []
    for name, backend_config in ai_backends.items():
        is_enabled = backend_config.get("enabled", True)
        if not is_enabled:
            continue
        backend_type = backend_config.get("type", "unknown")
        is_configured, _ = _check_backend_configured(backend_type, backend_config)
        if is_configured:
            available.append({
                "id": name,
                "model": backend_config.get("model", backend_type),
                "type": backend_type,
            })

    return {
        "backend": override if override else "auto",
        "available_backends": available,
    }


class BackendOverrideRequest(BaseModel):
    backend: str | None  # "auto", null, or a backend ID


@router.post("/config/backend_override")
async def set_backend_override(body: BackendOverrideRequest):
    """Set global AI backend override.

    Send "auto" or null to disable the override.
    Send a backend ID (e.g. "gemini") to force all agents to use that backend.
    """
    from paths import save_system_setting

    backend = body.backend

    # Normalize: "auto" and null both mean "no override"
    if backend == "auto" or backend is None:
        save_system_setting("global_ai_override", None)
        system_log("[Config] Global AI override: disabled (auto)")
        return {"status": "ok", "backend": "auto"}

    # Validate backend exists and is available
    config = load_config()
    ai_backends = config.get("ai_backends", {})
    if backend not in ai_backends:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}")

    backend_config = ai_backends[backend]
    if not backend_config.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"Backend '{backend}' is disabled")

    save_system_setting("global_ai_override", backend)
    system_log(f"[Config] Global AI override: {backend}")

    return {"status": "ok", "backend": backend}


# =============================================================================
# User Preferences
# =============================================================================

class PreferenceRequest(BaseModel):
    """Request body for saving a preference."""
    key: str  # Dot-notation key, e.g. "ui.selected_category"
    value: Any  # Can be str, bool, int, etc.


def _get_preferences_file() -> Path:
    """Get path to preferences.json in workspace/.state/"""
    state_dir = get_workspace_dir() / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "preferences.json"


def _load_preferences() -> dict:
    """Load preferences from workspace/.state/preferences.json"""
    import json
    prefs_file = _get_preferences_file()
    if prefs_file.exists():
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"[Preferences] Error loading: {e}")
    return {}


def _save_preferences(prefs: dict) -> None:
    """Save preferences to workspace/.state/preferences.json"""
    import json
    prefs_file = _get_preferences_file()
    try:
        with open(prefs_file, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"[Preferences] Error saving: {e}")


@router.get("/preferences")
async def get_preferences():
    """Get all user preferences."""
    prefs = _load_preferences()
    return prefs


@router.post("/preferences")
async def save_preference(body: PreferenceRequest):
    """Save a single user preference.

    Key uses dot-notation, e.g. "ui.selected_category" will be stored as:
    {"ui": {"selected_category": "value"}}
    """
    prefs = _load_preferences()

    # Parse dot-notation key and set value
    keys = body.key.split(".")
    current = prefs
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = body.value

    _save_preferences(prefs)
    log(f"[Preferences] Saved: {body.key} = {body.value}")

    # Broadcast to all clients (Quick Access, other windows)
    broadcast_global_event("preferences_changed", {
        "key": body.key,
        "value": body.value
    })

    return {"status": "ok", "key": body.key, "value": body.value}


# =============================================================================
# Simple Mode
# =============================================================================

def _get_simple_mode() -> bool:
    """Get current simple mode state from preferences."""
    prefs = _load_preferences()
    return prefs.get("ui", {}).get("simple_mode", False)


def _set_simple_mode(enabled: bool) -> None:
    """Set simple mode state in preferences."""
    prefs = _load_preferences()
    if "ui" not in prefs:
        prefs["ui"] = {}
    prefs["ui"]["simple_mode"] = enabled
    _save_preferences(prefs)
    log(f"[Simple Mode] {'Enabled' if enabled else 'Disabled'}")


@router.get("/simple-mode")
async def get_simple_mode():
    """Get current simple mode status."""
    return {"enabled": _get_simple_mode()}


@router.post("/toggle-simple-mode")
async def toggle_simple_mode():
    """Toggle simple mode on/off."""
    current = _get_simple_mode()
    new_state = not current
    _set_simple_mode(new_state)
    return {
        "enabled": new_state,
        "message": f"Simple mode {'enabled' if new_state else 'disabled'}"
    }


# =============================================================================
# Demo Mode
# =============================================================================

@router.get("/demo-mode")
async def get_demo_mode():
    """Get current demo mode status and configuration."""
    config = load_config()
    demo_config = config.get("demo_mode", {})
    return {
        "enabled": demo_config.get("enabled", False),
        "mocks_dir": demo_config.get("mocks_dir", "mocks"),
        "show_toggle": demo_config.get("show_toggle", True),
        "fallback_behavior": demo_config.get("fallback_behavior", "error"),
        "log_mock_usage": demo_config.get("log_mock_usage", True)
    }


class DemoModeRequest(BaseModel):
    """Request body for demo mode toggle."""
    enabled: bool


@router.post("/demo-mode")
async def set_demo_mode(body: DemoModeRequest):
    """Toggle demo mode on/off."""
    try:
        from paths import save_system_setting as _save_system_setting
    except ImportError:
        from paths import save_system_setting as _save_system_setting

    # Load current config to preserve other demo_mode settings
    config = load_config()
    demo_config = config.get("demo_mode", {})
    demo_config["enabled"] = body.enabled

    # Save updated demo_mode object to system.json
    _save_system_setting("demo_mode", demo_config)

    log(f"[Demo Mode] {'Enabled' if body.enabled else 'Disabled'}")

    return {
        "enabled": body.enabled,
        "message": f"Demo mode {'enabled' if body.enabled else 'disabled'}"
    }


# =============================================================================
# MCP Status
# =============================================================================

import importlib


def _get_mcp_info(mcp_name: str) -> dict:
    """Get MCP info including configured status, description, and metadata.

    Each MCP module should have:
    - is_configured() function to check its configuration requirements
    - TOOL_METADATA dict with icon, color, beta flag (optional)

    Description is extracted from the module docstring.
    """
    import sys as _sys
    result = {"configured": False, "description": None, "beta": False, "icon": "build", "color": "#757575"}

    try:
        # Handle plugin MCPs (format: "pluginName:mcpName")
        if ":" in mcp_name:
            # Plugin MCP - find the module via discovery and load from file
            try:
                from ai_agent.mcp_discovery import discover_mcp_servers
                servers = discover_mcp_servers()
                plugin_server = next((s for s in servers if s['name'] == mcp_name), None)
                if not plugin_server:
                    return result
                # Load module directly from file (avoids complex import path issues)
                init_file = plugin_server['path'] / "__init__.py"
                if not init_file.exists():
                    return result
                spec = importlib.util.spec_from_file_location(
                    f"plugin_mcp_{mcp_name.replace(':', '_')}", init_file
                )
                if not spec or not spec.loader:
                    return result
                module = importlib.util.module_from_spec(spec)
                # Add required paths for module dependencies
                plugin_mcp_parent = plugin_server['path'].parent
                if str(plugin_mcp_parent) not in _sys.path:
                    _sys.path.insert(0, str(plugin_mcp_parent))
                spec.loader.exec_module(module)
            except Exception as e:
                log(f"[MCP Status] Could not load plugin {mcp_name}: {e}")
                return result
        else:
            # Ensure MCP directory is in sys.path
            mcp_dir = DESKAGENT_DIR / "mcp"
            if str(mcp_dir) not in _sys.path:
                _sys.path.insert(0, str(mcp_dir))
            # Import the MCP module dynamically (package name = folder name)
            module = importlib.import_module(mcp_name)

        # Call its is_configured() function if it exists
        if hasattr(module, "is_configured"):
            result["configured"] = module.is_configured()
        else:
            result["configured"] = True

        # Get description from module docstring
        if module.__doc__:
            # Extract first meaningful line (skip title lines with ===)
            lines = [l.strip() for l in module.__doc__.strip().split('\n') if l.strip()]
            for line in lines:
                if not line.startswith('=') and len(line) > 5:
                    result["description"] = line
                    break

        # Get TOOL_METADATA (icon, color, beta flag)
        if hasattr(module, "TOOL_METADATA"):
            meta = module.TOOL_METADATA
            result["beta"] = meta.get("beta", False)
            result["icon"] = meta.get("icon", "build")
            result["color"] = meta.get("color", "#757575")

    except ImportError as e:
        log(f"[MCP Status] Could not import {mcp_name}: {e}")
    except Exception as e:
        log(f"[MCP Status] Error checking {mcp_name}: {e}")

    return result


@router.get("/mcp/status")
async def get_mcp_status():
    """Get status of all installed MCP servers."""
    mcps = []

    # Get MCP directory
    mcp_dir = DESKAGENT_DIR / "mcp"
    if not mcp_dir.exists():
        return {"mcps": []}

    # List all MCP subdirectories (each is an MCP server)
    for item in sorted(mcp_dir.iterdir()):
        if item.is_dir() and not item.name.startswith("_"):
            mcp_name = item.name

            # Check if it has __init__.py (is a valid package)
            init_file = item / "__init__.py"
            installed = init_file.exists()

            # Get MCP info (configured status, description, beta flag)
            mcp_info = _get_mcp_info(mcp_name) if installed else {
                "configured": False, "description": None, "beta": False
            }

            mcps.append({
                "name": mcp_name,
                "installed": installed,
                "configured": mcp_info["configured"],
                "description": mcp_info["description"],
                "beta": mcp_info.get("beta", False)
            })

    # Add plugin MCPs
    try:
        from assistant.services.plugins import get_plugin_mcp_dirs
        for plugin_name, plugin_mcp_dir in get_plugin_mcp_dirs():
            init_file = plugin_mcp_dir / "__init__.py"
            installed = init_file.exists()
            mcp_info = _get_mcp_info(plugin_name) if installed else {
                "configured": False, "description": None, "beta": False
            }
            mcps.append({
                "name": plugin_name,
                "installed": installed,
                "configured": mcp_info["configured"],
                "description": mcp_info["description"],
                "beta": mcp_info.get("beta", False),
                "plugin": True
            })
    except ImportError:
        pass

    return {"mcps": mcps}


def _extract_mcp_tools(mcp_name: str) -> list[dict]:
    """Extract tool names and descriptions from MCP using FastMCP internal API.

    Uses FastMCP's _tool_manager._tools to get the registered tools directly,
    which is cleaner than regex parsing.

    Args:
        mcp_name: Name of the MCP (e.g., 'outlook' or 'janitza:janitza' for plugins)

    Returns:
        List of dicts with 'name' and 'description' for each tool
    """
    import sys as _sys

    tools = []

    try:
        # Handle plugin MCPs (format: "pluginName:mcpName")
        if ":" in mcp_name:
            # Plugin MCP - find the module via discovery and load from file
            try:
                from ai_agent.mcp_discovery import discover_mcp_servers
                servers = discover_mcp_servers()
                plugin_server = next((s for s in servers if s['name'] == mcp_name), None)
                if not plugin_server:
                    return tools
                # Load module directly from file (avoids complex import path issues)
                init_file = plugin_server['path'] / "__init__.py"
                if not init_file.exists():
                    return tools
                spec = importlib.util.spec_from_file_location(
                    f"plugin_mcp_tools_{mcp_name.replace(':', '_')}", init_file
                )
                if not spec or not spec.loader:
                    return tools
                module = importlib.util.module_from_spec(spec)
                # Add required paths for module dependencies
                plugin_mcp_parent = plugin_server['path'].parent
                if str(plugin_mcp_parent) not in _sys.path:
                    _sys.path.insert(0, str(plugin_mcp_parent))
                spec.loader.exec_module(module)
            except Exception as e:
                log(f"[MCP Info] Could not load plugin {mcp_name}: {e}")
                return tools
        else:
            # Ensure MCP directory is in sys.path
            mcp_dir = DESKAGENT_DIR / "mcp"
            if str(mcp_dir) not in _sys.path:
                _sys.path.insert(0, str(mcp_dir))
            # Import the MCP module
            module = importlib.import_module(mcp_name)

        # Get the FastMCP instance
        mcp_instance = getattr(module, 'mcp', None)
        if not mcp_instance:
            return tools

        # Get tools from FastMCP _tool_manager (same approach as anonymization_proxy)
        registered_tools = []

        # Method 1: Check for _tool_manager._tools (FastMCP)
        if hasattr(mcp_instance, '_tool_manager'):
            tool_manager = mcp_instance._tool_manager
            if hasattr(tool_manager, '_tools'):
                registered_tools = list(tool_manager._tools.values())

        # Method 2: Check for _tools directly
        if not registered_tools and hasattr(mcp_instance, '_tools'):
            registered_tools = list(mcp_instance._tools.values())

        # Extract tool info
        for tool in registered_tools:
            # Get the actual function
            if callable(tool):
                func = tool
            elif hasattr(tool, 'fn'):
                func = tool.fn
            elif hasattr(tool, 'func'):
                func = tool.func
            else:
                continue

            func_name = getattr(func, '__name__', None)
            if not func_name:
                continue

            # Get description from docstring
            description = ""
            if func.__doc__:
                # Get first non-empty line of docstring
                lines = [l.strip() for l in func.__doc__.strip().split('\n') if l.strip()]
                if lines:
                    description = lines[0]

            tools.append({
                "name": func_name,
                "description": description
            })

    except ImportError as e:
        log(f"[MCP Info] Could not import {mcp_name}: {e}")
    except Exception as e:
        log(f"[MCP Info] Error getting tools from {mcp_name}: {e}")

    return tools


def _get_mcp_full_description(mcp_dir: Path) -> str | None:
    """Get full module docstring from MCP __init__.py.

    Args:
        mcp_dir: Path to the MCP package directory

    Returns:
        Full docstring (excluding title lines with ===) or None
    """
    init_file = mcp_dir / "__init__.py"
    if not init_file.exists():
        return None

    try:
        content = init_file.read_text(encoding="utf-8")

        # Extract module docstring (first triple-quoted string)
        import re
        docstring_match = re.match(r'^[^"\']*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', content, re.DOTALL)

        if docstring_match:
            docstring = docstring_match.group(1) or docstring_match.group(2) or ""

            # Filter out title lines (lines with only = or - characters)
            lines = docstring.strip().split('\n')
            filtered_lines = []
            for line in lines:
                stripped = line.strip()
                # Skip lines that are just separator characters
                if stripped and not all(c in '=-' for c in stripped):
                    filtered_lines.append(line)

            return '\n'.join(filtered_lines).strip()

    except Exception as e:
        log(f"[MCP Info] Error reading docstring from {init_file}: {e}")

    return None


@router.get("/mcp/info/{mcp_name:path}")
async def get_mcp_info_detailed(mcp_name: str):
    """Get detailed information about an MCP server including its tools.

    Args:
        mcp_name: Name of the MCP (e.g., 'outlook', 'billomat', 'janitza:janitza' for plugins)

    Returns:
        JSON with name, description, configured status, and list of tools
    """
    from fastapi import HTTPException

    # Handle plugin MCPs (format: "pluginName:mcpName")
    if ":" in mcp_name:
        # Plugin MCP - use discover_mcp_servers to find the correct path
        try:
            from ai_agent.mcp_discovery import discover_mcp_servers
            servers = discover_mcp_servers()
            plugin_server = next((s for s in servers if s['name'] == mcp_name), None)
            if not plugin_server:
                raise HTTPException(status_code=404, detail=f"Plugin MCP '{mcp_name}' not found")
            mcp_dir = plugin_server['path']
            init_file = mcp_dir / "__init__.py"
            if not init_file.exists():
                raise HTTPException(status_code=404, detail=f"Plugin MCP '{mcp_name}' is not a valid package")
        except ImportError:
            raise HTTPException(status_code=404, detail=f"Plugin MCP '{mcp_name}' not found (discovery unavailable)")
    else:
        # Standard MCP - check deskagent/mcp directory
        mcp_dir = DESKAGENT_DIR / "mcp" / mcp_name
        if not mcp_dir.exists() or not mcp_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"MCP '{mcp_name}' not found")
        init_file = mcp_dir / "__init__.py"
        if not init_file.exists():
            raise HTTPException(status_code=404, detail=f"MCP '{mcp_name}' is not a valid package (missing __init__.py)")

    # Get configured status using existing helper
    mcp_info = _get_mcp_info(mcp_name)

    # Get full description
    description = _get_mcp_full_description(mcp_dir)

    # Extract tools using FastMCP internal API
    tools = _extract_mcp_tools(mcp_name)

    return {
        "name": mcp_name,
        "description": description,
        "configured": mcp_info.get("configured", False),
        "tools": tools
    }


@router.get("/plugins/status")
async def get_plugins_status():
    """Get status of all installed plugins with their contents."""
    try:
        from assistant.services.plugins import list_plugins
        plugins = list_plugins()
        return {"plugins": plugins}
    except ImportError:
        return {"plugins": []}


# ============================================================================
# Anonymization Settings & Test Endpoints
# ============================================================================

@router.get("/anonymization/settings")
async def get_anonymization_settings():
    """Get anonymization settings from system.json.

    Also reports whether the underlying presidio/spaCy stack is actually
    available (`available`) so the WebUI can show a warning if
    `enabled=true` but the optional dependency is missing (AGPL /
    Community Edition without `pip install deskagent[anonymizer]`).
    """
    try:
        from config import load_config
        config = load_config()
        anon_settings = config.get("anonymization", {})
        enabled = anon_settings.get("enabled", False)

        # Probe runtime availability without crashing if the module
        # import itself fails (e.g. completely missing optional deps).
        available = False
        try:
            from ai_agent import anonymizer as _anon
            available = bool(_anon.is_available())
        except Exception:
            available = False

        return {
            "enabled": enabled,
            "log_anonymization": anon_settings.get("log_anonymization", False),
            "available": available,
            "warning": (
                "Anonymization is enabled but the presidio/spaCy stack is "
                "not installed. Install via: pip install \"deskagent[anonymizer]\" "
                "and download spaCy models."
            ) if (enabled and not available) else None,
        }
    except Exception as e:
        return {"error": str(e), "enabled": False, "log_anonymization": False, "available": False, "warning": None}


class AnonymizationSettingRequest(BaseModel):
    key: str  # "enabled" or "log_anonymization"
    value: bool


@router.post("/anonymization/settings")
async def set_anonymization_setting(body: AnonymizationSettingRequest):
    """Update an anonymization setting in system.json."""
    from paths import save_system_setting

    if body.key not in ("enabled", "log_anonymization"):
        return {"error": f"Invalid key: {body.key}"}

    # Save under anonymization section
    save_system_setting(f"anonymization.{body.key}", body.value)
    log(f"[Anonymization] Set {body.key} = {body.value}")

    return {"status": "ok", "key": body.key, "value": body.value}


@router.get("/anonymization/whitelist")
async def get_anonymization_whitelist():
    """Get merged whitelist from anonymizer configs."""
    try:
        from ai_agent.anonymizer import _load_anonymizer_config, _get_merged_whitelist
        from config import load_config

        config = load_config()
        whitelist = _get_merged_whitelist(config)
        anon_config = _load_anonymizer_config()

        return {
            "whitelist": sorted(whitelist),
            "count": len(whitelist),
            "known_persons": anon_config.get("known_persons", []),
            "known_companies": anon_config.get("known_companies", [])
        }
    except Exception as e:
        return {"error": str(e), "whitelist": [], "count": 0}


def _fetch_outlook_emails_sync(count: int = 10):
    """Fetch emails from PRIMARY inbox only (not all mailboxes).

    Uses GetFirst/GetNext for efficient iteration - stops early once we have enough.
    Windows only - requires Outlook COM.
    """
    import sys as _sys
    if _sys.platform != 'win32':
        return []  # Outlook not available on macOS/Linux

    import json
    from datetime import datetime, timedelta
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")

        # Get DEFAULT inbox (primary mailbox only)
        inbox = namespace.GetDefaultFolder(6)  # olFolderInbox
        mailbox_name = inbox.Parent.Name

        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)  # Newest first

        cutoff = datetime.now() - timedelta(days=7)
        emails = []

        # Use GetFirst/GetNext - more efficient than for-loop for early exit
        msg = messages.GetFirst()
        while msg and len(emails) < count:
            try:
                received_time = msg.ReceivedTime
                if hasattr(received_time, 'replace'):
                    received_time = received_time.replace(tzinfo=None)

                # Stop if we've gone past the cutoff (sorted newest first)
                if received_time < cutoff:
                    break

                body = msg.Body or ""
                emails.append({
                    "entry_id": msg.EntryID,
                    "subject": msg.Subject or "",
                    "sender": msg.SenderName or "",
                    "sender_email": msg.SenderEmailAddress or "",
                    "received": received_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "mailbox": mailbox_name,
                    "folder": "Inbox",
                    "body_preview": body[:300].replace('\r\n', ' ').replace('\n', ' ').strip(),
                    "body": body[:2000]
                })
            except Exception:
                pass
            msg = messages.GetNext()

        return json.dumps(emails, ensure_ascii=False)
    finally:
        pythoncom.CoUninitialize()


def _fetch_graph_emails_sync(count: int):
    """Synchronous helper to fetch Graph emails (runs in thread pool)."""
    import sys as _sys
    mcp_dir = DESKAGENT_DIR / "mcp"
    if str(mcp_dir) not in _sys.path:
        _sys.path.insert(0, str(mcp_dir))
    from msgraph.msgraph_email import graph_get_recent_emails
    from msgraph.msgraph_auth import graph_status
    status_result = graph_status()
    if "authenticated" in status_result.lower() and "true" in status_result.lower():
        return graph_get_recent_emails(days=7, limit=count)
    return None


@router.post("/anonymization/test")
async def test_anonymization(count: int = 5):
    """Test anonymization on recent emails."""
    import json as json_module
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        from config import load_config
        from ai_agent.anonymizer import anonymize, _get_merged_whitelist

        config = load_config()
        whitelist = _get_merged_whitelist(config)
        emails = []
        source = None

        outlook_error = None
        graph_error = None

        # Run blocking calls in thread pool to avoid blocking async loop
        from functools import partial
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            # Try Outlook COM first (primary inbox only)
            try:
                result = await loop.run_in_executor(executor, partial(_fetch_outlook_emails_sync, count))
                log(f"[Anon Test] Outlook result: {result[:200] if result else 'None'}...")
                if result and not result.startswith("Error") and not result.startswith("Fehler"):
                    data = json_module.loads(result)
                    if isinstance(data, list) and len(data) > 0:
                        emails = data
                        source = "Outlook Desktop - Primary Inbox"
                    else:
                        outlook_error = "No emails in result"
                elif result:
                    outlook_error = result[:100]
            except Exception as e:
                outlook_error = str(e)
                log(f"[Anon Test] Outlook exception: {e}")

            # Try Graph API if Outlook failed (also in thread pool)
            if not emails:
                try:
                    result = await loop.run_in_executor(executor, partial(_fetch_graph_emails_sync, count))
                    log(f"[Anon Test] Graph result: {result[:200] if result else 'None'}...")
                    if result and not result.startswith("Error") and not result.startswith("Fehler"):
                        data = json_module.loads(result)
                        if isinstance(data, list) and len(data) > 0:
                            emails = data
                            source = "Microsoft Graph API"
                        else:
                            graph_error = "No emails in result"
                    elif result:
                        graph_error = result[:100]
                    else:
                        graph_error = "Not authenticated or no result"
                except Exception as e:
                    graph_error = str(e)
                    log(f"[Anon Test] Graph exception: {e}")

        if not emails:
            error_details = []
            if outlook_error:
                error_details.append(f"Outlook: {outlook_error}")
            if graph_error:
                error_details.append(f"Graph: {graph_error}")
            return {
                "error": "No email source available",
                "details": " | ".join(error_details) if error_details else "Both sources failed silently",
                "results": [],
                "source": None
            }

        # Process each email (also in thread pool - Presidio is CPU-intensive)
        def process_emails_sync():
            results = []
            for email in emails:
                subject = email.get("subject", "(no subject)")
                sender = email.get("sender", "(unknown)")
                # Try different body field names (different MCPs use different names)
                body = email.get("body", email.get("body_preview", email.get("preview", "")))

                # Combine for testing
                test_text = f"Subject: {subject}\nFrom: {sender}\n\n{body}"

                # Run anonymization
                anonymized, context = anonymize(test_text, config)

                # Find whitelist hits (terms preserved)
                whitelist_hits = []
                for term in whitelist:
                    if term.lower() in test_text.lower() and term.lower() in anonymized.lower():
                        whitelist_hits.append(term)

                results.append({
                    "subject": subject,
                    "sender": sender,
                    "original": test_text[:1500] + ("..." if len(test_text) > 1500 else ""),
                    "anonymized": anonymized[:1500] + ("..." if len(anonymized) > 1500 else ""),
                    "mappings": context.mappings,
                    "entity_count": len(context.mappings),
                    "whitelist_protected": whitelist_hits[:10]
                })
            return results

        # Run anonymization in thread pool to avoid blocking async loop
        with ThreadPoolExecutor(max_workers=1) as executor:
            results = await loop.run_in_executor(executor, process_emails_sync)

        return {
            "source": source,
            "email_count": len(results),
            "results": results,
            "whitelist_count": len(whitelist)
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc(), "results": []}


# =============================================================================
# Claude Desktop Integration
# =============================================================================

@router.get("/claude-desktop/status")
async def get_claude_desktop_status():
    """Get Claude Desktop integration status and config."""
    import json
    import os
    from config import load_config

    config = load_config()
    cd_config = config.get("claude_desktop", {})

    # Check if Claude Desktop config exists and has deskagent
    configured = False
    config_path = ""
    try:
        import sys as _sys
        if _sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                config_path = os.path.join(appdata, "Claude", "claude_desktop_config.json")
        elif _sys.platform == "darwin":
            config_path = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
        else:
            config_path = os.path.expanduser("~/.config/Claude/claude_desktop_config.json")

        if config_path and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                desktop_config = json.loads(f.read())
            mcp_servers = desktop_config.get("mcpServers", {})
            configured = "deskagent" in mcp_servers
    except Exception:
        pass

    # Check if proxy is running
    proxy_running = False
    try:
        from services.mcp_proxy_manager import _get_fastmcp_port
        import urllib.request
        port = _get_fastmcp_port()
        req = urllib.request.Request(f"http://localhost:{port}/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            proxy_running = resp.status == 200
    except Exception:
        pass

    return {
        "hub_enabled": cd_config.get("hub_enabled", False),
        "auth_token": cd_config.get("auth_token", ""),
        "port": cd_config.get("port", 19001),
        "configured_in_claude": configured,
        "config_path": config_path,
        "proxy_running": proxy_running,
        "allowed_mcps": cd_config.get("allowed_mcps", []),
    }


class ClaudeDesktopSettingRequest(BaseModel):
    hub_enabled: bool = None
    port: int = None


@router.post("/claude-desktop/settings")
async def set_claude_desktop_settings(body: ClaudeDesktopSettingRequest):
    """Update Claude Desktop integration settings."""
    from paths import save_system_setting

    if body.hub_enabled is not None:
        save_system_setting("claude_desktop.hub_enabled", body.hub_enabled)
        log(f"[ClaudeDesktop] hub_enabled = {body.hub_enabled}")

        # Start/stop proxy
        if body.hub_enabled:
            try:
                from services.mcp_proxy_manager import start_hub_if_enabled
                start_hub_if_enabled()
            except Exception as e:
                log(f"[ClaudeDesktop] Failed to start hub: {e}")

    if body.port is not None and 1024 <= body.port <= 65535:
        save_system_setting("claude_desktop.port", body.port)
        log(f"[ClaudeDesktop] port = {body.port}")

    return {"status": "ok"}


@router.post("/claude-desktop/setup")
async def setup_claude_desktop():
    """Configure Claude Desktop to use DeskAgent as MCP hub."""
    import os
    try:
        import sys as _sys
        # routes/system.py -> routes/ -> assistant/ -> scripts/ -> deskagent/
        deskagent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        mcp_desk_dir = os.path.join(deskagent_dir, "mcp", "desk")
        mcp_dir = os.path.join(deskagent_dir, "mcp")
        for p in (mcp_desk_dir, mcp_dir):
            if p not in _sys.path:
                _sys.path.insert(0, p)

        from claude_desktop import desk_setup_claude_desktop
        result = desk_setup_claude_desktop(transport="stdio")
        return {"status": "ok", "result": result}
    except Exception as e:
        import traceback
        log(f"[ClaudeDesktop] Setup failed: {e}")
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


@router.post("/claude-desktop/remove")
async def remove_claude_desktop():
    """Remove DeskAgent from Claude Desktop config."""
    import os
    try:
        import sys as _sys
        deskagent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        mcp_desk_dir = os.path.join(deskagent_dir, "mcp", "desk")
        mcp_dir = os.path.join(deskagent_dir, "mcp")
        for p in (mcp_desk_dir, mcp_dir):
            if p not in _sys.path:
                _sys.path.insert(0, p)

        from claude_desktop import desk_remove_claude_desktop
        result = desk_remove_claude_desktop()
        return {"status": "ok", "result": result}
    except Exception as e:
        log(f"[ClaudeDesktop] Remove failed: {e}")
        return {"status": "error", "error": str(e)}


def _get_available_mcps() -> list[str]:
    """Scan MCP directories and return sorted list of available MCP names.

    Includes both system MCPs (deskagent/mcp/) and plugin MCPs (plugins/*/mcp/).
    Excludes __pycache__, desk, and directories starting with _ or .
    """
    from paths import get_mcp_dir

    mcp_dir = get_mcp_dir()
    skip_dirs = {"__pycache__", "desk"}
    available = []
    if mcp_dir.exists():
        for entry in mcp_dir.iterdir():
            if entry.is_dir() and entry.name not in skip_dirs and not entry.name.startswith(("_", ".")):
                available.append(entry.name)

    # Add plugin MCPs
    try:
        from assistant.services.plugins import get_plugin_mcp_dirs
        for plugin_name, _ in get_plugin_mcp_dirs():
            if plugin_name not in available:
                available.append(plugin_name)
    except ImportError:
        pass

    available.sort()
    return available


@router.get("/claude-desktop/allowed-mcps")
async def get_allowed_mcps():
    """Get allowed MCPs for Claude Desktop and list of all available MCPs."""
    from config import load_config

    config = load_config()
    cd_config = config.get("claude_desktop", {})
    allowed_mcps = cd_config.get("allowed_mcps", [])
    available_mcps = _get_available_mcps()

    return {
        "allowed_mcps": allowed_mcps,
        "available_mcps": available_mcps,
    }


class AllowedMcpsRequest(BaseModel):
    allowed_mcps: list[str] = []


@router.post("/claude-desktop/allowed-mcps")
async def set_allowed_mcps(body: AllowedMcpsRequest):
    """Save allowed MCPs list for Claude Desktop to system.json."""
    from paths import save_system_setting

    save_system_setting("claude_desktop.allowed_mcps", body.allowed_mcps)
    log(f"[ClaudeDesktop] allowed_mcps = {body.allowed_mcps}")

    return {"status": "ok", "allowed_mcps": body.allowed_mcps}
