# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for ai_agent.dev_context module.
Tests task-keyed DevContext storage for parallel execution isolation.

Planfeature-034: Fix Parallel DevContext Mixing
"""

import asyncio
import sys
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestDevContextBasics:
    """Tests for basic DevContext functionality."""

    def setup_method(self):
        """Clear state before each test."""
        from ai_agent.dev_context import _dev_contexts, _dev_contexts_lock
        with _dev_contexts_lock:
            _dev_contexts.clear()

    def test_reset_creates_empty_context(self):
        """Reset erzeugt leeren Context mit korrekten Defaults."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, get_dev_context

        try:
            create_task_context(task_id="test-reset")
            reset_dev_context()

            ctx = get_dev_context()
            assert ctx["system_prompt"] == ""
            assert ctx["user_prompt"] == ""
            assert ctx["tool_results"] == []
            assert ctx["model"] == ""
            assert ctx["timestamp"] is not None
            assert ctx["iteration"] == 0
            assert ctx["max_iterations"] == 0
            assert ctx["anonymization"] == {}
        finally:
            clear_task_context()

    def test_add_tool_result(self):
        """Tool-Result wird korrekt hinzugefuegt."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        try:
            create_task_context(task_id="test-tool")
            reset_dev_context()

            add_dev_tool_result(
                tool_name="outlook_get_selected_email",
                result="Email content here...",
                anon_count=2,
                args={"entry_id": "abc123"}
            )

            ctx = get_dev_context()
            assert len(ctx["tool_results"]) == 1
            tr = ctx["tool_results"][0]
            assert tr["tool"] == "outlook_get_selected_email"
            assert tr["result"] == "Email content here..."
            assert tr["anon_count"] == 2
            assert tr["args"]["entry_id"] == "abc123"
        finally:
            clear_task_context()

    def test_add_tool_result_truncates_long_results(self):
        """Lange Tool-Results werden auf 10000 Zeichen gekuerzt."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        try:
            create_task_context(task_id="test-truncate")
            reset_dev_context()

            long_result = "x" * 20000
            add_dev_tool_result(tool_name="test_tool", result=long_result)

            ctx = get_dev_context()
            assert len(ctx["tool_results"][0]["result"]) == 10000
        finally:
            clear_task_context()

    def test_capture_prompts(self):
        """System/User-Prompt und Model werden gespeichert."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, capture_dev_context, get_dev_context

        try:
            create_task_context(task_id="test-capture")
            reset_dev_context()

            capture_dev_context(
                system_prompt="You are a helpful assistant.",
                user_prompt="What is the weather?",
                model="claude-sonnet-4-5-20250514"
            )

            ctx = get_dev_context()
            assert ctx["system_prompt"] == "You are a helpful assistant."
            assert ctx["user_prompt"] == "What is the weather?"
            assert ctx["model"] == "claude-sonnet-4-5-20250514"
            assert ctx["timestamp"] is not None
        finally:
            clear_task_context()

    def test_capture_partial_update(self):
        """capture_dev_context aktualisiert nur uebergebene Felder."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, capture_dev_context, get_dev_context

        try:
            create_task_context(task_id="test-partial")
            reset_dev_context()

            capture_dev_context(system_prompt="System prompt")
            capture_dev_context(model="gpt-4")

            ctx = get_dev_context()
            assert ctx["system_prompt"] == "System prompt"
            assert ctx["model"] == "gpt-4"
            assert ctx["user_prompt"] == ""  # Not changed
        finally:
            clear_task_context()

    def test_get_returns_copy(self):
        """get_dev_context() gibt Kopie zurueck (kein Aliasing)."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, get_dev_context

        try:
            create_task_context(task_id="test-copy")
            reset_dev_context()

            ctx1 = get_dev_context()
            ctx1["system_prompt"] = "Modified externally"

            ctx2 = get_dev_context()
            assert ctx2["system_prompt"] == ""  # Original unchanged
        finally:
            clear_task_context()

    def test_update_iteration(self):
        """Iteration/Max-Iteration werden gespeichert."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, update_dev_iteration, get_dev_context

        try:
            create_task_context(task_id="test-iter")
            reset_dev_context()

            update_dev_iteration(3, 10)

            ctx = get_dev_context()
            assert ctx["iteration"] == 3
            assert ctx["max_iterations"] == 10
        finally:
            clear_task_context()

    def test_set_anonymization(self):
        """Anonymisierungs-Mappings werden gespeichert."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, set_dev_anonymization, get_dev_context

        try:
            create_task_context(task_id="test-anon")
            reset_dev_context()

            mappings = {"[PERSON_1]": "John Doe", "[EMAIL_1]": "john@example.com"}
            set_dev_anonymization(mappings)

            ctx = get_dev_context()
            assert ctx["anonymization"] == mappings
        finally:
            clear_task_context()

    def test_set_anonymization_none(self):
        """set_dev_anonymization mit None setzt leeres Dict."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, set_dev_anonymization, get_dev_context

        try:
            create_task_context(task_id="test-anon-none")
            reset_dev_context()

            set_dev_anonymization(None)

            ctx = get_dev_context()
            assert ctx["anonymization"] == {}
        finally:
            clear_task_context()


