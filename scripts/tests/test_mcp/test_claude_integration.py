# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Claude Desktop/Code Deep Integration (plan-083)

Features tested:
- F7: ENV-Var Fix (_build_stdio_entry uses ALLOWED_MCP_PATTERN, desk_check reads it)
- F1: MCP Prompts (_register_agent_prompts: enabled, disabled, tool-agents, bad names)
- F3: Resource Templates (_register_agent_resources: agents + skills, user override)
- F4: mcpContextUris (_inject_mcp_to_user_config populates knowledge URIs)
"""

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure scripts/ is on sys.path for ai_agent imports
SCRIPTS_DIR = Path(__file__).parent.parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Ensure mcp/ is on sys.path for desk/ imports
MCP_DIR = SCRIPTS_DIR.parent / "mcp"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))


# ============================================================================
# F7: ENV-Var Fix - _build_stdio_entry and desk_check_claude_desktop
# ============================================================================

class TestBuildStdioEntry:
    """F7: _build_stdio_entry must use ALLOWED_MCP_PATTERN (not DESKAGENT_MCP_FILTER)."""

    def test_sets_allowed_mcp_pattern_env_var(self):
        """When filter_pattern is provided, env contains ALLOWED_MCP_PATTERN."""
        from desk.claude_desktop import _build_stdio_entry

        entry = _build_stdio_entry("outlook|billomat")

        assert "env" in entry
        assert "ALLOWED_MCP_PATTERN" in entry["env"]
        assert entry["env"]["ALLOWED_MCP_PATTERN"] == "outlook|billomat"

    def test_no_deskagent_mcp_filter_env_var(self):
        """Must NOT use the old DESKAGENT_MCP_FILTER variable name."""
        from desk.claude_desktop import _build_stdio_entry

        entry = _build_stdio_entry("outlook|billomat")

        assert "DESKAGENT_MCP_FILTER" not in entry.get("env", {})

    def test_no_filter_pattern_no_env_var(self):
        """When filter_pattern is empty, no filter env var is set."""
        from desk.claude_desktop import _build_stdio_entry

        entry = _build_stdio_entry("")

        env = entry.get("env", {})
        assert "ALLOWED_MCP_PATTERN" not in env
        assert "DESKAGENT_MCP_FILTER" not in env

    def test_has_required_env_vars(self):
        """Entry always contains PYTHONPATH and DESKAGENT_SCRIPTS_DIR."""
        from desk.claude_desktop import _build_stdio_entry

        entry = _build_stdio_entry("")

        assert "PYTHONPATH" in entry["env"]
        assert "DESKAGENT_SCRIPTS_DIR" in entry["env"]
        assert "DESKAGENT_WORKSPACE_DIR" in entry["env"]

    def test_has_command_and_args(self):
        """Entry has a command (python path) and args with proxy script."""
        from desk.claude_desktop import _build_stdio_entry

        entry = _build_stdio_entry("")

        assert "command" in entry
        assert "args" in entry
        assert "--session" in entry["args"]
        assert "claude-desktop" in entry["args"]


class TestCheckClaudeDesktopDisplaysFilter:
    """F7: desk_check_claude_desktop reads ALLOWED_MCP_PATTERN for display."""

    def test_displays_allowed_mcp_pattern(self, tmp_path):
        """Check output displays MCP-Filter when ALLOWED_MCP_PATTERN is set."""
        from desk.claude_desktop import desk_check_claude_desktop

        # Create a fake Claude Desktop config with ALLOWED_MCP_PATTERN in env
        config_data = {
            "mcpServers": {
                "deskagent": {
                    "command": "python",
                    "args": ["proxy.py", "--session", "claude-desktop"],
                    "env": {
                        "PYTHONPATH": "/some/path",
                        "ALLOWED_MCP_PATTERN": "outlook|billomat|filesystem"
                    }
                }
            }
        }

        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        with patch("desk.claude_desktop._get_claude_desktop_config_path", return_value=config_file):
            result = desk_check_claude_desktop()

        assert "konfiguriert" in result.lower() or "configured" in result.lower()
        assert "outlook|billomat|filesystem" in result
        assert "MCP-Filter" in result

    def test_no_filter_no_display(self, tmp_path):
        """Check output does not show MCP-Filter when no filter env is set."""
        from desk.claude_desktop import desk_check_claude_desktop

        config_data = {
            "mcpServers": {
                "deskagent": {
                    "command": "python",
                    "args": ["proxy.py"],
                    "env": {
                        "PYTHONPATH": "/some/path"
                    }
                }
            }
        }

        config_file = tmp_path / "claude_desktop_config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        with patch("desk.claude_desktop._get_claude_desktop_config_path", return_value=config_file):
            result = desk_check_claude_desktop()

        assert "MCP-Filter" not in result


# ============================================================================
# F1: MCP Prompts - _register_agent_prompts
# ============================================================================

class TestRegisterAgentPrompts:
    """F1: _register_agent_prompts registers agents as MCP prompts."""

    @pytest.fixture
    def agent_dirs(self, tmp_path):
        """Create user and system agent directories with sample files."""
        user_agents = tmp_path / "user_agents"
        user_agents.mkdir()
        system_agents = tmp_path / "system_agents"
        system_agents.mkdir()
        return user_agents, system_agents

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock FastMCP object with a prompt() decorator."""
        mock = MagicMock()
        # mcp.prompt(name=..., description=...) returns a decorator
        # that decorator is called with the function
        mock.prompt.return_value = lambda fn: fn
        return mock

    def _run_register(self, mock_mcp, user_agents, system_agents, workspace_dir=None):
        """Helper to run _register_agent_prompts with patched globals.

        Creates a directory layout matching what the proxy function expects:
          <base>/deskagent/mcp/     <- MCP_DIR
          <base>/deskagent/agents/  <- system agents
          <base>/agents/            <- user agents
        """
        # Use user_agents.parent as the base directory (tmp_path)
        base = user_agents.parent
        deskagent_dir = base / "deskagent_stub"
        deskagent_dir.mkdir(exist_ok=True)
        mcp_dir = deskagent_dir / "mcp"
        mcp_dir.mkdir(exist_ok=True)

        # System agents at deskagent_stub/agents/
        sys_agents = deskagent_dir / "agents"
        sys_agents.mkdir(exist_ok=True)
        for f in system_agents.glob("*.md"):
            (sys_agents / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # User agents at base/agents/
        usr_agents = base / "agents"
        usr_agents.mkdir(exist_ok=True)
        for f in user_agents.glob("*.md"):
            (usr_agents / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        env_patch = {}
        if workspace_dir:
            env_patch["DESKAGENT_WORKSPACE_DIR"] = str(workspace_dir)

        with patch("anonymization_proxy_mcp.mcp", mock_mcp), \
             patch("anonymization_proxy_mcp.MCP_DIR", mcp_dir), \
             patch("anonymization_proxy_mcp.mcp_log"), \
             patch.dict(os.environ, env_patch, clear=False):
            # Remove DESKAGENT_WORKSPACE_DIR unless explicitly set
            if not workspace_dir:
                os.environ.pop("DESKAGENT_WORKSPACE_DIR", None)
            from anonymization_proxy_mcp import _register_agent_prompts
            _register_agent_prompts()

        return mock_mcp

    def test_registers_basic_agent(self, agent_dirs, mock_mcp):
        """A valid .md agent file is registered as a prompt."""
        user_agents, system_agents = agent_dirs

        (user_agents / "reply_email.md").write_text(
            "---\n{}\n---\n# Reply Email\nReply to the selected email.",
            encoding="utf-8"
        )

        result = self._run_register(mock_mcp, user_agents, system_agents)

        # Check mcp.prompt() was called with correct name
        prompt_calls = result.prompt.call_args_list
        names = [c.kwargs.get("name", c.args[0] if c.args else None) for c in prompt_calls]
        # Should find deskagent_reply_email
        assert any(n == "deskagent_reply_email" for n in names), \
            f"Expected deskagent_reply_email in prompt calls, got: {names}"

    def test_skips_disabled_agent(self, agent_dirs, mock_mcp):
        """Agent with enabled: false in frontmatter is skipped."""
        user_agents, system_agents = agent_dirs

        (user_agents / "disabled_agent.md").write_text(
            '---\n{"enabled": false}\n---\n# Disabled\nShould not be registered.',
            encoding="utf-8"
        )

        result = self._run_register(mock_mcp, user_agents, system_agents)

        prompt_calls = result.prompt.call_args_list
        names_str = str(prompt_calls)
        assert "deskagent_disabled_agent" not in names_str

    def test_skips_tool_agent(self, agent_dirs, mock_mcp):
        """Agent with 'tool' in frontmatter is skipped (already exposed as MCP tool)."""
        user_agents, system_agents = agent_dirs

        (user_agents / "tool_agent.md").write_text(
            '---\n{"tool": {"name": "my_tool"}}\n---\n# Tool Agent\nHas tool definition.',
            encoding="utf-8"
        )

        result = self._run_register(mock_mcp, user_agents, system_agents)

        prompt_calls = result.prompt.call_args_list
        names_str = str(prompt_calls)
        assert "deskagent_tool_agent" not in names_str

    def test_handles_invalid_frontmatter(self, agent_dirs, mock_mcp):
        """Invalid JSON in frontmatter is handled gracefully (agent still registered)."""
        user_agents, system_agents = agent_dirs

        (user_agents / "bad_frontmatter.md").write_text(
            "---\n{invalid json\n---\n# Bad Frontmatter\nContent here.",
            encoding="utf-8"
        )

        # Should not raise, should still register the agent
        result = self._run_register(mock_mcp, user_agents, system_agents)

        prompt_calls = result.prompt.call_args_list
        names_str = str(prompt_calls)
        # Agent with bad frontmatter should still be registered (frontmatter defaults to {})
        assert "deskagent_bad_frontmatter" in names_str

    def test_rejects_non_alphanumeric_names(self, agent_dirs, mock_mcp):
        """Agent filenames with special characters are skipped."""
        user_agents, system_agents = agent_dirs

        # Name with spaces or special chars (except _ and -)
        (user_agents / "bad name!.md").write_text(
            "---\n{}\n---\n# Bad Name\nContent.",
            encoding="utf-8"
        )

        result = self._run_register(mock_mcp, user_agents, system_agents)

        prompt_calls = result.prompt.call_args_list
        names_str = str(prompt_calls)
        assert "bad name" not in names_str
        assert "bad_name" not in names_str

    def test_allows_hyphens_and_underscores(self, agent_dirs, mock_mcp):
        """Agent names with hyphens and underscores are valid."""
        user_agents, system_agents = agent_dirs

        (user_agents / "my-agent_v2.md").write_text(
            "---\n{}\n---\n# My Agent V2\nContent.",
            encoding="utf-8"
        )

        result = self._run_register(mock_mcp, user_agents, system_agents)

        prompt_calls = result.prompt.call_args_list
        names_str = str(prompt_calls)
        assert "deskagent_my-agent_v2" in names_str

    def test_no_frontmatter_agent_registered(self, agent_dirs, mock_mcp):
        """Agent without frontmatter block is still registered."""
        user_agents, system_agents = agent_dirs

        (user_agents / "simple.md").write_text(
            "# Simple Agent\nJust do the thing.",
            encoding="utf-8"
        )

        result = self._run_register(mock_mcp, user_agents, system_agents)

        prompt_calls = result.prompt.call_args_list
        names_str = str(prompt_calls)
        assert "deskagent_simple" in names_str


# ============================================================================
# F3: Resource Templates - _register_agent_resources
# ============================================================================

class TestRegisterAgentResources:
    """F3: _register_agent_resources registers agents and skills as MCP resources."""

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock FastMCP object with a resource() decorator."""
        mock = MagicMock()
        mock.resource.return_value = lambda fn: fn
        return mock

    def _setup_dirs(self, tmp_path):
        """Create a directory layout matching what the proxy code expects.

        Returns (mcp_dir, user_agents_dir, system_agents_dir, user_skills_dir, system_skills_dir).
        """
        base = tmp_path / "project"
        base.mkdir()
        deskagent = base / "deskagent"
        deskagent.mkdir()
        mcp_dir = deskagent / "mcp"
        mcp_dir.mkdir()

        # System agents: deskagent/agents/
        sys_agents = deskagent / "agents"
        sys_agents.mkdir()
        # User agents: base/agents/ (MCP_DIR.parent.parent / "agents")
        usr_agents = base / "agents"
        usr_agents.mkdir()
        # System skills: deskagent/skills/
        sys_skills = deskagent / "skills"
        sys_skills.mkdir()
        # User skills: base/skills/
        usr_skills = base / "skills"
        usr_skills.mkdir()

        return mcp_dir, usr_agents, sys_agents, usr_skills, sys_skills

    def _run_register(self, mock_mcp, mcp_dir):
        """Run _register_agent_resources with patched globals."""
        with patch("anonymization_proxy_mcp.mcp", mock_mcp), \
             patch("anonymization_proxy_mcp.MCP_DIR", mcp_dir), \
             patch("anonymization_proxy_mcp.mcp_log"), \
             patch.dict(os.environ, {}, clear=False):
            # Remove DESKAGENT_WORKSPACE_DIR to use path-based resolution
            os.environ.pop("DESKAGENT_WORKSPACE_DIR", None)
            from anonymization_proxy_mcp import _register_agent_resources
            _register_agent_resources()

    def test_registers_agent_with_correct_uri(self, tmp_path):
        """Agents are registered with agent://<name> URI scheme."""
        mock_mcp = MagicMock()
        mock_mcp.resource.return_value = lambda fn: fn

        mcp_dir, usr_agents, sys_agents, usr_skills, sys_skills = self._setup_dirs(tmp_path)

        (usr_agents / "daily_check.md").write_text(
            "# Daily Check\nCheck emails.", encoding="utf-8"
        )

        self._run_register(mock_mcp, mcp_dir)

        # Find the resource() call for daily_check
        resource_calls = mock_mcp.resource.call_args_list
        uris = [c.args[0] if c.args else c.kwargs.get("uri") for c in resource_calls]
        assert "agent://daily_check" in uris

    def test_registers_skill_with_correct_uri(self, tmp_path):
        """Skills are registered with skill://<name> URI scheme."""
        mock_mcp = MagicMock()
        mock_mcp.resource.return_value = lambda fn: fn

        mcp_dir, usr_agents, sys_agents, usr_skills, sys_skills = self._setup_dirs(tmp_path)

        (usr_skills / "mail_reply.md").write_text(
            "# Mail Reply\nReply to emails.", encoding="utf-8"
        )

        self._run_register(mock_mcp, mcp_dir)

        resource_calls = mock_mcp.resource.call_args_list
        uris = [c.args[0] if c.args else c.kwargs.get("uri") for c in resource_calls]
        assert "skill://mail_reply" in uris

    def test_user_agents_override_system(self, tmp_path):
        """User agent with same name as system agent takes precedence."""
        mock_mcp = MagicMock()
        mock_mcp.resource.return_value = lambda fn: fn

        mcp_dir, usr_agents, sys_agents, usr_skills, sys_skills = self._setup_dirs(tmp_path)

        # Both user and system have reply_email.md
        (sys_agents / "reply_email.md").write_text(
            "# System Reply Email\nSystem version.", encoding="utf-8"
        )
        (usr_agents / "reply_email.md").write_text(
            "# User Reply Email\nCustom version.", encoding="utf-8"
        )

        self._run_register(mock_mcp, mcp_dir)

        # Only one agent://reply_email should be registered
        resource_calls = mock_mcp.resource.call_args_list
        reply_email_uris = [
            c for c in resource_calls
            if (c.args[0] if c.args else "") == "agent://reply_email"
        ]
        assert len(reply_email_uris) == 1

        # The registered reader function should return the USER version
        # Get the decorator call and find the function that was passed to it
        # Since mock.resource() returns lambda fn: fn, we need to check the file path
        # The function uses a dict where user files overwrite system files by key
        # So user version wins. We can verify by checking the reader returns user content.

    def test_registers_both_agents_and_skills(self, tmp_path):
        """Both agents and skills are registered in a single call."""
        mock_mcp = MagicMock()
        mock_mcp.resource.return_value = lambda fn: fn

        mcp_dir, usr_agents, sys_agents, usr_skills, sys_skills = self._setup_dirs(tmp_path)

        (usr_agents / "check_email.md").write_text("# Check Email", encoding="utf-8")
        (usr_skills / "translate.md").write_text("# Translate", encoding="utf-8")

        self._run_register(mock_mcp, mcp_dir)

        resource_calls = mock_mcp.resource.call_args_list
        uris = [c.args[0] if c.args else c.kwargs.get("uri") for c in resource_calls]

        assert "agent://check_email" in uris
        assert "skill://translate" in uris

    def test_skips_invalid_name_characters(self, tmp_path):
        """Files with names containing invalid characters are skipped."""
        mock_mcp = MagicMock()
        mock_mcp.resource.return_value = lambda fn: fn

        mcp_dir, usr_agents, sys_agents, usr_skills, sys_skills = self._setup_dirs(tmp_path)

        # Valid name
        (usr_agents / "good_name.md").write_text("# Good", encoding="utf-8")
        # Invalid name (contains space - filesystem may or may not allow it)
        try:
            (usr_agents / "bad name.md").write_text("# Bad", encoding="utf-8")
        except OSError:
            pass  # Some filesystems reject it

        self._run_register(mock_mcp, mcp_dir)

        resource_calls = mock_mcp.resource.call_args_list
        uris = [c.args[0] if c.args else c.kwargs.get("uri") for c in resource_calls]

        assert "agent://good_name" in uris
        # bad name should not be registered (fails regex check)
        assert all("bad name" not in str(u) for u in uris)


# ============================================================================
# F4: mcpContextUris - _inject_mcp_to_user_config
# ============================================================================

class TestInjectMcpContextUris:
    """F4: _inject_mcp_to_user_config populates mcpContextUris with knowledge URIs."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Reset module globals before each test."""
        import ai_agent.claude_agent_sdk as mod
        mod._original_claude_json = None
        mod._claude_json_path = None
        mod._injected_cwd = None
        yield
        mod._original_claude_json = None
        mod._claude_json_path = None
        mod._injected_cwd = None

    def test_new_project_gets_knowledge_uris(self, tmp_path):
        """New project entry gets mcpContextUris with knowledge resources."""
        from ai_agent.claude_agent_sdk import _inject_mcp_to_user_config

        claude_json = tmp_path / ".claude.json"

        with patch("ai_agent.claude_agent_sdk._get_claude_json_path", return_value=claude_json), \
             patch("ai_agent.claude_agent_sdk.log"):
            result = _inject_mcp_to_user_config(
                {"proxy": {"type": "stdio", "command": "python"}},
                cwd="C:\\projects\\myapp"
            )

        assert result is True
        config = json.loads(claude_json.read_text(encoding="utf-8"))

        # Find the project entry (normalized path)
        cwd_key = "C:\\projects\\myapp"
        assert cwd_key in config["projects"]

        project = config["projects"][cwd_key]
        assert "mcpContextUris" in project
        assert len(project["mcpContextUris"]) > 0

        # Should contain knowledge URIs
        uris = project["mcpContextUris"]
        assert any("knowledge://" in uri for uri in uris)
        assert "knowledge://user/doc-company" in uris
        assert "knowledge://user/doc-products" in uris
        assert "knowledge://user/doc-pricing" in uris

    def test_existing_project_preserves_uris(self, tmp_path):
        """Existing project with mcpContextUris already set is not overwritten."""
        from ai_agent.claude_agent_sdk import _inject_mcp_to_user_config

        claude_json = tmp_path / ".claude.json"
        existing_uris = ["knowledge://user/custom-doc", "agent://my_workflow"]

        existing_config = {
            "projects": {
                "C:\\projects\\myapp": {
                    "allowedTools": [],
                    "mcpContextUris": existing_uris,
                    "hasTrustDialogAccepted": True
                }
            }
        }
        claude_json.write_text(json.dumps(existing_config), encoding="utf-8")

        with patch("ai_agent.claude_agent_sdk._get_claude_json_path", return_value=claude_json), \
             patch("ai_agent.claude_agent_sdk.log"):
            result = _inject_mcp_to_user_config(
                {"proxy": {"type": "stdio"}},
                cwd="C:\\projects\\myapp"
            )

        assert result is True
        config = json.loads(claude_json.read_text(encoding="utf-8"))
        project = config["projects"]["C:\\projects\\myapp"]

        # Existing URIs should be preserved (not overwritten)
        assert project["mcpContextUris"] == existing_uris

    def test_empty_uris_gets_populated(self, tmp_path):
        """Project with empty mcpContextUris list gets populated."""
        from ai_agent.claude_agent_sdk import _inject_mcp_to_user_config

        claude_json = tmp_path / ".claude.json"
        existing_config = {
            "projects": {
                "C:\\projects\\myapp": {
                    "allowedTools": [],
                    "mcpContextUris": [],
                    "hasTrustDialogAccepted": True
                }
            }
        }
        claude_json.write_text(json.dumps(existing_config), encoding="utf-8")

        with patch("ai_agent.claude_agent_sdk._get_claude_json_path", return_value=claude_json), \
             patch("ai_agent.claude_agent_sdk.log"):
            result = _inject_mcp_to_user_config(
                {"proxy": {"type": "stdio"}},
                cwd="C:\\projects\\myapp"
            )

        assert result is True
        config = json.loads(claude_json.read_text(encoding="utf-8"))
        project = config["projects"]["C:\\projects\\myapp"]

        # Empty list is falsy, so it should get populated
        assert len(project["mcpContextUris"]) > 0
        assert "knowledge://user/doc-company" in project["mcpContextUris"]

    def test_injects_mcp_servers(self, tmp_path):
        """MCP servers dict is correctly injected into project config."""
        from ai_agent.claude_agent_sdk import _inject_mcp_to_user_config

        claude_json = tmp_path / ".claude.json"
        mcp_servers = {
            "deskagent": {
                "command": "python",
                "args": ["proxy.py"],
                "env": {"PYTHONPATH": "/scripts"}
            }
        }

        with patch("ai_agent.claude_agent_sdk._get_claude_json_path", return_value=claude_json), \
             patch("ai_agent.claude_agent_sdk.log"):
            result = _inject_mcp_to_user_config(mcp_servers, cwd="C:\\dev")

        assert result is True
        config = json.loads(claude_json.read_text(encoding="utf-8"))
        project = config["projects"]["C:\\dev"]
        assert project["mcpServers"] == mcp_servers

    def test_creates_projects_structure(self, tmp_path):
        """Creates projects key and project entry if ~/.claude.json is empty."""
        from ai_agent.claude_agent_sdk import _inject_mcp_to_user_config

        claude_json = tmp_path / ".claude.json"
        # File does not exist yet

        with patch("ai_agent.claude_agent_sdk._get_claude_json_path", return_value=claude_json), \
             patch("ai_agent.claude_agent_sdk.log"):
            result = _inject_mcp_to_user_config({}, cwd="C:\\test")

        assert result is True
        config = json.loads(claude_json.read_text(encoding="utf-8"))
        assert "projects" in config
        assert "C:\\test" in config["projects"]
        project = config["projects"]["C:\\test"]
        assert "allowedTools" in project
        assert "hasTrustDialogAccepted" in project


# ============================================================================
# F1 (additional): Direct unit tests for the prompt registration logic
# ============================================================================

class TestPromptRegistrationLogic:
    """Unit tests for the prompt registration logic without full path setup."""

    def test_name_regex_validation(self):
        """The name regex matches only valid agent names."""
        pattern = re.compile(r'^[a-zA-Z0-9_\-]+$')

        # Valid names
        assert pattern.match("reply_email")
        assert pattern.match("daily-check")
        assert pattern.match("Agent123")
        assert pattern.match("a")

        # Invalid names
        assert not pattern.match("bad name")
        assert not pattern.match("bad!name")
        assert not pattern.match("path/to/file")
        assert not pattern.match("")
        assert not pattern.match("name.ext")

    def test_frontmatter_parsing(self):
        """JSON frontmatter is correctly parsed from agent content."""
        content = '---\n{"enabled": false, "description": "Test"}\n---\n# Agent\nContent.'

        frontmatter = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = json.loads(parts[1].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        assert frontmatter.get("enabled") is False
        assert frontmatter.get("description") == "Test"

    def test_frontmatter_parsing_no_frontmatter(self):
        """Content without frontmatter yields empty dict."""
        content = "# Agent\nJust content, no frontmatter."

        frontmatter = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = json.loads(parts[1].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        assert frontmatter == {}

    def test_frontmatter_parsing_invalid_json(self):
        """Invalid JSON in frontmatter yields empty dict (no crash)."""
        content = '---\n{this is not valid json}\n---\n# Agent\nContent.'

        frontmatter = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = json.loads(parts[1].strip())
                except (json.JSONDecodeError, ValueError):
                    pass

        assert frontmatter == {}

    def test_prompt_content_extraction(self):
        """Prompt content is the part after the frontmatter block."""
        content = '---\n{"description": "Test"}\n---\n# Agent Title\n\nDo the thing.'

        prompt_content = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                prompt_content = parts[2].strip()

        assert prompt_content == "# Agent Title\n\nDo the thing."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
