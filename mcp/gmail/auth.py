# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Gmail MCP - Authentication Module
=================================
OAuth2 authentication tools for Gmail and Google Calendar.
"""

from gmail.base import (
    mcp, gmail_tool,
    get_credentials, get_config, start_auth_flow, complete_auth_flow,
    clear_credentials, TOKEN_FILE, GMAIL_SCOPES
)
from _mcp_api import mcp_log


@mcp.tool()
@gmail_tool
def gmail_authenticate() -> str:
    """Start Gmail OAuth2 authentication.

    Opens your browser to sign in with Google and grant permissions.
    After signing in, permissions are saved automatically.

    Prerequisites:
    - Gmail API enabled in Google Cloud Console
    - OAuth 2.0 credentials (Desktop app) created
    - client_id and client_secret configured in apis.json

    Returns:
        Success message or error description
    """
    # Check if already authenticated
    creds = get_credentials()
    if creds and creds.valid:
        return "Already authenticated. Use gmail_logout() to sign out first."

    # Start auth flow
    mcp_log("[Gmail] Starting authentication flow...")
    flow = start_auth_flow()

    # Complete auth (opens browser, waits for callback)
    complete_auth_flow(flow)

    return """Authentication successful!

You are now signed in to Gmail. Your credentials are saved and will be
refreshed automatically.

Available features:
- Gmail: Search, read, send emails, manage labels
- Google Calendar: View and create events

Use gmail_status() to check your authentication status."""


@mcp.tool()
@gmail_tool
def gmail_status() -> str:
    """Check Gmail authentication status.

    Returns:
        Current authentication status with account info
    """
    creds = get_credentials()

    if not creds:
        config = get_config()
        has_config = bool(config.get("client_id") and config.get("client_secret"))

        if has_config:
            return """Not authenticated.

Gmail is configured but you haven't signed in yet.
Use gmail_authenticate() to sign in with your Google account."""
        else:
            return """Not configured.

Gmail MCP requires OAuth2 credentials from Google Cloud Console.

Setup steps:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create a project (or select existing)
3. Enable Gmail API and Google Calendar API
4. Create OAuth 2.0 credentials (Desktop app type)
5. Add to config/apis.json:

"gmail": {
    "enabled": true,
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_port": 8080
}

6. Use gmail_authenticate() to sign in"""

    # Check validity
    status = "VALID" if creds.valid else "EXPIRED"
    expiry = creds.expiry.strftime("%Y-%m-%d %H:%M:%S") if creds.expiry else "Unknown"

    # Try to get account email
    account_info = ""
    if creds.valid:
        try:
            from googleapiclient.discovery import build
            service = build('oauth2', 'v2', credentials=creds)
            user_info = service.userinfo().get().execute()
            email = user_info.get('email', 'Unknown')
            name = user_info.get('name', '')
            account_info = f"\nAccount: {name} <{email}>" if name else f"\nAccount: {email}"
        except Exception as e:
            mcp_log(f"[Gmail] Could not get user info: {e}")

    return f"""Gmail Authentication Status: {status}
{account_info}
Token expiry: {expiry}
Has refresh token: {bool(creds.refresh_token)}
Token file: {TOKEN_FILE}

Scopes:
{chr(10).join(f'  - {s.split("/")[-1]}' for s in GMAIL_SCOPES)}"""


@mcp.tool()
@gmail_tool
def gmail_logout() -> str:
    """Sign out of Gmail and clear stored credentials.

    Removes the stored token file. You will need to re-authenticate
    using gmail_authenticate() to use Gmail features again.

    Returns:
        Confirmation message
    """
    creds = get_credentials()
    if not creds:
        return "Not currently authenticated. Nothing to clear."

    clear_credentials()

    return """Signed out of Gmail.

Your stored credentials have been removed.
Use gmail_authenticate() to sign in again."""


@mcp.tool()
@gmail_tool
def gmail_refresh_token() -> str:
    """Manually refresh the Gmail access token.

    Normally tokens are refreshed automatically. Use this if you're
    experiencing authentication issues.

    Returns:
        Refresh status
    """
    from google.auth.transport.requests import Request
    from gmail.base import save_credentials

    creds = get_credentials()
    if not creds:
        return "Not authenticated. Use gmail_authenticate() first."

    if not creds.refresh_token:
        return "No refresh token available. Re-authenticate with gmail_authenticate()."

    try:
        creds.refresh(Request())
        save_credentials(creds)
        return f"""Token refreshed successfully.

New expiry: {creds.expiry.strftime('%Y-%m-%d %H:%M:%S') if creds.expiry else 'Unknown'}"""
    except Exception as e:
        return f"Refresh failed: {e}\n\nTry gmail_authenticate() to re-authenticate."
