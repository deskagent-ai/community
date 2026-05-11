# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Tests for MCP Health Tracking Module."""

import time
from datetime import datetime, timedelta

import pytest

from ai_agent.mcp_health import (
    MCPHealthStatus,
    MCPHealthTracker,
    MCPStatus,
    get_tracker,
)


class TestMCPStatus:
    """Tests for MCPStatus enum."""

    def test_status_values(self):
        """Test that all status values exist."""
        assert MCPStatus.HEALTHY.value == "healthy"
        assert MCPStatus.DEGRADED.value == "degraded"
        assert MCPStatus.FAILED.value == "failed"


class TestMCPHealthStatus:
    """Tests for MCPHealthStatus dataclass."""

    def test_default_values(self):
        """Test default values for new status."""
        status = MCPHealthStatus(name="test_mcp")

        assert status.name == "test_mcp"
        assert status.status == MCPStatus.HEALTHY
        assert status.last_error is None
        assert status.error_count == 0
        assert status.retry_count == 0
        assert status.last_attempt is None
        assert status.last_success is None

    def test_custom_values(self):
        """Test setting custom values."""
        now = datetime.now()
        status = MCPHealthStatus(
            name="test_mcp",
            status=MCPStatus.DEGRADED,
            last_error="Connection failed",
            error_count=3,
            retry_count=2,
            last_attempt=now,
            last_success=now,
        )

        assert status.status == MCPStatus.DEGRADED
        assert status.last_error == "Connection failed"
        assert status.error_count == 3
        assert status.retry_count == 2


class TestMCPHealthTracker:
    """Tests for MCPHealthTracker class."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh tracker for each test."""
        # Reset singleton for testing
        MCPHealthTracker._instance = None
        MCPHealthTracker._initialized = False
        tracker = MCPHealthTracker()
        tracker.reset_all()
        return tracker

    def test_singleton(self, tracker):
        """Test that tracker is a singleton."""
        tracker2 = MCPHealthTracker()
        assert tracker is tracker2

    def test_mark_healthy(self, tracker):
        """Test marking an MCP as healthy."""
        tracker.mark_healthy("outlook")
        status = tracker.get_status("outlook")

        assert status is not None
        assert status.status == MCPStatus.HEALTHY
        assert status.error_count == 0
        assert status.retry_count == 0
        assert status.last_success is not None
        assert status.last_attempt is not None

    def test_mark_failed_first_time(self, tracker):
        """Test marking an MCP as failed for the first time."""
        tracker.mark_failed("outlook", "Connection timeout")
        status = tracker.get_status("outlook")

        assert status is not None
        assert status.status == MCPStatus.DEGRADED  # Not FAILED yet
        assert status.last_error == "Connection timeout"
        assert status.error_count == 1
        assert status.retry_count == 1

    def test_mark_failed_reaches_max_retries(self, tracker):
        """Test that status becomes FAILED after MAX_RETRIES."""
        for i in range(tracker.MAX_RETRIES):
            tracker.mark_failed("outlook", f"Error {i}")

        status = tracker.get_status("outlook")
        assert status.status == MCPStatus.FAILED
        assert status.retry_count == tracker.MAX_RETRIES

    def test_mark_failed_permanent(self, tracker):
        """Test permanent failure flag."""
        tracker.mark_failed("outlook", "API key invalid", permanent=True)
        status = tracker.get_status("outlook")

        assert status.status == MCPStatus.FAILED

    def test_mark_healthy_resets_counters(self, tracker):
        """Test that mark_healthy resets all error counters."""
        # First fail a few times
        tracker.mark_failed("outlook", "Error 1")
        tracker.mark_failed("outlook", "Error 2")

        status = tracker.get_status("outlook")
        assert status.error_count == 2
        assert status.retry_count == 2

        # Then mark healthy
        tracker.mark_healthy("outlook")

        status = tracker.get_status("outlook")
        assert status.status == MCPStatus.HEALTHY
        assert status.error_count == 0
        assert status.retry_count == 0
        assert status.last_error is None

    def test_should_retry_new_mcp(self, tracker):
        """Test should_retry for unknown MCP."""
        assert tracker.should_retry("new_mcp") is True

    def test_should_retry_healthy(self, tracker):
        """Test should_retry for healthy MCP."""
        tracker.mark_healthy("outlook")
        assert tracker.should_retry("outlook") is True

    def test_should_retry_max_exceeded(self, tracker):
        """Test should_retry when max retries exceeded."""
        for _ in range(tracker.MAX_RETRIES):
            tracker.mark_failed("outlook", "Error")

        assert tracker.should_retry("outlook") is False

    def test_should_retry_backoff(self, tracker):
        """Test exponential backoff in should_retry."""
        # Override base delay for faster testing
        original_base = tracker.RETRY_DELAY_BASE
        tracker.RETRY_DELAY_BASE = 0.1  # 100ms

        try:
            tracker.mark_failed("outlook", "Error")

            # Immediately after failure, backoff should prevent retry
            # (delay = 0.1 * 2^1 = 0.2s)
            assert tracker.should_retry("outlook") is False

            # Wait for backoff
            time.sleep(0.25)
            assert tracker.should_retry("outlook") is True
        finally:
            tracker.RETRY_DELAY_BASE = original_base

    def test_get_status_unknown(self, tracker):
        """Test get_status for unknown MCP."""
        assert tracker.get_status("unknown_mcp") is None

    def test_get_all_statuses(self, tracker):
        """Test get_all_statuses."""
        tracker.mark_healthy("outlook")
        tracker.mark_failed("filesystem", "Permission denied")

        statuses = tracker.get_all_statuses()

        assert len(statuses) == 2
        assert "outlook" in statuses
        assert "filesystem" in statuses
        assert statuses["outlook"].status == MCPStatus.HEALTHY
        assert statuses["filesystem"].status == MCPStatus.DEGRADED

    def test_reset(self, tracker):
        """Test resetting a single MCP."""
        tracker.mark_healthy("outlook")
        tracker.mark_healthy("filesystem")

        tracker.reset("outlook")

        assert tracker.get_status("outlook") is None
        assert tracker.get_status("filesystem") is not None

    def test_reset_all(self, tracker):
        """Test resetting all MCPs."""
        tracker.mark_healthy("outlook")
        tracker.mark_healthy("filesystem")

        tracker.reset_all()

        assert tracker.get_status("outlook") is None
        assert tracker.get_status("filesystem") is None
        assert tracker.get_all_statuses() == {}


