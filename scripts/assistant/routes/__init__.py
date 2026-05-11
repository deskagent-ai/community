# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Routes for DeskAgent.

All routes are now implemented as FastAPI routers:
- tasks.py: Task management + SSE streaming
- execution.py: Task starting (agents, skills, prompts)
- system.py: System status, version, costs, logs
- ui.py: Web UI serving and static files
- watchers.py: Email and Teams watcher endpoints
- msgraph.py: Microsoft Graph API settings
- history.py: Chat session history management
- oauth.py: Universal OAuth2 for MCP plugins
- integrations.py: Unified Integrations Hub API
- license.py: License status, activation, deactivation
- mcp_api.py: MCP API for Nuitka builds (config, paths, logging, anonymization)
"""

from .tasks import router as tasks_router
from .system import router as system_router
from .ui import router as ui_router
from .execution import router as execution_router
from .watchers import router as watchers_router
from .msgraph import router as msgraph_router
from .history import router as history_router
from .oauth import router as oauth_router
from .integrations import router as integrations_router
from .license import router as license_router
from .mcp_api import router as mcp_api_router

__all__ = [
    "tasks_router",
    "system_router",
    "ui_router",
    "execution_router",
    "watchers_router",
    "msgraph_router",
    "history_router",
    "oauth_router",
    "integrations_router",
    "license_router",
    "mcp_api_router",
]
