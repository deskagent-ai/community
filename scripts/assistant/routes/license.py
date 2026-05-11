# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
License API Routes for DeskAgent.

Provides endpoints for license status, activation, and deactivation.

Behavior depends on edition:
- AGPL / Community Edition (no `config/license.json` AND/OR no
  `app.license_api_url` configured): Routes are served by
  ``NullLicenseProvider`` and never make network calls.
- Commercial Edition (license.json present and license API configured):
  Routes are served by the network-aware ``LicenseManager``.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ActivateRequest(BaseModel):
    """Request body for license activation."""
    code: Optional[str] = None  # SUB-XXXX-... format
    invoice_number: Optional[str] = None
    zip_code: Optional[str] = None
    email: Optional[str] = None


def _agpl_mode() -> bool:
    """Check if AGPL/Community mode is active (lazy import for startup speed)."""
    try:
        from ..services.license_manager import is_agpl_mode
        return is_agpl_mode()
    except Exception:
        return False


@router.get("/license/status")
async def get_license_status():
    """
    Get current license status.

    Returns the full 14-field license schema (matches the AGPL
    ``NullLicenseProvider`` schema, see ``license_manager.py``).
    """
    if _agpl_mode():
        from ..services.license_manager import NullLicenseProvider
        return NullLicenseProvider.get_license_status()

    from ..services.license_manager import LicenseManager
    manager = LicenseManager.get_instance()
    return manager.get_license_status()


@router.post("/license/activate")
async def activate_license(body: ActivateRequest):
    """
    Activate license with code OR invoice+zip.

    In AGPL mode this is a no-op that returns
    ``{"success": false, "reason": "agpl_mode"}``.
    """
    if _agpl_mode():
        from ..services.license_manager import NullLicenseProvider
        return NullLicenseProvider.activate()

    from ..services.license_manager import LicenseManager
    manager = LicenseManager.get_instance()

    # Validate input
    if not body.code and not (body.invoice_number and body.zip_code):
        raise HTTPException(
            status_code=400,
            detail="Provide either 'code' or 'invoice_number' + 'zip_code'"
        )

    result = manager.start_session(
        code=body.code,
        invoice_number=body.invoice_number,
        zip_code=body.zip_code,
        email=body.email
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/license/deactivate")
async def deactivate_license():
    """
    End current session and clear saved credentials.

    In AGPL mode this is a no-op that returns ``{"success": true}``.
    """
    if _agpl_mode():
        from ..services.license_manager import NullLicenseProvider
        return NullLicenseProvider.deactivate()

    from ..services.license_manager import LicenseManager
    manager = LicenseManager.get_instance()
    manager.end_session()
    manager.clear_credentials()
    return {"status": "ok", "message": "License deactivated"}


@router.get("/license/credentials")
async def get_saved_credentials():
    """
    Get saved activation credentials for UI pre-fill.

    In AGPL mode this returns ``{}``.
    """
    if _agpl_mode():
        from ..services.license_manager import NullLicenseProvider
        return NullLicenseProvider.get_saved_credentials()

    from ..services.license_manager import LicenseManager
    manager = LicenseManager.get_instance()
    return manager.get_saved_credentials()


@router.get("/license/check-agent")
async def check_agent_license(agent_name: str = None):
    """
    Check if an agent can be executed with current license.

    Called before agent execution to implement soft lock.

    In AGPL mode all agents are always allowed.
    """
    if _agpl_mode():
        from ..services.license_manager import NullLicenseProvider
        return NullLicenseProvider.check_agent(agent_name)

    from ..services.license_manager import LicenseManager
    manager = LicenseManager.get_instance()

    if not manager.is_licensed():
        return {
            "allowed": False,
            "reason": "no_license",
            "message": "License required to run agents. Please activate your license in Settings."
        }

    # Future: Check edition-based feature gating
    # edition = manager.get_license_status().get("edition")
    # if not is_agent_allowed_for_edition(agent_name, edition):
    #     return {"allowed": False, "reason": "edition_limit", "message": "..."}

    return {"allowed": True}
