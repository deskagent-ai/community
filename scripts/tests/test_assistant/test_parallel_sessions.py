# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Tests for parallel session isolation (planfeature-023, planfeature-046)."""
import threading
import time
import pytest
from unittest.mock import patch, MagicMock, call


class TestParallelSessionGuard:
    """Test that running sessions are not prematurely completed."""

    def test_running_session_not_completed(self):
        """When session A is running and agent starts new session B,
        session A must NOT be completed."""
        from assistant.core.state import (
            start_or_continue_session,
            _running_sessions,
            _running_sessions_lock,
        )
        from assistant.core import state as state_module

        # Setup: mock session_store
        with patch.object(state_module, 'session_store') as mock_store, \
             patch.object(state_module, 'SESSION_STORE_AVAILABLE', True):

            mock_store.get_active_session.return_value = "session_A"
            mock_store.create_session.return_value = "session_B"

            # Mark session_A as running
            with _running_sessions_lock:
                _running_sessions["session_A"] = None

            try:
                result = start_or_continue_session(
                    "daily_check", "claude_sdk", "claude-sonnet",
                    force_new_session=True, triggered_by="webui"
                )

                # session_A must NOT be completed
                mock_store.complete_session.assert_not_called()
                # New session B created
                assert result == "session_B"
            finally:
                with _running_sessions_lock:
                    _running_sessions.pop("session_A", None)
                    _running_sessions.pop("session_B", None)

    def test_idle_session_completed(self):
        """When session A is NOT running and agent starts new session B,
        session A SHOULD be completed (normal behavior)."""
        from assistant.core.state import (
            start_or_continue_session,
            _running_sessions,
            _running_sessions_lock,
        )
        from assistant.core import state as state_module

        with patch.object(state_module, 'session_store') as mock_store, \
             patch.object(state_module, 'SESSION_STORE_AVAILABLE', True):

            mock_store.get_active_session.return_value = "session_A"
            mock_store.create_session.return_value = "session_B"

            # Ensure session_A is NOT in running sessions
            with _running_sessions_lock:
                _running_sessions.pop("session_A", None)

            try:
                result = start_or_continue_session(
                    "daily_check", "claude_sdk", "claude-sonnet",
                    force_new_session=True, triggered_by="webui"
                )

                # session_A MUST be completed
                mock_store.complete_session.assert_called_once_with("session_A")
                assert result == "session_B"
            finally:
                with _running_sessions_lock:
                    _running_sessions.pop("session_B", None)

    def test_new_session_marked_running_immediately(self):
        """New session must be in _running_sessions immediately after creation."""
        from assistant.core.state import (
            start_or_continue_session,
            _running_sessions,
            _running_sessions_lock,
        )
        from assistant.core import state as state_module

        with patch.object(state_module, 'session_store') as mock_store, \
             patch.object(state_module, 'SESSION_STORE_AVAILABLE', True):

            mock_store.get_active_session.return_value = None
            mock_store.create_session.return_value = "session_new"

            try:
                result = start_or_continue_session(
                    "daily_check", "claude_sdk", "claude-sonnet",
                    force_new_session=True, triggered_by="webui"
                )

                assert result == "session_new"
                with _running_sessions_lock:
                    assert "session_new" in _running_sessions
            finally:
                with _running_sessions_lock:
                    _running_sessions.pop("session_new", None)

    def test_racing_parallel_starts(self):
        """Two threads starting sessions for same agent - both should exist."""
        from assistant.core.state import (
            start_or_continue_session,
            _running_sessions,
            _running_sessions_lock,
        )
        from assistant.core import state as state_module

        results = []
        errors = []
        call_count = [0]

        def create_session_side_effect(*args, **kwargs):
            call_count[0] += 1
            return f"session_{call_count[0]}"

        with patch.object(state_module, 'session_store') as mock_store, \
             patch.object(state_module, 'SESSION_STORE_AVAILABLE', True):

            mock_store.get_active_session.return_value = None
            mock_store.create_session.side_effect = create_session_side_effect

            def start_session():
                try:
                    sid = start_or_continue_session(
                        "daily_check", "claude_sdk", "claude-sonnet",
                        force_new_session=True, triggered_by="webui"
                    )
                    results.append(sid)
                except Exception as e:
                    errors.append(str(e))

            t1 = threading.Thread(target=start_session)
            t2 = threading.Thread(target=start_session)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            try:
                assert len(errors) == 0, f"Errors: {errors}"
                assert len(results) == 2
                # Both sessions exist and are different
                assert results[0] != results[1]
                # complete_session should NOT have been called (no pre-existing active session)
                mock_store.complete_session.assert_not_called()
            finally:
                with _running_sessions_lock:
                    for r in results:
                        _running_sessions.pop(r, None)


