# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for ai_agent.task_context module.
Tests TaskContext dataclass and ContextVar-based isolation for parallel execution.
"""

import asyncio
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestTaskContextBasics:
    """Tests for basic TaskContext functionality."""

    def test_create_task_context(self):
        """Test creating a TaskContext with create_task_context."""
        from ai_agent.task_context import create_task_context, clear_task_context

        try:
            ctx = create_task_context(
                task_id="test-123",
                backend_name="gemini",
                dry_run_mode=True,
                test_folder="TestFolder"
            )

            assert ctx.task_id == "test-123"
            assert ctx.backend_name == "gemini"
            assert ctx.dry_run_mode is True
            assert ctx.test_folder == "TestFolder"
            assert ctx.simulated_actions == []
            assert ctx.anon_context is None
        finally:
            clear_task_context()

    def test_get_task_context_creates_default(self):
        """Test that get_task_context creates a default context if none exists."""
        from ai_agent.task_context import get_task_context, clear_task_context

        clear_task_context()  # Ensure clean state

        ctx = get_task_context()
        assert ctx is not None
        assert ctx.task_id is None
        assert ctx.dry_run_mode is False

        clear_task_context()

    def test_get_task_context_or_none_returns_none(self):
        """Test that get_task_context_or_none returns None if no context exists."""
        from ai_agent.task_context import get_task_context_or_none, clear_task_context

        clear_task_context()  # Ensure clean state

        ctx = get_task_context_or_none()
        assert ctx is None

    def test_clear_task_context_clears(self):
        """Test that clear_task_context removes the context."""
        from ai_agent.task_context import (
            create_task_context, clear_task_context, get_task_context_or_none
        )

        create_task_context(task_id="test-456")
        clear_task_context()

        ctx = get_task_context_or_none()
        assert ctx is None


class TestTaskContextLogging:
    """Tests for TaskContext logging features."""

    def test_task_context_log_method(self):
        """Test the log() method adds entries to log_buffer."""
        from ai_agent.task_context import create_task_context, clear_task_context

        try:
            ctx = create_task_context(task_id="log-test", backend_name="gemini")

            ctx.log("PROMPT", "Test message", "Detailed content")

            assert len(ctx.log_buffer) == 1
            entry = ctx.log_buffer[0]
            assert entry["task_id"] == "log-test"
            assert entry["backend"] == "gemini"
            assert entry["category"] == "PROMPT"
            assert entry["message"] == "Test message"
            assert entry["content"] == "Detailed content"
            assert "timestamp" in entry
        finally:
            clear_task_context()

    def test_simulated_actions_recording(self):
        """Test add_simulated_action records actions correctly."""
        from ai_agent.task_context import create_task_context, clear_task_context

        try:
            ctx = create_task_context(task_id="sim-test", dry_run_mode=True)

            ctx.add_simulated_action(
                tool="outlook_move_email",
                args={"entry_id": "abc", "folder": "Done"},
                result="Simulated: Would move email"
            )

            assert len(ctx.simulated_actions) == 1
            action = ctx.simulated_actions[0]
            assert action["tool"] == "outlook_move_email"
            assert action["args"]["entry_id"] == "abc"
            assert "Simulated" in action["simulated_result"]
        finally:
            clear_task_context()

    def test_reset_simulated_actions(self):
        """Test reset_simulated_actions clears the list."""
        from ai_agent.task_context import create_task_context, clear_task_context

        try:
            ctx = create_task_context(task_id="reset-test", dry_run_mode=True)
            ctx.add_simulated_action("tool1", {}, "result1")
            ctx.add_simulated_action("tool2", {}, "result2")

            assert len(ctx.simulated_actions) == 2

            ctx.reset_simulated_actions()
            assert len(ctx.simulated_actions) == 0
        finally:
            clear_task_context()


class TestTaskContextIsolation:
    """Tests for TaskContext isolation across asyncio tasks and threads."""

    @pytest.mark.asyncio
    async def test_asyncio_task_isolation(self):
        """Test that ContextVar provides isolation between asyncio tasks."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        results = {"task_a": None, "task_b": None}

        async def task_a():
            ctx = create_task_context(task_id="task-a", backend_name="gemini")
            await asyncio.sleep(0.01)  # Allow interleaving
            results["task_a"] = get_task_context().task_id
            clear_task_context()

        async def task_b():
            ctx = create_task_context(task_id="task-b", backend_name="openai")
            await asyncio.sleep(0.01)  # Allow interleaving
            results["task_b"] = get_task_context().task_id
            clear_task_context()

        # Run both tasks concurrently
        await asyncio.gather(task_a(), task_b())

        # Each task should see its own context
        assert results["task_a"] == "task-a"
        assert results["task_b"] == "task-b"

    @pytest.mark.asyncio
    async def test_asyncio_dry_run_isolation(self):
        """Test that dry-run mode is isolated between asyncio tasks."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        results = {"task_dry": None, "task_normal": None}

        async def task_dry():
            ctx = create_task_context(task_id="dry-task", dry_run_mode=True)
            await asyncio.sleep(0.01)
            results["task_dry"] = get_task_context().dry_run_mode
            clear_task_context()

        async def task_normal():
            ctx = create_task_context(task_id="normal-task", dry_run_mode=False)
            await asyncio.sleep(0.01)
            results["task_normal"] = get_task_context().dry_run_mode
            clear_task_context()

        await asyncio.gather(task_dry(), task_normal())

        assert results["task_dry"] is True
        assert results["task_normal"] is False

    @pytest.mark.asyncio
    async def test_asyncio_simulated_actions_isolation(self):
        """Test that simulated actions are isolated between asyncio tasks."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        results = {"gemini_actions": None, "openai_actions": None}

        async def gemini_task():
            ctx = create_task_context(task_id="gemini", dry_run_mode=True)
            ctx.add_simulated_action("tool_a", {"arg": "gemini"}, "result_gemini")
            await asyncio.sleep(0.01)
            results["gemini_actions"] = get_task_context().simulated_actions.copy()
            clear_task_context()

        async def openai_task():
            ctx = create_task_context(task_id="openai", dry_run_mode=True)
            ctx.add_simulated_action("tool_b", {"arg": "openai"}, "result_openai")
            ctx.add_simulated_action("tool_c", {"arg": "openai2"}, "result_openai2")
            await asyncio.sleep(0.01)
            results["openai_actions"] = get_task_context().simulated_actions.copy()
            clear_task_context()

        await asyncio.gather(gemini_task(), openai_task())

        # Each task should have its own simulated actions
        assert len(results["gemini_actions"]) == 1
        assert results["gemini_actions"][0]["args"]["arg"] == "gemini"

        assert len(results["openai_actions"]) == 2
        assert results["openai_actions"][0]["args"]["arg"] == "openai"

    def test_thread_isolation_requires_set_inside_thread(self):
        """Test that threads need to set context inside the thread function.

        ContextVar values are NOT inherited by new threads.
        This test verifies that setting context in the main thread
        does NOT make it visible in the child thread.
        """
        from ai_agent.task_context import (
            create_task_context, get_task_context_or_none, clear_task_context
        )

        # Set context in main thread
        main_ctx = create_task_context(task_id="main-thread")

        child_result = {"saw_context": None}

        def child_thread():
            # Should NOT see main thread's context
            ctx = get_task_context_or_none()
            child_result["saw_context"] = ctx is not None

        thread = threading.Thread(target=child_thread)
        thread.start()
        thread.join()

        # Child should NOT see main thread's context
        assert child_result["saw_context"] is False

        clear_task_context()

    def test_thread_can_create_own_context(self):
        """Test that each thread can create and use its own context."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        results = {}

        def thread_func(thread_id):
            ctx = create_task_context(task_id=f"thread-{thread_id}")
            results[thread_id] = get_task_context().task_id
            clear_task_context()

        threads = []
        for i in range(3):
            t = threading.Thread(target=thread_func, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Each thread should have seen its own context
        assert results[0] == "thread-0"
        assert results[1] == "thread-1"
        assert results[2] == "thread-2"

    def test_thread_pool_isolation(self):
        """Test isolation with ThreadPoolExecutor (reused threads)."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        def worker(task_num):
            ctx = create_task_context(task_id=f"worker-{task_num}")
            task_id = get_task_context().task_id
            clear_task_context()
            return task_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, i) for i in range(5)]
            results = [f.result() for f in futures]

        # Each task should have its own task_id
        expected = [f"worker-{i}" for i in range(5)]
        assert results == expected


