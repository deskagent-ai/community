# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP - Base Module
=======================
Configuration, authentication, and shared utilities for Gmail and Google Calendar.
"""

# CRITICAL: Setup embedded Python paths FIRST for Nuitka builds
try:
    import _path_setup
except ImportError:
    pass  # Not in Nuitka build

import json
import os
import sys
import base64
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, get_config_dir, mcp_log

# Alias for modules that expect system_log
system_log = mcp_log

# Import shared utilities
try:
    from mcp_shared.email_utils import extract_latest_message, html_to_text
except ImportError:
    def extract_latest_message(body, max_length=0): return body[:max_length] if max_length else body
    def html_to_text(content, mode="full"): return content

# Google API libraries
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import httplib2
    import google_auth_httplib2
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    mcp_log("[Gmail] Google API libraries not installed. Run: pip install google-auth google-auth-oauthlib google-api-python-client")

# API timeout in seconds (prevents hangs on network issues)
API_TIMEOUT = 30


mcp = FastMCP("gmail")

# Tools that return external/untrusted content (prompt injection risk)
HIGH_RISK_TOOLS = {
    "gmail_search_emails",
    "gmail_get_email",
    "gmail_get_recent_emails",
    "gmail_get_emails_by_label",
    "gmail_get_unread_emails",
    "gmail_get_starred_emails",
    "gmail_read_pdf_attachment",
}

# Destructive tools that create, send, or delete data (irreversible operations)
# Reversible operations (move, label, flag, mark_read) are NOT in this set
DESTRUCTIVE_TOOLS = {
    "gmail_create_draft",
    "gmail_create_reply_draft",
    "gmail_send_draft",
    "gmail_trash_email",
    "gmail_create_label",
    "gcal_create_event",
    "gcal_create_meeting",
}

# =============================================================================
# Configuration
# =============================================================================

# Google OAuth2 scopes
GMAIL_SCOPES = [
    # Gmail - read and modify
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.labels',
    # Google Calendar
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

# Token cache file
TOKEN_FILE = get_config_dir() / ".gmail_token.json"

# Default redirect port for OAuth2
DEFAULT_REDIRECT_PORT = 8080


def get_config():
    """Load Gmail configuration from apis.json."""
    try:
        config = load_config()
        return config.get("gmail", {})
    except Exception as e:
        mcp_log(f"[Gmail] Config load error: {e}")
    return {}


def is_configured() -> bool:
    """Check if Gmail MCP is configured and enabled.

    Returns True if:
    - gmail section exists in apis.json
    - enabled is not explicitly False
    - client_id and client_secret are set (or token exists)
    """
    config = get_config()

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    # Check if configured (credentials or existing token)
    has_credentials = bool(config.get("client_id") and config.get("client_secret"))
    has_token = TOKEN_FILE.exists()

    return has_credentials or has_token


def get_client_config():
    """Get OAuth2 client configuration for installed app flow."""
    config = get_config()
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    if not client_id or not client_secret:
        return None

    # Format as installed app credentials
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{get_redirect_port()}"]
        }
    }


def get_redirect_port():
    """Get OAuth2 redirect port from config."""
    config = get_config()
    return config.get("redirect_port", DEFAULT_REDIRECT_PORT)


# =============================================================================
# Authentication
# =============================================================================

_credentials = None
_gmail_service = None
_calendar_service = None


def get_credentials():
    """Get valid Google credentials, loading from cache or prompting for auth.

    Returns:
        google.oauth2.credentials.Credentials or None
    """
    global _credentials

    if not GOOGLE_API_AVAILABLE:
        raise RuntimeError("Google API libraries not installed. Run: pip install google-auth google-auth-oauthlib google-api-python-client")

    # Check cached credentials
    if _credentials and _credentials.valid:
        return _credentials

    # Try to load from file
    if TOKEN_FILE.exists():
        try:
            _credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), GMAIL_SCOPES)
            mcp_log("[Gmail] Loaded credentials from cache")
        except Exception as e:
            mcp_log(f"[Gmail] Failed to load token: {e}")
            _credentials = None

    # Refresh if expired
    if _credentials and _credentials.expired and _credentials.refresh_token:
        try:
            _credentials.refresh(Request())
            save_credentials(_credentials)
            mcp_log("[Gmail] Refreshed credentials")
            return _credentials
        except Exception as e:
            mcp_log(f"[Gmail] Refresh failed: {e}")
            _credentials = None

    return _credentials if (_credentials and _credentials.valid) else None


def save_credentials(creds):
    """Save credentials to file."""
    global _credentials
    _credentials = creds
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        mcp_log("[Gmail] Saved credentials to cache")
    except Exception as e:
        mcp_log(f"[Gmail] Failed to save credentials: {e}")


def clear_credentials():
    """Clear stored credentials."""
    global _credentials, _gmail_service, _calendar_service
    _credentials = None
    _gmail_service = None
    _calendar_service = None

    if TOKEN_FILE.exists():
        try:
            TOKEN_FILE.unlink()
            mcp_log("[Gmail] Cleared credentials")
        except Exception as e:
            mcp_log(f"[Gmail] Failed to delete token file: {e}")


def start_auth_flow():
    """Start OAuth2 authentication flow.

    Opens browser for Google sign-in. Returns the flow object
    that will receive the authorization code.

    Returns:
        InstalledAppFlow object
    """
    client_config = get_client_config()
    if not client_config:
        raise RuntimeError(
            "Gmail not configured. Add client_id and client_secret to apis.json under 'gmail' section.\n"
            "Get credentials from: https://console.cloud.google.com/apis/credentials"
        )

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=GMAIL_SCOPES,
        redirect_uri=f"http://localhost:{get_redirect_port()}"
    )

    return flow


def complete_auth_flow(flow) -> bool:
    """Complete OAuth2 flow by running local server.

    Opens browser and waits for user to authenticate.

    Args:
        flow: InstalledAppFlow from start_auth_flow()

    Returns:
        True if successful
    """
    global _credentials, _gmail_service, _calendar_service

    # Clear existing services
    _gmail_service = None
    _calendar_service = None

    # Run local server to receive callback
    creds = flow.run_local_server(
        port=get_redirect_port(),
        prompt="consent",  # Always show consent screen
        success_message="Authentication successful! You can close this window.",
        open_browser=True
    )

    save_credentials(creds)
    _credentials = creds
    return True


def require_auth(func):
    """Decorator to ensure authentication before API calls.

    Usage:
        @mcp.tool()
        @require_auth
        def my_tool():
            # Will only execute if authenticated
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        creds = get_credentials()
        if not creds:
            # Auto-trigger authentication
            mcp_log("[Gmail] Not authenticated, starting auth flow...")
            try:
                flow = start_auth_flow()
                if complete_auth_flow(flow):
                    mcp_log("[Gmail] Auto-auth successful, continuing...")
                    # Retry getting credentials
                    creds = get_credentials()
                    if creds:
                        return func(*args, **kwargs)
            except Exception as e:
                mcp_log(f"[Gmail] Auto-auth failed: {e}")
            return "ERROR: Gmail authentication required. Please complete the sign-in in your browser."
        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# API Services
