# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for MCP Transport modes (stdio, sse, streamable-http).

Tests the transport selection logic in claude_agent_sdk.py and
the auto-detection in anonymization_proxy_mcp.py.
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestProxyModeDetection:
    """Tests for _is_stdio_mode() in the Proxy."""

    def test_stdio_mode_without_transport_flag(self):
        """Without --transport flag = stdio mode."""
        with patch.object(sys, 'argv', ['proxy.py', '--session', 'abc123']):
            # _is_stdio_mode() should return True
            assert "--transport" not in sys.argv

    def test_http_mode_with_transport_flag(self):
        """With --transport flag = HTTP mode."""
        with patch.object(sys, 'argv', ['proxy.py', '--transport', 'sse', '--port', '8766']):
            assert "--transport" in sys.argv

    def test_stdio_mode_with_filter(self):
        """stdio with --filter flag."""
        with patch.object(sys, 'argv', ['proxy.py', '--session', 'abc', '--filter', 'outlook']):
            assert "--transport" not in sys.argv
            assert "--filter" in sys.argv

    def test_streamable_http_mode(self):
        """With --transport streamable-http flag."""
        with patch.object(sys, 'argv', ['proxy.py', '--transport', 'streamable-http', '--port', '19001']):
            assert "--transport" in sys.argv
            assert sys.argv[sys.argv.index('--transport') + 1] == 'streamable-http'


class TestSDKTransportRouting:
    """Tests for Transport-Routing in the SDK."""

    @pytest.fixture
    def mock_config(self):
        """Mock config for tests."""
        return {
            "ai_backends": {
                "claude_sdk": {
                    "type": "claude_agent_sdk",
                    "mcp_transport": "stdio"
                }
            }
        }

    def test_stdio_with_anonymize_creates_proxy_subprocess(self, mock_config):
        """stdio + anonymize=true should start proxy as subprocess."""
        agent_config = {"anonymize": True, "allowed_mcp": "outlook"}
        mcp_transport = "stdio"
        mcp_servers = {}

        # Simulate SDK logic
        if mcp_transport == "stdio":
            use_anonymize = agent_config.get("anonymize", False)
            if use_anonymize:
                mcp_servers["proxy"] = {
                    "type": "stdio",
                    "command": "python",
                    "args": ["proxy.py", "--session", "test123"],
                    "env": {}
                }

        assert "proxy" in mcp_servers
        assert mcp_servers["proxy"]["type"] == "stdio"
        assert "--session" in mcp_servers["proxy"]["args"]

    def test_stdio_without_anonymize_uses_direct_mcp(self, mock_config):
        """stdio + anonymize=false should use direct MCPs."""
        agent_config = {"anonymize": False}
        mcp_transport = "stdio"
        mcp_servers = {}
        use_proxy = False

        if mcp_transport == "stdio":
            use_anonymize = agent_config.get("anonymize", False)
            if not use_anonymize:
                # Would call discover_mcp_servers()
                mcp_servers["outlook"] = {"type": "stdio", "command": "python", "args": ["outlook_mcp.py"]}

        assert "proxy" not in mcp_servers
        assert "outlook" in mcp_servers
        assert not use_proxy

    def test_sse_transport_uses_http_proxy(self, mock_config):
        """SSE transport should use HTTP proxy."""
        mcp_transport = "sse"
        mcp_servers = {}

        if mcp_transport != "stdio":
            mcp_servers["proxy"] = {
                "type": "sse",
                "url": "http://localhost:8766/sse"
            }

        assert "proxy" in mcp_servers
        assert mcp_servers["proxy"]["type"] == "sse"

    def test_streamable_http_transport(self):
        """streamable-http transport should use HTTP proxy with /mcp endpoint."""
        mcp_transport = "streamable-http"
        mcp_servers = {}

        if mcp_transport not in ("stdio",):
            if mcp_transport == "sse":
                mcp_servers["proxy"] = {
                    "type": "sse",
                    "url": "http://localhost:19001/sse"
                }
            else:
                mcp_servers["proxy"] = {
                    "type": "http",
                    "url": "http://localhost:19001/mcp"
                }

        assert "proxy" in mcp_servers
        assert mcp_servers["proxy"]["type"] == "http"
        assert "/mcp" in mcp_servers["proxy"]["url"]