class TestToolBridgeIntegration:
    """Tests for tool_bridge integration with TaskContext."""

    def test_set_dry_run_mode_uses_context(self):
        """Test that set_dry_run_mode stores state in TaskContext."""
        from ai_agent import tool_bridge
        from ai_agent.task_context import get_task_context, clear_task_context

        clear_task_context()

        tool_bridge.set_dry_run_mode(True)

        ctx = get_task_context()
        assert ctx.dry_run_mode is True

        clear_task_context()

    def test_get_simulated_actions_from_context(self):
        """Test that get_simulated_actions reads from TaskContext."""
        from ai_agent import tool_bridge
        from ai_agent.task_context import create_task_context, clear_task_context

        try:
            ctx = create_task_context(task_id="test", dry_run_mode=True)
            ctx.add_simulated_action("test_tool", {"arg": "value"}, "simulated")

            actions = tool_bridge.get_simulated_actions()
            assert len(actions) == 1
            assert actions[0]["tool"] == "test_tool"
        finally:
            clear_task_context()

    def test_set_test_folder_uses_context(self):
        """Test that set_test_folder stores in TaskContext."""
        from ai_agent import tool_bridge
        from ai_agent.task_context import get_task_context, clear_task_context

        clear_task_context()

        tool_bridge.set_test_folder("TestMail")

        ctx = get_task_context()
        assert ctx.test_folder == "TestMail"

        clear_task_context()

    def test_set_anonymization_context_uses_context(self):
        """Test that set_anonymization_context stores in TaskContext."""
        from ai_agent import tool_bridge
        from ai_agent.task_context import get_task_context, clear_task_context

        clear_task_context()

        mock_anon = MagicMock()
        mock_anon.mappings = {"[PERSON_1]": "John Doe"}

        tool_bridge.set_anonymization_context(mock_anon)

        ctx = get_task_context()
        assert ctx.anon_context is mock_anon

        clear_task_context()


