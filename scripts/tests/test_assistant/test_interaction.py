# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for the interaction module (User Interaction Handler).

Tests the event-based confirmation request/response flow
and [063] round-ready handshake for multi-round confirmations.
"""

import threading
import time
import pytest

import sys
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _mock_skills_module():
    """Mock assistant.skills in sys.modules for interaction tests, with cleanup."""
    mock_skills = MagicMock()
    mock_skills.log = MagicMock()
    mock_skills.load_config = MagicMock(return_value={})

    saved = sys.modules.get('assistant.skills')
    sys.modules['assistant.skills'] = mock_skills

    # Force re-import of interaction so it picks up the mock
    sys.modules.pop('assistant.interaction', None)

    yield mock_skills

    # Restore original module (or remove mock)
    sys.modules.pop('assistant.interaction', None)
    if saved is not None:
        sys.modules['assistant.skills'] = saved
    else:
        sys.modules.pop('assistant.skills', None)


class TestEventBasedConfirmation:
    """Tests for the event-based confirmation flow."""

    def test_submit_response_wakes_up_waiting_thread(self):
        """Test that submit_response signals the waiting thread via Event."""
        # Import fresh to get our mocked version
        from assistant import interaction

        # Clear any existing pending confirmations
        interaction._pending.clear()

        task_id = "test-task-001"
        response_received = threading.Event()
        result_holder = {}

        def wait_for_confirmation():
            """Background thread waiting for confirmation."""
            result = interaction.request_confirmation(
                task_id=task_id,
                question="Confirm?",
                data={"name": "Test"},
                timeout=5
            )
            result_holder['result'] = result
            response_received.set()

        # Start waiting thread
        waiter = threading.Thread(target=wait_for_confirmation)
        waiter.start()

        # Give the thread time to start waiting
        time.sleep(0.1)

        # Verify request is pending
        assert task_id in interaction._pending
        pending = interaction._pending[task_id]
        assert pending.response_event is not None

        # Submit response - this should wake up the waiting thread
        start_time = time.time()
        success = interaction.submit_response(
            task_id=task_id,
            confirmed=True,
            data={"name": "Updated"}
        )
        assert success is True

        # Wait for waiter to complete
        response_received.wait(timeout=2)
        elapsed = time.time() - start_time

        # Verify it was fast (not waiting for timeout)
        assert elapsed < 1.0, f"Response took too long: {elapsed}s (should be < 1s)"

        # Verify result
        assert 'result' in result_holder
        assert result_holder['result']['confirmed'] is True
        assert result_holder['result']['data']['name'] == "Updated"

        # Clean up
        waiter.join(timeout=1)

    def test_timeout_returns_unconfirmed(self):
        """Test that timeout returns unconfirmed response."""
        from assistant import interaction

        interaction._pending.clear()

        task_id = "test-task-timeout"

        # Request with very short timeout
        result = interaction.request_confirmation(
            task_id=task_id,
            question="Confirm?",
            data={"test": True},
            timeout=1  # 1 second timeout
        )

        assert result['confirmed'] is False
        assert 'error' in result or 'on_cancel' in result

    def test_submit_response_to_nonexistent_task(self):
        """Test that submitting to non-existent task returns False."""
        from assistant import interaction

        interaction._pending.clear()

        success = interaction.submit_response(
            task_id="nonexistent-task",
            confirmed=True,
            data={}
        )

        assert success is False

    def test_get_pending_returns_none_for_unknown_task(self):
        """Test that get_pending returns None for unknown task."""
        from assistant import interaction

        interaction._pending.clear()

        result = interaction.get_pending("unknown-task")
        assert result is None

    def test_response_event_is_created_per_confirmation(self):
        """Test that each PendingConfirmation has its own Event."""
        from assistant import interaction

        interaction._pending.clear()

        # Create two confirmations
        interaction._pending["task-1"] = interaction.PendingConfirmation(
            task_id="task-1",
            question="Q1",
            data={}
        )
        interaction._pending["task-2"] = interaction.PendingConfirmation(
            task_id="task-2",
            question="Q2",
            data={}
        )

        # Verify they have different Event instances
        event1 = interaction._pending["task-1"].response_event
        event2 = interaction._pending["task-2"].response_event

        assert event1 is not event2
        assert not event1.is_set()
        assert not event2.is_set()

        # Set one, verify other is not affected
        event1.set()
        assert event1.is_set()
        assert not event2.is_set()

    def test_on_cancel_preserved_in_response(self):
        """Test that on_cancel settings are preserved when user cancels."""
        from assistant import interaction

        interaction._pending.clear()

        task_id = "test-cancel"
        result_holder = {}
        done = threading.Event()

        def wait_for_conf():
            result = interaction.request_confirmation(
                task_id=task_id,
                question="Continue?",
                data={},
                timeout=5,
                on_cancel="continue",
                on_cancel_message="User skipped this step"
            )
            result_holder['result'] = result
            done.set()

        thread = threading.Thread(target=wait_for_conf)
        thread.start()
        time.sleep(0.1)

        # User cancels
        interaction.submit_response(task_id, confirmed=False, data={})

        done.wait(timeout=2)
        thread.join(timeout=1)

        result = result_holder.get('result', {})
        assert result.get('confirmed') is False
        assert result.get('on_cancel') == "continue"
        assert result.get('on_cancel_message') == "User skipped this step"


class TestGhostDialogGuard:
    """[064] Tests for get_pending() ghost dialog prevention guard."""

    def test_get_pending_returns_none_after_response_set(self):
        """[064] get_pending() returns None when response_event is already set (ghost dialog prevention)."""
        from assistant import interaction

        interaction._pending.clear()
        task_id = "test-ghost-guard"

        # Create a pending confirmation
        with interaction._lock:
            interaction._pending[task_id] = interaction.PendingConfirmation(
                task_id=task_id,
                question="Confirm?",
                data={"company": "Test GmbH", "email": "test@example.com"}
            )

        # Before response: get_pending should return data
        result = interaction.get_pending(task_id)
        assert result is not None
        assert result["question"] == "Confirm?"
        assert result["data"]["company"] == "Test GmbH"

        # Simulate submit_response setting the event (without full submit flow)
        interaction._pending[task_id].response_event.set()

        # After response_event.set(): get_pending should return None (ghost guard)
        result = interaction.get_pending(task_id)
        assert result is None

    def test_get_pending_race_window_after_submit_response(self):
        """[064] During race window between submit_response() and del _pending[],
        get_pending() must return None (not stale data)."""
        from assistant import interaction

        interaction._pending.clear()
        task_id = "test-ghost-race"

        # Create a pending confirmation and submit response (but don't wait for cleanup)
        with interaction._lock:
            interaction._pending[task_id] = interaction.PendingConfirmation(
                task_id=task_id,
                question="Confirm order?",
                data={"item": "Widget"}
            )

        # Submit response (sets response_event, but _pending entry remains
        # until request_confirmation() thread cleans up)
        interaction.submit_response(task_id, confirmed=True, data={"item": "Widget"})

        # The entry still exists in _pending (agent thread hasn't cleaned up yet)
        assert task_id in interaction._pending

        # But get_pending() should return None because response_event is set
        result = interaction.get_pending(task_id)
        assert result is None

        # Clean up
        interaction._pending.clear()
        with interaction._round_ready_lock:
            interaction._round_ready.pop(task_id, None)

    def test_get_pending_normal_flow_unaffected(self):
        """[064] Normal flow: get_pending() returns data when response_event is NOT set."""
        from assistant import interaction

        interaction._pending.clear()
        task_id = "test-ghost-normal"

        with interaction._lock:
            interaction._pending[task_id] = interaction.PendingConfirmation(
                task_id=task_id,
                question="Please confirm",
                data={"name": "Alice"},
                editable_fields=["name"],
                dialog_type="",
                options=[]
            )

        # Normal case: response_event not set -> should return data
        result = interaction.get_pending(task_id)
        assert result is not None
        assert result["question"] == "Please confirm"
        assert result["data"]["name"] == "Alice"
        assert result["editable_fields"] == ["name"]

        # Clean up
        interaction._pending.clear()


class TestParseConfirmationRequest:
    """Tests for parse_confirmation_request."""

    def test_parse_valid_confirmation(self):
        """Test parsing a valid CONFIRMATION_NEEDED block."""
        from assistant import interaction

        content = '''Some text before
CONFIRMATION_NEEDED: {
  "question": "Confirm these details?",
  "data": {"name": "Test", "email": "test@example.com"},
  "editable_fields": ["name"]
}
Some text after'''

        result = interaction.parse_confirmation_request(content)

        assert result is not None
        assert result['question'] == "Confirm these details?"
        assert result['data']['name'] == "Test"
        assert result['editable_fields'] == ["name"]

    def test_parse_valid_question(self):
        """Test parsing a valid QUESTION_NEEDED block."""
        from assistant import interaction

        content = '''QUESTION_NEEDED: {
  "question": "Do you want to proceed?",
  "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]
}'''

        result = interaction.parse_confirmation_request(content)

        assert result is not None
        assert result['question'] == "Do you want to proceed?"
        assert result['type'] == "question"
        assert len(result['options']) == 2

    def test_parse_no_marker(self):
        """Test that content without marker returns None."""
        from assistant import interaction

        content = "This is just regular content"
        result = interaction.parse_confirmation_request(content)
        assert result is None

    def test_parse_invalid_json(self):
        """Test that invalid JSON returns None."""
        from assistant import interaction

        content = 'CONFIRMATION_NEEDED: { invalid json }'
        result = interaction.parse_confirmation_request(content)
        assert result is None


class TestCleanupStale:
    """Tests for cleanup_stale."""

    def test_cleanup_removes_old_confirmations(self):
        """Test that old confirmations are cleaned up."""
        from assistant import interaction

        interaction._pending.clear()

        # Create an old confirmation
        old_conf = interaction.PendingConfirmation(
            task_id="old-task",
            question="Old?",
            data={},
            timestamp=time.time() - 700  # 700 seconds ago
        )
        interaction._pending["old-task"] = old_conf

        # Create a recent confirmation
        new_conf = interaction.PendingConfirmation(
            task_id="new-task",
            question="New?",
            data={},
            timestamp=time.time()
        )
        interaction._pending["new-task"] = new_conf

        # Cleanup with 600 second max age
        interaction.cleanup_stale(max_age=600)

        # Old should be removed, new should remain
        assert "old-task" not in interaction._pending
        assert "new-task" in interaction._pending


class TestRoundReadyHandshake:
    """[063] Tests for round-ready handshake in multi-round confirmation dialogs."""

    def _cleanup_round_ready(self, interaction, task_id):
        """Helper to clean up round-ready state after tests."""
        with interaction._round_ready_lock:
            interaction._round_ready.pop(task_id, None)

    def test_wait_with_signal_proceeds_immediately(self):
        """T7: wait_for_round_ready() with signal -> proceeds immediately."""
        from assistant import interaction

        task_id = "test-rr-signal"
        interaction.prepare_round_ready(task_id)

        # Signal from another thread
        def signal():
            time.sleep(0.1)
            interaction.signal_round_ready(task_id)

        t = threading.Thread(target=signal)
        t.start()

        start = time.time()
        result = interaction.wait_for_round_ready(task_id, timeout=5.0)
        elapsed = time.time() - start

        assert result is True
        assert elapsed < 1.0, f"Should have proceeded quickly, took {elapsed}s"

        t.join(timeout=2)

    def test_wait_without_signal_times_out(self):
        """T8: wait_for_round_ready() without signal -> timeout."""
        from assistant import interaction

        task_id = "test-rr-timeout"
        interaction.prepare_round_ready(task_id)

        start = time.time()
        result = interaction.wait_for_round_ready(task_id, timeout=0.5)
        elapsed = time.time() - start

        assert result is False
        assert elapsed >= 0.4, f"Should have waited ~0.5s, took {elapsed}s"
        assert elapsed < 2.0, f"Should not wait too long, took {elapsed}s"

    def test_prepare_signal_lifecycle(self):
        """T9: prepare_round_ready() + signal_round_ready() full lifecycle."""
        from assistant import interaction

        task_id = "test-rr-lifecycle"

        # Step 1: Prepare
        interaction.prepare_round_ready(task_id)
        with interaction._round_ready_lock:
            assert task_id in interaction._round_ready
            assert not interaction._round_ready[task_id].is_set()

        # Step 2: Signal
        was_waiting = interaction.signal_round_ready(task_id)
        assert was_waiting is True

        with interaction._round_ready_lock:
            assert task_id in interaction._round_ready
            assert interaction._round_ready[task_id].is_set()

        # Step 3: Wait (should return immediately since already signaled)
        result = interaction.wait_for_round_ready(task_id, timeout=1.0)
        assert result is True

        # Step 4: Cleanup happened in wait_for_round_ready finally block
        with interaction._round_ready_lock:
            assert task_id not in interaction._round_ready

    def test_signal_without_prepare_returns_false(self):
        """T11: signal_round_ready() without prepare -> False."""
        from assistant import interaction

        result = interaction.signal_round_ready("nonexistent-task")
        assert result is False

    def test_submit_response_confirmed_prepares_round_ready(self):
        """T12: submit_response(confirmed=True) calls prepare_round_ready()."""
        from assistant import interaction

        interaction._pending.clear()
        task_id = "test-rr-submit-confirm"

        # Pre-populate pending
        with interaction._lock:
            interaction._pending[task_id] = interaction.PendingConfirmation(
                task_id=task_id,
                question="Confirm?",
                data={"field": "value"}
            )

        # Submit confirmed response
        interaction.submit_response(task_id, confirmed=True, data={"field": "value"})

        # Verify round-ready event was prepared
        with interaction._round_ready_lock:
            assert task_id in interaction._round_ready
            assert not interaction._round_ready[task_id].is_set()

        # Cleanup
        self._cleanup_round_ready(interaction, task_id)

    def test_wait_cleanup_on_exception(self):
        """T13: wait_for_round_ready() cleanup after exception (try-finally)."""
        from assistant import interaction

        task_id = "test-rr-exception"
        interaction.prepare_round_ready(task_id)

        # Verify event exists
        with interaction._round_ready_lock:
            assert task_id in interaction._round_ready

        # Monkey-patch the event's wait() to raise an exception
        with interaction._round_ready_lock:
            original_event = interaction._round_ready[task_id]

        def bad_wait(timeout=None):
            raise RuntimeError("Simulated error")

        original_event.wait = bad_wait

        # wait_for_round_ready should still clean up despite exception
        with pytest.raises(RuntimeError, match="Simulated error"):
            interaction.wait_for_round_ready(task_id, timeout=1.0)

        # Verify cleanup happened
        with interaction._round_ready_lock:
            assert task_id not in interaction._round_ready

    def test_submit_response_not_confirmed_skips_round_ready(self):
        """T15: submit_response(confirmed=False) must NOT prepare_round_ready()."""
        from assistant import interaction

        interaction._pending.clear()
        task_id = "test-rr-submit-cancel"

        # Pre-populate pending
        with interaction._lock:
            interaction._pending[task_id] = interaction.PendingConfirmation(
                task_id=task_id,
                question="Confirm?",
                data={"field": "value"}
            )

        # Submit cancelled response
        interaction.submit_response(task_id, confirmed=False, data={})

        # Verify round-ready event was NOT prepared
        with interaction._round_ready_lock:
            assert task_id not in interaction._round_ready

    def test_parallel_wait_for_different_tasks(self):
        """T16: Parallel wait_for_round_ready() for different tasks simultaneously."""
        from assistant import interaction

        results = {}
        errors = []

        def wait_and_record(task_id, delay_signal):
            """Wait for round-ready, then record result."""
            try:
                interaction.prepare_round_ready(task_id)

                def signal_later():
                    time.sleep(delay_signal)
                    interaction.signal_round_ready(task_id)

                t = threading.Thread(target=signal_later)
                t.start()

                result = interaction.wait_for_round_ready(task_id, timeout=5.0)
                results[task_id] = result
                t.join(timeout=2)
            except Exception as e:
                errors.append(f"{task_id}: {e}")

        t1 = threading.Thread(target=wait_and_record, args=("task-parallel-1", 0.1))
        t2 = threading.Thread(target=wait_and_record, args=("task-parallel-2", 0.2))

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(errors) == 0, f"Errors: {errors}"
        assert results.get("task-parallel-1") is True
        assert results.get("task-parallel-2") is True

    def test_prepare_twice_overwrites_event(self):
        """T17: prepare_round_ready() twice for same task_id overwrites the event."""
        from assistant import interaction

        task_id = "test-rr-double-prepare"

        # Prepare first
        interaction.prepare_round_ready(task_id)
        with interaction._round_ready_lock:
            event1 = interaction._round_ready[task_id]

        # Prepare again (should create new event)
        interaction.prepare_round_ready(task_id)
        with interaction._round_ready_lock:
            event2 = interaction._round_ready[task_id]

        # Events should be different instances
        assert event1 is not event2
        assert not event2.is_set()

        # Cleanup
        self._cleanup_round_ready(interaction, task_id)

    def test_wait_without_prepare_proceeds_immediately(self):
        """wait_for_round_ready() without prepare -> proceeds immediately (no-op)."""
        from assistant import interaction

        start = time.time()
        result = interaction.wait_for_round_ready("never-prepared-task", timeout=5.0)
        elapsed = time.time() - start

        assert result is True  # No event = proceed immediately
        assert elapsed < 0.5, f"Should have returned immediately, took {elapsed}s"

    def test_cleanup_stale_removes_orphaned_round_ready(self):
        """cleanup_stale() removes orphaned round-ready events."""
        from assistant import interaction

        task_id = "test-rr-stale"

        # Create an orphaned round-ready event (no one waiting)
        interaction.prepare_round_ready(task_id)

        with interaction._round_ready_lock:
            assert task_id in interaction._round_ready

        # Run cleanup
        interaction.cleanup_stale()

        # Orphaned event should be removed
        with interaction._round_ready_lock:
            assert task_id not in interaction._round_ready


class TestRoundReadyRoute:
    """[063] T14: Route tests for POST /task/{id}/round-ready endpoint."""

    @pytest.fixture
    def test_client(self):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient
        from assistant.app import create_app

        app = create_app()
        return TestClient(app)

    def test_round_ready_unknown_task_returns_404(self, test_client):
        """T14: POST /round-ready with unknown task_id -> 404."""
        response = test_client.post("/task/nonexistent-task-xyz/round-ready")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_round_ready_known_task_returns_ok(self, test_client):
        """POST /round-ready with known task -> 200 OK."""
        from assistant.core import tasks as _tasks, tasks_lock as _tasks_lock

        task_id = "test-route-rr"
        # Create a task so it exists
        with _tasks_lock:
            _tasks[task_id] = {"status": "running", "agent": "test"}

        try:
            response = test_client.post(f"/task/{task_id}/round-ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "was_waiting" in data
        finally:
            with _tasks_lock:
                _tasks.pop(task_id, None)


class TestContinuationPromptAntiDuplicate:
    """[064] Test that continuation prompt warns against re-asking confirmed data."""

    def test_contains_anti_duplicate_warning(self):
        """continuation_prompt warns explicitly against re-asking for confirmed data."""
        import inspect
        from assistant import agents

        source = inspect.getsource(agents)
        assert "bereits vom Benutzer bestaetigt" in source, \
            "Anti-duplicate warning missing from continuation prompt in agents.py"
        assert "frage NICHT erneut danach" in source, \
            "Anti-duplicate instruction missing from continuation prompt in agents.py"
