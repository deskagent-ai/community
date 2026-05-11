# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Application Factory for DeskAgent.

Replaces the previous http.server based implementation with FastAPI + SSE.
"""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# Ensure path setup for imports
_current_dir = Path(__file__).parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR

TEMP_UPLOADS_DIR = PROJECT_DIR / ".temp" / "uploads"


def get_templates_dir() -> Path:
    """Get templates directory - evaluated at runtime to support --shared-dir reload."""
    import paths
    return paths.DESKAGENT_DIR / "scripts" / "templates"


def _cleanup_temp_uploads():
    """Clean up temporary uploaded files from .temp/uploads/"""
    try:
        if TEMP_UPLOADS_DIR.exists():
            import shutil
            file_count = len(list(TEMP_UPLOADS_DIR.iterdir()))
            if file_count > 0:
                shutil.rmtree(TEMP_UPLOADS_DIR)
                TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                system_log(f"[Cleanup] Deleted {file_count} temp files")
    except Exception as e:
        system_log(f"[Cleanup] Error: {e}")


def _init_system_log():
    """Initialize the system log file."""
    try:
        import ai_agent
        import platform

        log_path = ai_agent.init_system_log()

        # Load version info
        import paths
        version_file = paths.DESKAGENT_DIR / "version.json"
        version_info = {"version": "unknown", "build": 0}
        if version_file.exists():
            with open(version_file, "r") as f:
                version_info = json.load(f)

        import sys

        ai_agent.system_log(f"[Startup] DeskAgent v{version_info.get('version', '?')} (Build {version_info.get('build', '?')})")
        ai_agent.system_log(f"[Startup] Python {platform.python_version()} on {platform.system()} {platform.release()}")
        ai_agent.system_log(f"[Startup] Executable: {sys.executable}")
        ai_agent.system_log(f"[Startup] DeskAgent dir: {paths.DESKAGENT_DIR}")
        ai_agent.system_log(f"[Startup] Project dir: {paths.PROJECT_DIR}")
        ai_agent.system_log(f"[Startup] Workspace: {paths._get_workspace_dir()}")
        ai_agent.system_log(f"[Startup] Config: {paths.get_config_dir()}")
        ai_agent.system_log(f"[Startup] Log file: {log_path}")
    except Exception as e:
        system_log(f"[Startup] System log init error: {e}")


def _start_watchers():
    """Start email and Teams watchers if enabled."""
    from .skills import load_config

    # Email watcher
    try:
        from . import watchers
        config = load_config()
        if config.get("email_watchers", {}).get("enabled", False):
            watchers.start_watcher()
            system_log("[Startup] Email Watcher started")
    except Exception as e:
        system_log(f"[Startup] Email Watcher startup error: {e}")

    # Teams watcher
    try:
        from . import teams_watcher
        if teams_watcher.is_enabled():
            if teams_watcher.start_watcher():
                system_log("[Startup] Teams Watcher started")
    except Exception as e:
        system_log(f"[Startup] Teams Watcher startup error: {e}")

    # Email auto-watcher (Gmail + Office 365)
    try:
        from . import email_auto_watcher
        if email_auto_watcher.is_any_enabled():
            started = email_auto_watcher.start_all_watchers()
            system_log(f"[Startup] Email Auto-Watcher started ({started} watchers)")
    except Exception as e:
        system_log(f"[Startup] Email Auto-Watcher startup error: {e}")

    # Scheduler (time-based agent execution)
    try:
        from . import scheduler
        if scheduler.is_any_enabled():
            started = scheduler.start_all_schedules()
            system_log(f"[Startup] Scheduler started ({started} schedules)")
    except Exception as e:
        system_log(f"[Startup] Scheduler startup error: {e}")


def _stop_watchers():
    """Stop all watchers."""
    try:
        from . import watchers
        watchers.stop_watcher()
    except Exception:
        pass

    try:
        from . import teams_watcher
        teams_watcher.stop_watcher()
    except Exception:
        pass

    try:
        from . import email_auto_watcher
        email_auto_watcher.stop_all_watchers()
    except Exception:
        pass

    try:
        from . import scheduler
        scheduler.stop_all_schedules()
    except Exception:
        pass

    try:
        from .services.file_watcher import stop_file_watcher
        stop_file_watcher()
    except Exception:
        pass


def _resume_workflows():
    """Resume interrupted workflows from DB state."""
    try:
        from workflows import manager as workflow_manager
        resumed = workflow_manager.resume_all()
        if resumed > 0:
            system_log(f"[Startup] Resumed {resumed} interrupted workflow(s)")
    except Exception as e:
        system_log(f"[Startup] Workflow resume error: {e}")


def _init_license_manager():
    """Initialize license manager and attempt auto-resume."""
    try:
        from .services.license_manager import LicenseManager
        manager = LicenseManager.get_instance()
        if manager.auto_resume():
            system_log("[Startup] License session resumed automatically")
        else:
            system_log("[Startup] License: No active session (unlicensed)")
    except Exception as e:
        system_log(f"[Startup] License init error: {e}")


def _shutdown_license_manager():
    """End license session on app close."""
    try:
        from .services.license_manager import LicenseManager
        LicenseManager.get_instance().end_session()
    except Exception:
        pass


# Global startup state - server accepts requests immediately, heavy init runs in background
_startup_complete = False
_startup_error = None


def _background_startup():
    """Run heavy startup tasks in background thread."""
    global _startup_complete, _startup_error
    try:
        # Pre-load MCP tools (biggest latency saver)
        # This creates the tool schema cache that the proxy reads for fast startup
        try:
            from ai_agent.tool_bridge import warmup_mcp_tools
            warmup_mcp_tools()
        except Exception as e:
            system_log(f"[FastAPI] MCP warmup error: {e}")

        # Preload MCP prerequisites AFTER warmup (MCPs are now loaded)
        # This fills the config cache so UI shows correct badges after startup
        # NOTE (plan-048): No cache invalidation needed here - warmup already
        # produces fresh data. Invalidating after warmup caused double work.
        checked_mcps = []
        try:
            from .services.discovery import preload_prerequisites
            import asyncio

            # Run async preload in sync context
            loop = asyncio.new_event_loop()
            checked_mcps = loop.run_until_complete(preload_prerequisites())
            loop.close()
        except Exception as e:
            system_log(f"[Startup] Prerequisites preload error: {e}")

        # Start watchers
        _start_watchers()

        # Start file watcher for agent directories
        try:
            from .services.file_watcher import start_file_watcher
            from paths import PROJECT_DIR, DESKAGENT_DIR
            start_file_watcher([
                PROJECT_DIR / "agents",
                DESKAGENT_DIR / "agents",
                PROJECT_DIR / "config"
            ])
        except Exception as e:
            system_log(f"[Startup] File watcher error: {e}")

        # Resume interrupted workflows
        _resume_workflows()

        _startup_complete = True
        system_log("[FastAPI] Background startup complete")

        # Broadcast startup_complete event to all connected clients
        # This triggers UI refresh with correct prerequisites
        try:
            from .core.sse_manager import broadcast_global_event
            import time
            broadcast_global_event("startup_complete", {
                "timestamp": time.time(),
                "prerequisites_loaded": True,
                "mcps_checked": checked_mcps
            })
            system_log("[FastAPI] Sent startup_complete SSE event")
        except Exception as e:
            system_log(f"[FastAPI] SSE broadcast error: {e}")

    except Exception as e:
        _startup_error = str(e)
        system_log(f"[FastAPI] Background startup error: {e}")


def is_startup_complete() -> bool:
    """Check if background startup is complete."""
    return _startup_complete


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    global _startup_complete
    # Startup - minimal, so server accepts requests ASAP
    system_log("[FastAPI] Starting up (minimal)...")

    # Initialize system log (fast)
    _init_system_log()

    # Clean up temp uploads (fast)
    _cleanup_temp_uploads()

    # Register event loop for SSE manager (fast)
    from .core import set_event_loop
    loop = asyncio.get_running_loop()
    set_event_loop(loop)
    system_log("[FastAPI] SSE event loop registered")

    # Initialize license manager synchronously (fast, ~200ms)
    # Must happen before background thread so /license/status is ready immediately
    _init_license_manager()

    # Start heavy tasks in background thread
    import threading
    threading.Thread(target=_background_startup, daemon=True).start()
    system_log("[FastAPI] Background startup initiated")

    yield

    # Shutdown
    system_log("[FastAPI] Shutting down...")

    # End license session
    _shutdown_license_manager()

    _stop_watchers()


def create_external_api() -> FastAPI:
    """Create external API sub-application with limited endpoints."""
    external_app = FastAPI(
        title="DeskAgent External API",
        description="""
