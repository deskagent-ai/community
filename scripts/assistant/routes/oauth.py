# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI OAuth Routes for MCP Plugin Authentication
===================================================
Universal OAuth2 handler for MCP plugins that define AUTH_CONFIG.

Endpoints:
- GET /oauth/providers - List all MCPs with OAuth support
- POST /oauth/{provider}/start - Start OAuth flow
- GET /oauth/callback - Universal OAuth callback
- GET /oauth/{provider}/status - Check auth status
- POST /oauth/{provider}/disconnect - Remove authentication
"""

import base64
import importlib
import importlib.util
import json
import sys
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Path is set up by assistant/__init__.py
from paths import get_config_dir, get_apis_config_path, get_mcp_dir

# Import system logger
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): print(msg)


router = APIRouter(prefix="/oauth")


# =============================================================================
# Request/Response Models
# =============================================================================

class OAuthStartResponse(BaseModel):
    """Response from starting OAuth flow."""
    auth_url: str
    state: str
    custom_auth: bool = False  # True if MCP handles its own auth flow
    user_code: Optional[str] = None  # Device code for user to enter (e.g., Microsoft 365)


class OAuthStatusResponse(BaseModel):
    """Response for OAuth status check."""
    status: str  # "not_configured" | "no_token" | "connected" | "expired"
    display_name: Optional[str] = None
    expires_at: Optional[str] = None
    authenticated_at: Optional[str] = None


class ProviderInfo(BaseModel):
    """Information about an OAuth provider."""
    provider: str
    display_name: str
    status: str
    icon: Optional[str] = None
    color: Optional[str] = None


# =============================================================================
# Helper Functions
# =============================================================================

def _get_redirect_uri(request: Request) -> str:
    """Build OAuth redirect URI from current request.

    Dynamically builds the redirect URI based on the actual server host/port,
    so OAuth works regardless of which port DeskAgent is running on.
    """
    # Get base URL from request (e.g., "http://localhost:8765/")
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/oauth/callback"


def _load_apis_config() -> dict:
    """Load apis.json configuration."""
    try:
        config_path = get_apis_config_path()
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        system_log(f"[OAuth] Error loading apis.json: {e}")
    return {}


def _save_apis_config(config: dict) -> bool:
    """Save apis.json configuration."""
    try:
        config_path = get_apis_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        system_log(f"[OAuth] Error saving apis.json: {e}")
        return False


def _get_token_file_path(provider: str, auth_config: dict) -> Path:
    """Get the token file path for a provider."""
    token_file = auth_config.get("token_file", f".{provider}_token.json")
    return get_config_dir() / token_file


def _load_token(provider: str, auth_config: dict) -> dict | None:
    """Load token data for a provider."""
    token_path = _get_token_file_path(provider, auth_config)
    if token_path.exists():
        try:
            return json.loads(token_path.read_text(encoding="utf-8"))
        except Exception as e:
            system_log(f"[OAuth] Error loading token for {provider}: {e}")
    return None


def _save_token(provider: str, auth_config: dict, token_data: dict) -> bool:
    """Save token data for a provider."""
    token_path = _get_token_file_path(provider, auth_config)
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(json.dumps(token_data, indent=2, ensure_ascii=False), encoding="utf-8")
        system_log(f"[OAuth] Saved token for {provider}")
        return True
    except Exception as e:
        system_log(f"[OAuth] Error saving token for {provider}: {e}")
        return False


def _delete_token(provider: str, auth_config: dict) -> bool:
    """Delete token file for a provider."""
    token_path = _get_token_file_path(provider, auth_config)
    if token_path.exists():
        try:
            token_path.unlink()
            system_log(f"[OAuth] Deleted token for {provider}")
            return True
        except Exception as e:
            system_log(f"[OAuth] Error deleting token for {provider}: {e}")
            return False
    return True


def _is_token_expired(token_data: dict) -> bool:
    """Check if a token is expired."""
    expires_at = token_data.get("expires_at")
    if not expires_at:
        # No expiry means token doesn't expire (or we don't know)
        return False

    try:
        expiry = datetime.fromisoformat(expires_at)
        # Add 5 minute buffer
        return datetime.now() >= expiry - timedelta(minutes=5)
    except Exception:
        return False


def _schema_to_auth_config(integration_schema: dict, provider: str) -> dict | None:
    """Convert INTEGRATION_SCHEMA to AUTH_CONFIG format for the OAuth flow."""
    if not integration_schema or integration_schema.get("auth_type") != "oauth":
        return None

    oauth_config = integration_schema.get("oauth", {})
    fields = integration_schema.get("fields", [])

    auth_config = {
        "type": "oauth2",
        "display_name": integration_schema.get("name", provider.title()),
        "custom_auth": oauth_config.get("custom_auth", False),
        "token_file": oauth_config.get("token_file", f".{provider}_token.json"),
        "icon": integration_schema.get("icon"),
        "color": integration_schema.get("color"),
        "config_keys": [f["key"] for f in fields if f.get("required", False)],
    }

    for key in ("auth_url", "token_url", "scopes"):
        if key in oauth_config:
            auth_config[key] = oauth_config[key]

    return auth_config


def _get_mcp_auth_config(provider: str) -> dict | None:
    """
    Load OAuth config from an MCP package.

    Uses AST parsing first (no module execution needed), then falls back
    to exec_module for dynamic schemas or legacy AUTH_CONFIG.

    Args:
        provider: MCP package name (e.g., "gmail", "msgraph")

    Returns:
        Auth config dict compatible with OAuth flow, or None if not found
    """
    mcp_dir = get_mcp_dir()
    provider_dir = mcp_dir / provider

    if not provider_dir.is_dir():
        return None

    init_file = provider_dir / "__init__.py"
    if not init_file.exists():
        return None

    # Phase 1: AST extraction (no code execution, no import issues)
    try:
        from assistant.services.integration_schema import _extract_schema_via_ast
        schema = _extract_schema_via_ast(init_file)
        if schema:
            auth_config = _schema_to_auth_config(schema, provider)
            if auth_config:
                system_log(f"[OAuth] Loaded INTEGRATION_SCHEMA via AST for {provider}")
                return auth_config
    except Exception as e:
        system_log(f"[OAuth] AST extraction failed for {provider}: {e}")

    # Phase 2: exec_module fallback (for dynamic schemas or legacy AUTH_CONFIG)
    try:
        spec = importlib.util.spec_from_file_location(f"mcp_{provider}", init_file)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)

        scripts_path = str(mcp_dir.parent / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)

        spec.loader.exec_module(module)

        # Check INTEGRATION_SCHEMA first
        integration_schema = getattr(module, "INTEGRATION_SCHEMA", None)
        auth_config = _schema_to_auth_config(integration_schema, provider)
        if auth_config:
            system_log(f"[OAuth] Loaded INTEGRATION_SCHEMA for {provider}")
            return auth_config

        # Legacy: AUTH_CONFIG
        auth_config = getattr(module, "AUTH_CONFIG", None)
        tool_metadata = getattr(module, "TOOL_METADATA", {})

        if auth_config:
            auth_config = dict(auth_config)
            if "icon" not in auth_config and "icon" in tool_metadata:
                auth_config["icon"] = tool_metadata["icon"]
            if "color" not in auth_config and "color" in tool_metadata:
                auth_config["color"] = tool_metadata["color"]

        return auth_config

    except Exception as e:
        system_log(f"[OAuth] Error loading auth config for {provider}: {e}")
        return None


def _get_all_oauth_providers() -> list[tuple[str, dict]]:
    """
    Scan MCP directories for providers with AUTH_CONFIG.

    Returns:
        List of (provider_name, auth_config) tuples
    """
    providers = []
    mcp_dir = get_mcp_dir()

    if not mcp_dir.exists():
        return providers

    for item in mcp_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            auth_config = _get_mcp_auth_config(item.name)
            if auth_config and auth_config.get("type") == "oauth2":
                providers.append((item.name, auth_config))

    return providers


def _get_provider_status(provider: str, auth_config: dict) -> str:
    """
    Get the authentication status for a provider.

    Returns:
        "not_configured" - No client_id in apis.json
        "no_token" - Configured but no token file
        "expired" - Token exists but is expired
        "connected" - Token exists and is valid
    """
    apis_config = _load_apis_config()
    provider_config = apis_config.get(provider, {})

    # Check if client_id exists
    config_keys = auth_config.get("config_keys", ["client_id", "client_secret"])
    has_config = all(provider_config.get(key) for key in config_keys)

    if not has_config:
        return "not_configured"

    # Check if token exists
    token_data = _load_token(provider, auth_config)
    if not token_data:
        return "no_token"

    # Check if expired
    if _is_token_expired(token_data):
        return "expired"

    return "connected"


# =============================================================================
# Routes
# =============================================================================

@router.get("/providers")
async def list_providers() -> list[ProviderInfo]:
    """
    List all MCP plugins that have OAuth support.

    Scans deskagent/mcp/ directories for __init__.py files with AUTH_CONFIG.
    """
    result = []

    for provider, auth_config in _get_all_oauth_providers():
        status = _get_provider_status(provider, auth_config)
        result.append(ProviderInfo(
            provider=provider,
            display_name=auth_config.get("display_name", provider.title()),
            status=status,
            icon=auth_config.get("icon"),
            color=auth_config.get("color"),
        ))

    return result


@router.post("/{provider}/start")
async def start_oauth(provider: str, request: Request) -> OAuthStartResponse:
    """
    Start OAuth flow for a provider.

    Builds the authorization URL with the provider's config and opens it.
    For providers with custom_auth=True, uses MCP's own auth flow.
    """
    # Get AUTH_CONFIG
    auth_config = _get_mcp_auth_config(provider)
    if not auth_config:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' not found or has no OAuth support"
        )

    # Get client credentials from apis.json
    apis_config = _load_apis_config()
    provider_config = apis_config.get(provider, {})

    # Check for custom auth (MCP handles its own flow)
    if auth_config.get("custom_auth"):
        system_log(f"[OAuth] Starting custom auth flow for {provider}")
        return _start_custom_auth(provider, auth_config, provider_config)

    client_id = provider_config.get("client_id")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail=f"No client_id configured for {provider}. Add it to apis.json under '{provider}.client_id'"
        )

    # Build authorization URL
    auth_url_base = auth_config.get("auth_url")
    if not auth_url_base:
        raise HTTPException(
            status_code=500,
            detail=f"Provider '{provider}' has no auth_url configured"
        )

    # Encode provider in state for callback routing
    state = base64.urlsafe_b64encode(provider.encode()).decode()

    # Build OAuth parameters - scopes can be overridden in apis.json
    scopes = provider_config.get("scopes") or auth_config.get("scopes", [])
    redirect_uri = _get_redirect_uri(request)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }

    # Handle scopes - some providers use space, some use comma
    if scopes:
        scope_separator = auth_config.get("scope_separator", " ")
        params["scope"] = scope_separator.join(scopes)

    # Add any custom auth parameters
    extra_params = auth_config.get("auth_params", {})
    params.update(extra_params)

    auth_url = f"{auth_url_base}?{urllib.parse.urlencode(params)}"

    system_log(f"[OAuth] Starting flow for {provider}")

    return OAuthStartResponse(auth_url=auth_url, state=state)


def _start_custom_auth(provider: str, auth_config: dict, provider_config: dict) -> OAuthStartResponse:
    """
    Start custom auth flow for MCPs that handle their own OAuth.

    For Google OAuth (gmail): Uses InstalledAppFlow directly without loading
    the MCP module (avoids async deadlock from _mcp_api HTTP loopback).

    For device code flows (msgraph): Loads the MCP module to get the flow.
    """
    try:
        # Google OAuth providers: handle directly without loading MCP module
        if auth_config.get("auth_url", "").startswith("https://accounts.google.com"):
            return _start_google_auth(provider, auth_config, provider_config)

        # Other custom_auth providers (msgraph device code, etc.): load MCP module
        return _start_mcp_auth(provider, auth_config, provider_config)

    except HTTPException:
        raise
    except Exception as e:
        system_log(f"[OAuth] Error starting custom auth for {provider}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start auth for {provider}: {str(e)}"
        )


def _start_google_auth(provider: str, auth_config: dict, provider_config: dict) -> OAuthStartResponse:
    """Start Google OAuth flow using InstalledAppFlow directly.

    This avoids loading the MCP module (which would cause an async deadlock
    due to _mcp_api making HTTP loopback requests to the same server).
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-auth-oauthlib not installed. Run: pip install google-auth-oauthlib"
        )

    client_id = provider_config.get("client_id")
    client_secret = provider_config.get("client_secret")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail=f"No client_id/client_secret configured for {provider}. "
                   f"Add them in Settings > Integrations or apis.json."
        )

    scopes = auth_config.get("scopes", [])
    redirect_port = provider_config.get("redirect_port", 8080)
    token_file = get_config_dir() / auth_config.get("token_file", f".{provider}_token.json")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{redirect_port}"]
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=scopes,
        redirect_uri=f"http://localhost:{redirect_port}"
    )

    def run_auth():
        try:
            creds = flow.run_local_server(
                port=redirect_port,
                prompt="consent",
                success_message="Authentication successful! You can close this window.",
                open_browser=True
            )
            # Save token
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json())
            system_log(f"[OAuth] Google auth completed for {provider}, token saved to {token_file}")

            # Invalidate MCP config cache
            try:
                from assistant.services.discovery import invalidate_mcp_config_cache
                invalidate_mcp_config_cache(provider)
            except Exception as cache_err:
                system_log(f"[OAuth] Cache invalidation warning: {cache_err}")
        except Exception as e:
            system_log(f"[OAuth] Google auth error for {provider}: {e}")

    thread = threading.Thread(target=run_auth, daemon=True)
    thread.start()

    system_log(f"[OAuth] Started Google auth flow for {provider} on port {redirect_port}")
    return OAuthStartResponse(auth_url="", state=provider, custom_auth=True)