class TestParallelIsolation:
    """Parallel-Isolation-Tests (Kern-Bug Fix)."""

    def setup_method(self):
        """Clear state before each test."""
        from ai_agent.dev_context import _dev_contexts, _dev_contexts_lock
        with _dev_contexts_lock:
            _dev_contexts.clear()

    @pytest.mark.asyncio
    async def test_parallel_tool_results_isolation(self):
        """Zwei asyncio Tasks, jeder fuegt eigene Tools hinzu - keine Vermischung."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        results = {"daily_check": None, "ask_sap": None}

        async def daily_check_task():
            create_task_context(task_id="task-2")
            reset_dev_context()

            add_dev_tool_result("graph_get_flagged_emails", "emails...", args={"folder": "Inbox"})
            await asyncio.sleep(0.01)  # Allow interleaving
            add_dev_tool_result("userecho_get_recent_new_tickets", "tickets...", args={})

            results["daily_check"] = get_dev_context()
            clear_task_context()

        async def ask_sap_task():
            create_task_context(task_id="task-4")
            reset_dev_context()

            add_dev_tool_result("sap_get_billing_documents", "docs...", args={"year": 2026})
            await asyncio.sleep(0.01)  # Allow interleaving
            add_dev_tool_result("chart_create", "chart data...", args={"type": "bar"})

            results["ask_sap"] = get_dev_context()
            clear_task_context()

        await asyncio.gather(daily_check_task(), ask_sap_task())

        # daily_check should only have its own tools
        dc_tools = [tr["tool"] for tr in results["daily_check"]["tool_results"]]
        assert dc_tools == ["graph_get_flagged_emails", "userecho_get_recent_new_tickets"]
        assert "sap_get_billing_documents" not in dc_tools
        assert "chart_create" not in dc_tools

        # ask_sap should only have its own tools
        sap_tools = [tr["tool"] for tr in results["ask_sap"]["tool_results"]]
        assert sap_tools == ["sap_get_billing_documents", "chart_create"]
        assert "graph_get_flagged_emails" not in sap_tools
        assert "userecho_get_recent_new_tickets" not in sap_tools

    @pytest.mark.asyncio
    async def test_parallel_reset_isolation(self):
        """Reset in Task B loescht Task A's Context nicht."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        results = {"task_a": None}

        async def task_a():
            create_task_context(task_id="task-a")
            reset_dev_context()
            add_dev_tool_result("tool_a1", "result_a1")
            add_dev_tool_result("tool_a2", "result_a2")

            # Wait for task_b to reset its context
            await asyncio.sleep(0.05)

            # Task A's tools should still be here
            results["task_a"] = get_dev_context()
            clear_task_context()

        async def task_b():
            await asyncio.sleep(0.01)  # Start after task_a has added tools
            create_task_context(task_id="task-b")
            reset_dev_context()  # This should NOT affect task_a
            clear_task_context()

        await asyncio.gather(task_a(), task_b())

        # Task A should still have its 2 tools after Task B's reset
        assert len(results["task_a"]["tool_results"]) == 2
        tools = [tr["tool"] for tr in results["task_a"]["tool_results"]]
        assert tools == ["tool_a1", "tool_a2"]

    @pytest.mark.asyncio
    async def test_parallel_capture_isolation(self):
        """Prompts/Model sind pro Task isoliert."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, capture_dev_context, get_dev_context

        results = {"gemini": None, "claude": None}

        async def gemini_task():
            create_task_context(task_id="gemini-task")
            reset_dev_context()
            capture_dev_context(
                system_prompt="Gemini system prompt",
                user_prompt="Gemini user prompt",
                model="gemini-2.5-pro"
            )
            await asyncio.sleep(0.01)
            results["gemini"] = get_dev_context()
            clear_task_context()

        async def claude_task():
            create_task_context(task_id="claude-task")
            reset_dev_context()
            capture_dev_context(
                system_prompt="Claude system prompt",
                user_prompt="Claude user prompt",
                model="claude-sonnet-4-5-20250514"
            )
            await asyncio.sleep(0.01)
            results["claude"] = get_dev_context()
            clear_task_context()

        await asyncio.gather(gemini_task(), claude_task())

        assert results["gemini"]["system_prompt"] == "Gemini system prompt"
        assert results["gemini"]["model"] == "gemini-2.5-pro"
        assert results["claude"]["system_prompt"] == "Claude system prompt"
        assert results["claude"]["model"] == "claude-sonnet-4-5-20250514"

    def test_thread_pool_isolation(self):
        """ThreadPoolExecutor mit wiederverwendeten Threads."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        def worker(task_num):
            task_id = f"worker-{task_num}"
            create_task_context(task_id=task_id)
            reset_dev_context()

            # Each worker adds its own tool
            add_dev_tool_result(f"tool_{task_num}", f"result_{task_num}")

            ctx = get_dev_context()
            clear_task_context()
            return ctx

        # Use only 2 workers for 5 tasks to force thread reuse
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, i) for i in range(5)]
            results = [f.result() for f in futures]

        # Each task should have exactly 1 tool result (its own)
        for i, result in enumerate(results):
            assert len(result["tool_results"]) == 1
            assert result["tool_results"][0]["tool"] == f"tool_{i}"


