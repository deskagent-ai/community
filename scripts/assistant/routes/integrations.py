# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
FastAPI Integrations Routes for Unified Integrations Hub
=========================================================
Provides endpoints for listing, configuring, and testing integrations.

Endpoints:
- GET /api/integrations/list - List all integrations with schemas and status
- GET /api/integrations/{name} - Get single integration details
- GET /api/integrations/by-auth-type - Get integrations grouped by auth type
- POST /api/integrations/{name}/test - Test an integration connection
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

# Import system logger
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): print(msg)

# Import integration schema service
from ..services.integration_schema import (
    get_all_integrations,
    get_all_integration_schemas,
    get_integrations_by_auth_type,
    get_integration_status,
    IntegrationInfo,
    IntegrationSchema,
    AuthType,
)


router = APIRouter(prefix="/api/integrations")


# =============================================================================
# Response Models
# =============================================================================

class FieldInfo(BaseModel):
    """Information about a configuration field."""
    key: str
    label: str
    type: str
    required: bool
    hint: Optional[str] = None
    default: Optional[str | int | bool] = None


class OAuthInfo(BaseModel):
    """OAuth configuration info."""
    custom_auth: bool = False
    token_file: Optional[str] = None
    auth_url: Optional[str] = None
    token_url: Optional[str] = None


class IntegrationSchemaResponse(BaseModel):
    """Schema information for an integration."""
    name: str
    icon: str
    color: str
    config_key: Optional[str] = None
    auth_type: str
    fields: list[FieldInfo] = []
    oauth: Optional[OAuthInfo] = None
    test_tool: Optional[str] = None
    description: Optional[str] = None
    beta: bool = False


class IntegrationResponse(BaseModel):
    """Full integration info including status."""
    mcp_name: str
    config: IntegrationSchemaResponse  # Renamed from 'schema' to avoid shadowing BaseModel attribute
    status: str
    has_is_configured: bool = False


class IntegrationsByAuthTypeResponse(BaseModel):
    """Integrations grouped by auth type."""
    oauth: list[IntegrationResponse] = []
    api_key: list[IntegrationResponse] = []
    credentials: list[IntegrationResponse] = []
    none: list[IntegrationResponse] = []


class TestResult(BaseModel):
    """Result of testing an integration."""
    success: bool
    message: str
    details: Optional[dict] = None


# =============================================================================
# Helper Functions
# =============================================================================

def _convert_schema(schema: IntegrationSchema) -> IntegrationSchemaResponse:
    """Convert internal schema to response model."""
    fields = [
        FieldInfo(
            key=f["key"],
            label=f["label"],
            type=f["type"],
            required=f.get("required", False),
            hint=f.get("hint"),
            default=f.get("default"),
        )
        for f in schema.get("fields", [])
    ]

    oauth = None
    if schema.get("auth_type") == "oauth" and "oauth" in schema:
        oauth_data = schema["oauth"]
        oauth = OAuthInfo(
            custom_auth=oauth_data.get("custom_auth", False),
            token_file=oauth_data.get("token_file"),
            auth_url=oauth_data.get("auth_url"),
            token_url=oauth_data.get("token_url"),
        )

    return IntegrationSchemaResponse(
        name=schema.get("name", "Unknown"),
        icon=schema.get("icon", "extension"),
        color=schema.get("color", "#757575"),
        config_key=schema.get("config_key"),
        auth_type=schema.get("auth_type", "none"),
        fields=fields,
        oauth=oauth,
        test_tool=schema.get("test_tool"),
        description=schema.get("description"),
        beta=schema.get("beta", False),
    )


def _convert_integration(info: IntegrationInfo) -> IntegrationResponse:
    """Convert internal integration info to response model."""
    return IntegrationResponse(
        mcp_name=info["mcp_name"],
        config=_convert_schema(info["schema"]),
        status=info["status"],
        has_is_configured=info["has_is_configured"],
    )


# =============================================================================
# Routes
# =============================================================================

@router.get("/list", response_model=list[IntegrationResponse])
async def list_integrations():
    """
    List all available integrations with their schemas and configuration status.

    Returns integrations sorted by display name, including:
    - Schema (name, icon, color, auth_type, fields)
    - Current configuration status
    - Whether MCP has is_configured() function
    """
    try:
        integrations = get_all_integrations()
        return [_convert_integration(i) for i in integrations]
    except Exception as e:
        system_log(f"[Integrations] Error listing integrations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-auth-type", response_model=IntegrationsByAuthTypeResponse)
