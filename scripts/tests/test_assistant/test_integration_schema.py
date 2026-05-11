# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for integration schema service.
"""

import pytest


class TestIntegrationSchemaService:
    """Tests for the integration schema service."""

    def test_get_all_integration_schemas(self):
        """Test that schemas can be loaded from MCPs."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        # Should have at least some schemas
        assert len(schemas) > 0

        # Check that each schema has required fields
        for mcp_name, schema in schemas.items():
            assert "name" in schema, f"Schema for {mcp_name} missing 'name'"
            assert "icon" in schema, f"Schema for {mcp_name} missing 'icon'"
            assert "color" in schema, f"Schema for {mcp_name} missing 'color'"
            assert "auth_type" in schema, f"Schema for {mcp_name} missing 'auth_type'"

    def test_schema_auth_types(self):
        """Test that auth_type is always valid."""
        from assistant.services.integration_schema import get_all_integration_schemas

        valid_auth_types = {"oauth", "api_key", "credentials", "none", "custom", "token"}
        schemas = get_all_integration_schemas()

        for mcp_name, schema in schemas.items():
            auth_type = schema.get("auth_type", "none")
            assert auth_type in valid_auth_types, f"Invalid auth_type for {mcp_name}: {auth_type}"

    def test_oauth_schema_has_oauth_config(self):
        """Test that OAuth schemas have oauth config."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        for mcp_name, schema in schemas.items():
            if schema.get("auth_type") == "oauth":
                # OAuth schemas should have oauth config
                assert "oauth" in schema or schema.get("config_key") is not None, \
                    f"OAuth schema {mcp_name} missing oauth config"

    def test_api_key_schema_has_fields(self):
        """Test that api_key schemas have required fields."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        for mcp_name, schema in schemas.items():
            if schema.get("auth_type") == "api_key":
                fields = schema.get("fields", [])
                # Should have at least one field for the API key
                assert len(fields) > 0, f"api_key schema {mcp_name} should have fields"

    def test_get_all_integrations(self):
        """Test that integrations include status."""
        from assistant.services.integration_schema import get_all_integrations

        integrations = get_all_integrations()

        # Should have at least some integrations
        assert len(integrations) > 0

        # Check structure
        for integration in integrations:
            assert "mcp_name" in integration
            assert "schema" in integration
            assert "status" in integration
            assert "has_is_configured" in integration

    def test_get_integrations_by_auth_type(self):
        """Test grouping by auth type."""
        from assistant.services.integration_schema import get_integrations_by_auth_type

        grouped = get_integrations_by_auth_type()

        # Should have all auth type keys
        assert "oauth" in grouped
        assert "api_key" in grouped
        assert "credentials" in grouped
        assert "none" in grouped

        # Each group should be a list
        for auth_type, items in grouped.items():
            assert isinstance(items, list)

    def test_is_integration_configured(self):
        """Test configuration checking."""
        from assistant.services.integration_schema import is_integration_configured

        # Schema with no auth should always be configured
        no_auth_schema = {
            "name": "Test",
            "icon": "test",
            "color": "#000",
            "auth_type": "none",
            "config_key": None,
        }
        assert is_integration_configured(no_auth_schema) is True

    def test_reload_schemas(self):
        """Test that schemas can be reloaded."""
        from assistant.services.integration_schema import reload_schemas, get_all_integration_schemas

        # First load
        schemas1 = get_all_integration_schemas()

        # Reload
        schemas2 = reload_schemas()

        # Should have same keys
        assert set(schemas1.keys()) == set(schemas2.keys())

    def test_msgraph_schema_loaded(self):
        """Test that msgraph INTEGRATION_SCHEMA is properly loaded."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        assert "msgraph" in schemas
        msgraph = schemas["msgraph"]

        assert msgraph["name"] == "Microsoft 365"
        assert msgraph["auth_type"] == "oauth"
        assert msgraph["icon"] == "cloud"
        assert msgraph["color"] == "#0078D4"

    def test_billomat_schema_loaded(self):
        """Test that billomat INTEGRATION_SCHEMA is properly loaded."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        assert "billomat" in schemas
        billomat = schemas["billomat"]

        assert billomat["name"] == "Billomat"
        assert billomat["auth_type"] == "api_key"
        assert len(billomat.get("fields", [])) >= 2  # billomat_id and api_key


