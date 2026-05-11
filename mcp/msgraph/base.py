# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Base Module
=================================
Configuration, authentication, and shared utilities.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from urllib.parse import quote
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, get_config_dir, mcp_log

# Import shared utilities
try:
    from mcp_shared.email_utils import extract_latest_message, html_to_text
except ImportError:
    def extract_latest_message(body, max_length=0): return body[:max_length] if max_length else body
    def html_to_text(content, mode="full"): return content

# Microsoft Authentication Library
try:
    import msal
    import requests
    MSAL_AVAILABLE = True
except ImportError:
    MSAL_AVAILABLE = False
    mcp_log("[MsGraph] MSAL not installed. Run: pip install msal requests")


mcp = FastMCP("msgraph")

# Tools that return external/untrusted content
HIGH_RISK_TOOLS = {
    # Email tools
    "graph_search_emails",
    "graph_get_email",
    "graph_get_recent_emails",
    "graph_get_folder_emails",
    "graph_get_flagged_emails",
    # Teams tools
    "teams_get_chats",
    "teams_get_messages",
    "teams_get_channel_messages",
    # Calendar tools (contain attendee names)
    "graph_get_upcoming_events",
    "graph_get_today_events",
}

# Read-only tools that only retrieve data without modifications
# Used by tool_mode: "read_only" to allow only safe operations
READ_ONLY_TOOLS = {
    # Email reading
    "graph_search_emails",
    "graph_get_email",
    "graph_get_recent_emails",
    "graph_get_folder_emails",
    "graph_get_flagged_emails",
    "graph_get_attachments",
    "graph_download_attachment",
    # Folder/category listing
    "graph_list_mailboxes",
    "graph_list_folders",
    "graph_list_categories",
    "graph_get_emails_by_category",
    # Calendar reading
    "graph_get_upcoming_events",
    "graph_get_today_events",
    # Teams reading
    "teams_get_chats",
    "teams_get_messages",
    "teams_list_teams",
    "teams_list_channels",
    "teams_get_channel_messages",
    # Status/auth
    "graph_status",
    "graph_authenticate",
    "graph_complete_auth",
}

# Destructive tools that create, send, or delete data (irreversible operations)
# Reversible operations (move, flag, categorize) are NOT in this set
DESTRUCTIVE_TOOLS = {
    # Email management
    "graph_delete_email",
    "graph_create_draft",
    "graph_create_reply_draft",
    # Calendar
    "graph_create_calendar_event",
    # Teams
    "teams_send_message",
    "teams_post_to_channel",
    "teams_post_webhook",
    "teams_post_to_configured_channel",
    "teams_setup_watcher",
}

# =============================================================================
# Configuration
# =============================================================================

# Default Azure AD app - DeskAgent official multi-tenant app
# Supports: Microsoft 365 Business, Personal Microsoft accounts
# Can be overridden in apis.json if user wants to use their own app
DEFAULT_CLIENT_ID = "5867d5ca-214e-493e-86e9-0d41134b6ae4"
DEFAULT_TENANT_ID = "common"  # "common" for multi-tenant + personal accounts

# Graph API endpoints
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = [
    # Email
    "Mail.Read", "Mail.ReadWrite", "Mail.Send",
    # Calendar
    "Calendars.Read", "Calendars.ReadWrite",
    # User
    "User.Read",
    # Teams Chat
    "Chat.Read", "Chat.ReadWrite", "ChatMessage.Send",
    # Teams Channels
    "Channel.ReadBasic.All", "ChannelMessage.Read.All", "ChannelMessage.Send",
    # Teams membership
    "Team.ReadBasic.All",
    # Note: offline_access is automatically added by MSAL and must NOT be in this list
    # (MSAL treats it as reserved and will throw an error if included)
]

# Token cache file (in project config directory)
TOKEN_CACHE_FILE = get_config_dir() / ".msgraph_token_cache.json"


def get_config():
    """Load Microsoft Graph configuration from apis.json."""
    try:
        config = load_config()
        return config.get("msgraph", {})
    except Exception as e:
        mcp_log(f"[MsGraph] Config load error: {e}")
    return {}


def get_client_id():
    """Get Azure AD client ID from config or default."""
    config = get_config()
    client_id = config.get("client_id")
    result = client_id if client_id else DEFAULT_CLIENT_ID
    mcp_log(f"[MsGraph] get_client_id: config={config}, client_id={client_id!r}, result={result[:8]}...")
    return result