# =============================================================================

def get_gmail_service():
    """Get authenticated Gmail API service with timeout."""
    global _gmail_service

    creds = get_credentials()
    if not creds:
        raise RuntimeError("Not authenticated. Use gmail_authenticate first.")

    if _gmail_service is None:
        # Create HTTP client with timeout to prevent hangs
        http = httplib2.Http(timeout=API_TIMEOUT)
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
        _gmail_service = build('gmail', 'v1', http=authed_http)
        mcp_log(f"[Gmail] Created Gmail service (timeout={API_TIMEOUT}s)")

    return _gmail_service


def get_calendar_service():
    """Get authenticated Google Calendar API service with timeout."""
    global _calendar_service

    creds = get_credentials()
    if not creds:
        raise RuntimeError("Not authenticated. Use gmail_authenticate first.")

    if _calendar_service is None:
        # Create HTTP client with timeout to prevent hangs
        http = httplib2.Http(timeout=API_TIMEOUT)
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
        _calendar_service = build('calendar', 'v3', http=authed_http)
        mcp_log(f"[Gmail] Created Calendar service (timeout={API_TIMEOUT}s)")

    return _calendar_service


# =============================================================================
# Error Handling Decorator
# =============================================================================

def gmail_tool(func):
    """Decorator for consistent error handling and logging."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            error_msg = f"Gmail API error: {e.resp.status} - {e.reason}"
            mcp_log(f"[Gmail] [{func.__name__}] {error_msg}")
            return f"ERROR: {error_msg}"
        except Exception as e:
            import traceback
            mcp_log(f"[Gmail] [{func.__name__}] Error: {e}")
            mcp_log(f"[Gmail] [{func.__name__}] Traceback: {traceback.format_exc()}")
            return f"ERROR: {str(e)}"
    return wrapper


# =============================================================================
# Message Helpers
# =============================================================================

def decode_message_body(payload: dict) -> str:
    """Extract and decode email body from Gmail API payload.

    Gmail API returns body data as base64url encoded strings.
    """
    body = ""

    if "body" in payload and payload["body"].get("data"):
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    elif "parts" in payload:
        # Multipart message - find text/plain or text/html
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain" and part.get("body", {}).get("data"):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break
            elif mime_type == "text/html" and part.get("body", {}).get("data") and not body:
                html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                body = html_to_text(html)
            elif mime_type.startswith("multipart/"):
                # Recursively check nested parts
                body = decode_message_body(part)
                if body:
                    break

    return body.strip()


def get_header(headers: list, name: str) -> str:
    """Get a header value by name from Gmail message headers."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