class TestSetupHintsInSchema:
    """Tests for setup hints in INTEGRATION_SCHEMA (plan-047)."""

    def test_configurable_mcps_have_setup(self):
        """Test that loaded MCPs with auth_type != 'none' have a setup field.

        Note: Not all MCPs can be loaded in the test environment (missing
        compiled dependencies), so we only test what was successfully loaded.
        """
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        # Only check MCPs that were successfully loaded
        # Plugin MCPs (like janitza:janitza) may not have setup yet
        for mcp_name, schema in schemas.items():
            auth_type = schema.get("auth_type", "none")
            if auth_type != "none" and ":" not in mcp_name:
                setup = schema.get("setup")
                assert setup is not None, (
                    f"MCP '{mcp_name}' has auth_type='{auth_type}' but no 'setup' field"
                )

    def test_setup_field_structure(self):
        """Test that setup fields have the required keys."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        for mcp_name, schema in schemas.items():
            setup = schema.get("setup")
            if setup is None:
                continue

            assert "description" in setup, f"setup for {mcp_name} missing 'description'"
            assert "requirement" in setup, f"setup for {mcp_name} missing 'requirement'"
            assert "setup_steps" in setup, f"setup for {mcp_name} missing 'setup_steps'"
            assert isinstance(setup["setup_steps"], list), (
                f"setup_steps for {mcp_name} should be a list"
            )

    def test_billomat_setup_data(self):
        """Test billomat setup data matches former MCP_HINTS."""
        from assistant.services.integration_schema import get_schema_for_mcp

        schema = get_schema_for_mcp("billomat")
        if schema is None:
            pytest.skip("billomat schema not loadable in test environment")
        setup = schema.get("setup")
        assert setup is not None
        assert setup["description"] == "Rechnungen und Angebote"
        assert setup["requirement"] == "Billomat API Key"
        assert len(setup["setup_steps"]) == 2

    def test_outlook_setup_has_alternative(self):
        """Test outlook setup has alternative field."""
        from assistant.services.integration_schema import get_schema_for_mcp

        schema = get_schema_for_mcp("outlook")
        if schema is None:
            pytest.skip("outlook schema not loadable in test environment")
        setup = schema.get("setup")
        assert setup is not None
        assert "alternative" in setup
        assert "msgraph" in setup["alternative"]

    def test_no_config_mcps_have_no_setup(self):
        """Test that MCPs with auth_type='none' and no setup return None."""
        from assistant.services.integration_schema import get_schema_for_mcp

        # clipboard should not need setup
        schema = get_schema_for_mcp("clipboard")
        if schema:
            assert schema.get("auth_type") == "none"
            # clipboard may or may not have a setup field, but shouldn't need config
            assert schema.get("setup") is None or schema.get("auth_type") == "none"

    def test_get_mcp_hint_wrapper_consistency(self):
        """Test that the wrapper returns data consistent with schema."""
        from assistant.services.mcp_hints import get_mcp_hint
        from assistant.services.integration_schema import get_schema_for_mcp

        schema = get_schema_for_mcp("billomat")
        if schema is None:
            pytest.skip("billomat schema not loadable in test environment")
        hint = get_mcp_hint("billomat")

        assert hint is not None
        assert hint["name"] == schema["name"]
        assert hint["description"] == schema["setup"]["description"]
        assert hint["requirement"] == schema["setup"]["requirement"]
        assert hint["setup_steps"] == schema["setup"]["setup_steps"]


class TestIntegrationSchemaCompatibility:
    """Tests for backward compatibility with AUTH_CONFIG."""

    def test_gmail_auth_config_to_schema(self):
        """Test that Gmail AUTH_CONFIG is converted to schema format."""
        from assistant.services.integration_schema import get_all_integration_schemas

        schemas = get_all_integration_schemas()

        assert "gmail" in schemas
        gmail = schemas["gmail"]

        # Should have been converted from AUTH_CONFIG
        assert gmail["auth_type"] == "oauth"
        assert "Gmail" in gmail["name"]

    def test_oauth_providers_match_schemas(self):
        """Test that OAuth providers in oauth.py match integration schemas."""
        from assistant.services.integration_schema import get_all_integration_schemas
        from assistant.routes.oauth import _get_all_oauth_providers

        schemas = get_all_integration_schemas()
        oauth_providers = dict(_get_all_oauth_providers())

        # All OAuth providers should have corresponding schemas
        for provider_name in oauth_providers.keys():
            assert provider_name in schemas, f"OAuth provider {provider_name} not in schemas"
            assert schemas[provider_name]["auth_type"] == "oauth"