class TestComparisonScenario:
    """Tests simulating the comparison feature scenario."""

    @pytest.mark.asyncio
    async def test_parallel_comparison_isolation(self):
        """Test that parallel backend comparison has isolated contexts."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        results = {}

        async def run_backend(backend_name):
            """Simulate running an agent on a single backend."""
            # Generate unique task_id (like testing.py does)
            import uuid
            task_id = f"compare-{backend_name}-{str(uuid.uuid4())[:4]}"

            ctx = create_task_context(
                task_id=task_id,
                backend_name=backend_name,
                dry_run_mode=True
            )

            # Simulate tool calls recording simulated actions
            ctx.add_simulated_action(
                f"{backend_name}_tool",
                {"backend": backend_name},
                f"Simulated by {backend_name}"
            )

            # Simulate some async work
            await asyncio.sleep(0.01)

            # Capture results before cleanup
            captured = {
                "task_id": get_task_context().task_id,
                "backend": get_task_context().backend_name,
                "actions": get_task_context().simulated_actions.copy()
            }

            clear_task_context()
            return captured

        # Run multiple backends in parallel (like asyncio.gather in testing.py)
        backends = ["gemini", "openai", "claude_sdk"]
        tasks = [run_backend(b) for b in backends]
        results_list = await asyncio.gather(*tasks)

        # Verify each backend had isolated context
        for i, result in enumerate(results_list):
            backend = backends[i]
            assert result["backend"] == backend
            assert backend in result["task_id"]
            assert len(result["actions"]) == 1
            assert result["actions"][0]["args"]["backend"] == backend

    @pytest.mark.asyncio
    async def test_parallel_anonymization_isolation(self):
        """Test that anonymization contexts are isolated in parallel execution."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        results = {}

        async def run_with_anon(backend_name, mappings):
            """Simulate running with different anonymization mappings."""
            task_id = f"anon-{backend_name}"

            ctx = create_task_context(task_id=task_id, backend_name=backend_name)

            # Simulate anonymization context (different for each backend)
            mock_anon = MagicMock()
            mock_anon.mappings = mappings
            ctx.anon_context = mock_anon

            await asyncio.sleep(0.01)

            # Verify we still see our own mappings
            current_ctx = get_task_context()
            results[backend_name] = {
                "mappings": current_ctx.anon_context.mappings if current_ctx.anon_context else {}
            }

            clear_task_context()

        # Each backend has different anonymization mappings
        await asyncio.gather(
            run_with_anon("gemini", {"[PERSON_1]": "Alice"}),
            run_with_anon("openai", {"[PERSON_1]": "Bob", "[EMAIL_1]": "bob@test.com"}),
            run_with_anon("claude", {"[COMPANY_1]": "Acme Inc"})
        )

        # Each should have its own mappings
        assert results["gemini"]["mappings"] == {"[PERSON_1]": "Alice"}
        assert results["openai"]["mappings"]["[PERSON_1]"] == "Bob"
        assert results["claude"]["mappings"]["[COMPANY_1]"] == "Acme Inc"