class TestCrossThreadAccess:
    """Cross-Thread-Tests for HTTP endpoint access."""

    def setup_method(self):
        """Clear state before each test."""
        from ai_agent.dev_context import _dev_contexts, _dev_contexts_lock
        with _dev_contexts_lock:
            _dev_contexts.clear()

    def test_get_with_explicit_task_id(self):
        """get_dev_context(task_id='2') aus anderem Thread."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        # Set up context in "agent thread"
        create_task_context(task_id="2")
        reset_dev_context()
        add_dev_tool_result("graph_get_flagged_emails", "emails...")
        clear_task_context()

        # Read from "HTTP thread" with explicit task_id
        result = {"ctx": None}

        def http_thread():
            # No TaskContext set here (simulates HTTP handler)
            result["ctx"] = get_dev_context(task_id="2")

        t = threading.Thread(target=http_thread)
        t.start()
        t.join()

        assert result["ctx"] is not None
        assert len(result["ctx"]["tool_results"]) == 1
        assert result["ctx"]["tool_results"][0]["tool"] == "graph_get_flagged_emails"

    def test_fallback_to_last_task_id(self):
        """get_dev_context() ohne task_id gibt letzten zurueck."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        # Task A runs first
        create_task_context(task_id="task-a")
        reset_dev_context()
        add_dev_tool_result("tool_a", "result_a")
        clear_task_context()

        # Task B runs second (becomes _last_task_id)
        create_task_context(task_id="task-b")
        reset_dev_context()
        add_dev_tool_result("tool_b", "result_b")
        clear_task_context()

        # Read from HTTP thread without explicit task_id
        # Should get task-b (last active)
        result = {"ctx": None}

        def http_thread():
            result["ctx"] = get_dev_context()

        t = threading.Thread(target=http_thread)
        t.start()
        t.join()

        assert result["ctx"] is not None
        assert len(result["ctx"]["tool_results"]) == 1
        assert result["ctx"]["tool_results"][0]["tool"] == "tool_b"