class MessageFormatter:
    """Format Gmail messages for display."""

    @staticmethod
    def format_date(date_str: str, format_type: str = "short") -> str:
        """Format date string for display.

        Args:
            date_str: Date string from Gmail (various formats)
            format_type: "short" (DD.MM.YYYY), "datetime", "time"
        """
        if not date_str:
            return ""

        try:
            # Gmail uses RFC 2822 format or ISO format
            from email.utils import parsedate_to_datetime
            try:
                dt = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                # Try ISO format
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            if format_type == "short":
                return dt.strftime("%d.%m.%Y")
            elif format_type == "datetime":
                return dt.strftime("%Y-%m-%d %H:%M")
            elif format_type == "time":
                return dt.strftime("%H:%M")
            else:
                return dt.strftime("%Y-%m-%d")
        except Exception:
            return date_str[:10] if len(date_str) >= 10 else date_str

    @staticmethod
    def format_email_list_item(msg: dict, show_id: bool = True) -> str:
        """Format email for list display.

        Args:
            msg: Gmail message dict (from messages.list or messages.get)
            show_id: Include message ID
        """
        msg_id = msg.get("id", "")
        thread_id = msg.get("threadId", "")

        # Get headers
        headers = msg.get("payload", {}).get("headers", [])
        subject = get_header(headers, "Subject") or "(No subject)"
        from_addr = get_header(headers, "From") or "Unknown"
        date_str = get_header(headers, "Date") or ""

        date_formatted = MessageFormatter.format_date(date_str, "short")

        # Labels as badges
        labels = msg.get("labelIds", [])
        badges = ""
        if "UNREAD" in labels:
            badges += " [NEW]"
        if "STARRED" in labels:
            badges += " [*]"
        if any(l for l in labels if l not in ["INBOX", "UNREAD", "STARRED", "CATEGORY_PRIMARY", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"]):
            # Has custom labels
            badges += " [L]"

        # Check for attachments
        payload = msg.get("payload", {})
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("filename"):
                    badges += " [+]"
                    break

        line = f"- [{date_formatted}] {from_addr}: {subject}{badges}"
        if show_id and msg_id:
            line += f"\n  ID: {msg_id}"
            if thread_id:
                line += f" | Thread: {thread_id}"

        return line


def format_full_email(msg: dict) -> str:
    """Format full email content for display."""
    headers = msg.get("payload", {}).get("headers", [])

    subject = get_header(headers, "Subject") or "(No subject)"
    from_addr = get_header(headers, "From") or "Unknown"
    to_addr = get_header(headers, "To") or ""
    cc_addr = get_header(headers, "Cc") or ""
    date_str = get_header(headers, "Date") or ""

    # Labels
    labels = msg.get("labelIds", [])
    label_str = ", ".join(labels) if labels else "None"

    # Body
    body = decode_message_body(msg.get("payload", {}))

    # Format output
    result = f"""Subject: {subject}
From: {from_addr}
To: {to_addr}"""

    if cc_addr:
        result += f"\nCc: {cc_addr}"

    result += f"""
Date: {date_str}
Labels: {label_str}
ID: {msg.get('id', '')}
Thread: {msg.get('threadId', '')}

{'-' * 40}
{body}
"""

    return result
