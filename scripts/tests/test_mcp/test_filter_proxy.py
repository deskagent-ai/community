# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for MCP Filter Proxy (planfeature-008)

Tests the dynamic per-session tool filtering functionality:
- F1: Proxy filters tool-list based on session filter
- F2: Each session has its own allowed_mcp filter
- F3: Filter is applied on tools/list request
- F4: Parallel sessions with different filters possible
- F5: Fallback to all tools when no filter set
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add MCP directory to path for imports
MCP_DIR = Path(__file__).parent.parent.parent.parent / "mcp"
sys.path.insert(0, str(MCP_DIR))


class TestSessionFilterStorage:
    """Test session filter storage functions."""

    def test_register_session_filter(self):
        """F2: Each session has its own filter."""
        from mcp_filter_proxy import (
            register_session_filter,
            get_session_filter,
            clear_session_filter,
            _session_filters
        )

        # Clear any previous state
        _session_filters.clear()

        # Register filter for session A
        register_session_filter("session_A", "outlook|billomat")
        assert get_session_filter("session_A") == "outlook|billomat"

        # Register different filter for session B
        register_session_filter("session_B", "msgraph|userecho")
        assert get_session_filter("session_B") == "msgraph|userecho"

        # F4: Both sessions have their own filters
        assert get_session_filter("session_A") == "outlook|billomat"
        assert get_session_filter("session_B") == "msgraph|userecho"

        # Cleanup
        clear_session_filter("session_A")
        clear_session_filter("session_B")

    def test_get_session_filter_not_exists(self):
        """F5: Fallback to None when no filter set."""
        from mcp_filter_proxy import get_session_filter, _session_filters

        _session_filters.clear()

        # Unknown session returns None (fallback to all tools)
        assert get_session_filter("unknown_session") is None

    def test_clear_session_filter(self):
        """Session cleanup removes filter."""
        from mcp_filter_proxy import (
            register_session_filter,
            get_session_filter,
            clear_session_filter,
            _session_filters
        )

        _session_filters.clear()

        register_session_filter("test_session", "outlook")
        assert get_session_filter("test_session") == "outlook"

        clear_session_filter("test_session")
        assert get_session_filter("test_session") is None


class TestToolFiltering:
    """Test tool filtering logic."""

    def test_filter_tools_response_basic(self):
        """F1/F3: Filter tools/list response based on session filter."""
        from mcp_filter_proxy import (
            register_session_filter,
            filter_tools_response,
            _session_filters
        )

        _session_filters.clear()

        # Register filter for outlook only
        register_session_filter("test", "outlook")

        # Create mock tools/list response
        response = {
            "result": {
                "tools": [
                    {"name": "outlook_get_email", "description": "Get email"},
                    {"name": "outlook_send_email", "description": "Send email"},
                    {"name": "billomat_create_invoice", "description": "Create invoice"},
                    {"name": "msgraph_get_events", "description": "Get events"},
                ]
            }
        }
        response_bytes = json.dumps(response).encode()

        # Filter the response
        filtered_bytes = filter_tools_response("test", response_bytes)
        filtered = json.loads(filtered_bytes)

        # Only outlook tools should remain
        tool_names = [t["name"] for t in filtered["result"]["tools"]]
        assert "outlook_get_email" in tool_names
        assert "outlook_send_email" in tool_names
        assert "billomat_create_invoice" not in tool_names
        assert "msgraph_get_events" not in tool_names

    def test_filter_tools_multiple_mcps(self):
        """F1: Filter with regex pattern matching multiple MCPs."""
        from mcp_filter_proxy import (
            register_session_filter,
            filter_tools_response,
            _session_filters
        )

        _session_filters.clear()

        # Register filter for outlook OR billomat
        register_session_filter("test", "outlook|billomat")

        response = {
            "result": {
                "tools": [
                    {"name": "outlook_get_email", "description": "Get email"},
                    {"name": "billomat_create_invoice", "description": "Create invoice"},
                    {"name": "msgraph_get_events", "description": "Get events"},
                ]
            }
        }
        response_bytes = json.dumps(response).encode()

        filtered_bytes = filter_tools_response("test", response_bytes)
        filtered = json.loads(filtered_bytes)

        tool_names = [t["name"] for t in filtered["result"]["tools"]]
        assert "outlook_get_email" in tool_names
        assert "billomat_create_invoice" in tool_names
        assert "msgraph_get_events" not in tool_names

    def test_filter_tools_no_filter_returns_all(self):
        """F5: No filter means all tools returned."""
        from mcp_filter_proxy import filter_tools_response, _session_filters

        _session_filters.clear()

        response = {
            "result": {
                "tools": [
                    {"name": "outlook_get_email"},
                    {"name": "billomat_create_invoice"},
                ]
            }
        }
        response_bytes = json.dumps(response).encode()

        # Session without filter
        filtered_bytes = filter_tools_response("no_filter_session", response_bytes)

        # Should return original unchanged
        assert filtered_bytes == response_bytes

    def test_filter_preserves_proxy_tools(self):
        """F5 detail: proxy_* tools always allowed (system tools)."""
        from mcp_filter_proxy import (
            register_session_filter,
            filter_tools_response,
            _session_filters
        )

        _session_filters.clear()

        # Filter that doesn't include "proxy"
        register_session_filter("test", "outlook")

        response = {
            "result": {
                "tools": [
                    {"name": "outlook_get_email"},
                    {"name": "proxy_reset_context"},
                    {"name": "proxy_get_session_id"},
                    {"name": "billomat_create_invoice"},
                ]
            }
        }
        response_bytes = json.dumps(response).encode()

        filtered_bytes = filter_tools_response("test", response_bytes)
        filtered = json.loads(filtered_bytes)

        tool_names = [t["name"] for t in filtered["result"]["tools"]]

        # outlook and proxy tools should be present
        assert "outlook_get_email" in tool_names
        assert "proxy_reset_context" in tool_names
        assert "proxy_get_session_id" in tool_names
        # billomat should be filtered out
        assert "billomat_create_invoice" not in tool_names

    def test_filter_handles_graph_prefix(self):
        """Tools with graph_ prefix map to msgraph MCP."""
        from mcp_filter_proxy import (
            register_session_filter,
            filter_tools_response,
            _session_filters
        )

        _session_filters.clear()

        # Filter for msgraph
        register_session_filter("test", "msgraph")

        response = {
            "result": {
                "tools": [
                    {"name": "graph_get_email"},  # should match msgraph
                    {"name": "graph_send_email"},  # should match msgraph
                    {"name": "outlook_get_email"},  # should NOT match
                ]
            }
        }
        response_bytes = json.dumps(response).encode()

        filtered_bytes = filter_tools_response("test", response_bytes)
        filtered = json.loads(filtered_bytes)

        tool_names = [t["name"] for t in filtered["result"]["tools"]]

        # graph_* tools should be present (mapped to msgraph)
        assert "graph_get_email" in tool_names
        assert "graph_send_email" in tool_names
        # outlook should be filtered out
        assert "outlook_get_email" not in tool_names


