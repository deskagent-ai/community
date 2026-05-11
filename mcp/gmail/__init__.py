# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP Server
================
MCP server for Gmail and Google Calendar operations.

Provides email (search, read, send, labels, attachments) and
calendar (view, create events/meetings) functionality using
Google APIs with OAuth2 authentication.

Configuration in apis.json:
    "gmail": {
        "enabled": true,
        "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
        "client_secret": "YOUR_CLIENT_SECRET",
        "redirect_port": 8080
    }

Setup:
    1. Create project in Google Cloud Console
    2. Enable Gmail API and Google Calendar API
    3. Create OAuth 2.0 credentials (Desktop app type)
    4. Add client_id and client_secret to apis.json
    5. Use gmail_authenticate() to sign in
"""

from gmail.base import (
    mcp,
    HIGH_RISK_TOOLS,
    DESTRUCTIVE_TOOLS,
    is_configured,
    get_gmail_service,
    get_calendar_service,
    get_credentials,
    GMAIL_SCOPES,
    start_auth_flow,
    complete_auth_flow,
)

# Import all tool modules to register them with FastMCP
from gmail import auth
from gmail import gmail_email as email
from gmail import actions
from gmail import attachments
from gmail import gmail_calendar as calendar

# Metadata for UI display
TOOL_METADATA = {
    "icon": "mail",
    "color": "#EA4335"  # Google red
}

# Integration schema for WebUI Integrations tab (new format)
INTEGRATION_SCHEMA = {
    "name": "Gmail & Calendar",
    "icon": "mail",
    "color": "#EA4335",  # Google red
    "config_key": "gmail",
    "auth_type": "oauth",
    "oauth": {
        "custom_auth": True,  # Use MCP's own auth flow instead of generic
        "token_file": ".gmail_token.json",
        "auth_url": "https://accounts.google.com/o/oauth2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        "scope_separator": " ",
    },
    "fields": [
        {
            "key": "client_id",
            "label": "Client ID",
            "type": "text",
            "required": True,
            "hint": "Google Cloud Console OAuth 2.0 Client ID",
        },
        {
            "key": "client_secret",
            "label": "Client Secret",
            "type": "password",
            "required": True,
            "hint": "Google Cloud Console OAuth 2.0 Client Secret",
        },
    ],
    "setup": {
        "description": "Google Mail und Kalender",
        "requirement": "Google Konto",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Gmail verbinden",
        ],
    },
}

# Legacy AUTH_CONFIG for backward compatibility (will be removed in future version)
AUTH_CONFIG = {
    "type": "oauth2",
    "display_name": "Gmail & Calendar",
    "auth_url": "https://accounts.google.com/o/oauth2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "scopes": GMAIL_SCOPES,
    "config_keys": ["client_id", "client_secret"],
    "token_file": ".gmail_token.json",
    "scope_separator": " ",
    "custom_auth": True,  # Use MCP's own auth flow instead of generic
    "icon": "mail",
    "color": "#EA4335",
}

__all__ = [
    'mcp',
    'HIGH_RISK_TOOLS',
    'DESTRUCTIVE_TOOLS',
    'is_configured',
    'get_gmail_service',
    'get_calendar_service',
    'get_credentials',
    'TOOL_METADATA',
    'INTEGRATION_SCHEMA',
    'AUTH_CONFIG',
    'GMAIL_SCOPES',
    'start_auth_flow',
    'complete_auth_flow',
]
