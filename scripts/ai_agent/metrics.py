# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Agent Metrics
=============
Performance tracking for AI agent executions.

This module provides the AgentMetrics class for collecting and summarizing
metrics during agent execution, including:
- AI turn counts (number of model calls)
- Tool call counts
- Efficiency ratios (tools per turn)
- Timing information
- Token usage tracking

Usage:
    metrics = AgentMetrics()
    metrics.start()
    # ... agent execution ...
    metrics.record_turn(tool_count=3, tokens_in=1000, tokens_out=500)
    metrics.stop()
    print(metrics.summary())
"""

import time

from .token_utils import format_tokens

__all__ = ["AgentMetrics"]


class AgentMetrics:
    """
    Tracks performance metrics for AI agents.

    Metrics tracked:
    - ai_turns: Number of AI model calls (roundtrips)
    - tool_calls: Number of MCP tool operations
    - efficiency: Tools per turn ratio (higher = more efficient)
    - duration_s: Total execution time
    - tokens_in/out: Token usage

    Example:
        >>> metrics = AgentMetrics()
        >>> metrics.start()
        >>> metrics.record_turn(tool_count=2, tokens_in=500, tokens_out=200)
        >>> metrics.record_turn(tool_count=1, tokens_in=300, tokens_out=100)
        >>> metrics.stop()
        >>> print(metrics.summary())
        AI Turns: 2 | Tool Calls: 3 | Efficiency: 1.5 tools/turn | ...
    """

    def __init__(self):
        """Initialize metrics with zero values."""
        self.ai_turns = 0
        self.tool_calls = 0
        self.start_time = None
        self.end_time = None
        self.tokens_in = 0
        self.tokens_out = 0
        self._turn_details = []  # List of {turn, tools, tokens_in, tokens_out}

    def start(self):
        """Start timing the agent execution."""
        self.start_time = time.time()

    def stop(self):
        """Stop timing the agent execution."""
        self.end_time = time.time()

    def record_turn(self, tool_count: int = 0, tokens_in: int = 0, tokens_out: int = 0):
        """
        Record an AI turn (one model call/response).

        Args:
            tool_count: Number of tools called in this turn
            tokens_in: Input tokens for this turn
            tokens_out: Output tokens for this turn
        """
        self.ai_turns += 1
        self.tool_calls += tool_count
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self._turn_details.append({
            "turn": self.ai_turns,
            "tools": tool_count,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out
        })

    @property
    def efficiency(self) -> float:
        """
        Calculate tools per turn ratio.

        Higher values indicate more efficient use of AI turns
        (more work done per model call).

        Returns:
            Tools per turn ratio, rounded to 2 decimal places
        """
        return round(self.tool_calls / self.ai_turns, 2) if self.ai_turns > 0 else 0

    @property
    def duration_s(self) -> float:
        """
        Get execution duration in seconds.

        Returns:
            Duration from start() to stop() (or current time if not stopped)
        """
        if self.start_time is None:
            return 0
        end = self.end_time or time.time()
        return round(end - self.start_time, 2)

    def to_dict(self) -> dict:
        """
        Convert metrics to dictionary for logging/display.

        Returns:
            Dict with all metric values including turn details
        """
        return {
            "ai_turns": self.ai_turns,
            "tool_calls": self.tool_calls,
            "efficiency": self.efficiency,
            "duration_s": self.duration_s,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "turn_details": self._turn_details
        }

    def summary(self) -> str:
        """
        Get a human-readable summary of metrics.

        Returns:
            Formatted string with key metrics
        """
        return (
            f"AI Turns: {self.ai_turns} | "
            f"Tool Calls: {self.tool_calls} | "
            f"Efficiency: {self.efficiency} tools/turn | "
            f"Duration: {self.duration_s}s | "
            f"Tokens: {format_tokens(self.tokens_in)} in / {format_tokens(self.tokens_out)} out"
        )

    def __repr__(self):
        """Return string representation for debugging."""
        return f"AgentMetrics({self.summary()})"