async def list_by_auth_type():
    """
    List all integrations grouped by authentication type.

    Groups:
    - oauth: OAuth2 authenticated services (Gmail, Microsoft 365, etc.)
    - api_key: API key authenticated services (Billomat, UserEcho, etc.)
    - credentials: Username/password services (ecoDMS, IMAP, etc.)
    - none: No auth required (local services like Outlook COM)
    """
    try:
        grouped = get_integrations_by_auth_type()
        return IntegrationsByAuthTypeResponse(
            oauth=[_convert_integration(i) for i in grouped.get("oauth", [])],
            api_key=[_convert_integration(i) for i in grouped.get("api_key", [])],
            credentials=[_convert_integration(i) for i in grouped.get("credentials", [])],
            none=[_convert_integration(i) for i in grouped.get("none", [])],
        )
    except Exception as e:
        system_log(f"[Integrations] Error grouping integrations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{name}", response_model=IntegrationResponse)
async def get_integration(name: str):
    """
    Get details for a specific integration by MCP name.

    Args:
        name: The MCP name (e.g., "gmail", "billomat", "outlook")
    """
    try:
        schemas = get_all_integration_schemas()

        if name not in schemas:
            raise HTTPException(
                status_code=404,
                detail=f"Integration '{name}' not found"
            )

        schema = schemas[name]
        status = get_integration_status(name, schema)

        # Check for is_configured function
        from ..services.integration_schema import _check_mcp_is_configured
        from paths import get_mcp_dir

        mcp_dir = get_mcp_dir()
        mcp_path = mcp_dir / name
        if mcp_path.is_dir():
            module_file = mcp_path / "__init__.py"
        else:
            module_file = mcp_dir / f"{name}_mcp.py"

        _, has_function = _check_mcp_is_configured(module_file, name)

        info: IntegrationInfo = {
            "mcp_name": name,
            "schema": schema,
            "status": status,
            "has_is_configured": has_function,
        }

        return _convert_integration(info)

    except HTTPException:
        raise
    except Exception as e:
        system_log(f"[Integrations] Error getting integration {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/test", response_model=TestResult)
async def test_integration(name: str):
    """
    Test an integration by calling its test_tool or is_configured().

    This endpoint attempts to verify that an integration is properly
    configured and can connect to its backend service.

    Args:
        name: The MCP name to test

    Returns:
        TestResult with success status and message
    """
    try:
        schemas = get_all_integration_schemas()

        if name not in schemas:
            raise HTTPException(
                status_code=404,
                detail=f"Integration '{name}' not found"
            )

        schema = schemas[name]

        # First check if integration has a test_tool defined
        test_tool = schema.get("test_tool")
        if test_tool:
            # TODO: Implement tool execution for testing
            # For now, just check is_configured
            pass

        # Use is_configured() if available
        from ..services.integration_schema import _check_mcp_is_configured
        from paths import get_mcp_dir

        mcp_dir = get_mcp_dir()
        mcp_path = mcp_dir / name
        if mcp_path.is_dir():
            module_file = mcp_path / "__init__.py"
        else:
            module_file = mcp_dir / f"{name}_mcp.py"

        is_configured, has_function = _check_mcp_is_configured(module_file, name)

        if has_function:
            if is_configured:
                return TestResult(
                    success=True,
                    message=f"{schema.get('name', name)} is configured and ready",
                    details={"method": "is_configured"}
                )
            else:
                return TestResult(
                    success=False,
                    message=f"{schema.get('name', name)} is not properly configured",
                    details={"method": "is_configured"}
                )

        # No is_configured function - check based on schema
        status = get_integration_status(name, schema)

        if status in ("configured", "connected"):
            return TestResult(
                success=True,
                message=f"{schema.get('name', name)} appears to be configured",
                details={"method": "schema_check", "status": status}
            )
        else:
            return TestResult(
                success=False,
                message=f"{schema.get('name', name)} status: {status}",
                details={"method": "schema_check", "status": status}
            )

    except HTTPException:
        raise
    except Exception as e:
        system_log(f"[Integrations] Error testing integration {name}: {e}")
        return TestResult(
            success=False,
            message=f"Test failed: {str(e)}",
            details={"error": str(e)}
        )


