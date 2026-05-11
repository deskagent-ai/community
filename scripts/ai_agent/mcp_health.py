# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Health Tracking Module
==========================
Tracks health status of MCP servers with retry logic and exponential backoff.

Classes:
- MCPStatus: Enum for health states (healthy, degraded, failed)
- MCPHealthStatus: Dataclass holding status details for one MCP
- MCPHealthTracker: Singleton tracker with thread-safe operations
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MCPStatus(Enum):
    """Health status of an MCP server."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class MCPHealthStatus:
    """Health status details for a single MCP server.

    Attributes:
        name: MCP server name (e.g., "outlook", "filesystem")
        status: Current health status
        last_error: Most recent error message, if any
        error_count: Total number of errors since last healthy state
        retry_count: Number of retry attempts since last success
        last_attempt: Timestamp of last connection/call attempt
        last_success: Timestamp of last successful operation
    """

    name: str
    status: MCPStatus = MCPStatus.HEALTHY
    last_error: Optional[str] = None
    error_count: int = 0
    retry_count: int = 0
    last_attempt: Optional[datetime] = None
    last_success: Optional[datetime] = None


class MCPHealthTracker:
    """Singleton tracker for MCP server health with thread-safe operations.

    Implements exponential backoff for retry logic and tracks health status
    across all MCP servers.

    Usage:
        tracker = MCPHealthTracker()
        tracker.mark_healthy("outlook")
        tracker.mark_failed("outlook", "Connection timeout")
        if tracker.should_retry("outlook"):
            # Attempt reconnection
    """

    _instance: Optional["MCPHealthTracker"] = None
    _initialized: bool = False

    # Configuration
    MAX_RETRIES: int = 3
    RETRY_DELAY_BASE: float = 1.0  # seconds
    RETRY_DELAY_MAX: float = 30.0  # seconds

    def __new__(cls) -> "MCPHealthTracker":
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the tracker (only once due to singleton)."""
        if MCPHealthTracker._initialized:
            return

        self._lock = threading.RLock()
        self._statuses: dict[str, MCPHealthStatus] = {}
        MCPHealthTracker._initialized = True

    def _get_or_create_status(self, mcp_name: str) -> MCPHealthStatus:
        """Get existing status or create new one for MCP.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            MCPHealthStatus for the given MCP
        """
        if mcp_name not in self._statuses:
            self._statuses[mcp_name] = MCPHealthStatus(name=mcp_name)
        return self._statuses[mcp_name]

    def mark_healthy(self, mcp_name: str) -> None:
        """Mark an MCP as healthy and reset error counters.

        Args:
            mcp_name: Name of the MCP server
        """
        with self._lock:
            status = self._get_or_create_status(mcp_name)
            status.status = MCPStatus.HEALTHY
            status.last_error = None
            status.error_count = 0
            status.retry_count = 0
            status.last_success = datetime.now()
            status.last_attempt = datetime.now()

    def mark_failed(
        self,
        mcp_name: str,
        error: str,
        permanent: bool = False
    ) -> None:
        """Mark an MCP as failed and increment retry counter.

        Args:
            mcp_name: Name of the MCP server
            error: Error message describing the failure
            permanent: If True, mark as FAILED immediately (no more retries)
        """
        with self._lock:
            status = self._get_or_create_status(mcp_name)
            status.last_error = error
            status.error_count += 1
            status.retry_count += 1
            status.last_attempt = datetime.now()

            if permanent or status.retry_count >= self.MAX_RETRIES:
                status.status = MCPStatus.FAILED
            else:
                status.status = MCPStatus.DEGRADED

    def should_retry(self, mcp_name: str) -> bool:
        """Check if retry is allowed based on retry count and backoff time.

        Implements exponential backoff: delay = min(base * 2^retry_count, max)

        Args:
            mcp_name: Name of the MCP server

        Returns:
            True if retry is allowed, False otherwise
        """
        with self._lock:
            status = self._statuses.get(mcp_name)

            # No status means never tried - allow
            if status is None:
                return True

            # Already healthy - no retry needed
            if status.status == MCPStatus.HEALTHY:
                return True

            # Max retries exceeded
            if status.retry_count >= self.MAX_RETRIES:
                return False

            # Check backoff time
            if status.last_attempt is None:
                return True

            delay = min(
                self.RETRY_DELAY_BASE * (2 ** status.retry_count),
                self.RETRY_DELAY_MAX
            )
            elapsed = (datetime.now() - status.last_attempt).total_seconds()

            return elapsed >= delay

    def get_status(self, mcp_name: str) -> Optional[MCPHealthStatus]:
        """Get the health status of a specific MCP.

        Args:
            mcp_name: Name of the MCP server

        Returns:
            MCPHealthStatus if tracked, None otherwise
        """
        with self._lock:
            return self._statuses.get(mcp_name)

    def get_all_statuses(self) -> dict[str, MCPHealthStatus]:
        """Get health status of all tracked MCPs.

        Returns:
            Dictionary mapping MCP names to their health status
        """
        with self._lock:
            return dict(self._statuses)

    def reset(self, mcp_name: str) -> None:
        """Reset the status of a specific MCP.

        Args:
            mcp_name: Name of the MCP server
        """
        with self._lock:
            if mcp_name in self._statuses:
                del self._statuses[mcp_name]

    def reset_all(self) -> None:
        """Reset the status of all MCPs."""
        with self._lock:
            self._statuses.clear()


# Module-level singleton instance for convenience
_tracker: Optional[MCPHealthTracker] = None


def get_tracker() -> MCPHealthTracker:
    """Get the global MCPHealthTracker instance.

    Returns:
        The singleton MCPHealthTracker instance
    """
    global _tracker
    if _tracker is None:
        _tracker = MCPHealthTracker()
    return _tracker