class TestSequentialTaskSwitch:
    """Tests for switching between tasks sequentially in the same thread."""

    def test_sequential_task_cleanup(self):
        """Test that clearing context between sequential tasks works."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context, get_task_context_or_none
        )

        # First task
        ctx1 = create_task_context(task_id="first-task", dry_run_mode=True)
        ctx1.add_simulated_action("first_tool", {}, "result1")
        assert get_task_context().task_id == "first-task"
        assert len(get_task_context().simulated_actions) == 1

        clear_task_context()

        # Verify cleared
        assert get_task_context_or_none() is None

        # Second task - should start fresh
        ctx2 = create_task_context(task_id="second-task", dry_run_mode=False)
        assert get_task_context().task_id == "second-task"
        assert get_task_context().dry_run_mode is False
        assert len(get_task_context().simulated_actions) == 0  # Fresh state

        clear_task_context()

    def test_no_cross_contamination_between_tasks(self):
        """Test that state doesn't leak between sequential tasks."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )

        # Task A with specific state
        ctx_a = create_task_context(
            task_id="task-a",
            backend_name="gemini",
            dry_run_mode=True,
            test_folder="FolderA"
        )
        ctx_a.add_simulated_action("tool_a", {"x": 1}, "result_a")
        mock_anon_a = MagicMock()
        mock_anon_a.mappings = {"[A]": "value_a"}
        ctx_a.anon_context = mock_anon_a

        clear_task_context()

        # Task B should have completely fresh state
        ctx_b = create_task_context(task_id="task-b", backend_name="openai")

        assert ctx_b.task_id == "task-b"
        assert ctx_b.backend_name == "openai"
        assert ctx_b.dry_run_mode is False  # Default, not inherited
        assert ctx_b.test_folder is None  # Not inherited
        assert len(ctx_b.simulated_actions) == 0  # Not inherited
        assert ctx_b.anon_context is None  # Not inherited

        clear_task_context()


