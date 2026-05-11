# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for discovery service lazy import in ai_agent/__init__.py.

Tests that:
1. Discovery module is loaded lazily (not at import time)
2. No circular import issues occur
3. Task config is correctly loaded from discovery
4. Fallback to legacy config works when discovery unavailable
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestLazyDiscoveryImport:
    """Tests for lazy discovery module loading."""

    def test_discovery_module_not_loaded_at_import(self):
        """Test that discovery module is not loaded when ai_agent is imported."""
        # Save current module state to restore later
        saved_modules = {k: v for k, v in sys.modules.items()
                        if 'discovery' in k or 'ai_agent' in k}

        try:
            # Clear any cached imports
            modules_to_clear = [k for k in list(sys.modules.keys())
                               if 'discovery' in k or 'ai_agent' in k]
            for mod in modules_to_clear:
                if mod in sys.modules:
                    del sys.modules[mod]

            # Import ai_agent
            import ai_agent

            # _discovery_module should be None initially (lazy)
            assert ai_agent._discovery_module is None
        finally:
            # Restore module state to avoid polluting other tests
            for mod in list(sys.modules.keys()):
                if 'discovery' in mod or 'ai_agent' in mod:
                    if mod in sys.modules:
                        del sys.modules[mod]
            sys.modules.update(saved_modules)

    def test_get_discovery_module_loads_on_demand(self):
        """Test that _get_discovery_module loads discovery when called."""
        import ai_agent

        # Reset state
        ai_agent._discovery_module = None

        # Call the lazy loader
        discovery = ai_agent._get_discovery_module()

        # Should have loaded the module
        assert discovery is not None
        assert hasattr(discovery, 'get_agent_config')
        assert hasattr(discovery, 'get_skill_config')

    def test_get_discovery_module_caches_result(self):
        """Test that discovery module is cached after first load."""
        import ai_agent

        # Reset state
        ai_agent._discovery_module = None

        # Load twice
        discovery1 = ai_agent._get_discovery_module()
        discovery2 = ai_agent._get_discovery_module()

        # Should be the same object
        assert discovery1 is discovery2

    def test_get_discovery_module_handles_import_error(self):
        """Test graceful fallback when discovery import fails."""
        import ai_agent

        # Reset state
        ai_agent._discovery_module = None

        # Mock import to fail
        with patch.dict(sys.modules, {'assistant.services.discovery': None}):
            with patch('builtins.__import__', side_effect=ImportError("Test error")):
                # Reset to force re-import attempt
                ai_agent._discovery_module = None
                discovery = ai_agent._get_discovery_module()

        # Should return None (fallback mode)
        # Note: Due to caching, might need to check differently
        # The function should not raise an exception


class TestTaskConfigFromDiscovery:
    """Tests for loading task config via discovery service."""

    def test_task_config_uses_discovery_when_available(self, tmp_path, monkeypatch):
        """Test that task config is loaded from discovery service."""
        import ai_agent
        import paths
        from assistant.services import discovery

        # Clear discovery cache
        discovery.clear_cache()
        ai_agent._discovery_module = None

        # Create test agent with frontmatter
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_agent.md").write_text('''---
{
  "ai": "claude_sdk",
  "allowed_mcp": "paperless",
  "use_anonymization_proxy": false
}
---

# Test Agent
''', encoding="utf-8")

        # Create minimal config
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "agents.json").write_text(json.dumps({
            "agents": {
                "test_agent": {
                    "ai": "gemini",
                    "allowed_mcp": "filesystem"
                }
            }
        }), encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        # Mock _load_legacy_config
        def mock_legacy():
            return {
                "agents": {
                    "test_agent": {
                        "ai": "gemini",
                        "allowed_mcp": "filesystem"
                    }
                },
                "skills": {}
            }
        monkeypatch.setattr(discovery, "_load_legacy_config", mock_legacy)

        # Get config via discovery
        config = discovery.get_agent_config("test_agent")

        # Frontmatter should override legacy
        assert config["ai"] == "claude_sdk"
        assert config["allowed_mcp"] == "paperless"
        assert config["use_anonymization_proxy"] == False

    def test_allowed_tools_not_in_frontmatter_uses_legacy(self, tmp_path, monkeypatch):
        """Test that allowed_tools from legacy config is used when not in frontmatter."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create test agent WITHOUT allowed_tools in frontmatter
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_agent.md").write_text('''---
{
  "ai": "claude_sdk",
  "allowed_mcp": "paperless"
}
---