class TestGetTracker:
    """Tests for get_tracker function."""

    def test_get_tracker_returns_singleton(self):
        """Test that get_tracker returns singleton."""
        # Reset for clean test
        MCPHealthTracker._instance = None
        MCPHealthTracker._initialized = False

        import ai_agent.mcp_health as mcp_health_module
        mcp_health_module._tracker = None

        tracker1 = get_tracker()
        tracker2 = get_tracker()

        assert tracker1 is tracker2


class TestBackoffCalculation:
    """Tests for backoff calculation logic."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh tracker for each test."""
        MCPHealthTracker._instance = None
        MCPHealthTracker._initialized = False
        tracker = MCPHealthTracker()
        tracker.reset_all()
        return tracker

    def test_backoff_increases_exponentially(self, tracker):
        """Test that backoff delay increases with each retry."""
        # Retry 0: delay = 1.0 * 2^0 = 1.0s
        # Retry 1: delay = 1.0 * 2^1 = 2.0s
        # Retry 2: delay = 1.0 * 2^2 = 4.0s

        expected_delays = [1.0, 2.0, 4.0]

        for i, expected in enumerate(expected_delays):
            delay = min(
                tracker.RETRY_DELAY_BASE * (2 ** i),
                tracker.RETRY_DELAY_MAX
            )
            assert delay == expected

    def test_backoff_respects_max(self, tracker):
        """Test that backoff respects maximum delay."""
        # With high retry count, delay should be capped
        high_retry = 10
        delay = min(
            tracker.RETRY_DELAY_BASE * (2 ** high_retry),
            tracker.RETRY_DELAY_MAX
        )
        assert delay == tracker.RETRY_DELAY_MAX
