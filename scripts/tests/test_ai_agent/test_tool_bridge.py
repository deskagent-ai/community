# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for ai_agent.tool_bridge module.
Tests MCP tool discovery, execution, and schema conversion.
"""

import json
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestDiscoverMcpTools:
    """Tests for MCP tool discovery."""

    def test_discover_tools_from_mcp_files(self, tmp_path, monkeypatch):
        """Test discovering tools from MCP server files."""
        from ai_agent import tool_bridge

        # Create mock MCP directory with a simple server
        mcp_dir = tmp_path / "mcp"
        mcp_dir.mkdir()

        # Create a minimal MCP server file
        (mcp_dir / "test_mcp.py").write_text('''
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("test")

@mcp.tool()
def test_tool(param: str) -> str:
    """A test tool."""
    return f"Result: {param}"
''', encoding="utf-8")

        # Patch get_mcp_dir to return our temp mcp directory
        monkeypatch.setattr(tool_bridge, "get_mcp_dir", lambda: mcp_dir)

        # Note: Full discovery requires actually importing the module
        # This tests the file detection part
        mcp_files = list(mcp_dir.glob("*_mcp.py"))
        assert len(mcp_files) == 1
        assert mcp_files[0].name == "test_mcp.py"


class TestExecuteTool:
    """Tests for tool execution."""

    def test_execute_known_tool(self):
        """Test executing a known MCP tool."""
        from ai_agent import tool_bridge

        mock_tool = MagicMock(return_value="Tool executed")

        # Mock get_tool_function to return our mock tool
        with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
            result = tool_bridge.execute_tool('test_tool', {'param': 'value'})

            mock_tool.assert_called_once_with(param='value')
            assert result == "Tool executed"

    def test_execute_unknown_tool_returns_error(self):
        """Test that unknown tool returns error message."""
        from ai_agent import tool_bridge

        # Mock get_tool_function to return None (tool not found)
        with patch.object(tool_bridge, 'get_tool_function', return_value=None):
            result = tool_bridge.execute_tool('nonexistent_tool', {})

            assert "error" in result.lower() or "unknown" in result.lower()

    def test_execute_tool_with_exception(self):
        """Test handling of tool execution errors."""
        from ai_agent import tool_bridge

        def failing_tool(**kwargs):
            raise Exception("Tool crashed")

        with patch.object(tool_bridge, 'get_tool_function', return_value=failing_tool):
            result = tool_bridge.execute_tool('failing_tool', {})

            assert "error" in result.lower()


class TestToolParameters:
    """Tests for tool parameter handling."""

    def test_passes_dict_parameters(self):
        """Test passing dictionary parameters to tools."""
        from ai_agent import tool_bridge

        received_params = {}

        def capture_tool(**kwargs):
            received_params.update(kwargs)
            return "OK"

        with patch.object(tool_bridge, 'get_tool_function', return_value=capture_tool):
            tool_bridge.execute_tool('capture', {
                'name': 'Test',
                'count': 42,
                'enabled': True
            })

            assert received_params['name'] == 'Test'
            assert received_params['count'] == 42
            assert received_params['enabled'] is True

    def test_handles_empty_parameters(self):
        """Test executing tool with no parameters."""
        from ai_agent import tool_bridge

        mock_tool = MagicMock(return_value="No params needed")

        with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
            result = tool_bridge.execute_tool('no_params', {})

            mock_tool.assert_called_once_with()
            assert result == "No params needed"


class TestGetOllamaTools:
    """Tests for get_ollama_tools function."""

    def test_returns_list(self):
        """Test that get_ollama_tools returns a list."""
        from ai_agent import tool_bridge

        tools = tool_bridge.get_ollama_tools()
        assert isinstance(tools, list)


class TestListTools:
    """Tests for list_tools function."""

    def test_list_returns_tool_names(self):
        """Test that list_tools returns tool names."""
        from ai_agent import tool_bridge

        # Mock _discover_mcp_tools to return known tools
        mock_function_map = {'tool_a': lambda: None, 'tool_b': lambda: None}
        with patch.object(tool_bridge, '_discover_mcp_tools', return_value=([], mock_function_map)):
            tools = tool_bridge.list_tools()

            assert 'tool_a' in tools
            assert 'tool_b' in tools


class TestGetToolFunction:
    """Tests for get_tool_function."""

    def test_get_existing_function(self):
        """Test getting an existing tool function."""
        from ai_agent import tool_bridge

        def my_tool():
            return "result"

        mock_function_map = {'my_tool': my_tool}
        with patch.object(tool_bridge, '_discover_mcp_tools', return_value=([], mock_function_map)):
            func = tool_bridge.get_tool_function('my_tool')
            assert func is my_tool

    def test_get_nonexistent_function(self):
        """Test getting a non-existent tool function returns None."""
        from ai_agent import tool_bridge

        with patch.object(tool_bridge, '_discover_mcp_tools', return_value=([], {})):
            func = tool_bridge.get_tool_function('nonexistent_xyz')
            assert func is None


class TestToolResultFormatting:
    """Tests for tool result formatting."""

    def test_string_result_returned_as_is(self):
        """Test that string results are returned unchanged."""
        from ai_agent import tool_bridge

        mock_tool = MagicMock(return_value="Plain text result")

        with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
            result = tool_bridge.execute_tool('text_tool', {})

            assert result == "Plain text result"

    def test_dict_result_converted_to_string(self):
        """Test that dict results are converted to string representation."""
        from ai_agent import tool_bridge

        mock_tool = MagicMock(return_value={'key': 'value', 'count': 42})

        with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
            result = tool_bridge.execute_tool('dict_tool', {})

            # execute_tool uses str() to convert results
            assert isinstance(result, str)
            assert 'key' in result
            assert 'value' in result
            assert '42' in result

    def test_list_result_converted_to_string(self):
        """Test that list results are converted to string representation."""
        from ai_agent import tool_bridge

        mock_tool = MagicMock(return_value=['item1', 'item2', 'item3'])

        with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
            result = tool_bridge.execute_tool('list_tool', {})

            # execute_tool uses str() to convert results
            assert isinstance(result, str)
            assert 'item1' in result
            assert 'item2' in result
            assert 'item3' in result

    def test_none_result_returns_empty_string(self):
        """Test that None results return empty string."""
        from ai_agent import tool_bridge

        mock_tool = MagicMock(return_value=None)

        with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
            result = tool_bridge.execute_tool('none_tool', {})

            assert result == ""


class TestDryRunMode:
    """Tests for dry-run mode functionality."""

    def test_set_dry_run_mode_enables(self):
        """Test that set_dry_run_mode(True) enables dry-run mode."""
        from ai_agent import tool_bridge

        # Ensure clean state
        tool_bridge.clear_dry_run()

        # Enable dry-run
        tool_bridge.set_dry_run_mode(True)

        # Get internal state via get_simulated_actions (which returns empty list when enabled)
        actions = tool_bridge.get_simulated_actions()
        assert isinstance(actions, list)
        assert len(actions) == 0  # No actions simulated yet

        # Cleanup
        tool_bridge.clear_dry_run()

    def test_set_dry_run_mode_disables(self):
        """Test that set_dry_run_mode(False) disables dry-run mode."""
        from ai_agent import tool_bridge

        # Enable then disable
        tool_bridge.set_dry_run_mode(True)
        tool_bridge.set_dry_run_mode(False)

        # Actions should be cleared
        actions = tool_bridge.get_simulated_actions()
        assert len(actions) == 0

    def test_clear_dry_run_resets_state(self):
        """Test that clear_dry_run() resets all dry-run state."""
        from ai_agent import tool_bridge

        # Enable dry-run
        tool_bridge.set_dry_run_mode(True)

        # Clear
        tool_bridge.clear_dry_run()

        # Should be cleared
        actions = tool_bridge.get_simulated_actions()
        assert len(actions) == 0

    def test_get_destructive_tools_returns_set(self):
        """Test that get_destructive_tools returns the dynamically discovered set.

        Note: Destructive tools are now dynamically discovered from MCP modules
        that define DESTRUCTIVE_TOOLS sets. This test verifies the accessor function
        returns a set (actual contents depend on MCP discovery).
        """
        from ai_agent import tool_bridge

        # The function should return a set
        destructive = tool_bridge.get_destructive_tools()
        assert isinstance(destructive, set)

        # It returns a copy (not the internal set)
        destructive.add("test_tool")
        assert "test_tool" not in tool_bridge.get_destructive_tools()

    def test_dry_run_simulates_destructive_tool(self):
        """Test that destructive tools are simulated in dry-run mode."""
        from ai_agent import tool_bridge

        # Enable dry-run
        tool_bridge.set_dry_run_mode(True)

        try:
            # Execute a tool that's in DRY_RUN_SIMULATE
            # We need to mock the get_tool_function to return something
            # but the execute_tool should intercept it in dry-run mode
            mock_tool = MagicMock(return_value="Should not be called")

            # Add the tool to _destructive_tools so dry-run mode intercepts it
            # (normally populated by MCP discovery, but we're mocking that)
            tool_bridge._destructive_tools.add('outlook_move_email')

            with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
                result = tool_bridge.execute_tool('outlook_move_email', {
                    'entry_id': 'test123',
                    'folder': 'ToDelete'
                })

                # In dry-run mode, the actual tool should NOT be called
                # Instead, it should return a simulated response
                assert isinstance(result, str)
                assert "simulated" in result.lower() or "dry-run" in result.lower() or "success" in result.lower()

                # Get simulated actions
                actions = tool_bridge.get_simulated_actions()
                assert len(actions) > 0
                assert actions[0]["tool"] == "outlook_move_email"

        finally:
            tool_bridge.clear_dry_run()
            tool_bridge._destructive_tools.discard('outlook_move_email')

    def test_dry_run_does_not_affect_read_tools(self):
        """Test that read-only tools still execute normally in dry-run mode."""
        from ai_agent import tool_bridge

        # Enable dry-run
        tool_bridge.set_dry_run_mode(True)

        try:
            # Execute a read tool (not in DRY_RUN_SIMULATE)
            mock_tool = MagicMock(return_value="Read result from tool")

            with patch.object(tool_bridge, 'get_tool_function', return_value=mock_tool):
                result = tool_bridge.execute_tool('outlook_get_selected_email', {})

                # The actual tool SHOULD be called for read operations
                mock_tool.assert_called_once()
                assert result == "Read result from tool"

        finally:
            tool_bridge.clear_dry_run()


class TestGetSimulatedActions:
    """Tests for get_simulated_actions function."""

    def test_returns_empty_list_when_disabled(self):
        """Test that get_simulated_actions returns empty list when dry-run is disabled."""
        from ai_agent import tool_bridge

        tool_bridge.clear_dry_run()
        actions = tool_bridge.get_simulated_actions()

        assert isinstance(actions, list)
        assert len(actions) == 0

    def test_returns_list(self):
        """Test that get_simulated_actions returns a list."""
        from ai_agent import tool_bridge

        tool_bridge.set_dry_run_mode(True)
        try:
            actions = tool_bridge.get_simulated_actions()
            assert isinstance(actions, list)
        finally:
            tool_bridge.clear_dry_run()


class TestDeanonymizeSdkArgs:
    """Tests for SDK tool argument de-anonymization (plan-080)."""

    def _make_anon_context(self, mappings=None, reverse_mappings=None, counters=None):
        """Create a mock AnonymizationContext."""
        from dataclasses import dataclass, field

        @dataclass
        class MockAnonymizationContext:
            mappings: dict = field(default_factory=dict)
            reverse_mappings: dict = field(default_factory=dict)
            counters: dict = field(default_factory=dict)

        return MockAnonymizationContext(
            mappings=mappings or {},
            reverse_mappings=reverse_mappings or {},
            counters=counters or {}
        )

    def test_deanonymize_from_seeded_cache(self):
        """Test de-anonymization using in-memory seeded cache (core fix)."""
        from ai_agent.tool_bridge import (
            seed_sdk_anon_context, _deanonymize_sdk_args, _clear_sdk_anon_context
        )

        ctx = self._make_anon_context(
            mappings={"<ORGANIZATION_3>": "Acme GmbH", "<LOCATION_4>": "Berlin"},
            reverse_mappings={"Acme GmbH": "<ORGANIZATION_3>", "Berlin": "<LOCATION_4>"},
            counters={"ORGANIZATION": 3, "LOCATION": 4}
        )

        try:
            seed_sdk_anon_context("test-080-1", ctx)
            args = {"name": "<ORGANIZATION_3>", "city": "<LOCATION_4>"}
            result = _deanonymize_sdk_args(args, "test-080-1")
            assert result["name"] == "Acme GmbH"
            assert result["city"] == "Berlin"
        finally:
            _clear_sdk_anon_context("test-080-1")

    def test_seed_copies_mappings_correctly(self):
        """Test that seed_sdk_anon_context copies all mapping fields."""
        from ai_agent.tool_bridge import (
            seed_sdk_anon_context, _get_sdk_anon_context, _clear_sdk_anon_context
        )

        ctx = self._make_anon_context(
            mappings={"<PERSON_1>": "Max Mustermann"},
            reverse_mappings={"Max Mustermann": "<PERSON_1>"},
            counters={"PERSON": 1}
        )

        try:
            seed_sdk_anon_context("test-080-2", ctx)
            cached = _get_sdk_anon_context("test-080-2")
            assert cached.mappings == {"<PERSON_1>": "Max Mustermann"}
            assert cached.reverse_mappings == {"Max Mustermann": "<PERSON_1>"}
            assert cached.counters == {"PERSON": 1}
        finally:
            _clear_sdk_anon_context("test-080-2")

    def test_prompt_mappings_persist_after_result_anon(self):
        """Test that prompt mappings remain after _anonymize_sdk_result adds new ones."""
        from ai_agent.tool_bridge import (
            seed_sdk_anon_context, _get_sdk_anon_context, _clear_sdk_anon_context
        )

        ctx = self._make_anon_context(
            mappings={"<PERSON_1>": "Max Mustermann"},
            reverse_mappings={"Max Mustermann": "<PERSON_1>"},
            counters={"PERSON": 1}
        )

        try:
            seed_sdk_anon_context("test-080-3", ctx)
            # Simulate what _anonymize_sdk_result does: add new mappings
            cached = _get_sdk_anon_context("test-080-3")
            cached.mappings["<EMAIL_1>"] = "max@example.com"
            cached.reverse_mappings["max@example.com"] = "<EMAIL_1>"

            # Original prompt mappings must still be there
            assert "<PERSON_1>" in cached.mappings
            assert cached.mappings["<PERSON_1>"] == "Max Mustermann"
            # New mappings also present
            assert "<EMAIL_1>" in cached.mappings
        finally:
            _clear_sdk_anon_context("test-080-3")

    def test_file_fallback_still_works(self, tmp_path, monkeypatch):
        """Test that file-based fallback works for HTTP-Proxy compat (regression)."""
        import json
        from ai_agent.tool_bridge import _deanonymize_sdk_args, _sdk_anon_contexts

        # Ensure no cache entry exists for this session
        session_id = "test-080-file-fallback"
        _sdk_anon_contexts.pop(session_id, None)

        # Create mock .logs dir and .temp dir
        logs_dir = tmp_path / ".logs"
        logs_dir.mkdir()
        temp_dir = tmp_path / ".temp"
        temp_dir.mkdir()
        mappings = {"<PERSON_5>": "Anna Schmidt"}
        (temp_dir / f"anon_mappings_{session_id}.json").write_text(
            json.dumps(mappings), encoding="utf-8"
        )

        # Patch paths.get_logs_dir (lazy import inside _deanonymize_sdk_args)
        import paths
        monkeypatch.setattr(paths, "get_logs_dir", lambda: logs_dir)

        args = {"recipient": "<PERSON_5>"}
        result = _deanonymize_sdk_args(args, session_id)
        assert result["recipient"] == "Anna Schmidt"

    def test_empty_anon_context_no_seeding(self):
        """Test that empty anon_context does not seed anything."""
        from ai_agent.tool_bridge import (
            seed_sdk_anon_context, _sdk_anon_contexts, _clear_sdk_anon_context
        )

        session_id = "test-080-empty"
        _sdk_anon_contexts.pop(session_id, None)

        # Empty context - should not seed
        ctx = self._make_anon_context(mappings={})
        seed_sdk_anon_context(session_id, ctx)

        # Session should not be in cache (no mappings to seed)
        assert session_id not in _sdk_anon_contexts

    def test_deanonymize_nested_dicts_and_lists(self):
        """Test de-anonymization in nested dicts and lists (review edge case)."""
        from ai_agent.tool_bridge import (
            seed_sdk_anon_context, _deanonymize_sdk_args, _clear_sdk_anon_context
        )

        ctx = self._make_anon_context(
            mappings={"<PERSON_1>": "Max", "<ORGANIZATION_2>": "Acme"},
            reverse_mappings={"Max": "<PERSON_1>", "Acme": "<ORGANIZATION_2>"}
        )

        try:
            seed_sdk_anon_context("test-080-nested", ctx)
            args = {
                "items": [
                    {"name": "<PERSON_1>", "company": "<ORGANIZATION_2>"},
                    {"name": "<PERSON_1>"}
                ],
                "tags": ["<ORGANIZATION_2>", "other"]
            }
            result = _deanonymize_sdk_args(args, "test-080-nested")
            assert result["items"][0]["name"] == "Max"
            assert result["items"][0]["company"] == "Acme"
            assert result["items"][1]["name"] == "Max"
            assert result["tags"][0] == "Acme"
            assert result["tags"][1] == "other"
        finally:
            _clear_sdk_anon_context("test-080-nested")

    def test_resume_session_with_existing_cache(self):
        """Test seeding when session already has cached context (review edge case)."""
        from ai_agent.tool_bridge import (
            seed_sdk_anon_context, _get_sdk_anon_context, _clear_sdk_anon_context
        )

        session_id = "test-080-resume"

        try:
            # Pre-existing context (from earlier tool-result anonymization)
            existing = _get_sdk_anon_context(session_id)
            existing.mappings["<EMAIL_1>"] = "test@example.com"

            # Now seed with prompt mappings (should merge, not replace)
            ctx = self._make_anon_context(
                mappings={"<PERSON_1>": "Max"},
                counters={"PERSON": 1}
            )
            seed_sdk_anon_context(session_id, ctx)

            cached = _get_sdk_anon_context(session_id)
            assert cached.mappings["<PERSON_1>"] == "Max"
            assert cached.mappings["<EMAIL_1>"] == "test@example.com"
        finally:
            _clear_sdk_anon_context(session_id)


class TestApplyDeanonMappings:
    """Tests for _apply_deanon_mappings helper function (plan-080)."""

    def test_simple_string_replacement(self):
        """Test basic placeholder replacement in strings."""
        from ai_agent.tool_bridge import _apply_deanon_mappings

        mappings = {"<PERSON_1>": "Max Mustermann"}
        result = _apply_deanon_mappings({"name": "<PERSON_1>"}, mappings)
        assert result["name"] == "Max Mustermann"

    def test_no_placeholders_unchanged(self):
        """Test that args without placeholders pass through unchanged."""
        from ai_agent.tool_bridge import _apply_deanon_mappings

        mappings = {"<PERSON_1>": "Max"}
        result = _apply_deanon_mappings({"query": "normal text"}, mappings)
        assert result["query"] == "normal text"

    def test_non_string_values_unchanged(self):
        """Test that numeric/bool values pass through unchanged."""
        from ai_agent.tool_bridge import _apply_deanon_mappings

        mappings = {"<PERSON_1>": "Max"}
        result = _apply_deanon_mappings({"count": 42, "active": True}, mappings)
        assert result["count"] == 42
        assert result["active"] is True


class TestPythonTypeToJsonSchema:
    """Tests for _python_type_to_json_schema type conversion (plan-050)."""

    def test_list_dict_conversion(self):
        """list[dict] must convert to array with object items."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[dict])
        assert result == {"type": "array", "items": {"type": "object"}}

    def test_list_list_conversion(self):
        """list[list] must convert to array with array items (with default string items)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[list])
        # Bare list recurses to get default items, ensuring Gemini compatibility
        assert result == {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}

    def test_list_list_str_recursive(self):
        """list[list[str]] must recursively produce nested array/array/string."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[list[str]])
        assert result == {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"}
            }
        }

    def test_list_str_unchanged(self):
        """list[str] must still work correctly (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[str])
        assert result == {"type": "array", "items": {"type": "string"}}

    def test_list_int_unchanged(self):
        """list[int] must still work correctly (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[int])
        assert result == {"type": "array", "items": {"type": "integer"}}

    def test_list_float_unchanged(self):
        """list[float] must still work correctly (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[float])
        assert result == {"type": "array", "items": {"type": "number"}}

    def test_list_bool_unchanged(self):
        """list[bool] must still work correctly (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(list[bool])
        assert result == {"type": "array", "items": {"type": "boolean"}}

    def test_simple_str(self):
        """str must convert to string (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(str)
        assert result == {"type": "string"}

    def test_simple_dict(self):
        """dict must convert to object (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(dict)
        assert result == {"type": "object"}

    def test_recursion_depth_limit(self):
        """Deeply nested types must not cause infinite recursion."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        # Simulate a deeply nested type by calling with high depth
        result = _python_type_to_json_schema(str, depth=11)
        assert result == {"type": "string"}  # Fallback at depth > 10

    def test_none_type(self):
        """None type must return string (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(None)
        assert result == {"type": "string"}

    def test_optional_str(self):
        """Optional[str] must convert to string (regression test)."""
        from ai_agent.tool_bridge import _python_type_to_json_schema

        result = _python_type_to_json_schema(str | None)
        assert result["type"] == "string"


class TestIsComplexParam:
    """Tests for _is_complex_param helper function (plan-050)."""

    def test_array_of_objects(self):
        """Array with object items is complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "array", "items": {"type": "object"}}
        assert _is_complex_param(param_def) is True

    def test_array_of_arrays(self):
        """Array with array items is complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "array", "items": {"type": "array"}}
        assert _is_complex_param(param_def) is True

    def test_array_of_strings_is_simple(self):
        """Array with string items is not complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "array", "items": {"type": "string"}}
        assert _is_complex_param(param_def) is False

    def test_array_without_items_is_simple(self):
        """Array without items definition is not complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "array"}
        assert _is_complex_param(param_def) is False

    def test_object_with_properties_is_complex(self):
        """Object with properties is complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "object", "properties": {"name": {"type": "string"}}}
        assert _is_complex_param(param_def) is True

    def test_object_without_properties_is_simple(self):
        """Object without properties is not complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "object"}
        assert _is_complex_param(param_def) is False

    def test_string_is_simple(self):
        """String type is not complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "string"}
        assert _is_complex_param(param_def) is False

    def test_integer_is_simple(self):
        """Integer type is not complex."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "integer"}
        assert _is_complex_param(param_def) is False

    def test_defensive_items_without_type(self):
        """Items dict without 'type' key must not crash."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "array", "items": {"description": "unknown"}}
        assert _is_complex_param(param_def) is False

    def test_defensive_items_not_dict(self):
        """Non-dict items value must not crash."""
        from ai_agent.tool_bridge import _is_complex_param

        param_def = {"type": "array", "items": "string"}
        assert _is_complex_param(param_def) is False

    def test_empty_param_def(self):
        """Empty param definition must not crash."""
        from ai_agent.tool_bridge import _is_complex_param

        assert _is_complex_param({}) is False


class TestConvertParamsToSdkSchema:
    """Tests for _convert_params_to_sdk_schema (plan-050)."""

    def test_simple_params_unchanged(self):
        """Simple parameter types produce simplified Python type mapping."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "enabled": {"type": "boolean"}
            },
            "required": ["name"]
        }
        result = _convert_params_to_sdk_schema(schema)
        assert result == {"name": str, "count": int, "enabled": bool}

    def test_complex_params_passthrough(self):
        """Complex parameter types pass through full JSON Schema."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        schema = {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "datasets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "data": {"type": "array", "items": {"type": "number"}}
                        }
                    }
                }
            },
            "required": ["chart_type", "labels", "datasets"]
        }
        result = _convert_params_to_sdk_schema(schema)
        # Full JSON Schema must be returned (has "properties" key)
        assert "properties" in result
        assert "datasets" in result["properties"]

    def test_array_of_arrays_triggers_passthrough(self):
        """list[list] parameter triggers full JSON Schema passthrough."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        schema = {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {"type": "array"}
                }
            }
        }
        result = _convert_params_to_sdk_schema(schema)
        assert "properties" in result

    def test_empty_properties(self):
        """Empty properties produce empty result."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        result = _convert_params_to_sdk_schema({"type": "object", "properties": {}})
        assert result == {}

    def test_no_properties_key(self):
        """Missing properties key produces empty result."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        result = _convert_params_to_sdk_schema({"type": "object"})
        assert result == {}

    def test_mixed_simple_and_array(self):
        """Mix of simple types and simple array stays simplified."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer"}
            }
        }
        result = _convert_params_to_sdk_schema(schema)
        # All simple types, no passthrough
        assert result == {"title": str, "tags": list, "count": int}

    def test_object_with_properties_triggers_passthrough(self):
        """Object param with properties triggers full JSON Schema."""
        from ai_agent.tool_bridge import _convert_params_to_sdk_schema

        schema = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {
                        "responsive": {"type": "boolean"}
                    }
                }
            }
        }
        result = _convert_params_to_sdk_schema(schema)
        assert "properties" in result
