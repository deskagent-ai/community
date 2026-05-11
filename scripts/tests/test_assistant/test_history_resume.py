# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for History Resume State Restoration [planfeature-039].

Verifies the full chain of SDK session ID persistence and resume:
1. end_current_session() persists sdk_session_id to DB
2. load_session_for_continue() restores sdk_session_id from DB
3. History API returns sdk_session_id
4. PromptRequest accepts resume_session_id
5. SDK resume skips history injection
"""

import pytest


@pytest.fixture
def test_db(tmp_path):
    """Create temporary database for testing."""
    db_path = tmp_path / "test_datastore.db"

    # Import and set test path
    from assistant import session_store
    session_store._set_db_path(db_path)

    yield db_path

    # Cleanup
    session_store._reset_db_path()
    if db_path.exists():
        db_path.unlink()


class TestSDKSessionPersistence:
    """Tests for SDK session ID persistence [FIX 039]."""

    def test_complete_session_with_sdk_session_id(self, test_db):
        """complete_session() stores sdk_session_id in DB."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        sdk_session_id = "sdk-test-session-12345"

        # Complete with sdk_session_id
        result = session_store.complete_session(session_id, sdk_session_id=sdk_session_id)
        assert result is True

        # Verify it's stored
        session = session_store.get_session(session_id)
        assert session is not None
        assert session.get("sdk_session_id") == sdk_session_id

    def test_complete_session_without_sdk_session_id(self, test_db):
        """complete_session() works without sdk_session_id (backwards compat)."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        result = session_store.complete_session(session_id)
        assert result is True

        session = session_store.get_session(session_id)
        assert session.get("sdk_session_id") is None

    def test_reactivate_session_preserves_sdk_session_id(self, test_db):
        """reactivate_session() preserves sdk_session_id."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        sdk_session_id = "sdk-preserved-session-789"

        session_store.complete_session(session_id, sdk_session_id=sdk_session_id)
        session_store.reactivate_session(session_id)

        session = session_store.get_session(session_id)
        assert session["status"] == "active"
        assert session.get("sdk_session_id") == sdk_session_id


class TestLoadSessionForContinue:
    """Tests for load_session_for_continue [Phase 1]."""

    def test_load_session_restores_sdk_session_id(self, test_db):
        """load_session_for_continue sets _last_sdk_session_id."""
        from assistant import session_store
        from assistant.core import state

        # Create and complete session with SDK ID
        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        session_store.add_turn(session_id, "user", "Hello")
        session_store.add_turn(session_id, "assistant", "Hi there!")
        sdk_session_id = "sdk-resume-test-456"
        session_store.complete_session(session_id, sdk_session_id=sdk_session_id)

        # Clear any existing state
        state.clear_sdk_session_id()
        assert state.get_sdk_session_id() is None

        # Load session for continue
        context = state.load_session_for_continue(session_id)
        assert context is not None

        # Verify SDK session ID was restored
        restored_id = state.get_sdk_session_id()
        assert restored_id == sdk_session_id

    def test_load_session_without_sdk_session_id(self, test_db):
        """load_session_for_continue handles missing sdk_session_id."""
        from assistant import session_store
        from assistant.core import state

        # Create session without SDK ID (non-SDK backend)
        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session_store.add_turn(session_id, "user", "Test")
        session_store.complete_session(session_id)

        # Clear state
        state.clear_sdk_session_id()

        # Load session
        context = state.load_session_for_continue(session_id)
        assert context is not None

        # SDK session ID should still be None
        assert state.get_sdk_session_id() is None


class TestPromptRequest:
    """Tests for PromptRequest model [Phase 5]."""

    def test_prompt_request_accepts_resume_session_id(self):
        """PromptRequest model accepts resume_session_id field."""
        from assistant.routes.execution import PromptRequest

        # Create with resume_session_id
        request = PromptRequest(
            prompt="Test prompt",
            continue_context=True,
            resume_session_id="sdk-session-12345"
        )

        assert request.prompt == "Test prompt"
        assert request.continue_context is True
        assert request.resume_session_id == "sdk-session-12345"

    def test_prompt_request_resume_session_id_optional(self):
        """PromptRequest resume_session_id is optional."""
        from assistant.routes.execution import PromptRequest

        request = PromptRequest(prompt="Test prompt")

        assert request.resume_session_id is None


class TestBuildContinuationPrompt:
    """Tests for SDK resume history skip [Phase 7]."""

    def test_sdk_resume_skips_history_injection(self, test_db):
        """When use_sdk_resume=True, history is NOT injected."""
        from assistant.core import state

        # Set up conversation history
        state.clear_conversation_history()
        state.add_to_history("user", "Previous question")
        state.add_to_history("assistant", "Previous answer")

        # Set SDK session ID (simulates resume)
        state.set_sdk_session_id("sdk-test-session")

        # Build continuation with SDK resume
        prompt = state.build_continuation_prompt("New question", use_sdk_resume=True)

        # Should NOT contain history
        assert "Vorheriger Konversationsverlauf" not in prompt
        assert "Previous question" not in prompt
        assert prompt == "New question"

    def test_normal_continuation_includes_history(self, test_db):
        """When use_sdk_resume=False, history IS injected."""
        from assistant.core import state

        # Set up conversation history
        state.clear_conversation_history()
        state.add_to_history("user", "Previous question")
        state.add_to_history("assistant", "Previous answer")

        # Build continuation WITHOUT SDK resume
        prompt = state.build_continuation_prompt("New question", use_sdk_resume=False)

        # Should contain history
        assert "Vorheriger Konversationsverlauf" in prompt
        assert "Previous question" in prompt

    def test_sdk_resume_without_session_id_includes_history(self, test_db):
        """When use_sdk_resume=True but no session ID, history IS injected."""
        from assistant.core import state

        # Set up conversation history
        state.clear_conversation_history()
        state.add_to_history("user", "Previous question")
        state.add_to_history("assistant", "Previous answer")

        # Clear SDK session ID
        state.clear_sdk_session_id()
        assert state.get_sdk_session_id() is None

        # Build continuation with use_sdk_resume=True but no session
        prompt = state.build_continuation_prompt("New question", use_sdk_resume=True)

        # Should still contain history (no session to resume from)
        assert "Vorheriger Konversationsverlauf" in prompt


class TestAgentTaskResumeSessionId:
    """Tests for AgentTask resume_session_id field [Phase 6b]."""

    def test_agent_task_has_resume_session_id_field(self):
        """AgentTask dataclass has resume_session_id field."""
        from assistant.core.agent_task import AgentTask, TaskType

        task = AgentTask(
            task_id="test-123",
            task_type=TaskType.PROMPT,
            name="Test prompt",
            icon=None,
            resume_session_id="sdk-session-to-resume"
        )

        assert task.resume_session_id == "sdk-session-to-resume"

    def test_agent_task_resume_session_id_optional(self):
        """AgentTask resume_session_id is optional."""
        from assistant.core.agent_task import AgentTask, TaskType

        task = AgentTask(
            task_id="test-123",
            task_type=TaskType.PROMPT,
            name="Test prompt",
            icon=None
        )

        assert task.resume_session_id is None


class TestRunTrackedPrompt:
    """Tests for run_tracked_prompt resume parameter [Phase 6a-2]."""

    def test_run_tracked_prompt_signature_has_resume_session_id(self):
        """run_tracked_prompt() has resume_session_id parameter."""
        import inspect
        from assistant.core.executor import run_tracked_prompt

        sig = inspect.signature(run_tracked_prompt)
        params = list(sig.parameters.keys())

        assert "resume_session_id" in params
