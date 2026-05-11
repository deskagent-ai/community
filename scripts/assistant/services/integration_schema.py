# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Integration Schema Service
==========================
Unified infrastructure for MCP integration configuration.

Collects INTEGRATION_SCHEMA from all MCPs for the Integrations Hub.
Provides helpers for checking configuration status and field validation.

Auth Types:
- oauth: OAuth2 flow (custom or standard)
- api_key: Simple API key authentication
- credentials: Username/password pair
- none: No authentication required (local services like Outlook COM)
- custom: Custom configuration (MCP-specific config file, e.g. banking.json)

Schema Format:
    INTEGRATION_SCHEMA = {
        "name": "Display Name",
        "icon": "material_icon",
        "color": "#hex",
        "config_key": "key_in_apis_json",  # None for local MCPs
        "auth_type": "oauth|api_key|credentials|none",
        "fields": [{"key": "...", "label": "...", "type": "...", "required": bool}],
        "oauth": {"custom_auth": bool, "token_file": "..."},  # For oauth type
        "test_tool": "tool_name_to_test",  # Optional
    }
"""

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import TypedDict, Literal, NotRequired

# Import system_log for logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# Import paths
try:
    from paths import get_mcp_dir, get_apis_config_path, get_config_dir
except ImportError:
    # Fallback for standalone execution
    def get_mcp_dir():
        return Path(__file__).parent.parent.parent.parent / "mcp"
    def get_apis_config_path():
        return Path(__file__).parent.parent.parent.parent.parent / "config" / "apis.json"
    def get_config_dir():
        return Path(__file__).parent.parent.parent.parent.parent / "config"


# =============================================================================
# Type Definitions
# =============================================================================

AuthType = Literal["oauth", "api_key", "credentials", "none", "custom"]


class FieldDefinition(TypedDict):
    """Definition of a configuration field."""
    key: str
    label: str
    type: Literal["text", "password", "url", "number", "boolean"]
    required: bool
    hint: NotRequired[str]
    default: NotRequired[str | int | bool]


class OAuthConfig(TypedDict, total=False):
    """OAuth-specific configuration."""
    custom_auth: bool  # True if MCP handles its own auth flow
    token_file: str    # Path to token cache file
    auth_url: NotRequired[str]   # For standard OAuth
    token_url: NotRequired[str]  # For standard OAuth
    scopes: NotRequired[list[str]]


class SetupInfo(TypedDict, total=False):
    """Setup hints for Prerequisites dialog.

    Contains user-facing information about how to configure an MCP.
    Migrated from the former central mcp_hints.py (plan-047).
    """
    description: str              # Short description ("Rechnungen und Angebote")
    requirement: str              # What is needed ("Billomat API Key")
    alternative: NotRequired[str] # Alternative MCP ("msgraph")
    setup_steps: list[str]        # Setup steps (HTML allowed)


class IntegrationSchema(TypedDict, total=False):
    """Schema definition for an integration."""
    name: str
    icon: str
    color: str
    config_key: str | None  # Key in apis.json, None for local MCPs
    auth_type: AuthType
    fields: list[FieldDefinition]
    oauth: OAuthConfig
    test_tool: str  # Tool to call for testing connection
    description: str  # Optional description
    setup: NotRequired[SetupInfo]  # Setup hints for Prerequisites dialog (plan-047)


class IntegrationInfo(TypedDict):
    """Full information about an integration including status."""
    mcp_name: str
    schema: IntegrationSchema
    status: Literal["configured", "not_configured", "no_token", "connected", "expired", "disabled"]
    has_is_configured: bool  # True if MCP has is_configured() function


# =============================================================================
# Schema Collection
# =============================================================================

# Cache for schemas (loaded once)
_schema_cache: dict[str, IntegrationSchema] | None = None


def _extract_schema_via_ast(module_file: Path) -> dict | None:
    """Extract INTEGRATION_SCHEMA from a Python file using AST parsing.

    This avoids executing the module (and its imports like _mcp_api).
    Works for schemas defined as pure dict literals.

    Returns:
        Schema dict or None if not found or not a literal
    """
    try:
        source = module_file.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(module_file))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "INTEGRATION_SCHEMA":
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    # Not a pure literal (e.g. f-strings, variable refs)
                    return None
    return None


def _load_schema_from_file(module_file: Path, mcp_name: str) -> IntegrationSchema | None:
    """Load INTEGRATION_SCHEMA from a single MCP module file.

    Strategy:
    1. AST parsing (fast, no imports, works without _mcp_api)
    2. exec_module fallback (for schemas with dynamic values)

    Args:
        module_file: Path to the Python file (__init__.py or *_mcp.py)
        mcp_name: Name of the MCP server

    Returns:
        Schema dict or None if not available
    """
    # --- Phase 1: AST extraction (no code execution) ---
    schema = _extract_schema_via_ast(module_file)
    if schema is not None:
        if 'auth_type' not in schema:
            schema['auth_type'] = 'none'
        if 'fields' not in schema:
            schema['fields'] = []
        return schema

    # --- Phase 2: exec_module fallback (for dynamic schemas) ---
    try:
        safe_name = mcp_name.replace(":", "_")
        spec = importlib.util.spec_from_file_location(
            f"{safe_name}_schema", module_file
        )
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'INTEGRATION_SCHEMA'):
            schema = dict(module.INTEGRATION_SCHEMA)
            if 'auth_type' not in schema:
                schema['auth_type'] = 'none'
            if 'fields' not in schema:
                schema['fields'] = []
            return schema

        # Legacy: Generate schema from AUTH_CONFIG + TOOL_METADATA
        auth_config = getattr(module, 'AUTH_CONFIG', None)
        tool_metadata = getattr(module, 'TOOL_METADATA', {})

        if auth_config and auth_config.get('type') == 'oauth2':
            schema: IntegrationSchema = {
                'name': auth_config.get('display_name', mcp_name.title()),
                'icon': auth_config.get('icon', tool_metadata.get('icon', 'extension')),
                'color': auth_config.get('color', tool_metadata.get('color', '#757575')),
                'config_key': mcp_name,
                'auth_type': 'oauth',
                'fields': [],
                'oauth': {
                    'custom_auth': auth_config.get('custom_auth', False),
                    'token_file': auth_config.get('token_file', f'.{mcp_name}_token.json'),
                },
            }
            config_keys = auth_config.get('config_keys', [])
            for key in config_keys:
                field: FieldDefinition = {
                    'key': key,
                    'label': key.replace('_', ' ').title(),
                    'type': 'password' if 'secret' in key.lower() else 'text',
                    'required': True,
                }
                schema['fields'].append(field)
            if 'auth_url' in auth_config:
                schema['oauth']['auth_url'] = auth_config['auth_url']
            if 'token_url' in auth_config:
                schema['oauth']['token_url'] = auth_config['token_url']
            if 'scopes' in auth_config:
                schema['oauth']['scopes'] = auth_config['scopes']
            return schema

        if tool_metadata:
            schema: IntegrationSchema = {
                'name': mcp_name.title(),
                'icon': tool_metadata.get('icon', 'extension'),
                'color': tool_metadata.get('color', '#757575'),
                'config_key': None,
                'auth_type': 'none',
                'fields': [],
            }
            return schema

        return None

    except Exception as e:
        system_log(f"[Integration Schema] Could not load {mcp_name}: {e}")
        return None


def _check_has_is_configured_ast(module_file: Path) -> bool:
    """Check if a module defines 'def is_configured' using AST parsing.

    This is a fast, side-effect-free alternative to exec_module().
    It only checks for the existence of the function definition,
    without executing any code.

    Args:
        module_file: Path to the Python module file

    Returns:
        True if the file contains a top-level 'def is_configured' definition
    """
    try:
        if not module_file.exists():
            return False
        source = module_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_file))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "is_configured":
                return True
        return False
    except Exception:
        return False


def _check_mcp_is_configured(module_file: Path, mcp_name: str) -> tuple[bool, bool]:
    """Check if an MCP is configured using its is_configured() function.

    Args:
        module_file: Path to the MCP module file
        mcp_name: Name of the MCP

    Returns:
        Tuple of (is_configured: bool, has_function: bool)
    """
    try:
        # Sanitize module name (replace : with _ for plugin MCPs)
        safe_name = mcp_name.replace(":", "_")
        spec = importlib.util.spec_from_file_location(
            f"{safe_name}_check", module_file
        )
        if not spec or not spec.loader:
            return False, False

        module = importlib.util.module_from_spec(spec)

        # Add scripts path for imports that the MCP might need
        mcp_dir = get_mcp_dir()
        scripts_path = str(mcp_dir.parent / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)

        spec.loader.exec_module(module)

        if hasattr(module, 'is_configured') and callable(module.is_configured):
            try:
                result = module.is_configured()
                return bool(result), True
            except Exception as e:
                system_log(f"[Integration Schema] is_configured() failed for {mcp_name}: {e}")
                return False, True

        return False, False

    except Exception as e:
        system_log(f"[Integration Schema] Could not check {mcp_name}: {e}")
        return False, False


def get_all_integration_schemas(refresh: bool = False) -> dict[str, IntegrationSchema]:
    """Scan all MCPs and collect their INTEGRATION_SCHEMA.

    Args:
        refresh: If True, force reload from files (ignore cache)

    Returns:
        Dict mapping MCP name to its schema
    """
    global _schema_cache

    if _schema_cache is not None and not refresh:
        return _schema_cache

    schemas = {}

    # Try centralized MCP discovery first
    try:
        from ai_agent.mcp_discovery import discover_mcp_servers

        servers = discover_mcp_servers()  # No filter = all servers
        for server in servers:
            mcp_name = server['name']
            path = server['path']

            # Determine file to load based on type
            if server['type'] == 'file':
                module_file = path
            else:  # package or plugin
                module_file = path / "__init__.py"

            if not module_file.exists():
                continue

            schema = _load_schema_from_file(module_file, mcp_name)
            if schema:
                schemas[mcp_name] = schema

        _schema_cache = schemas
        return schemas

    except ImportError:
        system_log("[Integration Schema] Fallback: discover_mcp_servers not available")

    # Fallback: Direct directory scanning
    mcp_dir = get_mcp_dir()
    if not mcp_dir.exists():
        _schema_cache = schemas
        return schemas

    # 1. Package-based MCPs: folder/__init__.py
    for item in mcp_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            init_file = item / "__init__.py"
            if init_file.exists():
                mcp_name = item.name
                schema = _load_schema_from_file(init_file, mcp_name)
                if schema:
                    schemas[mcp_name] = schema

    # 2. Legacy single-file MCPs: *_mcp.py
    for mcp_file in mcp_dir.glob("*_mcp.py"):
        if mcp_file.stem == "anonymization_proxy_mcp":
            continue

        mcp_name = mcp_file.stem.replace('_mcp', '')
        if mcp_name not in schemas:  # Don't override packages
            schema = _load_schema_from_file(mcp_file, mcp_name)
            if schema:
                schemas[mcp_name] = schema

    _schema_cache = schemas
    return schemas


def reload_schemas() -> dict[str, IntegrationSchema]:
    """Force reload all schemas from MCP files."""
    return get_all_integration_schemas(refresh=True)


def get_schema_for_mcp(mcp_name: str) -> IntegrationSchema | None:
    """Get INTEGRATION_SCHEMA for a specific MCP.

    Uses the cached schema collection. If not yet loaded, triggers a full scan.

    Args:
        mcp_name: Name of the MCP server (e.g. "billomat", "outlook")

    Returns:
        Schema dict or None if MCP has no schema
    """
    schemas = get_all_integration_schemas()
    return schemas.get(mcp_name)


# =============================================================================
# Declarative Prerequisites Check (planfeature-042)
# =============================================================================

def check_mcp_configured_from_schema(mcp_name: str) -> bool:
    """Check MCP configuration declaratively via INTEGRATION_SCHEMA.

    Loads INTEGRATION_SCHEMA from MCP module (without full import) and checks
    config fields directly against apis.json - NO HTTP call needed.

    This replaces the old importlib-based is_configured() approach for
    prerequisites checks in discovery.py.

    Args:
        mcp_name: Name of the MCP server (e.g. "billomat", "msgraph")

    Returns:
        True if configured, False if config is missing
    """
    schema = get_schema_for_mcp(mcp_name)
    if not schema:
        return False  # No schema = not checkable

    auth_type = schema.get("auth_type", "none")

    # auth_type "none" = always available (e.g. outlook COM, clipboard, filesystem)
    if auth_type == "none":
        return True

    # Load config directly (no HTTP, compiled server has direct access)
    try:
        from config import load_config
        config = load_config()
    except ImportError:
        # Fallback to apis.json only
        config = _load_apis_config()

    # Check enabled flag
    config_key = schema.get("config_key", mcp_name)
    if config_key:
        mcp_config = config.get(config_key, {})
        if mcp_config.get("enabled") is False:
            return False

    # OAuth: Check token file existence (using existing get_integration_status)
    if auth_type == "oauth":
        status = get_integration_status(mcp_name, schema)
        # "connected" or "expired" means token exists (configured)
        # "no_token" means configured but needs OAuth connect
        # "not_configured" means fields missing
        return status not in ("not_configured", "disabled")

    # Custom (e.g. SEPA): Special handler
    if auth_type == "custom":
        return _check_custom_configured(mcp_name, schema, config)

    # Standard (api_key, credentials): Check required fields against config
    return is_integration_configured(schema, config)


def _check_custom_configured(mcp_name: str, schema: IntegrationSchema, config: dict) -> bool:
    """Check configuration for custom auth_type MCPs.

    Handles special cases like SEPA (banking.json) that don't use apis.json.

    Args:
        mcp_name: MCP name
        schema: Integration schema
        config: Loaded config dict

    Returns:
        True if configured
    """
    config_file = schema.get("config_file")

    # SEPA special case: banking.json with account entries
    if config_file == "banking.json":
        try:
            banking_path = get_config_dir() / "banking.json"
            if not banking_path.exists():
                return False

            banking_data = json.loads(banking_path.read_text(encoding="utf-8"))

            # Check if at least one enabled account has an IBAN
            for key, value in banking_data.items():
                if key == "default":
                    continue
                if isinstance(value, dict):
                    if value.get("enabled") is False:
                        continue
                    if value.get("iban"):
                        return True

            return False
        except Exception as e:
            system_log(f"[Integration Schema] Error checking banking.json: {e}")
            return False

    # Generic custom: Check if config_key has any non-empty values
    config_key = schema.get("config_key", mcp_name)
    if config_key:
        mcp_config = config.get(config_key, {})
        if mcp_config.get("enabled") is False:
            return False
        # Check required fields if any
        return is_integration_configured(schema, config)

    return False


# =============================================================================
# Configuration Status
# =============================================================================

def _load_apis_config() -> dict:
    """Load apis.json configuration."""
    try:
        config_path = get_apis_config_path()
        if config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        system_log(f"[Integration Schema] Error loading apis.json: {e}")
    return {}


def _get_token_path(schema: IntegrationSchema) -> Path | None:
    """Get the token file path for an OAuth integration."""
    if schema.get('auth_type') != 'oauth':
        return None

    oauth_config = schema.get('oauth', {})
    token_file = oauth_config.get('token_file')
    if not token_file:
        return None

    return get_config_dir() / token_file


def _is_token_valid(token_path: Path) -> bool:
    """Check if a token file exists and is not expired."""
    if not token_path.exists():
        return False

    try:
        from datetime import datetime
        token_data = json.loads(token_path.read_text(encoding="utf-8"))

        # Check expires_at if present
        expires_at = token_data.get('expires_at')
        if expires_at:
            expiry = datetime.fromisoformat(expires_at)
            if datetime.now() >= expiry:
                return False  # Expired

        return True
    except Exception:
        return False


def is_integration_configured(schema: IntegrationSchema, config: dict | None = None) -> bool:
    """Check if an integration is configured based on its schema.

    Args:
        schema: The integration schema
        config: Optional apis.json config (loaded if not provided)

    Returns:
        True if all required fields are configured
    """
    if config is None:
        config = _load_apis_config()

    auth_type = schema.get('auth_type', 'none')
    config_key = schema.get('config_key')

    # No auth required
    if auth_type == 'none':
        return True

    # Get integration-specific config
    if not config_key:
        return True  # No config key means no external config needed

    integration_config = config.get(config_key, {})

    # Check if explicitly disabled
    if integration_config.get('enabled') is False:
        return False

    # Check required fields
    fields = schema.get('fields', [])
    for field in fields:
        if field.get('required', False):
            key = field['key']
            if not integration_config.get(key):
                return False

    return True


def get_integration_status(
    mcp_name: str,
    schema: IntegrationSchema
) -> Literal["configured", "not_configured", "no_token", "connected", "expired", "disabled"]:
    """Get the configuration status of an integration.

    Args:
        mcp_name: Name of the MCP
        schema: The integration schema

    Returns:
        Status string:
        - "disabled": Explicitly disabled in config
        - "not_configured": Missing required fields
        - "no_token": OAuth configured but no token yet (show "Connect" button)
        - "configured": All fields set (for api_key/credentials/none)
        - "connected": OAuth token valid
        - "expired": OAuth token expired
    """
    apis_config = _load_apis_config()
    config_key = schema.get('config_key')
    auth_type = schema.get('auth_type', 'none')

    # Check if explicitly disabled
    if config_key:
        integration_config = apis_config.get(config_key, {})
        if integration_config.get('enabled') is False:
            return "disabled"

    # Check required fields
    if not is_integration_configured(schema, apis_config):
        return "not_configured"

    # For OAuth, also check token status
    if auth_type == 'oauth':
        token_path = _get_token_path(schema)
        if token_path:
            if not token_path.exists():
                # Configured but no token yet - show "Connect" button
                return "no_token"
            if not _is_token_valid(token_path):
                return "expired"
            return "connected"

    return "configured"


def get_all_integrations() -> list[IntegrationInfo]:
    """Get all integrations with their schemas and status.

    Returns:
        List of IntegrationInfo dicts, sorted by name
    """
    schemas = get_all_integration_schemas()
    mcp_dir = get_mcp_dir()
    result = []

    # Build a lookup for plugin MCP paths from discovery
    plugin_paths = {}
    try:
        from ai_agent.mcp_discovery import discover_mcp_servers
        servers = discover_mcp_servers()
        for server in servers:
            if server.get('type') == 'plugin':
                plugin_paths[server['name']] = server['path']
    except ImportError:
        pass

    for mcp_name, schema in schemas.items():
        # Determine module file for is_configured check
        if ":" in mcp_name and mcp_name in plugin_paths:
            # Plugin MCP - use path from discovery
            module_file = plugin_paths[mcp_name] / "__init__.py"
        else:
            # Standard MCP
            mcp_path = mcp_dir / mcp_name
            if mcp_path.is_dir():
                module_file = mcp_path / "__init__.py"
            else:
                module_file = mcp_dir / f"{mcp_name}_mcp.py"

        # Fast AST check for is_configured() existence (no module execution)
        has_function = _check_has_is_configured_ast(module_file)

        # Get status from config/token checks (no MCP execution needed)
        status = get_integration_status(mcp_name, schema)

        result.append({
            'mcp_name': mcp_name,
            'schema': schema,
            'status': status,
            'has_is_configured': has_function,
        })

    # Sort by name
    result.sort(key=lambda x: x['schema'].get('name', x['mcp_name']))
    return result


def get_integrations_by_auth_type() -> dict[AuthType, list[IntegrationInfo]]:
    """Get all integrations grouped by auth type.

    Returns:
        Dict mapping auth type to list of IntegrationInfo
    """
    all_integrations = get_all_integrations()

    result: dict[AuthType, list[IntegrationInfo]] = {
        'oauth': [],
        'api_key': [],
        'credentials': [],
        'none': [],
        'custom': [],
    }

    for integration in all_integrations:
        auth_type = integration['schema'].get('auth_type', 'none')
        if auth_type in result:
            result[auth_type].append(integration)
        else:
            result['none'].append(integration)

    return result