def get_tenant_id():
    """Get Azure AD tenant ID from config or default."""
    config = get_config()
    return config.get("tenant_id") or DEFAULT_TENANT_ID


# =============================================================================
# Authentication
# =============================================================================

_token_cache = None
_app = None
_access_token = None
_token_expiry = None


def get_msal_app():
    """Get or create MSAL PublicClientApplication with persistent token cache."""
    global _app, _token_cache

    if not MSAL_AVAILABLE:
        raise RuntimeError("MSAL not installed. Run: pip install msal requests")

    if _app is None:
        # Load token cache from file
        _token_cache = msal.SerializableTokenCache()
        if TOKEN_CACHE_FILE.exists():
            try:
                _token_cache.deserialize(TOKEN_CACHE_FILE.read_text())
                mcp_log("[MsGraph] Loaded token cache from file")
            except Exception as e:
                mcp_log(f"[MsGraph] Token cache load error: {e}")

        client_id = get_client_id()
        tenant_id = get_tenant_id()
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        mcp_log(f"[MsGraph] Creating MSAL app: client_id={client_id[:8]}..., tenant_id={tenant_id}, authority={authority}")

        if not client_id:
            raise RuntimeError("No client_id available for MSAL authentication")

        _app = msal.PublicClientApplication(
            client_id=client_id,
            authority=authority,
            token_cache=_token_cache
        )

    return _app


def save_token_cache():
    """Save token cache to file."""
    global _token_cache
    if _token_cache and _token_cache.has_state_changed:
        try:
            TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE_FILE.write_text(_token_cache.serialize())
            mcp_log(f"[MsGraph] Saved token cache to {TOKEN_CACHE_FILE}")
        except Exception as e:
            msg = f"[MsGraph] Token cache save error (path={TOKEN_CACHE_FILE}): {e}"
            mcp_log(msg)
            print(msg, file=sys.stderr)


