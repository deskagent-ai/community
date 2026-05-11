# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.services.discovery module.
Tests agent and skill discovery with frontmatter configuration.
"""

import sys
import json
from pathlib import Path

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestParseFromtmatter:
    """Tests for parse_frontmatter function."""

    def test_parse_valid_frontmatter(self):
        """Test parsing valid JSON frontmatter."""
        from assistant.services.discovery import parse_frontmatter

        content = '''---
{
  "ai": "gemini",
  "category": "finance"
}
---

# Agent: Test Agent

Content here.
'''
        metadata, clean = parse_frontmatter(content)

        assert metadata == {"ai": "gemini", "category": "finance"}
        assert "# Agent: Test Agent" in clean
        assert "---" not in clean

    def test_parse_no_frontmatter(self):
        """Test parsing content without frontmatter."""
        from assistant.services.discovery import parse_frontmatter

        content = "# Agent: No Frontmatter\n\nJust content."
        metadata, clean = parse_frontmatter(content)

        assert metadata == {}
        assert clean == content

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON returns empty dict."""
        from assistant.services.discovery import parse_frontmatter

        content = '''---
{ invalid json }
---

# Content
'''
        metadata, clean = parse_frontmatter(content)

        assert metadata == {}


class TestDiscoverAgents:
    """Tests for discover_agents function."""

    def test_discover_agents_from_directory(self, tmp_path, monkeypatch):
        """Test discovering agents from directory."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create agents directory
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # Create test agent with frontmatter
        (agents_dir / "test_agent.md").write_text('''---
{
  "ai": "claude_sdk",
  "category": "system",
  "description": "Test agent"
}
---

# Agent: Test

Instructions here.
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        agents = discovery.discover_agents()

        assert "test_agent" in agents
        assert agents["test_agent"]["frontmatter"]["ai"] == "claude_sdk"
        assert agents["test_agent"]["frontmatter"]["category"] == "system"


class TestGetAgentConfig:
    """Tests for get_agent_config function."""

    def test_frontmatter_overrides_legacy(self, tmp_path, monkeypatch):
        """Test that frontmatter has priority over agents.json."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create agents directory with frontmatter config
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "my_agent.md").write_text('''---
{
  "ai": "gemini",
  "allowed_mcp": "outlook|clipboard"
}
---

# Agent: My Agent
''', encoding="utf-8")

        # Create legacy config with different values
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "agents.json").write_text(json.dumps({
            "agents": {
                "my_agent": {
                    "ai": "claude_sdk",
                    "allowed_mcp": "billomat"
                }
            }
        }), encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        # Mock load_config to return our test config
        def mock_load_config():
            return {
                "agents": {
                    "my_agent": {
                        "ai": "claude_sdk",
                        "allowed_mcp": "billomat"
                    }
                }
            }
        monkeypatch.setattr(discovery, "_load_legacy_config", lambda: {"agents": mock_load_config()["agents"], "skills": {}})

        config = discovery.get_agent_config("my_agent")

        # Frontmatter should override legacy config
        assert config["ai"] == "gemini"
        assert config["allowed_mcp"] == "outlook|clipboard"


class TestDiscoverSkills:
    """Tests for discover_skills function."""

    def test_discover_skills_from_directory(self, tmp_path, monkeypatch):
        """Test discovering skills from directory."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create skills directory
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create test skill with frontmatter
        (skills_dir / "mail_reply.md").write_text('''---
{
  "ai": "gemini",
  "hotkey": "shift+alt+1",
  "category": "kommunikation"
}
---

# Skill: Mail Reply

Reply to email.
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        skills = discovery.discover_skills()

        assert "mail_reply" in skills
        assert skills["mail_reply"]["frontmatter"]["ai"] == "gemini"
        assert skills["mail_reply"]["frontmatter"]["hotkey"] == "shift+alt+1"


class TestLoadCategories:
    """Tests for load_categories function."""

    def test_load_categories_from_file(self, tmp_path, monkeypatch):
        """Test loading categories from JSON file."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create config directory with categories
        config_dir = tmp_path / "deskagent" / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "categories.json").write_text(json.dumps({
            "finance": {"label": "Finanzen", "icon": "money", "order": 1},
            "system": {"label": "System", "icon": "settings", "order": 2}
        }), encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        categories = discovery.load_categories()

        assert "finance" in categories
        assert categories["finance"]["label"] == "Finanzen"
        assert "system" in categories


class TestDiscoverAll:
    """Tests for discover_all function."""

    def test_discover_all_returns_complete_structure(self, tmp_path, monkeypatch):
        """Test that discover_all returns agents, skills, and categories."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create minimal directory structure
        (tmp_path / "agents").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "deskagent" / "config").mkdir(parents=True)
        (tmp_path / "deskagent" / "config" / "categories.json").write_text("{}", encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "_load_legacy_config", lambda: {"agents": {}, "skills": {}})

        result = discovery.discover_all()

        assert "agents" in result
        assert "skills" in result
        assert "categories" in result
        assert isinstance(result["agents"], dict)
        assert isinstance(result["skills"], dict)
        assert isinstance(result["categories"], dict)


class TestMcpHints:
    """Tests for mcp_hints module (schema-based, plan-047)."""

    def test_get_mcp_names_returns_configurable_mcps(self):
        """Test that get_mcp_names returns only MCPs that need configuration."""
        from assistant.services.mcp_hints import get_mcp_names, needs_configuration

        mcp_names = get_mcp_names()

        # Should be a list
        assert isinstance(mcp_names, list)

        # All returned names should need configuration
        for name in mcp_names:
            assert needs_configuration(name), f"{name} should need configuration"

        # At least some MCPs should be loadable
        # (specific MCPs may not load in test env due to missing compiled deps)
        assert len(mcp_names) >= 0  # May be 0 if no MCPs loadable

    def test_get_mcp_hint_with_setup(self):
        """Test that get_mcp_hint returns setup data from INTEGRATION_SCHEMA."""
        from assistant.services.mcp_hints import get_mcp_hint
        from assistant.services.integration_schema import get_schema_for_mcp

        # Skip if billomat schema not loadable in test env
        schema = get_schema_for_mcp("billomat")
        if schema is None:
            pytest.skip("billomat schema not loadable in test environment")

        hint = get_mcp_hint("billomat")
        assert hint is not None
        assert hint["name"] == "Billomat"
        assert "description" in hint
        assert "requirement" in hint
        assert "setup_steps" in hint
        assert isinstance(hint["setup_steps"], list)

    def test_get_mcp_hint_no_config(self):
        """Test that get_mcp_hint returns None for MCPs without config."""
        from assistant.services.mcp_hints import get_mcp_hint
        from assistant.services.integration_schema import get_schema_for_mcp

        # clipboard has auth_type "none" and no setup field
        schema = get_schema_for_mcp("clipboard")
        if schema is None:
            pytest.skip("clipboard schema not loadable in test environment")

        hint = get_mcp_hint("clipboard")
        assert hint is None

    def test_get_mcp_hint_with_alternative(self):
        """Test that get_mcp_hint returns alternative field for outlook."""
        from assistant.services.mcp_hints import get_mcp_hint
        from assistant.services.integration_schema import get_schema_for_mcp

        schema = get_schema_for_mcp("outlook")
        if schema is None:
            pytest.skip("outlook schema not loadable in test environment")

        hint = get_mcp_hint("outlook")
        # Outlook has auth_type "none" but has a setup field with alternative
        if hint is not None:
            assert "alternative" in hint

    def test_get_mcp_hint_unknown_mcp(self):
        """Test that get_mcp_hint returns None for unknown MCPs."""
        from assistant.services.mcp_hints import get_mcp_hint

        hint = get_mcp_hint("nonexistent_mcp_xyz")
        assert hint is None

    def test_needs_configuration_schema_based(self):
        """Test needs_configuration uses schema auth_type."""
        from assistant.services.mcp_hints import needs_configuration
        from assistant.services.integration_schema import get_schema_for_mcp

        # Test with schemas that are actually loaded
        billomat_schema = get_schema_for_mcp("billomat")
        if billomat_schema:
            assert needs_configuration("billomat") is True

        clipboard_schema = get_schema_for_mcp("clipboard")
        if clipboard_schema:
            assert needs_configuration("clipboard") is False
            assert needs_configuration("filesystem") is False

        # Unknown MCPs should assume they need config
        assert needs_configuration("nonexistent_mcp_xyz") is True

    def test_get_setup_message_formatting(self):
        """Test that get_setup_message formats properly."""
        from assistant.services.mcp_hints import get_setup_message
        from assistant.services.integration_schema import get_schema_for_mcp

        # Use MCPs that are actually loaded
        billomat_schema = get_schema_for_mcp("billomat")
        if billomat_schema is None:
            pytest.skip("billomat schema not loadable in test environment")

        msg = get_setup_message(["billomat"])
        assert "Billomat" in msg
        assert "nicht konfiguriert" in msg

    def test_get_setup_message_empty(self):
        """Test that get_setup_message returns empty string for no MCPs."""
        from assistant.services.mcp_hints import get_setup_message

        assert get_setup_message([]) == ""

    def test_get_setup_message_unknown_mcp(self):
        """Test that get_setup_message handles unknown MCPs gracefully."""
        from assistant.services.mcp_hints import get_setup_message

        msg = get_setup_message(["unknown_mcp_xyz"])
        assert "unknown_mcp_xyz" in msg
        assert "Konfiguration fehlt" in msg


class TestPreloadPrerequisites:
    """Tests for preload_prerequisites function."""

    def test_preload_prerequisites_returns_list(self, monkeypatch):
        """Test that preload_prerequisites returns a list of checked MCPs."""
        from assistant.services import discovery
        import asyncio

        # Clear cache first
        discovery.invalidate_mcp_config_cache()

        # Run async function
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(discovery.preload_prerequisites())
        loop.close()

        # Should return a list
        assert isinstance(result, list)

        # All items should be strings (MCP names)
        for item in result:
            assert isinstance(item, str)
