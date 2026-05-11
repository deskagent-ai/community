# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for MCP Health Tracking Integration in tool_bridge.py
"""
import pytest
import sys
from pathlib import Path

# Add scripts path
scripts_path = Path(__file__).parent.parent.parent
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))

from ai_agent.mcp_health import get_tracker, MCPStatus


class TestMCPHealthIntegration:
    """Tests for MCP health tracking integration."""

    def setup_method(self):
        """Reset tracker before each test."""
        tracker = get_tracker()
        tracker.reset_all()

    def test_mark_healthy(self):
        """Test marking an MCP as healthy."""
        tracker = get_tracker()
        tracker.mark_healthy("test_mcp")

        status = tracker.get_status("test_mcp")
        assert status is not None
        assert status.status == MCPStatus.HEALTHY
        assert status.error_count == 0
        assert status.retry_count == 0

    def test_mark_failed_degraded(self):
        """Test that first failure marks MCP as degraded."""
        tracker = get_tracker()
        tracker.mark_failed("test_mcp", "connection error")

        status = tracker.get_status("test_mcp")
        assert status.status == MCPStatus.DEGRADED
        assert status.retry_count == 1
        assert status.last_error == "connection error"

    def test_mark_failed_permanent(self):
        """Test permanent failure (e.g., SyntaxError)."""
        tracker = get_tracker()
        tracker.mark_failed("test_mcp", "syntax error", permanent=True)

        status = tracker.get_status("test_mcp")
        assert status.status == MCPStatus.FAILED
        assert tracker.should_retry("test_mcp") is False

    def test_should_retry_healthy(self):
        """Test that healthy MCPs can retry (no-op)."""
        tracker = get_tracker()
        tracker.mark_healthy("test_mcp")

        assert tracker.should_retry("test_mcp") is True

    def test_should_retry_unknown(self):
        """Test that unknown MCPs can be tried."""
        tracker = get_tracker()
        # Never seen this MCP before
        assert tracker.should_retry("unknown_mcp") is True

    def test_should_retry_max_exceeded(self):
        """Test that MCPs exceeding max retries are skipped."""
        tracker = get_tracker()

        # Fail enough times to exceed max retries (default is 3)
        for i in range(4):
            tracker.mark_failed("test_mcp", f"error {i}")

        status = tracker.get_status("test_mcp")
        assert status.status == MCPStatus.FAILED
        assert tracker.should_retry("test_mcp") is False

    def test_recovery_after_success(self):
        """Test that MCP recovers after success."""
        tracker = get_tracker()

        # Fail a couple times
        tracker.mark_failed("test_mcp", "error 1")
        tracker.mark_failed("test_mcp", "error 2")

        status = tracker.get_status("test_mcp")
        assert status.status == MCPStatus.DEGRADED
        assert status.retry_count == 2

        # Now succeed
        tracker.mark_healthy("test_mcp")

        status = tracker.get_status("test_mcp")
        assert status.status == MCPStatus.HEALTHY
        assert status.retry_count == 0
        assert status.error_count == 0

    def test_import_in_tool_bridge(self):
        """Test that tool_bridge imports mcp_health correctly."""
        from ai_agent import tool_bridge

        # Check that get_tracker is imported
        assert hasattr(tool_bridge, 'get_tracker')

        # Check that it's the same tracker instance
        assert tool_bridge.get_tracker() is get_tracker()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
