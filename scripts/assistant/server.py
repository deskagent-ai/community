# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI server for DeskAgent - Stream Deck and Web UI integration.

Uses FastAPI + uvicorn with Server-Sent Events (SSE) for real-time streaming.

Key components:
- app.py: FastAPI application factory with lifespan management
- routes/tasks.py: SSE streaming endpoint (/task/{id}/stream)
- routes/execution.py: Task starting endpoints (/agent, /skill, /prompt)
- routes/system.py: System status and configuration endpoints
- routes/ui.py: Web UI serving
- routes/watchers.py: Email and Teams watcher endpoints
- core/sse_manager.py: Thread-safe SSE event queue management
- core/executor.py: Task execution (run_tracked_task, run_tracked_agent, etc.)
- core/streaming.py: Streaming callbacks and de-anonymization
"""

import sys
from pathlib import Path

import ai_agent
from ai_agent import log
from .skills import clear_all_skill_contexts
from .core import (
    # Task state
    tasks as _tasks,
    tasks_lock as _tasks_lock,

    # Server state
    set_tray_icon,
    request_shutdown,

    # File utilities
    cleanup_temp_uploads,
    MCP_DIR,
)

# Path is set up by assistant/__init__.py
from paths import get_config_dir


# =============================================================================
# MCP Module Loading
# =============================================================================

# Cache for imported MCP modules
_mcp_module_cache = {}


def import_mcp_module(module_name: str):
    """Import an MCP module, ensuring the MCP directory is in sys.path.

    Consolidates the repeated pattern:
        import sys
        mcp_dir = DESKAGENT_DIR / "mcp"
        if str(mcp_dir) not in sys.path:
            sys.path.insert(0, str(mcp_dir))
        import module_name

    Args:
        module_name: Name of the MCP module (e.g., "msgraph_mcp", "outlook_mcp")

    Returns:
        The imported module
    """
    import importlib

    # Return cached module if already imported
    if module_name in _mcp_module_cache:
        return _mcp_module_cache[module_name]

    # Ensure MCP directory is in path
    if str(MCP_DIR) not in sys.path:
        sys.path.insert(0, str(MCP_DIR))

    # Import and cache the module
    module = importlib.import_module(module_name)
    _mcp_module_cache[module_name] = module
    return module


# =============================================================================
# Shutdown and Cleanup
# =============================================================================

def perform_cleanup():
    """Perform cleanup before shutdown."""
    log("[Shutdown] Starting cleanup...")

    # Cancel all running tasks
    with _tasks_lock:
        running_tasks = [tid for tid, task in _tasks.items() if task.get("status") == "running"]
        for task_id in running_tasks:
            log(f"[Shutdown] Cancelling task {task_id}")
            _tasks[task_id]["cancel_requested"] = True

    # Stop email watchers
    try:
        from . import watchers
        if watchers.is_running():
            log("[Shutdown] Stopping email watchers...")
            watchers.stop_watcher()
    except Exception as e:
        log(f"[Shutdown] Error stopping watchers: {e}")

    # Clear skill contexts
    try:
        clear_all_skill_contexts()
        log("[Shutdown] Cleared skill contexts")
    except Exception as e:
        log(f"[Shutdown] Error clearing skill contexts: {e}")

    # Clean up temp uploads
    cleanup_temp_uploads()

    # Clear browser/heartbeat state so next startup opens browser
    try:
        from .state import clear_ui_heartbeat, clear_browser_state
        clear_ui_heartbeat()
        clear_browser_state()
        log("[Shutdown] Cleared browser state")
    except Exception as e:
        log(f"[Shutdown] Error clearing browser state: {e}")

    log("[Shutdown] Cleanup completed")


# =============================================================================
# HTTP Server Entry Point
# =============================================================================

def start_http_server(port):
    """Start FastAPI server with uvicorn.

    Replaces the previous http.server based implementation with FastAPI + SSE.
    The FastAPI app handles all routes including SSE streaming.
    """
    import traceback

    # Initialize system log early so we can log errors
    ai_agent.init_system_log()

    # Use system_log for persistent logging (works in background mode too)
    def slog(msg):
        print(msg)
        ai_agent.system_log(msg)

    try:
        import uvicorn
    except ImportError as e:
        slog(f"[FastAPI] FATAL: Cannot import uvicorn: {e}")
        return

    slog(f"[FastAPI] Starting server on port {port}...")

    # AGPL/Community: Warn if anonymization is enabled but the
    # underlying presidio/spacy stack is not installed. Avoids silent
    # behavior where users think their data is anonymized when it isn't.
    try:
        from config import load_config
        cfg = load_config()
        if cfg.get("anonymization", {}).get("enabled", False):
            from ai_agent import anonymizer as _anon
            if not _anon.is_available():
                slog(
                    "[Anonymizer] WARNING: anonymization.enabled=true but "
                    "presidio/spaCy stack is not available. PII will NOT "
                    "be anonymized. Install via: "
                    "pip install \"deskagent[anonymizer]\" "
                    "and download spaCy models."
                )
    except Exception as e:
        slog(f"[Anonymizer] Startup check failed (non-fatal): {e}")

    try:
        # Create the FastAPI application
        from .app import create_app
        slog("[FastAPI] Creating app...")
        app = create_app()
        slog("[FastAPI] App created successfully")

        # Run with uvicorn
        # Use 0.0.0.0 for Docker/headless, localhost otherwise
        import os
        bind_host = os.environ.get("DESKAGENT_BIND_HOST", "localhost")

        # AGPL Section 13: When DeskAgent is bound to all interfaces it can
        # be reached over the network - which triggers the AGPL "remote
        # network interaction" clause if the operator has *modified*
        # DeskAgent. We log a one-time notice so operators are aware of
        # the source-disclosure obligation.
        if bind_host == "0.0.0.0":
            slog(
                "[FastAPI] AGPL Section 13 Notice: Running in network mode. "
                "If you offer this service to remote users AND have modified "
                "DeskAgent, you must provide source code access to those users. "
                "See knowledge/doc-licensing.md or contact info@realvirtual.io for "
                "Commercial License (removes AGPL obligations)."
            )

        slog(f"[FastAPI] Starting uvicorn on {bind_host}:{port}...")
        uvicorn.run(
            app,
            host=bind_host,
            port=port,
            log_level="warning",
            access_log=False
        )
    except Exception as e:
        error_msg = f"[FastAPI] Server error: {e}\n{traceback.format_exc()}"
        slog(error_msg)
    finally:
        slog("[FastAPI] Shutting down...")
        perform_cleanup()


# =============================================================================
# Backward Compatibility Exports
# =============================================================================

# Re-export task runners from core.executor for backward compatibility
# Routes and other modules can now import directly from core
from .core import (
    run_tracked_task,
    run_tracked_agent,
    run_tracked_prompt,
    run_tests,
    TaskCancelledException,
    create_streaming_callback,
    create_is_cancelled_callback,
)
