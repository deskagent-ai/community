# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for paths and config modules.
Tests centralized path logic with parent-folder search.
"""

import json
import sys
from pathlib import Path

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestDeepMerge:
    """Tests for deep_merge function."""

    def test_simple_merge(self):
        """Test merging simple dictionaries."""
        from config import deep_merge

        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = deep_merge(base, override)

        assert result["a"] == 1
        assert result["b"] == 3  # overridden
        assert result["c"] == 4  # added

    def test_nested_merge(self):
        """Test merging nested dictionaries."""
        from config import deep_merge

        base = {"outer": {"inner1": 1, "inner2": 2}}
        override = {"outer": {"inner2": 99, "inner3": 3}}

        result = deep_merge(base, override)

        assert result["outer"]["inner1"] == 1  # preserved
        assert result["outer"]["inner2"] == 99  # overridden
        assert result["outer"]["inner3"] == 3  # added

    def test_override_non_dict_with_dict(self):
        """Test that dict overrides non-dict value."""
        from config import deep_merge

        base = {"key": "string_value"}
        override = {"key": {"nested": "value"}}

        result = deep_merge(base, override)

        assert result["key"] == {"nested": "value"}

    def test_override_dict_with_non_dict(self):
        """Test that non-dict overrides dict value."""
        from config import deep_merge

        base = {"key": {"nested": "value"}}
        override = {"key": "simple_string"}

        result = deep_merge(base, override)

        assert result["key"] == "simple_string"

    def test_empty_override(self):
        """Test merging with empty override."""
        from config import deep_merge

        base = {"a": 1, "b": {"c": 2}}
        override = {}

        result = deep_merge(base, override)

        assert result == {"a": 1, "b": {"c": 2}}

    def test_empty_base(self):
        """Test merging with empty base."""
        from config import deep_merge

        base = {}
        override = {"a": 1}

        result = deep_merge(base, override)

        assert result == {"a": 1}


class TestPathConstants:
    """Tests for path constants."""

    def test_deskagent_dir_exists(self):
        """Test that DESKAGENT_DIR is correctly set."""
        from paths import DESKAGENT_DIR

        assert DESKAGENT_DIR.exists()
        assert DESKAGENT_DIR.name == "deskagent"

    def test_project_dir_is_parent_of_deskagent(self):
        """Test that PROJECT_DIR is parent of DESKAGENT_DIR."""
        from paths import PROJECT_DIR, DESKAGENT_DIR

        assert PROJECT_DIR == DESKAGENT_DIR.parent


class TestGetDirFunctions:
    """Tests for get_*_dir functions with parent-folder search."""

    def test_get_mcp_dir_always_deskagent(self):
        """Test that MCP dir is always in deskagent."""
        from paths import get_mcp_dir, DESKAGENT_DIR

        mcp_dir = get_mcp_dir()

        assert mcp_dir == DESKAGENT_DIR / "mcp"

    def test_get_logs_dir_creates_if_missing(self, tmp_path, monkeypatch):
        """Test that logs dir is created if missing."""
        from paths import get_logs_dir
        import paths

        monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)

        logs_dir = get_logs_dir()

        assert logs_dir.exists()
        assert logs_dir.name == ".logs"

    def test_get_data_dir_creates_if_missing(self, tmp_path, monkeypatch):
        """Test that data dir is created if missing."""
        from paths import get_data_dir
        import paths

        monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path)

        data_dir = get_data_dir()

        assert data_dir.exists()
        assert data_dir.name == ".state"

    def test_get_config_dir_creates_if_missing(self, tmp_path, monkeypatch):
        """Test that config dir is created if missing."""
        from paths import get_config_dir
        import paths

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)

        config_dir = get_config_dir()

        assert config_dir.exists()
        assert config_dir.name == "config"


class TestParentFolderSearch:
    """Tests for parent-folder search logic."""

    def test_agents_dir_prefers_user_space(self, tmp_path, monkeypatch):
        """Test that user agents dir is preferred over deskagent."""
        import paths

        # Setup: Create user agents with files
        user_agents = tmp_path / "agents"
        user_agents.mkdir()
        (user_agents / "my_agent.md").write_text("# Agent content", encoding="utf-8")

        # Create deskagent structure
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()
        deskagent_agents = deskagent / "agents"
        deskagent_agents.mkdir()
        (deskagent_agents / "default.md").write_text("# Default", encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)

        result = paths.get_agents_dir()

        assert result == user_agents

    def test_agents_dir_fallback_to_deskagent(self, tmp_path, monkeypatch):
        """Test fallback to deskagent when no user agents."""
        import paths

        # Create deskagent structure only
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()
        deskagent_agents = deskagent / "agents"
        deskagent_agents.mkdir()
        (deskagent_agents / "default.md").write_text("# Default", encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)

        result = paths.get_agents_dir()

        assert result == deskagent_agents

    def test_skills_dir_prefers_user_space(self, tmp_path, monkeypatch):
        """Test that user skills dir is preferred over deskagent."""
        import paths

        # Setup: Create user skills with files
        user_skills = tmp_path / "skills"
        user_skills.mkdir()
        (user_skills / "my_skill.md").write_text("name: My Skill", encoding="utf-8")

        # Create deskagent structure
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()
        deskagent_skills = deskagent / "skills"
        deskagent_skills.mkdir()

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)

        result = paths.get_skills_dir()

        assert result == user_skills

    def test_knowledge_dir_prefers_user_space(self, tmp_path, monkeypatch):
        """Test that user knowledge dir is preferred over deskagent."""
        import paths

        # Setup: Create user knowledge with files
        user_knowledge = tmp_path / "knowledge"
        user_knowledge.mkdir()
        (user_knowledge / "company.md").write_text("# Company Info", encoding="utf-8")

        # Create deskagent structure
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()
        deskagent_knowledge = deskagent / "knowledge"
        deskagent_knowledge.mkdir()

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)

        result = paths.get_knowledge_dir()

        assert result == user_knowledge


class TestLoadConfig:
    """Tests for config loading with deep merge."""

    def test_load_user_config_only(self, tmp_path, monkeypatch):
        """Test loading only user config when no default exists."""
        import paths
        import config

        # Create config directory and user config
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        user_config = {"name": "My Assistant", "port": 8080}
        (config_dir / "config.json").write_text(
            json.dumps(user_config), encoding="utf-8"
        )

        # Create deskagent dir without default config
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result["name"] == "My Assistant"
        assert result["port"] == 8080

    def test_load_default_config_only(self, tmp_path, monkeypatch):
        """Test loading only default config when no user config exists."""
        import paths
        import config

        # Create deskagent with config dir containing system.json (new structure)
        deskagent = tmp_path / "deskagent"
        config_dir = deskagent / "config"
        config_dir.mkdir(parents=True)
        default_config = {"name": "Default", "timeout": 120}
        (config_dir / "system.json").write_text(
            json.dumps(default_config), encoding="utf-8"
        )

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result["name"] == "Default"
        assert result["timeout"] == 120

    def test_deep_merge_configs(self, tmp_path, monkeypatch):
        """Test that user config is deep-merged over default."""
        import paths
        import config

        # Create deskagent with config dir containing system.json (product defaults)
        deskagent = tmp_path / "deskagent"
        product_config = deskagent / "config"
        product_config.mkdir(parents=True)
        default_config = {
            "name": "Default",
            "timeout": 120,
            "ui": {"theme": "dark", "port": 8765}
        }
        (product_config / "system.json").write_text(
            json.dumps(default_config), encoding="utf-8"
        )

        # Create user config that overrides some values (user config dir)
        user_config_dir = tmp_path / "config"
        user_config_dir.mkdir()
        user_config = {
            "name": "My Assistant",
            "ui": {"theme": "light"}  # Override theme, keep port
        }
        (user_config_dir / "system.json").write_text(
            json.dumps(user_config), encoding="utf-8"
        )

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result["name"] == "My Assistant"  # overridden
        assert result["timeout"] == 120  # from default
        assert result["ui"]["theme"] == "light"  # overridden
        assert result["ui"]["port"] == 8765  # from default

    def test_fallback_to_root_config(self, tmp_path, monkeypatch):
        """Test fallback to config.json in project root."""
        import paths
        import config

        # Create config.json in root (legacy location)
        root_config = {"name": "Root Config", "legacy": True}
        (tmp_path / "config.json").write_text(
            json.dumps(root_config), encoding="utf-8"
        )

        # Create deskagent dir without default config
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result["name"] == "Root Config"
        assert result["legacy"] is True

    def test_empty_config_when_nothing_exists(self, tmp_path, monkeypatch):
        """Test that empty dict is returned when no configs exist."""
        import paths
        import config

        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result == {}


class TestMultiFileConfig:
    """Tests for new multi-file config structure."""

    def test_load_split_configs(self, tmp_path, monkeypatch):
        """Test loading config from multiple JSON files."""
        import paths
        import config

        # Create deskagent with default configs
        deskagent = tmp_path / "deskagent"
        deskagent_config = deskagent / "config"
        deskagent_config.mkdir(parents=True)

        # Default system.json
        (deskagent_config / "system.json").write_text(json.dumps({
            "name": "Default",
            "server_port": 8765,
            "ui": {"theme": "dark"}
        }), encoding="utf-8")

        # Default backends.json
        (deskagent_config / "backends.json").write_text(json.dumps({
            "default_ai": "claude_sdk",
            "ai_backends": {
                "gemini": {"type": "gemini_adk", "model": "gemini-2.5-pro"}
            }
        }), encoding="utf-8")

        # Default apis.json (empty)
        (deskagent_config / "apis.json").write_text(json.dumps({
            "billomat": {"id": "", "api_key": ""}
        }), encoding="utf-8")

        # Default agents.json
        (deskagent_config / "agents.json").write_text(json.dumps({
            "skills": {"translate": {"enabled": True}},
            "agents": {"demo": {"enabled": True}}
        }), encoding="utf-8")

        # Create user config directory with overrides
        user_config = tmp_path / "config"
        user_config.mkdir()

        # User system.json override
        (user_config / "system.json").write_text(json.dumps({
            "name": "My Assistant",
            "context": "My Company"
        }), encoding="utf-8")

        # User apis.json with real keys
        (user_config / "apis.json").write_text(json.dumps({
            "billomat": {"id": "mycompany", "api_key": "secret123"},
            "ai_backends": {"gemini": {"api_key": "gemini-key-123"}}
        }), encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        # Check merged values
        assert result["name"] == "My Assistant"  # User override
        assert result["context"] == "My Company"  # User addition
        assert result["server_port"] == 8765  # Default
        assert result["ui"]["theme"] == "dark"  # Default
        assert result["default_ai"] == "claude_sdk"  # From backends
        assert result["billomat"]["id"] == "mycompany"  # User override
        assert result["billomat"]["api_key"] == "secret123"  # User override

    def test_api_keys_merged_into_backends(self, tmp_path, monkeypatch):
        """Test that API keys in user backends.json merge into backend definitions."""
        import paths
        import config

        # Create deskagent with default configs
        deskagent = tmp_path / "deskagent"
        deskagent_config = deskagent / "config"
        deskagent_config.mkdir(parents=True)

        # Product backends.json with backend definitions (no api_key)
        (deskagent_config / "backends.json").write_text(json.dumps({
            "ai_backends": {
                "gemini": {"type": "gemini_adk", "model": "gemini-2.5-pro"},
                "claude_api": {"type": "claude_api", "model": "claude-sonnet"}
            }
        }), encoding="utf-8")

        # Empty defaults for other files
        (deskagent_config / "system.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "apis.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "agents.json").write_text("{}", encoding="utf-8")

        # User config with API keys in backends.json (where they belong)
        user_config = tmp_path / "config"
        user_config.mkdir()

        (user_config / "backends.json").write_text(json.dumps({
            "ai_backends": {
                "gemini": {"api_key": "gemini-secret"},
                "claude_api": {"api_key": "claude-secret"}
            }
        }), encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        # API keys should be merged into backend definitions via deep_merge
        assert result["ai_backends"]["gemini"]["type"] == "gemini_adk"
        assert result["ai_backends"]["gemini"]["api_key"] == "gemini-secret"
        assert result["ai_backends"]["claude_api"]["type"] == "claude_api"
        assert result["ai_backends"]["claude_api"]["api_key"] == "claude-secret"

    def test_skills_and_agents_merged(self, tmp_path, monkeypatch):
        """Test that skills and agents from user override demo defaults."""
        import paths
        import config

        # Create deskagent with demo agents
        deskagent = tmp_path / "deskagent"
        deskagent_config = deskagent / "config"
        deskagent_config.mkdir(parents=True)

        (deskagent_config / "system.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "backends.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "apis.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "agents.json").write_text(json.dumps({
            "skills": {"translate": {"ai": "claude", "enabled": True}},
            "agents": {"demo_email": {"ai": "claude_sdk", "enabled": True}}
        }), encoding="utf-8")

        # User adds custom agents
        user_config = tmp_path / "config"
        user_config.mkdir()

        (user_config / "agents.json").write_text(json.dumps({
            "skills": {"custom_skill": {"ai": "gemini", "enabled": True}},
            "agents": {"my_agent": {"ai": "claude_sdk", "enabled": True}}
        }), encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        # Both demo and user skills/agents should exist
        assert "translate" in result["skills"]  # Demo
        assert "custom_skill" in result["skills"]  # User
        assert "demo_email" in result["agents"]  # Demo
        assert "my_agent" in result["agents"]  # User

    def test_legacy_fallback_when_no_split_configs(self, tmp_path, monkeypatch):
        """Test that legacy config.json is used when split configs don't exist."""
        import paths
        import config

        # Create deskagent with default config (old style)
        deskagent = tmp_path / "deskagent"
        deskagent.mkdir()
        (deskagent / "config.default.json").write_text(json.dumps({
            "name": "Legacy Default"
        }), encoding="utf-8")

        # Create legacy config.json in root
        (tmp_path / "config.json").write_text(json.dumps({
            "name": "Legacy User",
            "billomat": {"id": "legacy"}
        }), encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result["name"] == "Legacy User"
        assert result["billomat"]["id"] == "legacy"

    def test_new_structure_takes_precedence(self, tmp_path, monkeypatch):
        """Test that new split config takes precedence over legacy."""
        import paths
        import config

        # Create deskagent with split config
        deskagent = tmp_path / "deskagent"
        deskagent_config = deskagent / "config"
        deskagent_config.mkdir(parents=True)

        (deskagent_config / "system.json").write_text(json.dumps({
            "name": "New Structure"
        }), encoding="utf-8")
        (deskagent_config / "backends.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "apis.json").write_text("{}", encoding="utf-8")
        (deskagent_config / "agents.json").write_text("{}", encoding="utf-8")

        # Also create user config with new structure
        user_config = tmp_path / "config"
        user_config.mkdir()
        (user_config / "system.json").write_text(json.dumps({
            "name": "User New Structure"
        }), encoding="utf-8")

        # And legacy config.json (should be ignored)
        (tmp_path / "config.json").write_text(json.dumps({
            "name": "Should Be Ignored"
        }), encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)

        result = config.load_config()

        assert result["name"] == "User New Structure"  # Not "Should Be Ignored"


class TestContentModeOverrides:
    """Tests for content_mode='both' with overrides_standard flag."""

    def test_overrides_standard_flag_agents(self, tmp_path, monkeypatch):
        """Test that overrides_standard is True when user agent overrides standard."""
        import paths
        import config

        # Create deskagent with standard agents
        deskagent = tmp_path / "deskagent"
        standard_agents = deskagent / "agents"
        standard_agents.mkdir(parents=True)
        (standard_agents / "reply_email.md").write_text("Standard reply agent", encoding="utf-8")
        (standard_agents / "standard_only.md").write_text("Standard only agent", encoding="utf-8")

        # Create user agents (one override, one unique)
        user_agents = tmp_path / "agents"
        user_agents.mkdir()
        (user_agents / "reply_email.md").write_text("User reply agent", encoding="utf-8")
        (user_agents / "custom_agent.md").write_text("Custom agent", encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "_runtime_content_mode", "both")

        result = config.get_all_agents_with_source()
        agents_by_name = {a["name"]: a for a in result}

        # reply_email: User version, overrides standard
        assert agents_by_name["reply_email"]["source"] == "user"
        assert agents_by_name["reply_email"]["overrides_standard"] is True

        # custom_agent: User only, no standard to override
        assert agents_by_name["custom_agent"]["source"] == "user"
        assert agents_by_name["custom_agent"]["overrides_standard"] is False

        # standard_only: Standard version (user has no override)
        assert agents_by_name["standard_only"]["source"] == "standard"
        assert agents_by_name["standard_only"]["overrides_standard"] is False

        # Cleanup
        monkeypatch.setattr(config, "_runtime_content_mode", None)

    def test_overrides_standard_flag_skills(self, tmp_path, monkeypatch):
        """Test that overrides_standard works for skills too."""
        import paths
        import config

        # Create deskagent with standard skills
        deskagent = tmp_path / "deskagent"
        standard_skills = deskagent / "skills"
        standard_skills.mkdir(parents=True)
        (standard_skills / "translate.md").write_text("Standard translate", encoding="utf-8")

        # Create user skill with same name
        user_skills = tmp_path / "skills"
        user_skills.mkdir()
        (user_skills / "translate.md").write_text("User translate", encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "_runtime_content_mode", "both")

        result = config.get_all_skills_with_source()
        skills_by_name = {s["name"]: s for s in result}

        assert skills_by_name["translate"]["source"] == "user"
        assert skills_by_name["translate"]["overrides_standard"] is True

        # Cleanup
        monkeypatch.setattr(config, "_runtime_content_mode", None)

    def test_no_overrides_in_custom_mode(self, tmp_path, monkeypatch):
        """Test that overrides_standard is False when not in 'both' mode."""
        import paths
        import config
        from unittest.mock import patch

        # Create deskagent with standard agents
        deskagent = tmp_path / "deskagent"
        standard_agents = deskagent / "agents"
        standard_agents.mkdir(parents=True)
        (standard_agents / "reply_email.md").write_text("Standard reply agent", encoding="utf-8")

        # Create user agent with same name
        user_agents = tmp_path / "agents"
        user_agents.mkdir()
        (user_agents / "reply_email.md").write_text("User reply agent", encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(config, "DESKAGENT_DIR", deskagent)
        monkeypatch.setattr(config, "_runtime_content_mode", "custom")

        # Mock plugin agents to avoid loading real plugins from filesystem
        with patch("assistant.services.plugins.get_plugin_agents", return_value={}):
            result = config.get_all_agents_with_source()

        # In custom mode, only user agents are loaded, no standard comparison
        assert len(result) == 1
        assert result[0]["name"] == "reply_email"
        assert result[0]["source"] == "user"
        # overrides_standard is False because we're not in "both" mode
        assert result[0]["overrides_standard"] is False

        # Cleanup
        monkeypatch.setattr(config, "_runtime_content_mode", None)