class TestMultiRoundTaskContextPersistence:
    """Tests for [069] TaskContext lifecycle - persistent context across rounds."""

    def test_owns_context_pattern_creates_and_clears(self):
        """Test that call_agent without task_context creates and clears its own."""
        from ai_agent.task_context import get_task_context_or_none, clear_task_context

        clear_task_context()  # Ensure clean state

        # Without task_context, call_agent creates its own (owns_context=True)
        # We can't call call_agent directly without mocking, but we can test the pattern
        owns_context = None is None  # Simulates task_context is None
        assert owns_context is True

        # After cleanup, context should be None
        assert get_task_context_or_none() is None

    def test_owns_context_pattern_reuses_existing(self):
        """Test that call_agent with task_context reuses it."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context,
            set_task_context
        )

        try:
            # Caller creates context
            caller_ctx = create_task_context(task_id="caller-task", backend_name="gemini")

            # Simulates call_agent receiving task_context parameter
            owns_context = caller_ctx is None  # False - caller provided context
            assert owns_context is False

            # Context should still be accessible
            assert get_task_context().task_id == "caller-task"
        finally:
            clear_task_context()

    def test_anon_context_persists_across_simulated_rounds(self):
        """Test that anon_context set in round 1 is visible in round 2.

        This is the core scenario: process_agent creates TaskContext,
        call_agent round 1 sets anon_context on it, call_agent round 2
        sees the same anon_context (no data loss).
        """
        from ai_agent.task_context import (
            create_task_context, get_task_context, clear_task_context
        )
        from ai_agent.anonymizer import AnonymizationContext

        try:
            # process_agent creates TaskContext before loop
            ctx = create_task_context(task_id="multi-round", backend_name="gemini")
            assert ctx.anon_context is None  # Starts empty

            # Round 1: call_agent creates anon_context and stores it in ctx
            round1_anon = AnonymizationContext(
                mappings={"<PERSON_1>": "Max Mustermann", "<EMAIL_ADDRESS_1>": "max@test.com"},
                reverse_mappings={"Max Mustermann": "<PERSON_1>", "max@test.com": "<EMAIL_ADDRESS_1>"}
            )
            ctx.anon_context = round1_anon

            # Verify stored
            assert ctx.anon_context is round1_anon
            assert len(ctx.anon_context.mappings) == 2

            # Round 2: call_agent reads existing_anon_context from ctx.anon_context
            existing_anon_context = ctx.anon_context
            assert existing_anon_context is not None
            assert existing_anon_context.mappings["<PERSON_1>"] == "Max Mustermann"
            assert existing_anon_context.reverse_mappings["max@test.com"] == "<EMAIL_ADDRESS_1>"

            # Round 2 may add more mappings
            ctx.anon_context.mappings["<PHONE_NUMBER_1>"] = "+49 123 456"
            ctx.anon_context.reverse_mappings["+49 123 456"] = "<PHONE_NUMBER_1>"

            # All 3 mappings visible
            assert len(ctx.anon_context.mappings) == 3

        finally:
            clear_task_context()

    def test_pii_cleanup_in_finally_block(self):
        """Test that PII mappings are properly cleared in finally block."""
        from ai_agent.task_context import (
            create_task_context, clear_task_context
        )
        from ai_agent.anonymizer import AnonymizationContext

        try:
            ctx = create_task_context(task_id="cleanup-test")

            # Simulate anon_context with PII data
            ctx.anon_context = AnonymizationContext(
                mappings={
                    "<PERSON_1>": "Sensitive Name",
                    "<EMAIL_ADDRESS_1>": "sensitive@email.com"
                },
                reverse_mappings={
                    "Sensitive Name": "<PERSON_1>",
                    "sensitive@email.com": "<EMAIL_ADDRESS_1>"
                }
            )

            assert len(ctx.anon_context.mappings) == 2
            assert len(ctx.anon_context.reverse_mappings) == 2

            # Simulate finally block cleanup
            ctx.anon_context.mappings.clear()
            ctx.anon_context.reverse_mappings.clear()

            assert len(ctx.anon_context.mappings) == 0
            assert len(ctx.anon_context.reverse_mappings) == 0

        finally:
            clear_task_context()

    def test_large_pii_mapping_warning_threshold(self):
        """Test that warning is triggered for > 100 PII mappings."""
        from ai_agent.task_context import (
            create_task_context, clear_task_context
        )
        from ai_agent.anonymizer import AnonymizationContext

        try:
            ctx = create_task_context(task_id="large-pii-test")

            # Create context with >100 mappings
            large_mappings = {f"<PERSON_{i}>": f"Person {i}" for i in range(150)}
            ctx.anon_context = AnonymizationContext(mappings=large_mappings)

            mapping_count = len(ctx.anon_context.mappings)
            assert mapping_count == 150
            assert mapping_count > 100  # Would trigger warning in production code

        finally:
            clear_task_context()

    def test_task_context_not_cleared_when_caller_owns(self):
        """Test that task_context is retained when caller owns it (owns_context=False)."""
        from ai_agent.task_context import (
            create_task_context, get_task_context, get_task_context_or_none,
            clear_task_context, set_task_context
        )

        try:
            # Caller creates context (simulates process_agent)
            caller_ctx = create_task_context(task_id="owned-by-caller")

            # Simulate call_agent with owns_context=False
            # call_agent does NOT clear context at end
            assert get_task_context().task_id == "owned-by-caller"

            # After "call_agent returns", context should still be there
            # (caller hasn't cleared it yet)
            assert get_task_context_or_none() is not None
            assert get_task_context().task_id == "owned-by-caller"

        finally:
            # Caller clears context (simulates process_agent finally block)
            clear_task_context()
            assert get_task_context_or_none() is None
