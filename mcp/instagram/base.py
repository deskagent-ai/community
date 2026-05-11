# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Instagram MCP - Base Module
===========================
Configuration, authentication, and shared utilities for Instagram Graph API.

Supports Instagram Business and Creator accounts via Meta (Facebook) OAuth2.
Requires a Facebook/Instagram Business account connected to a Facebook Page.

Meta OAuth2 Flow:
1. User authenticates via Facebook Login
2. Short-lived user token is exchanged for long-lived token (60 days)
3. Page access tokens are retrieved
4. Instagram Business Account ID is obtained from the connected Page

API Base: https://graph.facebook.com/v18.0/
"""

import json
import webbrowser
import http.server
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from threading import Thread
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, get_config_dir, mcp_log

# HTTP client
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    mcp_log("[Instagram] requests library not installed. Run: pip install requests")


mcp = FastMCP("instagram")

# Tools that return external/untrusted content (prompt injection risk)
HIGH_RISK_TOOLS = {
    "instagram_get_media",
    "instagram_get_comments",
    "instagram_get_mentions",
    "instagram_get_messages",
}

# Tools that modify data (for dry-run simulation)
DESTRUCTIVE_TOOLS = {
    "instagram_create_post",
    "instagram_create_story",
    "instagram_reply_comment",
    "instagram_delete_comment",
    "instagram_send_message",
}

# =============================================================================
# Configuration
# =============================================================================

# Meta Graph API version
API_VERSION = "v18.0"
API_BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# Meta OAuth2 endpoints
META_AUTH_URL = f"https://www.facebook.com/{API_VERSION}/dialog/oauth"
META_TOKEN_URL = f"https://graph.facebook.com/{API_VERSION}/oauth/access_token"

# Instagram Graph API scopes
# Reference: https://developers.facebook.com/docs/permissions/reference
INSTAGRAM_SCOPES = [
    "instagram_basic",              # Read profile info and media
    "instagram_content_publish",    # Publish media
    "instagram_manage_comments",    # Read and manage comments
    "instagram_manage_insights",    # Read insights
    "instagram_manage_messages",    # Read and send messages
    "pages_read_engagement",        # Read Page data (required for IG Business)
    "pages_show_list",              # List user's Pages
    "business_management",          # Access business accounts
]

# Token cache file
TOKEN_FILE = get_config_dir() / ".instagram_token.json"

# Default redirect port for OAuth2
DEFAULT_REDIRECT_PORT = 8081


def get_config():
    """Load Instagram configuration from apis.json."""
    try:
        config = load_config()
        return config.get("instagram", {})
    except Exception as e:
        mcp_log(f"[Instagram] Config load error: {e}")
    return {}


def is_configured() -> bool:
    """Check if Instagram MCP is configured and enabled.

    Returns True if:
    - instagram section exists in apis.json
    - enabled is not explicitly False
    - app_id and app_secret are set (or token exists)
    """
    config = get_config()

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    # Check if configured (credentials or existing token)
    has_credentials = bool(config.get("app_id") and config.get("app_secret"))
    has_token = TOKEN_FILE.exists()

    return has_credentials or has_token


def get_redirect_port():
    """Get OAuth2 redirect port from config."""
    config = get_config()
    return config.get("redirect_port", DEFAULT_REDIRECT_PORT)


def get_redirect_uri():
    """Get OAuth2 redirect URI."""
    return f"http://localhost:{get_redirect_port()}/"


# =============================================================================
# Token Storage
# =============================================================================

_token_data = None


def get_credentials():
    """Get stored Instagram credentials.

    Returns:
        dict with token data or None if not authenticated
    """
    global _token_data

    if not REQUESTS_AVAILABLE:
        raise RuntimeError("requests library not installed. Run: pip install requests")

    # Return cached if valid
    if _token_data and _is_token_valid(_token_data):
        return _token_data

    # Try to load from file
    if TOKEN_FILE.exists():
        try:
            _token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            mcp_log("[Instagram] Loaded credentials from cache")

            # Check if token is expired
            if not _is_token_valid(_token_data):
                mcp_log("[Instagram] Token expired, need to re-authenticate")
                _token_data = None
                return None

            return _token_data
        except Exception as e:
            mcp_log(f"[Instagram] Failed to load token: {e}")
            _token_data = None

    return None


def _is_token_valid(token_data: dict) -> bool:
    """Check if token is still valid."""
    if not token_data:
        return False

    expires_at = token_data.get("expires_at")
    if not expires_at:
        # No expiry means it's a long-lived token that doesn't expire (or we don't know)
        # Check if we have the required fields
        return bool(token_data.get("access_token"))

    try:
        expiry = datetime.fromisoformat(expires_at)
        # Add 5 minute buffer
        return datetime.now() < expiry - timedelta(minutes=5)
    except Exception:
        return False


def save_credentials(token_data: dict):
    """Save credentials to file."""
    global _token_data
    _token_data = token_data

    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        mcp_log("[Instagram] Saved credentials to cache")
    except Exception as e:
        mcp_log(f"[Instagram] Failed to save credentials: {e}")


def clear_credentials():
    """Clear stored credentials."""
    global _token_data
    _token_data = None

    if TOKEN_FILE.exists():
        try:
            TOKEN_FILE.unlink()
            mcp_log("[Instagram] Cleared credentials")
        except Exception as e:
            mcp_log(f"[Instagram] Failed to delete token file: {e}")


# =============================================================================
# OAuth2 Authentication
# =============================================================================

_auth_code = None
_auth_error = None


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handle OAuth2 callback."""

    def do_GET(self):
        global _auth_code, _auth_error

        # Parse query parameters
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>Authentication Successful!</h1>
                    <p>You can close this window and return to DeskAgent.</p>
                </body>
                </html>
            """)
        elif "error" in params:
            _auth_error = params.get("error_description", params["error"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            error_msg = params.get("error_description", ["Unknown error"])[0]
            self.wfile.write(f"""
                <html>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>Authentication Failed</h1>
                    <p>{error_msg}</p>
                </body>
                </html>
            """.encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress HTTP server logs
        pass


def start_auth_flow() -> str:
    """Start OAuth2 authentication flow.

    Opens browser for Meta/Facebook sign-in.

    Returns:
        Authorization URL that was opened
    """
    config = get_config()
    app_id = config.get("app_id")

    if not app_id:
        raise RuntimeError(
            "Instagram not configured. Add app_id and app_secret to apis.json under 'instagram' section.\n"
            "Get credentials from: https://developers.facebook.com/apps/"
        )

    # Build authorization URL
    params = {
        "client_id": app_id,
        "redirect_uri": get_redirect_uri(),
        "scope": ",".join(INSTAGRAM_SCOPES),
        "response_type": "code",
        "state": "deskagent",
    }

    auth_url = f"{META_AUTH_URL}?{urllib.parse.urlencode(params)}"
    mcp_log("[Instagram] Opening authorization URL...")

    # Open browser
    webbrowser.open(auth_url)

    return auth_url


def complete_auth_flow(timeout: int = 300) -> dict:
    """Complete OAuth2 flow by waiting for callback.

    Args:
        timeout: Seconds to wait for callback (default 5 minutes)

    Returns:
        Token data dict with access_token, expires_at, etc.
    """
    global _auth_code, _auth_error
    _auth_code = None
    _auth_error = None

    config = get_config()
    app_id = config.get("app_id")
    app_secret = config.get("app_secret")

    if not app_id or not app_secret:
        raise RuntimeError("Instagram app_id and app_secret required in apis.json")

    port = get_redirect_port()

    # Start callback server
    server = http.server.HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.timeout = timeout

    mcp_log(f"[Instagram] Waiting for OAuth callback on port {port}...")

    # Handle one request
    server.handle_request()
    server.server_close()

    if _auth_error:
        raise RuntimeError(f"Authentication failed: {_auth_error}")

    if not _auth_code:
        raise RuntimeError("No authorization code received")

    mcp_log("[Instagram] Received authorization code, exchanging for token...")

    # Exchange code for short-lived token
    token_response = requests.get(
        META_TOKEN_URL,
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": get_redirect_uri(),
            "code": _auth_code,
        }
    )

    if not token_response.ok:
        error_data = token_response.json()
        raise RuntimeError(f"Token exchange failed: {error_data.get('error', {}).get('message', token_response.text)}")

    token_data = token_response.json()
    short_token = token_data.get("access_token")

    if not short_token:
        raise RuntimeError("No access token in response")

    mcp_log("[Instagram] Got short-lived token, exchanging for long-lived token...")

    # Exchange for long-lived token (valid for 60 days)
    long_token_response = requests.get(
        META_TOKEN_URL,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }
    )

    if not long_token_response.ok:
        error_data = long_token_response.json()
        raise RuntimeError(f"Long-lived token exchange failed: {error_data.get('error', {}).get('message', long_token_response.text)}")

    long_token_data = long_token_response.json()
    access_token = long_token_data.get("access_token")
    expires_in = long_token_data.get("expires_in", 5184000)  # Default 60 days

    if not access_token:
        raise RuntimeError("No long-lived access token in response")

    # Calculate expiry
    expires_at = datetime.now() + timedelta(seconds=expires_in)

    # Get Instagram Business Account info
    mcp_log("[Instagram] Getting connected Instagram accounts...")
    instagram_account = _get_instagram_account(access_token)

    # Build token data
    result = {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "expires_at": expires_at.isoformat(),
        "instagram_account_id": instagram_account.get("id") if instagram_account else None,
        "instagram_username": instagram_account.get("username") if instagram_account else None,
        "page_id": instagram_account.get("page_id") if instagram_account else None,
        "page_access_token": instagram_account.get("page_access_token") if instagram_account else None,
        "authenticated_at": datetime.now().isoformat(),
    }

    save_credentials(result)
    mcp_log(f"[Instagram] Authentication complete. Account: @{result.get('instagram_username', 'unknown')}")

    return result


def _get_instagram_account(user_access_token: str) -> dict | None:
    """Get the first Instagram Business Account connected to user's Pages.

    Meta requires: User owns a Page -> Page is connected to Instagram Business account

    Returns:
        dict with id, username, page_id, page_access_token or None
    """
    # Get user's Pages
    pages_response = requests.get(
        f"{API_BASE_URL}/me/accounts",
        params={
            "access_token": user_access_token,
            "fields": "id,name,access_token,instagram_business_account",
        }
    )

    if not pages_response.ok:
        mcp_log(f"[Instagram] Failed to get Pages: {pages_response.text}")
        return None

    pages_data = pages_response.json()
    pages = pages_data.get("data", [])

    if not pages:
        mcp_log("[Instagram] No Facebook Pages found. You need a Page connected to an Instagram Business account.")
        return None

    # Find first Page with Instagram Business account
    for page in pages:
        ig_account = page.get("instagram_business_account")
        if ig_account:
            ig_id = ig_account.get("id")

            # Get Instagram account details
            ig_response = requests.get(
                f"{API_BASE_URL}/{ig_id}",
                params={
                    "access_token": user_access_token,
                    "fields": "id,username,name,profile_picture_url,followers_count,follows_count,media_count",
                }
            )

            if ig_response.ok:
                ig_data = ig_response.json()
                return {
                    "id": ig_data.get("id"),
                    "username": ig_data.get("username"),
                    "name": ig_data.get("name"),
                    "profile_picture_url": ig_data.get("profile_picture_url"),
                    "followers_count": ig_data.get("followers_count"),
                    "follows_count": ig_data.get("follows_count"),
                    "media_count": ig_data.get("media_count"),
                    "page_id": page.get("id"),
                    "page_name": page.get("name"),
                    "page_access_token": page.get("access_token"),
                }

    mcp_log("[Instagram] No Instagram Business account found connected to any Page.")
    return None


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
            mcp_log("[Instagram] Not authenticated, starting auth flow...")
            try:
                start_auth_flow()
                token_data = complete_auth_flow()
                if token_data:
                    mcp_log("[Instagram] Auto-auth successful, continuing...")
                    return func(*args, **kwargs)
            except Exception as e:
                mcp_log(f"[Instagram] Auto-auth failed: {e}")
            return "ERROR: Instagram authentication required. Use instagram_authenticate() to sign in."
        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# API Request Helper
# =============================================================================

def api_request(
    endpoint: str,
    method: str = "GET",
    params: dict = None,
    data: dict = None,
    use_page_token: bool = False
) -> dict:
    """Make a request to the Instagram Graph API.

    Args:
        endpoint: API endpoint (e.g., "me/media" or "{ig_user_id}/media")
        method: HTTP method (GET, POST, DELETE)
        params: Query parameters
        data: POST data
        use_page_token: Use Page access token instead of User token

    Returns:
        API response as dict

    Raises:
        RuntimeError on API error
    """
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Not authenticated. Use instagram_authenticate() first.")

    # Choose token
    if use_page_token:
        access_token = creds.get("page_access_token") or creds.get("access_token")
    else:
        access_token = creds.get("access_token")

    if not access_token:
        raise RuntimeError("No access token available")

    # Build URL
    if endpoint.startswith("http"):
        url = endpoint
    else:
        url = f"{API_BASE_URL}/{endpoint}"

    # Add access token to params
    params = params or {}
    params["access_token"] = access_token

    # Make request
    try:
        if method.upper() == "GET":
            response = requests.get(url, params=params)
        elif method.upper() == "POST":
            response = requests.post(url, params=params, json=data)
        elif method.upper() == "DELETE":
            response = requests.delete(url, params=params)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        # Parse response
        if response.status_code == 204:
            return {"success": True}

        result = response.json()

        # Check for errors
        if "error" in result:
            error = result["error"]
            error_msg = error.get("message", str(error))
            error_code = error.get("code", "unknown")
            raise RuntimeError(f"Instagram API error ({error_code}): {error_msg}")

        return result

    except requests.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")


def get_instagram_account_id() -> str:
    """Get the Instagram Business Account ID from stored credentials."""
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Not authenticated. Use instagram_authenticate() first.")

    ig_id = creds.get("instagram_account_id")
    if not ig_id:
        raise RuntimeError("No Instagram Business Account connected. Re-authenticate with instagram_authenticate().")

    return ig_id


# =============================================================================
# Error Handling Decorator
# =============================================================================

def instagram_tool(func):
    """Decorator for consistent error handling and logging."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError as e:
            error_msg = str(e)
            mcp_log(f"[{func.__name__}] {error_msg}")
            return f"ERROR: {error_msg}"
        except Exception as e:
            import traceback
            mcp_log(f"[{func.__name__}] Error: {e}")
            mcp_log(f"[{func.__name__}] Traceback: {traceback.format_exc()}")
            return f"ERROR: {str(e)}"
    return wrapper


# =============================================================================
# Content Helpers
# =============================================================================

def format_media_item(media: dict) -> str:
    """Format a media item for display."""
    media_type = media.get("media_type", "UNKNOWN")
    timestamp = media.get("timestamp", "")
    caption = media.get("caption", "(no caption)")
    likes = media.get("like_count", 0)
    comments = media.get("comments_count", 0)
    permalink = media.get("permalink", "")
    media_id = media.get("id", "")

    # Format timestamp
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    # Truncate caption if too long
    if len(caption) > 100:
        caption = caption[:100] + "..."

    return f"""[{media_type}] {timestamp}
Caption: {caption}
Likes: {likes} | Comments: {comments}
ID: {media_id}
URL: {permalink}"""


def format_comment(comment: dict) -> str:
    """Format a comment for display."""
    username = comment.get("username", "unknown")
    text = comment.get("text", "")
    timestamp = comment.get("timestamp", "")
    comment_id = comment.get("id", "")
    likes = comment.get("like_count", 0)

    # Format timestamp
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    return f"@{username} ({timestamp}): {text} [Likes: {likes}] (ID: {comment_id})"