class TestCleanup:
    """Cleanup-Tests for memory management."""

    def setup_method(self):
        """Clear state before each test."""
        from ai_agent.dev_context import _dev_contexts, _dev_contexts_lock
        with _dev_contexts_lock:
            _dev_contexts.clear()

    def test_clear_removes_context(self):
        """clear_dev_context() entfernt Task-Context."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import (
            reset_dev_context, add_dev_tool_result, clear_dev_context,
            _dev_contexts, _dev_contexts_lock
        )

        create_task_context(task_id="to-clear")
        reset_dev_context()
        add_dev_tool_result("some_tool", "result")
        clear_task_context()

        # Verify context exists
        with _dev_contexts_lock:
            assert "to-clear" in _dev_contexts

        # Clear it
        clear_dev_context(task_id="to-clear")

        # Verify it's gone
        with _dev_contexts_lock:
            assert "to-clear" not in _dev_contexts

    def test_clear_does_not_affect_other_tasks(self):
        """Cleanup fuer Task A laesst Task B intakt."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import (
            reset_dev_context, add_dev_tool_result, clear_dev_context,
            get_dev_context, _dev_contexts, _dev_contexts_lock
        )

        # Create context for Task A
        create_task_context(task_id="task-a")
        reset_dev_context()
        add_dev_tool_result("tool_a", "result_a")
        clear_task_context()

        # Create context for Task B
        create_task_context(task_id="task-b")
        reset_dev_context()
        add_dev_tool_result("tool_b", "result_b")
        clear_task_context()

        # Clear Task A
        clear_dev_context(task_id="task-a")

        # Task A should be gone
        with _dev_contexts_lock:
            assert "task-a" not in _dev_contexts

        # Task B should still be there
        ctx_b = get_dev_context(task_id="task-b")
        assert len(ctx_b["tool_results"]) == 1
        assert ctx_b["tool_results"][0]["tool"] == "tool_b"

    def test_clear_nonexistent_task_is_safe(self):
        """Clearing a non-existent task does not raise."""
        from ai_agent.dev_context import clear_dev_context

        # Should not raise
        clear_dev_context(task_id="does-not-exist")


class TestBackwardCompatibility:
    """Tests for backward compatibility with single-agent usage."""

    def setup_method(self):
        """Clear state before each test."""
        from ai_agent.dev_context import _dev_contexts, _dev_contexts_lock
        with _dev_contexts_lock:
            _dev_contexts.clear()

    def test_works_without_task_context(self):
        """DevContext works when no TaskContext is set (fallback to _default)."""
        from ai_agent.task_context import clear_task_context
        from ai_agent.dev_context import (
            reset_dev_context, add_dev_tool_result, capture_dev_context,
            get_dev_context
        )

        clear_task_context()  # Ensure no TaskContext

        reset_dev_context()
        capture_dev_context(system_prompt="Test prompt", model="test-model")
        add_dev_tool_result("test_tool", "test result")

        ctx = get_dev_context()
        assert ctx["system_prompt"] == "Test prompt"
        assert ctx["model"] == "test-model"
        assert len(ctx["tool_results"]) == 1
        assert ctx["tool_results"][0]["tool"] == "test_tool"

    def test_multiple_tool_results_accumulate(self):
        """Multiple add_dev_tool_result calls accumulate in order."""
        from ai_agent.task_context import create_task_context, clear_task_context
        from ai_agent.dev_context import reset_dev_context, add_dev_tool_result, get_dev_context

        try:
            create_task_context(task_id="accumulate-test")
            reset_dev_context()

            add_dev_tool_result("tool_1", "result_1")
            add_dev_tool_result("tool_2", "result_2")
            add_dev_tool_result("tool_3", "result_3")

            ctx = get_dev_context()
            assert len(ctx["tool_results"]) == 3
            tools = [tr["tool"] for tr in ctx["tool_results"]]
            assert tools == ["tool_1", "tool_2", "tool_3"]
        finally:
            clear_task_context()