class TestParallelConfirmationIsolation:
    """[046] Tests that confirmation dialogs are correctly assigned to their session."""

    def test_confirmation_stores_session_id_in_pending(self):
        """request_confirmation() stores session_id from TaskContext in PendingConfirmation."""
        from assistant.interaction import request_confirmation, _pending, _lock

        with patch('assistant.interaction.add_turn_to_session', create=True), \
             patch('assistant.interaction.log'):

            # Mock TaskContext with session_id
            mock_ctx = MagicMock()
            mock_ctx.session_id = "s_001"

            with patch('ai_agent.task_context.get_task_context_or_none', return_value=mock_ctx):
                # Start request in a thread (it blocks waiting for response)
                def do_request():
                    request_confirmation(
                        task_id="task-001",
                        question="Confirm?",
                        data={"field": "value"},
                        timeout=1  # Short timeout for test
                    )

                t = threading.Thread(target=do_request)
                t.start()

                # Give thread time to register the pending confirmation
                time.sleep(0.2)

                with _lock:
                    assert "task-001" in _pending
                    assert _pending["task-001"].session_id == "s_001"

                t.join(timeout=3)

                # Cleanup
                with _lock:
                    _pending.pop("task-001", None)

    def test_confirmation_passes_session_id_to_add_turn(self):
        """request_confirmation() passes session_id to add_turn_to_session."""
        from assistant.interaction import request_confirmation, _pending, _lock

        mock_add_turn = MagicMock()

        with patch('assistant.interaction.log'):
            # Mock TaskContext
            mock_ctx = MagicMock()
            mock_ctx.session_id = "s_002"

            with patch('ai_agent.task_context.get_task_context_or_none', return_value=mock_ctx), \
                 patch('assistant.core.state.add_turn_to_session', mock_add_turn):

                def do_request():
                    request_confirmation(
                        task_id="task-002",
                        question="Proceed?",
                        data={"key": "val"},
                        timeout=1
                    )

                t = threading.Thread(target=do_request)
                t.start()
                time.sleep(0.2)

                # Verify add_turn_to_session was called with session_id
                mock_add_turn.assert_called_once()
                _, kwargs = mock_add_turn.call_args
                # Check positional or keyword args
                call_args = mock_add_turn.call_args
                assert call_args.kwargs.get("session_id") == "s_002" or \
                       (len(call_args.args) > 0 and "s_002" in str(call_args))

                t.join(timeout=3)

                # Cleanup
                with _lock:
                    _pending.pop("task-002", None)

    def test_response_reads_session_id_from_pending(self):
        """submit_response() reads session_id from PendingConfirmation, not TaskContext."""
        from assistant.interaction import (
            submit_response, _pending, _lock, PendingConfirmation
        )

        mock_add_turn = MagicMock()

        with patch('assistant.interaction.log'):
            # Pre-populate _pending with a PendingConfirmation that has session_id
            with _lock:
                _pending["task-003"] = PendingConfirmation(
                    task_id="task-003",
                    question="Confirm data?",
                    data={"name": "Test"},
                    session_id="s_003",
                    editable_fields=["name"]
                )

            with patch('assistant.core.state.add_turn_to_session', mock_add_turn):
                # Submit response with a QUESTION_NEEDED response (has "response" key)
                result = submit_response(
                    task_id="task-003",
                    confirmed=True,
                    data={"response": "Yes, proceed"}
                )

                assert result is True
                # Verify session_id from PendingConfirmation was used
                mock_add_turn.assert_called_once()
                call_kwargs = mock_add_turn.call_args.kwargs
                assert call_kwargs.get("session_id") == "s_003"

            # Cleanup (submit_response should have already removed it via response_event)
            with _lock:
                _pending.pop("task-003", None)

    def test_parallel_confirmations_isolated(self):
        """Two parallel confirmations store separate session_ids."""
        from assistant.interaction import request_confirmation, _pending, _lock

        with patch('assistant.interaction.log'), \
             patch('assistant.core.state.add_turn_to_session'):

            results = {}
            errors = []

            def do_confirm(task_id, session_id):
                try:
                    mock_ctx = MagicMock()
                    mock_ctx.session_id = session_id

                    with patch('ai_agent.task_context.get_task_context_or_none', return_value=mock_ctx):
                        request_confirmation(
                            task_id=task_id,
                            question=f"Confirm {task_id}?",
                            data={"id": task_id},
                            timeout=1
                        )
                except Exception as e:
                    errors.append(str(e))

            t1 = threading.Thread(target=do_confirm, args=("task-A", "s_A"))
            t2 = threading.Thread(target=do_confirm, args=("task-B", "s_B"))
            t1.start()
            t2.start()

            time.sleep(0.3)

            # Verify both pending confirmations have correct session_ids
            with _lock:
                if "task-A" in _pending:
                    results["task-A"] = _pending["task-A"].session_id
                if "task-B" in _pending:
                    results["task-B"] = _pending["task-B"].session_id

            t1.join(timeout=3)
            t2.join(timeout=3)

            assert len(errors) == 0, f"Errors: {errors}"
            assert results.get("task-A") == "s_A"
            assert results.get("task-B") == "s_B"

            # Cleanup
            with _lock:
                _pending.pop("task-A", None)
                _pending.pop("task-B", None)

    def test_sse_event_contains_task_id(self):
        """publish_event() injects task_id into all event payloads."""
        import asyncio
        from assistant.core.sse_manager import (
            publish_event, create_queue, remove_queue,
            set_event_loop, _sse_queues
        )

        # Create a real event loop for this test
        loop = asyncio.new_event_loop()

        try:
            set_event_loop(loop)
            queue = create_queue("task-sse-001")

            # Publish an event
            publish_event("task-sse-001", "pending_input", {
                "question": "Proceed?",
                "options": []
            })

            # Run the event loop briefly to process the call_soon_threadsafe
            async def get_event():
                try:
                    return await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    return None

            event = loop.run_until_complete(get_event())

            assert event is not None, "No event received from queue"
            assert event.data["task_id"] == "task-sse-001"
            assert event.data["question"] == "Proceed?"

        finally:
            remove_queue("task-sse-001")
            set_event_loop(None)
            loop.close()
