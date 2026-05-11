# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Instagram MCP - Authentication Module
=====================================
OAuth2 authentication tools for Instagram Graph API.
"""

from instagram.base import (
    mcp, instagram_tool,
    get_credentials, get_config, start_auth_flow, complete_auth_flow,
    clear_credentials, TOKEN_FILE, INSTAGRAM_SCOPES,
    api_request, API_BASE_URL
)
from _mcp_api import mcp_log


@mcp.tool()
@instagram_tool
def instagram_authenticate() -> str:
    """Start Instagram OAuth2 authentication.

    Opens your browser to sign in with Facebook and grant Instagram permissions.
    After signing in, permissions are saved automatically.

    Prerequisites:
    - Meta Developer App created at developers.facebook.com
    - Instagram Graph API added to the app
    - OAuth redirect URI configured (http://localhost:8081/)
    - app_id and app_secret configured in apis.json
    - Facebook Page connected to an Instagram Business/Creator account

    Returns:
        Success message or error description
    """
    # Check if already authenticated
    creds = get_credentials()
    if creds:
        username = creds.get("instagram_username", "unknown")
        return f"""Already authenticated as @{username}.

Use instagram_logout() to sign out first, then instagram_authenticate() to sign in with a different account."""

    # Start auth flow
    mcp_log("[Instagram] Starting authentication flow...")
    start_auth_flow()

    # Complete auth (waits for callback)
    token_data = complete_auth_flow()

    username = token_data.get("instagram_username", "unknown")
    ig_id = token_data.get("instagram_account_id", "unknown")
    expires = token_data.get("expires_at", "unknown")

    return f"""Authentication successful!

Connected Instagram Account:
- Username: @{username}
- Account ID: {ig_id}
- Token expires: {expires}

Your credentials are saved and will be valid for ~60 days.

Available features:
- View and publish media (posts, stories, reels)
- Read and respond to comments
- View insights and analytics
- Manage messages (if enabled)

Use instagram_status() to check your authentication status."""


@mcp.tool()
@instagram_tool
def instagram_status() -> str:
    """Check Instagram authentication status.

    Returns:
        Current authentication status with account info
    """
    creds = get_credentials()

    if not creds:
        config = get_config()
        has_config = bool(config.get("app_id") and config.get("app_secret"))

        if has_config:
            return """Not authenticated.

Instagram is configured but you haven't signed in yet.
Use instagram_authenticate() to sign in with your Facebook account.

Note: You need an Instagram Business or Creator account connected to a Facebook Page."""
        else:
            return """Not configured.

Instagram MCP requires a Meta Developer App.

Setup steps:
1. Go to https://developers.facebook.com/apps/
2. Create a new app (Business type recommended)
3. Add "Instagram Graph API" product
4. Go to App Settings > Basic to get App ID and Secret
5. Add OAuth redirect URI: http://localhost:8081/
6. Add to config/apis.json:

"instagram": {
    "enabled": true,
    "app_id": "YOUR_META_APP_ID",
    "app_secret": "YOUR_META_APP_SECRET",
    "redirect_port": 8081
}

7. Use instagram_authenticate() to sign in

Note: You also need:
- A Facebook Page
- An Instagram Business or Creator account
- The Instagram account connected to the Facebook Page"""

    # Check token validity
    from datetime import datetime
    expires_at = creds.get("expires_at", "")
    is_valid = True
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            is_valid = datetime.now() < expiry
        except Exception:
            pass

    status = "VALID" if is_valid else "EXPIRED"
    username = creds.get("instagram_username", "unknown")
    ig_id = creds.get("instagram_account_id", "unknown")
    page_name = creds.get("page_name", "unknown")
    authenticated_at = creds.get("authenticated_at", "unknown")

    # Try to get fresh account info
    account_info = ""
    if is_valid:
        try:
            result = api_request(
                f"{ig_id}",
                params={"fields": "username,name,followers_count,follows_count,media_count"}
            )
            followers = result.get("followers_count", 0)
            following = result.get("follows_count", 0)
            posts = result.get("media_count", 0)
            account_info = f"""
Account Stats:
  Followers: {followers:,}
  Following: {following:,}
  Posts: {posts:,}"""
        except Exception as e:
            mcp_log(f"[Instagram] Could not get account info: {e}")

    scopes_formatted = "\n".join(f"  - {s}" for s in INSTAGRAM_SCOPES)

    return f"""Instagram Authentication Status: {status}

Account: @{username}
Account ID: {ig_id}
Connected Page: {page_name}
Authenticated: {authenticated_at}
Token expires: {expires_at}
Token file: {TOKEN_FILE}
{account_info}

Requested Scopes:
{scopes_formatted}"""


@mcp.tool()
@instagram_tool
def instagram_logout() -> str:
    """Sign out of Instagram and clear stored credentials.

    Removes the stored token file. You will need to re-authenticate
    using instagram_authenticate() to use Instagram features again.

    Returns:
        Confirmation message
    """
    creds = get_credentials()
    if not creds:
        return "Not currently authenticated. Nothing to clear."

    username = creds.get("instagram_username", "unknown")
    clear_credentials()

    return f"""Signed out of Instagram (@{username}).

Your stored credentials have been removed.
Use instagram_authenticate() to sign in again."""


@mcp.tool()
@instagram_tool
def instagram_get_accounts() -> str:
    """List all Instagram Business accounts connected to your Facebook Pages.

    This is useful if you have multiple Instagram accounts connected to different
    Facebook Pages and want to see which ones are available.

    Returns:
        List of connected Instagram Business accounts
    """
    creds = get_credentials()
    if not creds:
        return "Not authenticated. Use instagram_authenticate() first."

    access_token = creds.get("access_token")
    if not access_token:
        return "No access token available. Re-authenticate with instagram_authenticate()."

    # Import requests for direct API calls
    import requests

    # Get user's Pages with Instagram accounts
    try:
        pages_response = requests.get(
            f"{API_BASE_URL}/me/accounts",
            params={
                "access_token": access_token,
                "fields": "id,name,access_token,instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count}",
            }
        )

        if not pages_response.ok:
            return f"Failed to get Pages: {pages_response.text}"

        pages_data = pages_response.json()
        pages = pages_data.get("data", [])

        if not pages:
            return """No Facebook Pages found.

To use Instagram Graph API, you need:
1. A Facebook Page that you admin
2. An Instagram Business or Creator account
3. The Instagram account connected to the Page

Connect your accounts at:
https://www.facebook.com/business/help/898752960195806"""

        # Format results
        result_lines = ["Connected Instagram Business Accounts:\n"]
        found_accounts = 0

        for page in pages:
            page_name = page.get("name", "Unknown Page")
            ig_account = page.get("instagram_business_account")

            if ig_account:
                found_accounts += 1
                ig_id = ig_account.get("id", "unknown")
                username = ig_account.get("username", "unknown")
                name = ig_account.get("name", "")
                followers = ig_account.get("followers_count", 0)
                posts = ig_account.get("media_count", 0)

                result_lines.append(f"""
{found_accounts}. @{username} ({name})
   Account ID: {ig_id}
   Connected to Page: {page_name}
   Followers: {followers:,} | Posts: {posts}""")
            else:
                result_lines.append(f"""
- Page "{page_name}" has no Instagram Business account connected.""")

        if found_accounts == 0:
            result_lines.append("""
No Instagram Business accounts found.

Your Facebook Pages don't have Instagram Business accounts connected.
Connect your Instagram account to a Page at:
https://www.facebook.com/business/help/898752960195806""")
        else:
            # Show which one is currently active
            current_ig_id = creds.get("instagram_account_id")
            if current_ig_id:
                result_lines.append(f"\nCurrently using account ID: {current_ig_id}")

        return "\n".join(result_lines)

    except Exception as e:
        return f"Error getting accounts: {e}"


@mcp.tool()
@instagram_tool
def instagram_refresh_token() -> str:
    """Refresh the Instagram long-lived access token.

    Long-lived tokens are valid for 60 days. This tool exchanges the
    current token for a new one with a fresh 60-day expiry.

    Note: Tokens can only be refreshed if they are at least 24 hours old
    and have not yet expired.

    Returns:
        Refresh status with new expiry
    """
    import requests
    from datetime import datetime, timedelta

    creds = get_credentials()
    if not creds:
        return "Not authenticated. Use instagram_authenticate() first."

    access_token = creds.get("access_token")
    if not access_token:
        return "No access token available. Re-authenticate with instagram_authenticate()."

    # Check if token is expired
    expires_at = creds.get("expires_at", "")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            if datetime.now() >= expiry:
                return "Token has expired. Re-authenticate with instagram_authenticate()."
        except Exception:
            pass

    # Refresh the token
    try:
        response = requests.get(
            f"{API_BASE_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": get_config().get("app_id"),
                "client_secret": get_config().get("app_secret"),
                "fb_exchange_token": access_token,
            }
        )

        if not response.ok:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", response.text)
            return f"Refresh failed: {error_msg}\n\nIf the token is too new, wait 24 hours before refreshing."

        token_data = response.json()
        new_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 5184000)  # Default 60 days

        if not new_token:
            return "No new token in response. Try again later or re-authenticate."

        # Calculate new expiry
        new_expiry = datetime.now() + timedelta(seconds=expires_in)

        # Update stored credentials
        creds["access_token"] = new_token
        creds["expires_in"] = expires_in
        creds["expires_at"] = new_expiry.isoformat()
        creds["refreshed_at"] = datetime.now().isoformat()

        from instagram.base import save_credentials
        save_credentials(creds)

        return f"""Token refreshed successfully!

New expiry: {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}
Valid for: {expires_in // 86400} days"""

    except Exception as e:
        return f"Refresh failed: {e}\n\nTry instagram_authenticate() to re-authenticate."
