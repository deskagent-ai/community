# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Microsoft Graph Routes
==============================
Handles Microsoft Graph API configuration and authentication for settings UI.
"""

import json
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ai_agent import log

# Path is set up by assistant/__init__.py
from paths import get_config_dir, get_apis_config_path

router = APIRouter(prefix="/msgraph")


class MSGraphConfigRequest(BaseModel):
    """Request body for saving MS Graph config."""
    client_id: str
    tenant_id: str = "common"


def _load_apis_config() -> dict:
    """Load apis.json configuration."""
    try:
        config_path = get_apis_config_path()
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"[MSGraph Routes] Error loading apis.json: {e}")
    return {}


def _save_apis_config(config: dict) -> bool:
    """Save apis.json configuration."""
    try:
        config_path = get_apis_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        log(f"[MSGraph Routes] Error saving apis.json: {e}")
        return False


def _get_msgraph_module():
    """Dynamically import msgraph module to access auth functions."""
    try:
        # Import from MCP directory
        mcp_dir = Path(__file__).parent.parent.parent.parent / "mcp"
        if str(mcp_dir) not in sys.path:
            sys.path.insert(0, str(mcp_dir))

        from msgraph import base as msgraph_base
        from msgraph import auth as msgraph_auth
        return msgraph_base, msgraph_auth
    except ImportError as e:
        log(f"[MSGraph Routes] Import error: {e}")
        return None, None


@router.get("/status")
async def get_msgraph_status():
    """Get Microsoft Graph authentication status and configuration."""
    apis_config = _load_apis_config()
    msgraph_config = apis_config.get("msgraph", {})

    client_id = msgraph_config.get("client_id", "")
    tenant_id = msgraph_config.get("tenant_id", "common")

    # Check if MSAL is available and get auth status
    is_authenticated = False
    user_display_name = None
    user_email = None

    msgraph_base, msgraph_auth = _get_msgraph_module()
    if msgraph_base and msgraph_base.MSAL_AVAILABLE:
        try:
            token = msgraph_base.get_access_token()
            if token:
                user_info = msgraph_base.graph_request("/me")
                is_authenticated = True
                user_display_name = user_info.get("displayName", "Unknown")
                user_email = user_info.get("mail") or user_info.get("userPrincipalName", "Unknown")
        except Exception as e:
            log(f"[MSGraph Routes] Auth check error: {e}")

    return {
        "client_id": client_id,
        "tenant_id": tenant_id,
        "is_authenticated": is_authenticated,
        "user_display_name": user_display_name,
        "user_email": user_email,
        "msal_available": msgraph_base.MSAL_AVAILABLE if msgraph_base else False
    }


@router.post("/config")
async def save_msgraph_config(config: MSGraphConfigRequest):
    """Save Microsoft Graph configuration (client_id, tenant_id)."""
    apis_config = _load_apis_config()

    # Initialize msgraph section if not exists
    if "msgraph" not in apis_config:
        apis_config["msgraph"] = {}

    # Update config
    apis_config["msgraph"]["client_id"] = config.client_id
    apis_config["msgraph"]["tenant_id"] = config.tenant_id

    if _save_apis_config(apis_config):
        # Clear cached MSAL app to force reload with new config
        msgraph_base, _ = _get_msgraph_module()
        if msgraph_base:
            msgraph_base._app = None
            msgraph_base._token_cache = None

        return {"success": True, "message": "Configuration saved"}
    else:
        return {"success": False, "error": "Failed to save configuration"}


@router.post("/authenticate")
async def authenticate_msgraph():
    """Start Microsoft Graph device code authentication flow."""
    msgraph_base, msgraph_auth = _get_msgraph_module()

    if not msgraph_base or not msgraph_base.MSAL_AVAILABLE:
        return {"success": False, "error": "MSAL not installed. Run: pip install msal requests"}

    try:
        # Check if already authenticated
        token = msgraph_base.get_access_token()
        if token:
            try:
                user_info = msgraph_base.graph_request("/me")
                return {
                    "success": True,
                    "already_authenticated": True,
                    "user_display_name": user_info.get("displayName", "Unknown"),
                    "user_email": user_info.get("mail") or user_info.get("userPrincipalName", "Unknown")
                }
            except Exception:
                pass  # Token invalid, continue with auth

        # Start device code flow
        flow = msgraph_base.start_device_code_flow()

        # Store flow in auth module for completion
        msgraph_auth._pending_flow = flow

        return {
            "success": True,
            "user_code": flow.get("user_code", ""),
            "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
            "message": flow.get("message", "")
        }
    except Exception as e:
        log(f"[MSGraph Routes] Auth error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/complete-auth")
async def complete_msgraph_auth():
    """Complete Microsoft Graph authentication after user has signed in."""
    msgraph_base, msgraph_auth = _get_msgraph_module()

    if not msgraph_base or not msgraph_auth:
        return {"success": False, "error": "MSGraph module not available"}

    if not msgraph_auth._pending_flow:
        return {"success": False, "error": "No pending authentication. Start authentication first."}

    try:
        msgraph_base.complete_device_code_flow(msgraph_auth._pending_flow, timeout=120)
        msgraph_auth._pending_flow = None

        # Get user info
        user_info = msgraph_base.graph_request("/me")
        return {
            "success": True,
            "user_display_name": user_info.get("displayName", "Unknown"),
            "user_email": user_info.get("mail") or user_info.get("userPrincipalName", "Unknown")
        }
    except Exception as e:
        msgraph_auth._pending_flow = None
        log(f"[MSGraph Routes] Complete auth error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/logout")
async def logout_msgraph():
    """Clear Microsoft Graph authentication tokens."""
    msgraph_base, msgraph_auth = _get_msgraph_module()

    if not msgraph_base:
        return {"success": False, "error": "MSGraph module not available"}

    try:
        # Clear token cache file
        if msgraph_base.TOKEN_CACHE_FILE.exists():
            msgraph_base.TOKEN_CACHE_FILE.unlink()

        # Clear in-memory cache
        msgraph_base._app = None
        msgraph_base._token_cache = None
        msgraph_base._access_token = None
        msgraph_base._token_expiry = None

        return {"success": True, "message": "Logged out successfully"}
    except Exception as e:
        log(f"[MSGraph Routes] Logout error: {e}")
        return {"success": False, "error": str(e)}