@router.post("/reload")
async def reload_schemas():
    """
    Force reload all integration schemas from MCP files.

    Useful after adding new MCPs or modifying INTEGRATION_SCHEMA.
    """
    try:
        from ..services.integration_schema import reload_schemas
        schemas = reload_schemas()
        return {
            "success": True,
            "message": f"Reloaded {len(schemas)} integration schemas",
            "integrations": list(schemas.keys())
        }
    except Exception as e:
        system_log(f"[Integrations] Error reloading schemas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Configuration Management Routes
# =============================================================================

class ConfigUpdateRequest(BaseModel):
    """Request body for updating integration configuration."""
    config: dict


class ConfigResponse(BaseModel):
    """Response containing integration configuration."""
    mcp_name: str
    config_key: Optional[str]
    config: dict


@router.get("/{name}/config", response_model=ConfigResponse)
async def get_integration_config(name: str):
    """
    Get the current configuration values for an integration.

    Returns the configuration from apis.json for the integration's config_key.
    Passwords are masked (only last 3 chars shown) for security.

    Args:
        name: The MCP name (e.g., "billomat", "ecodms")
    """
    try:
        schemas = get_all_integration_schemas()

        if name not in schemas:
            raise HTTPException(
                status_code=404,
                detail=f"Integration '{name}' not found"
            )

        schema = schemas[name]
        config_key = schema.get("config_key")

        if not config_key:
            # Local integration with no config
            return ConfigResponse(
                mcp_name=name,
                config_key=None,
                config={}
            )

        # Load from apis.json
        from paths import get_apis_config_path
        import json

        apis_path = get_apis_config_path()
        apis_config = {}
        if apis_path.exists():
            apis_config = json.loads(apis_path.read_text(encoding="utf-8"))

        integration_config = apis_config.get(config_key, {})

        # Mask password fields for security
        fields = schema.get("fields", [])
        masked_config = {}
        for field in fields:
            key = field["key"]
            value = integration_config.get(key, "")
            if field.get("type") == "password" and value:
                # Show only last 3 characters
                masked_config[key] = "••••••••" + value[-3:] if len(value) > 3 else "••••"
            else:
                masked_config[key] = value

        return ConfigResponse(
            mcp_name=name,
            config_key=config_key,
            config=masked_config
        )

    except HTTPException:
        raise
    except Exception as e:
        system_log(f"[Integrations] Error getting config for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/config")
async def save_integration_config(name: str, request: ConfigUpdateRequest):
    """
    Save configuration for an integration.

    Updates apis.json with the new configuration values.
    Only fields defined in the integration's schema are saved.

    Args:
        name: The MCP name
        request: Configuration key-value pairs to save
    """
    try:
        schemas = get_all_integration_schemas()

        if name not in schemas:
            raise HTTPException(
                status_code=404,
                detail=f"Integration '{name}' not found"
            )

        schema = schemas[name]
        config_key = schema.get("config_key")

        if not config_key:
            raise HTTPException(
                status_code=400,
                detail=f"Integration '{name}' does not support configuration"
            )

        # Validate fields against schema
        allowed_fields = {f["key"] for f in schema.get("fields", [])}
        provided_fields = set(request.config.keys())
        unknown_fields = provided_fields - allowed_fields

        if unknown_fields:
            system_log(f"[Integrations] Warning: Unknown fields for {name}: {unknown_fields}")

        # Load current apis.json
        from paths import get_apis_config_path
        import json

        apis_path = get_apis_config_path()
        apis_config = {}
        if apis_path.exists():
            apis_config = json.loads(apis_path.read_text(encoding="utf-8"))

        # Get current config for this integration
        current_config = apis_config.get(config_key, {})

        # Update only the provided fields
        # Skip masked password values (don't overwrite with mask)
        for key, value in request.config.items():
            if key in allowed_fields:
                # Check if it's a masked password value
                if value and value.startswith("••••"):
                    # Don't overwrite with mask, keep current value
                    continue
                current_config[key] = value

        # Save back
        apis_config[config_key] = current_config

        # Ensure directory exists
        apis_path.parent.mkdir(parents=True, exist_ok=True)

        apis_path.write_text(
            json.dumps(apis_config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        system_log(f"[Integrations] Saved config for {name} ({config_key})")

        return {
            "success": True,
            "message": f"Configuration saved for {schema.get('name', name)}",
            "config_key": config_key
        }

    except HTTPException:
        raise
    except Exception as e:
        system_log(f"[Integrations] Error saving config for {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
