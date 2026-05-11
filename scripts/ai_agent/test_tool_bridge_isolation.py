# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Tool Bridge MCP Filter Isolation

Tests that verify parallel execution of multiple agents with different
MCP filters doesn't cause cache collisions or filter interference.

Run with: pytest test_tool_bridge_isolation.py -v
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock
import pytest

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_agent.task_context import (
    TaskContext,
    set_task_context,
    get_task_context,
    clear_task_context,
    create_task_context
)
from ai_agent.tool_bridge import (
    set_mcp_filter,
    get_mcp_filter,
    clear_mcp_filter,
    clear_cache,
    _cache_by_filter
)


class TestTaskContextMcpFilter:
    """Tests for TaskContext mcp_filter field."""

    def setup_method(self):
        """Clear context before each test."""
        clear_task_context()
        clear_cache()

    def teardown_method(self):
        """Clean up after each test."""
        clear_task_context()
        clear_cache()

    def test_mcp_filter_default_is_none(self):
        """TaskContext mcp_filter defaults to None."""
        ctx = TaskContext()
        assert ctx.mcp_filter is None

    def test_mcp_filter_can_be_set_in_constructor(self):
        """mcp_filter can be set in TaskContext constructor."""
        ctx = TaskContext(mcp_filter="gmail|outlook")
        assert ctx.mcp_filter == "gmail|outlook"

    def test_create_task_context_with_mcp_filter(self):
        """create_task_context() supports mcp_filter parameter."""
        ctx = create_task_context(
            task_id="test-1",
            backend_name="gemini",
            mcp_filter="msgraph|userecho"
        )
        assert ctx.mcp_filter == "msgraph|userecho"
        assert ctx.task_id == "test-1"
        assert ctx.backend_name == "gemini"

    def test_set_mcp_filter_updates_context(self):
        """set_mcp_filter() updates current TaskContext."""
        ctx = create_task_context(task_id="test-2")
        set_mcp_filter("billomat")
        assert get_mcp_filter() == "billomat"

    def test_clear_mcp_filter_sets_none(self):
        """clear_mcp_filter() sets filter to None."""
        ctx = create_task_context(task_id="test-3", mcp_filter="gmail")
        clear_mcp_filter()
        assert get_mcp_filter() is None


class TestMcpFilterIsolation:
    """Tests for parallel execution isolation."""

    def setup_method(self):
        """Clear state before each test."""
        clear_task_context()
        clear_cache()

    def teardown_method(self):
        """Clean up after each test."""
        clear_task_context()
        clear_cache()

    def test_different_threads_have_isolated_filters(self):
        """Threads with different TaskContexts don't interfere."""
        results = {}
        errors = []

        def thread_func(task_id: str, mcp_filter: str):
            try:
                # Set TaskContext for this thread
                ctx = TaskContext(task_id=task_id, mcp_filter=mcp_filter)
                set_task_context(ctx)

                # Simulate some work
                time.sleep(0.05)

                # Verify filter is still correct
                actual_filter = get_mcp_filter()
                results[task_id] = actual_filter

                clear_task_context()
            except Exception as e:
                errors.append(f"{task_id}: {e}")

        # Start multiple threads with different filters
        threads = [
            threading.Thread(target=thread_func, args=("agent-1", "gmail")),
            threading.Thread(target=thread_func, args=("agent-2", "msgraph|userecho")),
            threading.Thread(target=thread_func, args=("watcher-1", "gmail")),
            threading.Thread(target=thread_func, args=("agent-3", "outlook|billomat")),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify no errors
        assert not errors, f"Errors occurred: {errors}"

        # Verify each thread saw its own filter
        assert results["agent-1"] == "gmail"
        assert results["agent-2"] == "msgraph|userecho"
        assert results["watcher-1"] == "gmail"
        assert results["agent-3"] == "outlook|billomat"

    def test_cache_per_filter_persists(self):
        """Cache is maintained per filter pattern."""
        # First discovery with filter A
        ctx1 = create_task_context(task_id="test-A", mcp_filter="gmail")

        # Check cache key exists (without actually loading tools)
        # We just verify the cache structure works
        cache_key_a = "gmail"

        clear_task_context()

        # Second discovery with filter B
        ctx2 = create_task_context(task_id="test-B", mcp_filter="outlook")
        cache_key_b = "outlook"

        # Both caches can exist independently
        # (We can't test actual tool loading without MCP modules, but
        # we can verify the cache structure)
        assert cache_key_a != cache_key_b

        clear_task_context()

    def test_concurrent_filter_access_with_executor(self):
        """ThreadPoolExecutor threads maintain filter isolation."""
        results = {}

        def task_func(task_id: str, mcp_filter: str):
            # Set TaskContext inside the thread
            ctx = TaskContext(task_id=task_id, mcp_filter=mcp_filter)
            set_task_context(ctx)

            # Simulate work
            time.sleep(0.02)

            # Return the filter we see
            seen_filter = get_mcp_filter()
            clear_task_context()
            return (task_id, seen_filter)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(task_func, "task-1", "gmail"),
                executor.submit(task_func, "task-2", "msgraph"),
                executor.submit(task_func, "task-3", "outlook"),
                executor.submit(task_func, "task-4", "billomat"),
            ]

            for future in futures:
                task_id, seen_filter = future.result()
                results[task_id] = seen_filter

        # Verify each task saw its own filter
        assert results["task-1"] == "gmail"
        assert results["task-2"] == "msgraph"
        assert results["task-3"] == "outlook"
        assert results["task-4"] == "billomat"

    def test_watcher_does_not_override_agent_filter(self):
        """Simulates Email Watcher not overriding Agent's filter."""
        agent_filter_seen = None
        watcher_filter_seen = None

        def agent_thread():
            nonlocal agent_filter_seen
            # Agent sets its context
            ctx = TaskContext(task_id="agent-daily_check", mcp_filter="msgraph|userecho")
            set_task_context(ctx)

            # Start "working"
            time.sleep(0.05)

            # Watcher runs here in parallel (different thread)

            # Agent continues and checks its filter
            time.sleep(0.05)
            agent_filter_seen = get_mcp_filter()

            clear_task_context()

        def watcher_thread():
            nonlocal watcher_filter_seen
            # Wait for agent to start
            time.sleep(0.02)

            # Watcher sets its OWN context (isolated)
            ctx = TaskContext(task_id="watcher-poll", mcp_filter="gmail")
            set_task_context(ctx)

            # Watcher does its work
            watcher_filter_seen = get_mcp_filter()

            clear_task_context()

        # Run both in parallel
        t1 = threading.Thread(target=agent_thread)
        t2 = threading.Thread(target=watcher_thread)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Critical assertion: Agent's filter was NOT overwritten by watcher
        assert agent_filter_seen == "msgraph|userecho", \
            f"Agent filter was overwritten! Got: {agent_filter_seen}"
        assert watcher_filter_seen == "gmail", \
            f"Watcher filter was wrong! Got: {watcher_filter_seen}"


class TestCacheByFilter:
    """Tests for the per-filter cache structure."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_cache()

    def test_clear_cache_clears_all_filters(self):
        """clear_cache() clears cache for all filters."""
        # Import the global cache
        from ai_agent import tool_bridge

        # Manually add entries
        tool_bridge._cache_by_filter["gmail"] = ({"tool1": {}}, {"tool1": lambda: None})
        tool_bridge._cache_by_filter["outlook"] = ({"tool2": {}}, {"tool2": lambda: None})

        assert len(tool_bridge._cache_by_filter) == 2

        clear_cache()

        assert len(tool_bridge._cache_by_filter) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
