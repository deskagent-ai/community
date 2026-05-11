# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Microsoft Graph MCP - Authentication Module
============================================
Authentication tools for device code flow.
"""

from msgraph.base import (
    mcp,
    MSAL_AVAILABLE,
    get_access_token, start_device_code_flow, complete_device_code_flow,
    graph_request
)


# =============================================================================
# MCP Tools - Authentication
# =============================================================================

_pending_flow = None


@mcp.tool()
def graph_authenticate() -> str:
    """Start Microsoft Graph authentication using device code flow.

    Returns instructions for the user to complete authentication.
    After user completes auth in browser, call graph_complete_auth.
    """
    global _pending_flow

    if not MSAL_AVAILABLE:
        return "ERROR: MSAL not installed. Run: pip install msal requests"

    # Check if already authenticated
    token = get_access_token()
    if token:
        try:
            # Verify token works
            user = graph_request("/me")
            return f"Already authenticated as: {user.get('displayName', 'Unknown')} ({user.get('mail', user.get('userPrincipalName', 'Unknown'))})"
        except Exception:
            pass  # Token invalid, need re-auth

    try:
        flow = start_device_code_flow()

        # Store flow for completion
        _pending_flow = flow

        message = flow.get("message", "")
        user_code = flow.get("user_code", "")
        verification_uri = flow.get("verification_uri", "https://microsoft.com/devicelogin")

        return f"""Microsoft Graph Authentication Required

1. Open: {verification_uri}
2. Enter code: {user_code}
3. Sign in with your Microsoft 365 account
4. After completing, call: graph_complete_auth()

{message}"""
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def graph_complete_auth(timeout: int = 120) -> str:
    """Complete Microsoft Graph authentication after user has signed in.

    Call this after the user has completed the device code flow in their browser.

    Args:
        timeout: Max seconds to wait for auth completion (default: 120)
    """
    global _pending_flow

    if not _pending_flow:
        return "ERROR: No pending authentication. Call graph_authenticate first."

    try:
        complete_device_code_flow(_pending_flow, timeout=timeout)
        _pending_flow = None

        # Get user info
        user = graph_request("/me")
        return f"Authentication successful! Signed in as: {user.get('displayName', 'Unknown')} ({user.get('mail', user.get('userPrincipalName', 'Unknown'))})"
    except Exception as e:
        _pending_flow = None
        return f"ERROR: {e}"


@mcp.tool()
def graph_status() -> str:
    """Check Microsoft Graph authentication status and show current user."""
    token = get_access_token()
    if not token:
        return "Not authenticated. Use graph_authenticate to sign in."

    try:
        user = graph_request("/me")
        return f"Authenticated as: {user.get('displayName', 'Unknown')} ({user.get('mail', user.get('userPrincipalName', 'Unknown'))})"
    except Exception as e:
        return f"Token invalid: {e}. Use graph_authenticate to re-sign in."