class TestRequestDetection:
    """Test tools/list request detection."""

    def test_is_tools_list_request_true(self):
        """Detect tools/list JSON-RPC request."""
        from mcp_filter_proxy import is_tools_list_request

        body = json.dumps({"method": "tools/list", "id": 1}).encode()
        assert is_tools_list_request(body) is True

    def test_is_tools_list_request_false(self):
        """Non tools/list requests return False."""
        from mcp_filter_proxy import is_tools_list_request

        body = json.dumps({"method": "tools/call", "id": 1}).encode()
        assert is_tools_list_request(body) is False

        body = json.dumps({"method": "other", "id": 1}).encode()
        assert is_tools_list_request(body) is False

    def test_is_tools_list_request_invalid_json(self):
        """Invalid JSON returns False."""
        from mcp_filter_proxy import is_tools_list_request

        body = b"not json"
        assert is_tools_list_request(body) is False


class TestStaleSessionCleanup:
    """Test session TTL and cleanup."""

    def test_cleanup_stale_sessions(self):
        """Stale sessions are cleaned up after TTL."""
        import time
        from mcp_filter_proxy import (
            register_session_filter,
            get_session_filter,
            cleanup_stale_sessions,
            _session_filters,
            _session_last_access,
            SESSION_TTL_SECONDS
        )

        _session_filters.clear()
        _session_last_access.clear()

        # Register a session
        register_session_filter("stale_session", "outlook")
        assert get_session_filter("stale_session") == "outlook"

        # Artificially make it stale (older than TTL)
        _session_last_access["stale_session"] = time.time() - SESSION_TTL_SECONDS - 100

        # Run cleanup
        cleaned = cleanup_stale_sessions()

        assert cleaned == 1
        assert get_session_filter("stale_session") is None

    def test_fresh_sessions_not_cleaned(self):
        """Fresh sessions are not cleaned up."""
        from mcp_filter_proxy import (
            register_session_filter,
            get_session_filter,
            cleanup_stale_sessions,
            _session_filters,
            _session_last_access
        )

        _session_filters.clear()
        _session_last_access.clear()

        # Register a fresh session
        register_session_filter("fresh_session", "billomat")

        # Run cleanup - should not affect fresh session
        cleaned = cleanup_stale_sessions()

        assert cleaned == 0
        assert get_session_filter("fresh_session") == "billomat"


class TestParallelSessions:
    """Test parallel session support (F4)."""

    def test_parallel_sessions_different_filters(self):
        """F4: Multiple sessions with different filters work independently."""
        from mcp_filter_proxy import (
            register_session_filter,
            filter_tools_response,
            _session_filters
        )

        _session_filters.clear()

        # Two agents with different filters
        register_session_filter("agent_A", "msgraph|userecho")
        register_session_filter("agent_B", "billomat|sepa")

        # Same tool list for both
        response = {
            "result": {
                "tools": [
                    {"name": "msgraph_get_events"},
                    {"name": "userecho_get_tickets"},
                    {"name": "billomat_create_invoice"},
                    {"name": "sepa_generate_xml"},
                    {"name": "outlook_get_email"},
                ]
            }
        }
        response_bytes = json.dumps(response).encode()

        # Filter for Agent A
        filtered_A = json.loads(filter_tools_response("agent_A", response_bytes))
        tools_A = [t["name"] for t in filtered_A["result"]["tools"]]

        # Filter for Agent B
        filtered_B = json.loads(filter_tools_response("agent_B", response_bytes))
        tools_B = [t["name"] for t in filtered_B["result"]["tools"]]

        # Agent A sees msgraph and userecho
        assert "msgraph_get_events" in tools_A
        assert "userecho_get_tickets" in tools_A
        assert "billomat_create_invoice" not in tools_A
        assert "sepa_generate_xml" not in tools_A

        # Agent B sees billomat and sepa
        assert "billomat_create_invoice" in tools_B
        assert "sepa_generate_xml" in tools_B
        assert "msgraph_get_events" not in tools_B
        assert "userecho_get_tickets" not in tools_B


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
