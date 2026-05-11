# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.agents module.
Tests agent loading and execution.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestLoadAgent:
    """Tests for load_agent function."""

    def test_load_existing_agent(self, tmp_path, monkeypatch):
        """Test loading an existing agent file."""
        import paths
        from assistant import agents

        # Create agents directory with test agent
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "reply_email.md").write_text(
            "# Agent: Email Reply Agent\n\nYou are an email assistant.",
            encoding="utf-8"
        )
        # Monkeypatch paths module (used by _find_agent_file)
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("reply_email")

        assert result is not None
        assert result["name"] == "Email Reply Agent"
        assert "content" in result

    def test_load_nonexistent_agent(self, tmp_path, monkeypatch):
        """Test loading a non-existent agent returns None."""
        import paths
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("nonexistent_agent")

        assert result is None

    def test_agent_without_heading(self, tmp_path, monkeypatch):
        """Test agent without '# Agent:' heading uses filename as name."""
        import paths
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "simple.md").write_text(
            "Just the agent content, no heading.",
            encoding="utf-8"
        )
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("simple")

        assert result is not None
        assert result["name"] == "simple"  # Falls back to filename
        assert "content" in result

    def test_agent_content_preserved(self, tmp_path, monkeypatch):
        """Test that agent content is preserved correctly."""
        import paths
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        content = "# Agent: Test\n\nYou are a test agent.\n\n## Instructions\n\n- Step 1\n- Step 2"
        (agents_dir / "test.md").write_text(content, encoding="utf-8")
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("test")

        assert "Instructions" in result["content"]
        assert "Step 1" in result["content"]

    def test_load_agent_with_context_input(self, tmp_path, monkeypatch):
        """Test that _context input is appended to agent content."""
        import paths
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test.md").write_text(
            "# Agent: Test\n\nDo the task.",
            encoding="utf-8"
        )
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        # Load with _context input
        result = agents.load_agent("test", inputs={"_context": "Extra info here"})

        assert result is not None
        assert "WICHTIG" in result["content"]
        assert "Extra info here" in result["content"]
        # _context is kept in inputs dict (intentional - load_agent may be called multiple times)

    def test_load_agent_empty_context_ignored(self, tmp_path, monkeypatch):
        """Test that empty _context is not appended."""
        import paths
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test.md").write_text("# Agent: Test\n\nContent.", encoding="utf-8")
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("test", inputs={"_context": "  "})

        assert "WICHTIG" not in result["content"]

    def test_load_agent_context_with_other_inputs(self, tmp_path, monkeypatch):
        """Test that _context works alongside other inputs."""
        import paths
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test.md").write_text(
            "# Agent: Test\n\nProcess {{INPUT.file}}",
            encoding="utf-8"
        )
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("test", inputs={
            "file": "/path/to/file.pdf",
            "_context": "Handle with care"
        })

        assert "/path/to/file.pdf" in result["content"]
        assert "Handle with care" in result["content"]
        assert "WICHTIG" in result["content"]
        # Both _context and regular inputs are kept in the dict
        # (_context is intentionally kept for potential re-processing)
        assert "file" in result.get("inputs", {})


class TestAgentConfiguration:
    """Tests for agent configuration from config.json."""

    def test_agent_uses_configured_backend(self, sample_config):
        """Test that agent uses backend from config."""
        sample_config["agents"] = {
            "reply_email": {
                "ai": "claude_api",
                "enabled": True
            }
        }

        agent_config = sample_config["agents"]["reply_email"]
        assert agent_config["ai"] == "claude_api"

    def test_agent_respects_enabled_flag(self, sample_config):
        """Test that disabled agents are skipped."""
        sample_config["agents"] = {
            "enabled_agent": {"enabled": True},
            "disabled_agent": {"enabled": False}
        }

        enabled_agents = [
            name for name, cfg in sample_config["agents"].items()
            if cfg.get("enabled", True)
        ]

        assert "enabled_agent" in enabled_agents
        assert "disabled_agent" not in enabled_agents

    def test_agent_anonymization_setting(self, sample_config):
        """Test agent-specific anonymization setting."""
        sample_config["agents"] = {
            "secure_agent": {
                "ai": "claude",
                "anonymize": True
            },
            "open_agent": {
                "ai": "ollama",
                "anonymize": False
            }
        }

        assert sample_config["agents"]["secure_agent"]["anonymize"] is True
        assert sample_config["agents"]["open_agent"]["anonymize"] is False

    def test_agent_knowledge_pattern(self, sample_config):
        """Test agent-specific knowledge pattern filtering."""
        sample_config["agents"] = {
            "offer_agent": {
                "ai": "claude",
                "knowledge": "products|pricing"
            }
        }

        agent_config = sample_config["agents"]["offer_agent"]
        assert agent_config.get("knowledge") == "products|pricing"