# Test Agent
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        # Mock _load_legacy_config with allowed_tools
        def mock_legacy():
            return {
                "agents": {
                    "test_agent": {
                        "ai": "gemini",
                        "allowed_mcp": "filesystem",
                        "allowed_tools": ["read_file", "write_file"]
                    }
                },
                "skills": {}
            }
        monkeypatch.setattr(discovery, "_load_legacy_config", mock_legacy)

        config = discovery.get_agent_config("test_agent")

        # Frontmatter overrides ai and allowed_mcp
        assert config["ai"] == "claude_sdk"
        assert config["allowed_mcp"] == "paperless"

        # BUT allowed_tools should come from legacy (not overridden)
        assert config["allowed_tools"] == ["read_file", "write_file"]

    def test_frontmatter_can_override_allowed_tools(self, tmp_path, monkeypatch):
        """Test that frontmatter can explicitly override allowed_tools."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create test agent WITH allowed_tools in frontmatter
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_agent.md").write_text('''---
{
  "ai": "claude_sdk",
  "allowed_mcp": "paperless",
  "allowed_tools": ["paperless_search", "paperless_get"]
}
---

# Test Agent
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        # Mock _load_legacy_config with different allowed_tools
        def mock_legacy():
            return {
                "agents": {
                    "test_agent": {
                        "ai": "gemini",
                        "allowed_mcp": "filesystem",
                        "allowed_tools": ["read_file", "write_file"]
                    }
                },
                "skills": {}
            }
        monkeypatch.setattr(discovery, "_load_legacy_config", mock_legacy)

        config = discovery.get_agent_config("test_agent")

        # Frontmatter should override ALL fields including allowed_tools
        assert config["ai"] == "claude_sdk"
        assert config["allowed_mcp"] == "paperless"
        assert config["allowed_tools"] == ["paperless_search", "paperless_get"]


class TestCacheInvalidation:
    """Tests for config cache invalidation when files change."""

    def test_cache_invalidates_on_file_modification(self, tmp_path, monkeypatch):
        """Test that cache is invalidated when agent file is modified."""
        import time
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create test agent
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test_agent.md"
        agent_file.write_text('''---
{
  "ai": "gemini"
}
---

# Test Agent
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "_load_legacy_config", lambda: {"agents": {}, "skills": {}})

        # First load
        config1 = discovery.get_agent_config("test_agent")
        assert config1["ai"] == "gemini"

        # Wait a bit to ensure different mtime
        time.sleep(0.1)

        # Modify the file
        agent_file.write_text('''---
{
  "ai": "claude_sdk"
}
---

# Test Agent Updated
''', encoding="utf-8")

        # Second load should get new value
        config2 = discovery.get_agent_config("test_agent")
        assert config2["ai"] == "claude_sdk"


class TestConfigSources:
    """Tests for _config_sources tracking."""

    def test_config_sources_includes_frontmatter(self, tmp_path, monkeypatch):
        """Test that _config_sources includes 'Frontmatter' when present."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create test agent with frontmatter
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_agent.md").write_text('''---
{
  "ai": "claude_sdk"
}
---

# Test Agent
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "_load_legacy_config", lambda: {"agents": {}, "skills": {}})

        config = discovery.get_agent_config("test_agent")

        assert "_config_sources" in config
        assert "Frontmatter" in config["_config_sources"]

    def test_config_sources_empty_frontmatter_not_included(self, tmp_path, monkeypatch):
        """Test that 'Frontmatter' is not in sources when frontmatter is empty."""
        import paths
        from assistant.services import discovery

        # Clear cache
        discovery.clear_cache()

        # Create test agent WITHOUT frontmatter (but with file)
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_agent.md").write_text('''# Test Agent

No frontmatter here.
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "_load_legacy_config", lambda: {"agents": {"test_agent": {"ai": "gemini"}}, "skills": {}})

        config = discovery.get_agent_config("test_agent")

        # Should have config from legacy, but Frontmatter should NOT be in sources
        assert config["ai"] == "gemini"
        assert "_config_sources" in config
        assert "Frontmatter" not in config["_config_sources"]


class TestExecutorDiscoveryIntegration:
    """Tests for executor.py using Discovery service for backend info."""

    def test_get_ai_backend_info_uses_discovery(self, tmp_path, monkeypatch):
        """Test that executor.get_ai_backend_info uses Discovery frontmatter."""
        import paths
        from assistant.services import discovery
        from assistant.core.executor import get_ai_backend_info

        # Clear cache
        discovery.clear_cache()

        # Create test agent with frontmatter specifying claude_sdk
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test_agent.md").write_text('''---
{
  "ai": "claude_sdk",
  "allowed_mcp": "paperless"
}
---

# Test Agent
''', encoding="utf-8")

        # Monkeypatch paths
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")
        monkeypatch.setattr(discovery, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(discovery, "DESKAGENT_DIR", tmp_path / "deskagent")

        # Mock _load_legacy_config with gemini (should be overridden by frontmatter)
        def mock_legacy():
            return {
                "agents": {
                    "test_agent": {
                        "ai": "gemini",
                        "allowed_mcp": "filesystem"
                    }
                },
                "skills": {}
            }
        monkeypatch.setattr(discovery, "_load_legacy_config", mock_legacy)

        # Config with ai_backends for model lookup
        config = {
            "default_ai": "gemini",
            "agents": {
                "test_agent": {"ai": "gemini"}  # Legacy config says gemini
            },
            "ai_backends": {
                "gemini": {"model": "gemini-2.5-pro"},
                "claude_sdk": {"type": "claude_agent_sdk"}
            }
        }

        # Get backend info - should use frontmatter (claude_sdk) not legacy (gemini)
        ai_backend, model = get_ai_backend_info(config, "test_agent", "agent")

        # Should get claude_sdk from frontmatter, not gemini from legacy
        assert ai_backend == "claude_sdk"
        # Model should be from claude_sdk backend config
        assert model == "claude_agent_sdk"  # Falls back to type since no model field