def _start_mcp_auth(provider: str, auth_config: dict, provider_config: dict) -> OAuthStartResponse:
    """Start custom auth flow by loading the MCP module.

    Used for non-Google providers (like msgraph device code flow).
    """
    mcp_dir = get_mcp_dir()
    module_path = mcp_dir / provider / "__init__.py"

    if not module_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"MCP module not found: {provider}"
        )

    # Add paths for MCP imports
    mcp_dir_str = str(mcp_dir)
    if mcp_dir_str not in sys.path:
        sys.path.insert(0, mcp_dir_str)
    scripts_path = str(mcp_dir.parent / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)

    spec = importlib.util.spec_from_file_location(provider, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[provider] = module
    spec.loader.exec_module(module)

    if not hasattr(module, 'start_auth_flow') or not hasattr(module, 'complete_auth_flow'):
        raise HTTPException(
            status_code=500,
            detail=f"MCP {provider} missing start_auth_flow or complete_auth_flow"
        )

    flow = module.start_auth_flow()
    system_log(f"[OAuth] Started custom auth flow for {provider}: {type(flow)}")

    # Check if this is a device code flow
    verification_uri = None
    user_code = None
    if isinstance(flow, dict):
        verification_uri = flow.get("verification_uri") or flow.get("verification_url")
        user_code = flow.get("user_code")
        if verification_uri and user_code:
            system_log(f"[OAuth] Device code flow for {provider}: {verification_uri} (code: {user_code})")

    def run_auth():
        try:
            module.complete_auth_flow(flow)
            system_log(f"[OAuth] Custom auth completed for {provider}")
            try:
                from assistant.services.discovery import invalidate_mcp_config_cache
                invalidate_mcp_config_cache(provider)
            except Exception as cache_err:
                system_log(f"[OAuth] Cache invalidation warning: {cache_err}")
        except Exception as e:
            system_log(f"[OAuth] Custom auth error for {provider}: {e}")

    thread = threading.Thread(target=run_auth, daemon=True)
    thread.start()

    return OAuthStartResponse(
        auth_url=verification_uri or "",
        state=provider,
        custom_auth=True,
        user_code=user_code
    )


@router.get("/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """
    Universal OAuth callback handler.

    Decodes provider from state, exchanges code for token, saves to file.
    """
    # Handle error from provider
    if error:
        error_msg = error_description or error
        system_log(f"[OAuth] Callback error: {error_msg}")
        return _render_callback_page(
            success=False,
            message=f"Authentication failed: {error_msg}"
        )

    # Validate required parameters
    if not code or not state:
        return _render_callback_page(
            success=False,
            message="Missing code or state parameter"
        )

    # Decode provider from state
    try:
        provider = base64.urlsafe_b64decode(state.encode()).decode()
    except Exception:
        return _render_callback_page(
            success=False,
            message="Invalid state parameter"
        )

    system_log(f"[OAuth] Callback received for {provider}")

    # Get AUTH_CONFIG
    auth_config = _get_mcp_auth_config(provider)
    if not auth_config:
        return _render_callback_page(
            success=False,
            message=f"Unknown provider: {provider}"
        )

    # Get client credentials
    apis_config = _load_apis_config()
    provider_config = apis_config.get(provider, {})

    client_id = provider_config.get("client_id")
    client_secret = provider_config.get("client_secret")

    if not client_id or not client_secret:
        return _render_callback_page(
            success=False,
            message=f"Missing client credentials for {provider}"
        )

    # Exchange code for token
    token_url = auth_config.get("token_url")
    if not token_url:
        return _render_callback_page(
            success=False,
            message=f"No token_url configured for {provider}"
        )

    try:
        token_data = _exchange_code_for_token(
            token_url=token_url,
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=_get_redirect_uri(request),
            auth_config=auth_config,
        )
    except Exception as e:
        system_log(f"[OAuth] Token exchange failed for {provider}: {e}")
        return _render_callback_page(
            success=False,
            message=f"Token exchange failed: {e}"
        )

    # Add metadata
    token_data["authenticated_at"] = datetime.now().isoformat()
    token_data["provider"] = provider

    # Calculate expiry if expires_in is present
    if "expires_in" in token_data and "expires_at" not in token_data:
        expires_in = int(token_data["expires_in"])
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        token_data["expires_at"] = expires_at.isoformat()

    # Save token
    if not _save_token(provider, auth_config, token_data):
        return _render_callback_page(
            success=False,
            message="Failed to save token"
        )

    display_name = auth_config.get("display_name", provider.title())
    system_log(f"[OAuth] Successfully authenticated {provider}")

    # Invalidate MCP config cache so prerequisites check refreshes
    try:
        from assistant.services.discovery import invalidate_mcp_config_cache
        invalidate_mcp_config_cache(provider)
        system_log(f"[OAuth] Invalidated MCP config cache for {provider}")
    except Exception as cache_err:
        system_log(f"[OAuth] Cache invalidation warning: {cache_err}")

    return _render_callback_page(
        success=True,
        message=f"Successfully connected to {display_name}!"
    )


@router.get("/{provider}/status")
async def get_status(provider: str) -> OAuthStatusResponse:
    """
    Get authentication status for a provider.
    """
    auth_config = _get_mcp_auth_config(provider)
    if not auth_config:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' not found or has no OAuth support"
        )

    status = _get_provider_status(provider, auth_config)

    response = OAuthStatusResponse(
        status=status,
        display_name=auth_config.get("display_name", provider.title()),
    )

    # Add token info if connected
    if status in ("connected", "expired"):
        token_data = _load_token(provider, auth_config)
        if token_data:
            response.expires_at = token_data.get("expires_at")
            response.authenticated_at = token_data.get("authenticated_at")

    return response


def _clear_provider_memory(provider: str):
    """Clear in-memory auth state for a provider.

    Uses the already-loaded module from sys.modules (same instance the MCP uses).
    Calls clear_credentials() if available, otherwise clears known auth variables.
    """
    # Try the already-loaded module from sys.modules first (same instance MCP uses)
    module = sys.modules.get(provider)

    if not module:
        # MCP modules run in separate processes - in-memory clear only works
        # if module was loaded in this process (e.g. In-Process MCP mode).
        # Token file deletion (done separately) handles the actual disconnect.
        system_log(f"[OAuth] Module {provider} not in sys.modules (MCP runs in separate process), skipping memory clear")
        return

    # Get the base submodule (where auth state lives)
    base_module = getattr(module, "base", None)

    # Preferred: call clear_credentials() if it exists (provider-agnostic)
    clear_fn = (
        getattr(base_module, "clear_credentials", None)
        or getattr(module, "clear_credentials", None)
    )
    if clear_fn and callable(clear_fn):
        clear_fn()
        system_log(f"[OAuth] Called clear_credentials() for {provider}")
        return

    # Fallback: clear known auth variables on the base module
    if base_module:
        cleared = []
        for attr in ("_credentials", "_gmail_service", "_calendar_service",
                      "_app", "_token_cache", "_access_token", "_token_expiry"):
            if hasattr(base_module, attr):
                setattr(base_module, attr, None)
                cleared.append(attr)
        if cleared:
            system_log(f"[OAuth] Cleared {', '.join(cleared)} for {provider}")


@router.post("/{provider}/disconnect")
async def disconnect(provider: str):
    """
    Disconnect/remove authentication for a provider.

    Deletes the token file and clears in-memory caches.
    """
    system_log(f"[OAuth] Disconnect request for provider: {provider}")

    auth_config = _get_mcp_auth_config(provider)
    if not auth_config:
        system_log(f"[OAuth] Provider '{provider}' not found or has no OAuth support")
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' not found or has no OAuth support"
        )

    system_log(f"[OAuth] Auth config for {provider}: custom_auth={auth_config.get('custom_auth')}, token_file={auth_config.get('token_file')}")

    # Clear in-memory state for custom_auth providers
    if auth_config.get("custom_auth"):
        system_log(f"[OAuth] Clearing in-memory state for custom_auth provider: {provider}")
        try:
            _clear_provider_memory(provider)
        except Exception as e:
            system_log(f"[OAuth] Error clearing in-memory state for {provider}: {e}")
            # Continue with file deletion even if memory clear fails

    token_deleted = _delete_token(provider, auth_config)
    system_log(f"[OAuth] Token deletion result for {provider}: {token_deleted}")

    if token_deleted:
        return {"success": True, "message": f"Disconnected from {provider}"}
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete token"
        )


# =============================================================================
# Token Exchange
# =============================================================================

def _exchange_code_for_token(
    token_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    auth_config: dict,
) -> dict:
    """
    Exchange authorization code for access token.

    Supports both POST body and Basic auth methods.
    """
    # Build token request data
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    # Some providers want credentials in body, some in header
    auth_method = auth_config.get("token_auth_method", "body")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    if auth_method == "basic":
        # Use HTTP Basic auth
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    else:
        # Include in body (default)
        data["client_id"] = client_id
        data["client_secret"] = client_secret

    # Encode data
    encoded_data = urllib.parse.urlencode(data).encode("utf-8")

    # Make request
    req = urllib.request.Request(
        token_url,
        data=encoded_data,
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_text = response.read().decode("utf-8")
            return json.loads(response_text)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("error_description") or error_json.get("error") or error_body
        except Exception:
            error_msg = error_body[:200]
        raise RuntimeError(f"HTTP {e.code}: {error_msg}")
    except Exception as e:
        raise RuntimeError(str(e))


# =============================================================================
# HTML Response Helper
# =============================================================================

def _render_callback_page(success: bool, message: str) -> str:
    """
    Render HTML page for OAuth callback.

    Shows success/error message and auto-closes after a delay.
    """
    status_class = "success" if success else "error"
    status_icon = "check_circle" if success else "error"
    status_color = "#4caf50" if success else "#f44336"

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DeskAgent OAuth</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            max-width: 400px;
            margin: 20px;
        }}
        .icon {{
            font-size: 64px;
            color: {status_color};
            margin-bottom: 20px;
        }}
        h1 {{
            font-size: 24px;
            margin-bottom: 16px;
            font-weight: 600;
        }}
        p {{
            color: rgba(255,255,255,0.7);
            line-height: 1.6;
            margin-bottom: 24px;
        }}
        .close-info {{
            font-size: 14px;
            color: rgba(255,255,255,0.5);
        }}
    </style>
</head>
<body>
    <div class="container">
        <span class="material-icons icon">{status_icon}</span>
        <h1>{"Authentication Complete" if success else "Authentication Failed"}</h1>
        <p>{message}</p>
        <p class="close-info">You can close this window and return to DeskAgent.</p>
    </div>
    <script>
        // Auto-close after 5 seconds if successful
        {"setTimeout(() => window.close(), 5000);" if success else ""}
    </script>
</body>
</html>
"""