def require_auth(func):
    """Decorator to ensure authentication before API calls.

    Automatically checks for valid access token and returns error if not authenticated.
    This eliminates the need for manual token checking in every tool function.

    Usage:
        @mcp.tool()
        @require_auth
        def my_tool():
            # No need for manual token check
            # func will only execute if authenticated
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = get_access_token()
        if not token:
            return "ERROR: Not authenticated. Use graph_authenticate first."
        return func(*args, **kwargs)
    return wrapper


def get_access_token():
    """Get valid access token, refreshing or re-authenticating as needed."""
    global _access_token, _token_expiry

    # Return cached token if still valid
    if _access_token and _token_expiry and datetime.now() < _token_expiry:
        return _access_token

    app = get_msal_app()

    # Try to get token silently (from cache or refresh token)
    accounts = app.get_accounts()
    if accounts:
        mcp_log(f"[MsGraph] Found {len(accounts)} cached account(s), trying silent auth...")
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _access_token = result["access_token"]
            _token_expiry = datetime.now() + timedelta(seconds=result.get("expires_in", 3600) - 300)
            save_token_cache()
            mcp_log("[MsGraph] Silent auth successful")
            return _access_token

    # Need interactive auth - return None (will trigger device code flow)
    mcp_log("[MsGraph] No valid token, need interactive auth")
    return None


def start_device_code_flow():
    """Start device code authentication flow. Returns instructions for user."""
    mcp_log(f"[MsGraph] Starting device code flow...")
    app = get_msal_app()

    mcp_log(f"[MsGraph] MSAL app created, calling initiate_device_flow with scopes: {GRAPH_SCOPES}")
    flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
    mcp_log(f"[MsGraph] Device flow response: {flow}")

    if "user_code" not in flow:
        raise RuntimeError(f"Device flow failed: {flow.get('error_description', 'Unknown error')}")

    return flow


def complete_device_code_flow(flow: dict, timeout: int = 120):
    """Complete device code flow after user has authenticated."""
    global _access_token, _token_expiry

    app = get_msal_app()

    result = app.acquire_token_by_device_flow(flow, timeout=timeout)

    if "access_token" in result:
        _access_token = result["access_token"]
        _token_expiry = datetime.now() + timedelta(seconds=result.get("expires_in", 3600) - 300)
        save_token_cache()
        mcp_log("[MsGraph] Device code auth successful")
        return True
    else:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Authentication failed: {error}")


# =============================================================================
# Message Formatter Helper Class
# =============================================================================

class MessageFormatter:
    """Format Microsoft Graph messages for display.

    Consolidates common formatting patterns used across email and Teams tools.
    """

    @staticmethod
    def format_date(date_str: str, format_type: str = "short") -> str:
        """Format ISO datetime string for display.

        Args:
            date_str: ISO datetime string (e.g., "2025-01-15T10:30:00Z")
            format_type: "short" (DD.MM.YYYY), "datetime" (YYYY-MM-DD HH:MM), "time" (HH:MM)

        Returns:
            Formatted date string, or empty string if parsing fails
        """
        if not date_str:
            return ""
        try:
            if format_type == "short":
                # DD.MM.YYYY format
                dt = datetime.fromisoformat(date_str[:10])
                return dt.strftime("%d.%m.%Y")
            elif format_type == "datetime":
                # YYYY-MM-DD HH:MM format
                return date_str[:16].replace("T", " ")
            elif format_type == "time":
                return date_str[11:16] if len(date_str) > 16 else ""
            else:
                return date_str[:10]
        except (ValueError, IndexError):
            return date_str[:10] if len(date_str) >= 10 else date_str

    @staticmethod
    def format_email_address(email_obj: dict) -> str:
        """Format email address object as 'Name <email@example.com>'.

        Args:
            email_obj: Dict with 'emailAddress' containing 'name' and 'address'
                       OR direct dict with 'name' and 'address'

        Returns:
            Formatted string like "John Doe <john@example.com>" or just email
        """
        if not email_obj:
            return "Unknown"

        # Handle nested structure from Graph API
        if "emailAddress" in email_obj:
            email_obj = email_obj.get("emailAddress", {})

        name = email_obj.get("name", "")
        addr = email_obj.get("address", "")

        if name and addr:
            return f"{name} <{addr}>"
        return addr or name or "Unknown"

    @staticmethod
    def format_email_list_item(msg: dict, show_id: bool = True) -> str:
        """Format email message for list display.

        Args:
            msg: Email message dict from Graph API
            show_id: Whether to include message ID on separate line

        Returns:
            Formatted string like "- [15.01.2025] John <john@ex.com>: Subject [+]"
        """
        msg_id = msg.get("id", "")
        date_str = MessageFormatter.format_date(msg.get("receivedDateTime", ""), "short")
        from_str = MessageFormatter.format_email_address(msg.get("from", {}))
        subject = msg.get("subject", "(No subject)")

        # Badges
        badges = ""
        if not msg.get("isRead"):
            badges += " [NEW]"
        if msg.get("hasAttachments"):
            badges += " [+]"

        line = f"- [{date_str}] {from_str}: {subject}{badges}"
        if show_id and msg_id:
            line += f"\n  ID: {msg_id}"
            # Include conversation_id for thread deduplication
            conv_id = msg.get("conversationId", "")
            if conv_id:
                line += f"\n  conversation_id: {conv_id}"
        return line

    @staticmethod
    def format_teams_message(msg: dict, max_content_length: int = 200) -> str:
        """Format Teams chat/channel message for display.

        Args:
            msg: Teams message dict from Graph API
            max_content_length: Max characters of content to show

        Returns:
            Formatted string like "[2025-01-15 10:30] John: Message content..."
        """
        msg_time = MessageFormatter.format_date(msg.get("createdDateTime", ""), "datetime")

        # Get sender
        from_user = msg.get("from", {})
        if from_user:
            sender = from_user.get("user", {}).get("displayName", "Unknown")
        else:
            sender = "System"

        # Get content
        body = msg.get("body", {})
        content = body.get("content", "")

        # Strip HTML if present
        if body.get("contentType") == "html":
            content = html_to_text(content, mode="simple")

        # Truncate content
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."

        # Handle subject (for channel messages)
        subject = msg.get("subject", "")
        if subject:
            return f"[{msg_time}] {sender}: **{subject}** - {content[:150]}"
        return f"[{msg_time}] {sender}: {content}"


def graph_request(endpoint: str, method: str = "GET", params: dict = None, json_body: dict = None):
    """Make authenticated request to Microsoft Graph API."""
    token = get_access_token()
    if not token:
        raise RuntimeError("Not authenticated. Use graph_authenticate first.")

    url = f"{GRAPH_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": 'outlook.timezone="Europe/Berlin"'
    }

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=30
    )

    if response.status_code == 401:
        # Token expired, clear and retry
        global _access_token
        _access_token = None
        raise RuntimeError("Token expired. Re-authenticate with graph_authenticate.")

    response.raise_for_status()
    return response.json() if response.text else {}