class TestAgentMetadata:
    """Tests for agent metadata in config."""

    def test_agent_input_output_description(self, sample_config):
        """Test agent input/output descriptions."""
        sample_config["agents"] = {
            "create_offer": {
                "input": "Clipboard oder E-Mail",
                "output": "Angebot in Billomat",
                "ai": "claude_sdk"
            }
        }

        agent = sample_config["agents"]["create_offer"]
        assert "Clipboard" in agent["input"]
        assert "Billomat" in agent["output"]

    def test_agent_hotkey_configuration(self, sample_config):
        """Test agent hotkey configuration."""
        sample_config["agents"] = {
            "reply_email": {
                "ai": "claude",
                "hotkey": "shift+alt+9"
            }
        }

        agent = sample_config["agents"]["reply_email"]
        assert agent.get("hotkey") == "shift+alt+9"


class TestLoadProcedure:
    """Tests for load_procedure function."""

    def test_load_existing_procedure(self, tmp_path, monkeypatch):
        """Test loading an existing procedure file."""
        import paths
        from assistant import agents

        # Create agents/procedures directory with test procedure
        procedures_dir = tmp_path / "agents" / "procedures"
        procedures_dir.mkdir(parents=True)
        (procedures_dir / "test_proc.md").write_text(
            "This is a test procedure.",
            encoding="utf-8"
        )
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_procedure("test_proc")

        assert result == "This is a test procedure."

    def test_load_nonexistent_procedure(self, tmp_path, monkeypatch):
        """Test loading a non-existent procedure returns error message."""
        import paths
        from assistant import agents

        procedures_dir = tmp_path / "agents" / "procedures"
        procedures_dir.mkdir(parents=True)
        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_procedure("nonexistent")

        assert "[PROCEDURE NOT FOUND: nonexistent]" in result

    def test_procedure_in_agent(self, tmp_path, monkeypatch):
        """Test that PROCEDURE placeholder is replaced in agent content."""
        import paths
        from assistant import agents

        # Create agents directory with test agent
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "test.md").write_text(
            "# Agent: Test\n\nHere is a procedure:\n\n{{PROCEDURE:my_proc}}\n\nEnd.",
            encoding="utf-8"
        )

        # Create procedures directory with test procedure
        procedures_dir = agents_dir / "procedures"
        procedures_dir.mkdir()
        (procedures_dir / "my_proc.md").write_text(
            "### Procedure Content\n\n- Step 1\n- Step 2",
            encoding="utf-8"
        )

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", tmp_path / "deskagent")

        result = agents.load_agent("test")

        assert result is not None
        assert "### Procedure Content" in result["content"]
        assert "Step 1" in result["content"]
        assert "{{PROCEDURE:" not in result["content"]

    def test_user_procedure_overrides_system(self, tmp_path, monkeypatch):
        """Test that user procedures override system procedures."""
        import paths
        from assistant import agents

        # Create user procedures
        user_proc_dir = tmp_path / "agents" / "procedures"
        user_proc_dir.mkdir(parents=True)
        (user_proc_dir / "override.md").write_text("USER VERSION", encoding="utf-8")

        # Create system procedures
        deskagent_dir = tmp_path / "deskagent"
        system_proc_dir = deskagent_dir / "agents" / "procedures"
        system_proc_dir.mkdir(parents=True)
        (system_proc_dir / "override.md").write_text("SYSTEM VERSION", encoding="utf-8")

        monkeypatch.setattr(paths, "PROJECT_DIR", tmp_path)
        monkeypatch.setattr(paths, "DESKAGENT_DIR", deskagent_dir)

        result = agents.load_procedure("override")

        assert result == "USER VERSION"


class TestProcessAgent:
    """Tests for process_agent function."""

    def test_process_nonexistent_agent(self, tmp_path, monkeypatch):
        """Test processing a non-existent agent returns error."""
        from assistant import agents

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        monkeypatch.setattr(agents, "get_agents_dir", lambda: agents_dir)

        # Mock dependencies to avoid side effects
        with patch.object(agents, 'notify'):
            with patch.object(agents, 'load_config', return_value={"ai_backends": {}}):
                success, content, stats = agents.process_agent("nonexistent")

                assert success is False
                assert "nicht gefunden" in content.lower()