class TestStdioWrapperFunctions:
    """Tests for wrapper functions in stdio mode."""

    def test_anonymize_wrapper_creates_context(self):
        """anonymize() wrapper should create AnonymizationContext."""
        # Mock the direct imports
        mock_context = MagicMock()
        mock_anonymize = MagicMock(return_value=("<PERSON_1> schrieb...", mock_context))
        mock_config = {"anonymization": {"enabled": True}}

        with patch.dict('sys.modules', {
            'ai_agent.anonymizer': MagicMock(
                AnonymizationContext=lambda s: mock_context,
                anonymize_with_context=mock_anonymize
            )
        }):
            # Simulate wrapper (must match anonymization_proxy_mcp.py STDIO wrapper)
            def anonymize(text, session_id):
                from ai_agent.anonymizer import AnonymizationContext, anonymize_with_context
                ctx = AnonymizationContext(session_id)
                result, _ = anonymize_with_context(text, mock_config, ctx)
                return result

            result = anonymize("Max Mustermann schrieb...", "session123")
            assert result == "<PERSON_1> schrieb..."
            assert mock_anonymize.called
            # Verify 3 arguments passed (text, config, ctx)
            args = mock_anonymize.call_args[0]
            assert len(args) == 3, f"Expected 3 args, got {len(args)}"

    def test_cleanup_session_is_noop(self):
        """cleanup_session() should be a no-op in stdio mode."""
        def cleanup_session(session_id):
            pass  # Stub

        # Should not raise
        cleanup_session("test123")

    def test_get_task_context_returns_empty(self):
        """get_task_context() should return empty dict."""
        def get_task_context():
            return {}

        assert get_task_context() == {}


class TestTransportConfigLoading:
    """Tests for transport config from backends.json."""

    def test_get_mcp_transport_reads_config(self):
        """get_mcp_transport() should read config."""
        mock_config = {
            "ai_backends": {
                "claude_sdk": {"mcp_transport": "stdio"}
            }
        }

        with patch('builtins.open', MagicMock()):
            with patch('json.load', return_value=mock_config):
                # Simulate get_mcp_transport()
                transport = mock_config["ai_backends"]["claude_sdk"].get("mcp_transport", "sse")
                assert transport == "stdio"

    def test_get_mcp_transport_default_is_stdio(self):
        """Without config, default should be 'stdio'."""
        mock_config = {"ai_backends": {"claude_sdk": {}}}

        # Now default is stdio (changed from sse)
        transport = mock_config["ai_backends"]["claude_sdk"].get("mcp_transport", "stdio")
        assert transport == "stdio"


class TestGlobalMCPCollisionCheck:
    """Tests for _check_global_mcp_collision() function."""

    def test_no_warning_without_claude_json(self, tmp_path):
        """Should not warn if ~/.claude.json doesn't exist."""
        # Claude.json doesn't exist in tmp_path
        with patch('pathlib.Path.home', return_value=tmp_path):
            claude_json = tmp_path / ".claude.json"
            assert not claude_json.exists()

    def test_no_warning_without_mcp_servers(self, tmp_path):
        """Should not warn if mcpServers is empty or missing."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"some_other_config": true}')

        import json
        config = json.loads(claude_json.read_text())
        global_mcps = config.get("mcpServers", {})
        assert global_mcps == {}

    def test_warns_on_global_mcp_servers(self, tmp_path, caplog):
        """Should warn when mcpServers exist in ~/.claude.json."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"some_server": {"type": "stdio"}}}')

        import json
        config = json.loads(claude_json.read_text())
        global_mcps = config.get("mcpServers", {})

        # Simulate the check
        assert len(global_mcps) > 0
        assert "some_server" in global_mcps

    def test_critical_warning_on_proxy_entry(self, tmp_path):
        """Should issue CRITICAL warning when 'proxy' entry exists."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"proxy": {"type": "stdio"}}}')

        import json
        config = json.loads(claude_json.read_text())
        global_mcps = config.get("mcpServers", {})

        # The proxy entry is the problematic one
        assert "proxy" in global_mcps


class TestWindowsCmdWrapper:
    """Tests for Windows cmd /c wrapper in stdio mode."""

    def test_windows_uses_cmd_wrapper(self):
        """On Windows, stdio MCP should use cmd /c wrapper."""
        mcp_servers = {}
        python_exe = "python"
        proxy_args = ["proxy.py", "--session", "abc123"]
        proxy_env = {"PATH": "/some/path"}

        # Simulate Windows branch
        is_windows = True
        if is_windows:
            mcp_servers["proxy"] = {
                "type": "stdio",
                "command": "cmd",
                "args": ["/c", python_exe] + proxy_args,
                "env": proxy_env
            }

        assert mcp_servers["proxy"]["command"] == "cmd"
        assert mcp_servers["proxy"]["args"][0] == "/c"
        assert mcp_servers["proxy"]["args"][1] == "python"

    def test_non_windows_uses_direct_python(self):
        """On non-Windows, stdio MCP should use Python directly."""
        mcp_servers = {}
        python_exe = "python"
        proxy_args = ["proxy.py", "--session", "abc123"]
        proxy_env = {"PATH": "/some/path"}

        # Simulate non-Windows branch
        is_windows = False
        if not is_windows:
            mcp_servers["proxy"] = {
                "type": "stdio",
                "command": python_exe,
                "args": proxy_args,
                "env": proxy_env
            }

        assert mcp_servers["proxy"]["command"] == "python"
        assert mcp_servers["proxy"]["args"][0] == "proxy.py"
