# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP Server
==========================
MCP Server for Microsoft 365 access via Graph API.
Enables server-side email search that finds ALL emails (not just locally cached).

Requires Azure AD app registration with delegated permissions:
- Mail.Read (read emails)
- Mail.ReadWrite (for future write operations)
- User.Read (basic profile)

Authentication: Device Code Flow (interactive, user-consented)

This package is split into modules for better maintainability:
- base.py: Configuration, authentication, helper classes
- auth.py: Authentication tools (device code flow)
- email.py: Email search, read, and management tools
- teams.py: Teams chat and channel tools
- watcher.py: Teams channel watcher setup and polling
"""

from _mcp_api import load_config

# Import the shared MCP instance and tool sets from base
from msgraph.base import mcp, HIGH_RISK_TOOLS, READ_ONLY_TOOLS, DESTRUCTIVE_TOOLS, DEFAULT_CLIENT_ID

# Import all modules to register their tools with mcp
from msgraph import auth
from msgraph import msgraph_email as email
from msgraph import teams
from msgraph import watcher
from msgraph import msgraph_calendar as calendar
from msgraph import actions

# Integration schema for WebUI Integrations tab (new format)
INTEGRATION_SCHEMA = {
    "name": "Microsoft 365",
    "icon": "cloud",
    "color": "#0078D4",  # Microsoft blue
    "config_key": "msgraph",
    "auth_type": "oauth",
    "oauth": {
        "custom_auth": True,  # MCP handles its own auth flow (MSAL Device Code)
        "token_file": ".msgraph_token_cache.json",
    },
    "fields": [
        {
            "key": "client_id",
            "label": "Client ID",
            "type": "text",
            "required": False,
            "hint": "Optional: Eigene Azure AD App",
        },
        {
            "key": "tenant_id",
            "label": "Tenant ID",
            "type": "text",
            "required": False,
            "default": "common",
            "hint": "Optional: 'common' für Multi-Tenant, oder spezifische Tenant-ID",
        },
    ],
    "setup": {
        "description": "E-Mail, Kalender, Teams via Graph API",
        "requirement": "Microsoft 365 Konto (geschäftlich oder privat)",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Microsoft 365 verbinden",
        ],
    },
}

# Legacy AUTH_CONFIG for backward compatibility (will be removed in future version)
AUTH_CONFIG = {
    "type": "oauth2",
    "display_name": "Microsoft 365",
    "custom_auth": True,  # MCP handles its own auth flow (MSAL Device Code)
    "config_keys": [],    # No API keys needed (preconfigured multi-tenant app)
    "token_file": ".msgraph_token_cache.json",
    "icon": "cloud",
    "color": "#0078D4",   # Microsoft blue
}

# Export the main entry points
__all__ = [
    'mcp', 'HIGH_RISK_TOOLS', 'READ_ONLY_TOOLS', 'DESTRUCTIVE_TOOLS',
    'is_configured', 'teams_poll_messages',
    'INTEGRATION_SCHEMA', 'AUTH_CONFIG', 'start_auth_flow', 'complete_auth_flow'
]

# Re-export teams_poll_messages for external use (by server.py watcher)
from msgraph.watcher import teams_poll_messages


def start_auth_flow():
    """Start MSAL device code authentication flow.

    Called by OAuth routes when user clicks "Connect" in Integrations tab.
    Returns the device code flow dict containing user_code and verification_uri.
    """
    from msgraph.base import start_device_code_flow
    return start_device_code_flow()


def complete_auth_flow(flow):
    """Complete MSAL device code flow after user has authenticated.

    Called by OAuth routes after start_auth_flow returns.
    Waits for user to complete login in browser.
    """
    from msgraph.base import complete_device_code_flow
    return complete_device_code_flow(flow)


def is_configured() -> bool:
    """Prüft ob Microsoft Graph API verfügbar und authentifiziert ist.

    Returns True nur wenn:
    1. msgraph nicht explizit deaktiviert ist
    2. User bereits authentifiziert ist (Token-Cache mit Accounts existiert)

    Ohne Authentifizierung zeigen Agents "Setup Missing" Badge.
    """
    config = load_config()
    msgraph = config.get("msgraph", {})

    # Check enabled flag (default: True if not set)
    if msgraph.get("enabled") is False:
        return False

    # Check if user has authenticated (token cache with accounts exists)
    try:
        from msgraph.base import TOKEN_CACHE_FILE
        import json

        if not TOKEN_CACHE_FILE.exists():
            return False

        # Parse token cache and check for accounts
        cache_data = json.loads(TOKEN_CACHE_FILE.read_text())
        # MSAL cache has "Account" key with account data
        accounts = cache_data.get("Account", {})
        if not accounts:
            return False

        return True
    except Exception as e:
        # Log the actual error so it's not silently swallowed
        try:
            from _mcp_api import mcp_log
            mcp_log(f"[MsGraph] is_configured() error: {e}")
        except Exception:
            pass
        return False


def run():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run()