Limited API for external tools and integrations.

## Authentication

If `api.api_key` is set in system.json, include it in requests:
```
X-API-Key: your-key-here
```

## Endpoints

- **Discovery**: List agents, skills, backends
- **Status**: Health check, version info
- **Costs**: Read-only cost tracking
- **History**: Read-only session history
- **Execution**: Start agents (requires API key if configured)
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    from .routes.external_api import router as external_router
    external_app.include_router(external_router)

    return external_app


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Check if internal API docs should be disabled
    from .skills import load_config
    config = load_config()
    api_config = config.get("api", {})

    # Disable internal docs if api.internal_docs_enabled is False
    internal_docs_enabled = api_config.get("internal_docs_enabled", True)

    app = FastAPI(
        title="DeskAgent",
        description="AI-powered Desktop Assistant (Full API)",
        version="0.6.0",
        lifespan=lifespan,
        docs_url="/docs" if internal_docs_enabled else None,
        redoc_url="/redoc" if internal_docs_enabled else None,
        openapi_url="/openapi.json" if internal_docs_enabled else None
    )

    # CORS middleware - restrict to localhost only (any port)
    # Blocks cross-site requests from external domains while allowing local dev on any port
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$',
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    from .routes.tasks import router as tasks_router
    from .routes.system import router as system_router
    from .routes.ui import router as ui_router
    from .routes.execution import router as execution_router
    from .routes.watchers import router as watchers_router
    from .routes.testing import router as testing_router
    from .routes.msgraph import router as msgraph_router
    from .routes.transcription import router as transcription_router
    from .routes.browser_consent import router as browser_consent_router
    from .routes.workflows import router as workflows_router
    from .routes.history import router as history_router
    from .routes.oauth import router as oauth_router
    from .routes.integrations import router as integrations_router
    from .routes.license import router as license_router
    from .routes.mcp_api import router as mcp_api_router

    app.include_router(tasks_router, prefix="/task", tags=["tasks"])
    app.include_router(system_router, tags=["system"])
    app.include_router(ui_router, tags=["ui"])
    app.include_router(execution_router, tags=["execution"])
    app.include_router(watchers_router, tags=["watchers"])
    app.include_router(testing_router, tags=["testing"])
    app.include_router(msgraph_router, tags=["msgraph"])
    app.include_router(transcription_router, tags=["transcription"])
    app.include_router(browser_consent_router, tags=["browser"])
    app.include_router(workflows_router, tags=["workflows"])
    app.include_router(history_router, tags=["history"])
    app.include_router(oauth_router, tags=["oauth"])
    app.include_router(integrations_router, tags=["integrations"])
    app.include_router(license_router, tags=["license"])
    app.include_router(mcp_api_router, prefix="/api/mcp", tags=["mcp"])

    # Mount external API sub-application (separate Swagger docs)
    external_app = create_external_api()
    app.mount("/api/external", external_app)

    # Mount static files
    templates_dir = get_templates_dir()
    if templates_dir.exists():
        app.mount("/static", StaticFiles(directory=str(templates_dir)), name="static")

    # Global exception handler - logs all unhandled errors to system.log
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Log unhandled exceptions to system.log for easier debugging."""
        error_msg = f"[HTTP] Unhandled error on {request.method} {request.url.path}: {exc}"
        error_trace = traceback.format_exc()

        # Log to system.log
        system_log(f"\n{'='*60}")
        system_log(error_msg)
        # Log first few lines of traceback
        for line in error_trace.split('\n')[:10]:
            if line.strip():
                system_log(f"  {line}")
        system_log('='*60)

        # Return JSON error response
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "path": request.url.path}
        )

    return app


# For running with uvicorn directly: python -m uvicorn scripts.assistant.app:app
app = create_app()
