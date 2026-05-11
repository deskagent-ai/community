# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Instagram MCP Server
====================
MCP server for Instagram Business/Creator account operations.

Provides media management, insights, comments, and messaging functionality
using Instagram Graph API with Meta (Facebook) OAuth2 authentication.

Configuration in apis.json:
    "instagram": {
        "enabled": true,
        "app_id": "YOUR_META_APP_ID",
        "app_secret": "YOUR_META_APP_SECRET",
        "redirect_port": 8081
    }

Setup:
    1. Create app at https://developers.facebook.com/apps/
    2. Add Instagram Basic Display and Instagram Graph API products
    3. Configure OAuth redirect URI: http://localhost:8081/
    4. Add app_id and app_secret to apis.json
    5. Connect a Facebook Page to an Instagram Business account
    6. Use instagram_authenticate() to sign in

Note: Instagram Graph API requires:
    - A Facebook Page
    - An Instagram Business or Creator account
    - The Instagram account must be connected to the Facebook Page
"""

from instagram.base import (
    mcp,
    HIGH_RISK_TOOLS,
    DESTRUCTIVE_TOOLS,
    is_configured,
    get_credentials,
    get_instagram_account_id,
    api_request,
    TOKEN_FILE,
    INSTAGRAM_SCOPES,
    start_auth_flow,
    complete_auth_flow,
)

# Import all tool modules to register them with FastMCP
from instagram import auth
from instagram import posts
from instagram import media
from instagram import insights

# Metadata for UI display
TOOL_METADATA = {
    "icon": "photo_camera",  # Google Material icon
    "color": "#E4405F",      # Instagram gradient pink
    "beta": True
}

# Integration Schema for WebUI Integrationen tab
INTEGRATION_SCHEMA = {
    "name": "Instagram",
    "icon": "photo_camera",
    "color": "#E4405F",
    "config_key": "instagram",
    "auth_type": "oauth",
    "beta": True,  # Mark as beta feature
    "oauth": {
        "custom_auth": True,  # Use MCP's own auth flow (start_auth_flow/complete_auth_flow)
        "token_file": ".instagram_token.json",
        "auth_url": "https://www.facebook.com/v18.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v18.0/oauth/access_token",
        "scopes": [
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_comments",
            "instagram_manage_insights",
            "instagram_manage_messages",
            "pages_read_engagement",
            "pages_show_list",
            "business_management",
        ],
        "scope_separator": ",",
        "config_keys": ["app_id", "app_secret"],
    },
    "setup": {
        "description": "Instagram Posts",
        "requirement": "Instagram Business Account",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Instagram verbinden",
        ],
    },
}

# OAuth Plugin Configuration - LEGACY, kept for compatibility
# TODO: Remove after full migration to INTEGRATION_SCHEMA
AUTH_CONFIG = {
    "type": "oauth2",
    "display_name": "Instagram",
    "auth_url": "https://www.facebook.com/v18.0/dialog/oauth",
    "token_url": "https://graph.facebook.com/v18.0/oauth/access_token",
    "scopes": INSTAGRAM_SCOPES,
    "config_keys": ["app_id", "app_secret"],
    "token_file": ".instagram_token.json",
    "scope_separator": ",",
    "custom_auth": True,  # Use MCP's own auth flow instead of generic
    "icon": "photo_camera",
    "color": "#E4405F",
}

__all__ = [
    'mcp',
    'HIGH_RISK_TOOLS',
    'DESTRUCTIVE_TOOLS',
    'is_configured',
    'get_credentials',
    'get_instagram_account_id',
    'api_request',
    'TOKEN_FILE',
    'TOOL_METADATA',
    'INTEGRATION_SCHEMA',
    'AUTH_CONFIG',  # Legacy, kept for compatibility
    'INSTAGRAM_SCOPES',
    'start_auth_flow',
    'complete_auth_flow',
]


def run():
    """Run the Instagram MCP server."""
    mcp.run()


if __name__ == "__main__":
    run()
