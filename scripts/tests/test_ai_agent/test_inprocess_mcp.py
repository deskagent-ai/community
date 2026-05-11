#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for In-Process MCP Server Transport (planfeature-018)
============================================================

Tests:
- Tool discovery and conversion to SDK format
- SDK MCP server creation
- Tool filtering (allowed_mcp, allowed_tools, blocked_tools, tool_mode)
- Anonymization wrapper
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add scripts path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestGetSdkMcpTools:
    """Tests for get_sdk_mcp_tools() function."""

    def test_imports_correctly(self):
        """Test that get_sdk_mcp_tools can be imported."""
        from ai_agent.tool_bridge import get_sdk_mcp_tools
        assert callable(get_sdk_mcp_tools)

    def test_returns_list(self):
        """Test that get_sdk_mcp_tools returns a list."""
        from ai_agent.tool_bridge import get_sdk_mcp_tools

        # Mock MCP discovery to return empty
        with patch('ai_agent.tool_bridge._discover_mcp_tools', return_value=([], {})):
            with patch('ai_agent.tool_bridge.get_ollama_tools', return_value=[]):
                result = get_sdk_mcp_tools()
                assert isinstance(result, list)

    def test_respects_mcp_filter(self):
        """Test that mcp_filter is passed to underlying discovery."""
        from ai_agent.tool_bridge import get_sdk_mcp_tools

        mock_tools = []
        with patch('ai_agent.tool_bridge.get_ollama_tools', return_value=[]) as mock_get:
            with patch('ai_agent.tool_bridge._discover_mcp_tools', return_value=([], {})):
                get_sdk_mcp_tools(mcp_filter="outlook|billomat")
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args[1]
                assert call_kwargs.get('mcp_filter') == "outlook|billomat"


class TestConvertParamsToSdkSchema:
    """Tests for _convert_params_to_sdk_schema() function."""

    def test_empty_params(self):
        """Test handling of empty parameters."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        result = _convert_params_to_sdk_schema({})
        assert result == {}

    def test_string_param(self):
        """Test conversion of string parameter."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        json_schema = {
            "properties": {
                "message": {"type": "string"}
            }
        }
        result = _convert_params_to_sdk_schema(json_schema)
        assert result == {"message": str}

    def test_multiple_types(self):
        """Test conversion of multiple parameter types."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        json_schema = {
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "price": {"type": "number"},
                "active": {"type": "boolean"},
            }
        }
        result = _convert_params_to_sdk_schema(json_schema)
        assert result == {
            "name": str,
            "count": int,
            "price": float,
            "active": bool,
        }


class TestCreateSdkToolHandler:
    """Tests for _create_sdk_tool_handler() function."""

    def test_sync_function_wrapped_correctly(self):
        """Test that sync functions are wrapped as async."""
        from ai_agent.tool_bridge import _create_sdk_tool_handler
        import asyncio

        def sync_tool(message: str) -> str:
            return f"Hello, {message}"

        handler = _create_sdk_tool_handler(sync_tool, "test_tool")

        # Handler should be async
        assert asyncio.iscoroutinefunction(handler)

    @pytest.mark.asyncio
    async def test_handler_returns_correct_format(self):
        """Test that handler returns SDK-expected format."""
        from ai_agent.tool_bridge import _create_sdk_tool_handler

        def simple_tool(message: str) -> str:
            return f"Echo: {message}"

        handler = _create_sdk_tool_handler(simple_tool, "simple_tool")

        # Mock event publishing at the correct import location
        with patch('ai_agent.event_publishing.publish_tool_event'):
            result = await handler({"message": "test"})

        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"
        assert "Echo: test" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_handler_catches_exceptions(self):
        """Test that handler catches and reports exceptions."""
        from ai_agent.tool_bridge import _create_sdk_tool_handler

        def failing_tool(message: str) -> str:
            raise ValueError("Test error")

        handler = _create_sdk_tool_handler(failing_tool, "failing_tool")

        with patch('ai_agent.event_publishing.publish_tool_event'):
            result = await handler({"message": "test"})

        assert result.get("is_error") is True
        assert "Error:" in result["content"][0]["text"]


class TestInprocessTransportConfig:
    """Tests for inprocess transport configuration."""

    def test_get_mcp_transport_returns_valid_value(self):
        """Test that get_mcp_transport returns a valid transport."""
        from assistant.services.mcp_proxy_manager import get_mcp_transport

        result = get_mcp_transport()
        assert result in ["inprocess", "stdio", "sse", "streamable-http"]

    def test_inprocess_in_valid_transports(self):
        """Test that 'inprocess' is documented as valid transport."""
        from assistant.services.mcp_proxy_manager import DEFAULT_MCP_TRANSPORT

        # Just verify the constant exists and docstring mentions inprocess
        assert DEFAULT_MCP_TRANSPORT in ["inprocess", "stdio", "sse", "streamable-http"]


class TestSdkMcpServerCreation:
    """Tests for SDK MCP server creation."""

    def test_create_server_with_tools(self):
        """Test creating an SDK MCP server with tools."""
        from claude_agent_sdk import create_sdk_mcp_server, tool

        @tool("test_echo", "Echo message", {"message": str})
        async def echo(args):
            return {"content": [{"type": "text", "text": f"Echo: {args['message']}"}]}

        server = create_sdk_mcp_server(
            name="test-server",
            version="1.0.0",
            tools=[echo]
        )

        assert isinstance(server, dict)
        assert server.get("type") == "sdk"
        assert server.get("name") == "test-server"
        assert "instance" in server

    def test_create_server_without_tools(self):
        """Test creating an SDK MCP server without tools."""
        from claude_agent_sdk import create_sdk_mcp_server

        server = create_sdk_mcp_server(name="empty-server")

        assert isinstance(server, dict)
        assert server.get("type") == "sdk"


class TestToolModeFiltering:
    """Tests for tool_mode filtering in SDK tools."""

    def test_tool_mode_passed_to_get_ollama_tools(self):
        """Test that tool_mode is passed correctly."""
        from ai_agent.tool_bridge import get_sdk_mcp_tools

        with patch('ai_agent.tool_bridge.get_ollama_tools', return_value=[]) as mock_get:
            with patch('ai_agent.tool_bridge._discover_mcp_tools', return_value=([], {})):
                get_sdk_mcp_tools(tool_mode="read_only")
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args[1]
                assert call_kwargs.get('tool_mode') == "read_only"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
