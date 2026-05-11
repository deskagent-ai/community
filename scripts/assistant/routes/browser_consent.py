# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Routes for Browser Integration Consent.

Provides endpoints for managing user consent for browser integration feature.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/browser-consent/status")
async def get_consent_status():
    """
    Get current consent status.

    Returns:
        JSON with consent_given, timestamp, version
    """
    from ..browser_consent import get_consent_info

    info = get_consent_info()
    return JSONResponse(info)


@router.post("/browser-consent/grant")
async def grant_consent():
    """
    Grant consent for browser integration.

    Returns:
        JSON with success status
    """
    from ..browser_consent import grant_consent as grant

    success = grant()

    if success:
        return {"success": True, "message": "Consent granted"}
    else:
        raise HTTPException(status_code=500, detail="Failed to save consent")


@router.post("/browser-consent/revoke")
async def revoke_consent():
    """
    Revoke consent for browser integration.

    Returns:
        JSON with success status
    """
    from ..browser_consent import revoke_consent as revoke

    success = revoke()

    if success:
        return {"success": True, "message": "Consent revoked"}
    else:
        raise HTTPException(status_code=500, detail="Failed to revoke consent")


@router.post("/browser-consent/decline")
async def decline_consent():
    """
    Decline consent for browser integration.

    Returns:
        JSON with success status
    """
    from ..browser_consent import decline_consent as decline

    success = decline()

    if success:
        return {"success": True, "message": "Consent declined"}
    else:
        raise HTTPException(status_code=500, detail="Failed to save decline")
