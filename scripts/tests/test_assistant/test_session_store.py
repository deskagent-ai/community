# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Unit tests for session_store module.
"""

import os
import sqlite3
import time
from pathlib import Path

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


class TestSessionStore:
    """Unit tests for session_store module."""

    def test_create_session(self, test_db):
        """Test session creation."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")

        assert session_id.startswith("s_")
        assert len(session_id) == 21  # s_YYYYMMDD_HHMMSS_mmm (with milliseconds)

        session = session_store.get_session(session_id)
        assert session is not None
        assert session["agent_name"] == "chat"
        assert session["backend"] == "claude_sdk"
        assert session["model"] == "claude-sonnet-4"
        assert session["status"] == "active"

    def test_create_session_without_model(self, test_db):
        """Test session creation without model specified."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini")

        session = session_store.get_session(session_id)
        assert session is not None
        assert session["model"] is None

    def test_add_turn(self, test_db):
        """Test adding turns to session."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        session_store.add_turn(session_id, "user", "Hello, how are you?")
        session_store.add_turn(session_id, "assistant", "I'm doing well!",
                               tokens=50, cost_usd=0.001)

        session = session_store.get_session(session_id)
        assert len(session["turns"]) == 2
        assert session["turns"][0]["role"] == "user"
        assert session["turns"][0]["content"] == "Hello, how are you?"
        assert session["turns"][1]["role"] == "assistant"
        assert session["turns"][1]["content"] == "I'm doing well!"
        assert session["turns"][1]["tokens"] == 50
        assert session["turns"][1]["cost_usd"] == 0.001
        assert session["total_tokens"] == 50
        assert session["total_cost_usd"] == 0.001

    def test_add_turn_invalid_session(self, test_db):
        """Test adding turn to non-existent session."""
        from assistant import session_store

        result = session_store.add_turn("nonexistent", "user", "Test")
        assert result is False

    def test_add_turn_with_task_id(self, test_db):
        """Test adding turn with task_id reference."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        session_store.add_turn(session_id, "assistant", "Response",
                               tokens=100, cost_usd=0.01, task_id="task_123")

        session = session_store.get_session(session_id)
        assert session["turns"][0]["task_id"] == "task_123"

    def test_content_truncation(self, test_db):
        """Test that very long content is truncated."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        long_content = "x" * 60000  # Exceeds MAX_CONTENT_LENGTH (50000)

        session_store.add_turn(session_id, "assistant", long_content)

        session = session_store.get_session(session_id)
        assert len(session["turns"][0]["content"]) <= 50100  # MAX + truncation notice
        assert "[... truncated ...]" in session["turns"][0]["content"]

    def test_preview_set_on_first_user_message(self, test_db):
        """Test that preview is set from first user message."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        session = session_store.get_session(session_id)
        assert session["preview"] is None

        session_store.add_turn(session_id, "user", "What is Python programming?")

        session = session_store.get_session(session_id)
        assert session["preview"] == "What is Python programming?"

    def test_preview_truncated_for_long_message(self, test_db):
        """Test that preview is truncated for long messages."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        long_message = "A" * 200

        session_store.add_turn(session_id, "user", long_message)

        session = session_store.get_session(session_id)
        assert len(session["preview"]) == 103  # 100 chars + "..."
        assert session["preview"].endswith("...")

    def test_get_session_context(self, test_db):
        """Test context building for continue/transfer."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session_store.add_turn(session_id, "user", "What is Python?")
        session_store.add_turn(session_id, "assistant", "Python is a programming language.")
        session_store.add_turn(session_id, "user", "Show me an example.")
        session_store.add_turn(session_id, "assistant", "Here's a simple example: print('Hello')")

        context = session_store.get_session_context(session_id)

        assert "previous conversation" in context.lower()
        assert "What is Python?" in context
        assert "Python is a programming language" in context
        assert "Show me an example" in context
        assert "User:" in context
        assert "Assistant:" in context
        assert "---" in context

    def test_get_session_context_truncation(self, test_db):
        """Test context truncation for many turns."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        # Add 15 turns (more than MAX_TURNS_FOR_CONTEXT)
        for i in range(15):
            session_store.add_turn(session_id, "user", f"Question {i}")
            session_store.add_turn(session_id, "assistant", f"Answer {i}")

        context = session_store.get_session_context(session_id, max_turns=10)

        # Should show truncation notice
        assert "Showing last 10" in context
        # Should contain later messages, not earlier ones
        assert "Question 14" in context or "Answer 14" in context

    def test_get_sessions_pagination(self, test_db):
        """Test session list with pagination."""
        from assistant import session_store

        # Create 5 sessions
        for i in range(5):
            session_store.create_session(f"agent_{i}", "claude_sdk", "claude-sonnet-4")
            time.sleep(0.01)  # Ensure different timestamps

        # Get first page
        page1 = session_store.get_sessions(limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = session_store.get_sessions(limit=2, offset=2)
        assert len(page2) == 2

        # Verify no overlap
        ids_page1 = {s["id"] for s in page1}
        ids_page2 = {s["id"] for s in page2}
        assert ids_page1.isdisjoint(ids_page2)

    def test_get_sessions_filter_by_agent(self, test_db):
        """Test session list filtered by agent name."""
        from assistant import session_store

        session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session_store.create_session("chat_claude", "claude_sdk", "claude-sonnet-4")
        session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        sessions = session_store.get_sessions(agent_name="chat")
        assert len(sessions) == 2
        for s in sessions:
            assert s["agent_name"] == "chat"

    def test_get_sessions_filter_by_status(self, test_db):
        """Test session list filtered by status."""
        from assistant import session_store

        s1 = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        s2 = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        session_store.complete_session(s1)

        active = session_store.get_sessions(status="active")
        completed = session_store.get_sessions(status="completed")

        assert len(active) == 1
        assert len(completed) == 1
        assert active[0]["id"] == s2
        assert completed[0]["id"] == s1

    def test_get_sessions_includes_turn_count(self, test_db):
        """Test that session list includes turn count."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session_store.add_turn(session_id, "user", "Test 1")
        session_store.add_turn(session_id, "assistant", "Response 1")
        session_store.add_turn(session_id, "user", "Test 2")

        sessions = session_store.get_sessions()
        assert sessions[0]["turn_count"] == 3

    def test_cleanup_old_sessions(self, test_db):
        """Test that cleanup respects max_sessions."""
        from assistant import session_store

        # Create 10 sessions
        for i in range(10):
            session_store.create_session("chat", "gemini", "gemini-2.5-pro")
            time.sleep(0.01)

        # Cleanup to max 5
        deleted = session_store.cleanup_old_sessions(max_sessions=5)

        assert deleted == 5
        remaining = session_store.get_sessions(limit=100)
        assert len(remaining) == 5

    def test_delete_session_cascades(self, test_db):
        """Test that deleting session also deletes turns."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        session_store.add_turn(session_id, "user", "Test message")
        session_store.add_turn(session_id, "assistant", "Test response")

        success = session_store.delete_session(session_id)

        assert success is True
        assert session_store.get_session(session_id) is None

        # Verify turns are also deleted (check directly in DB)
        conn = session_store.get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,))
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0

    def test_delete_nonexistent_session(self, test_db):
        """Test deleting non-existent session returns False."""
        from assistant import session_store

        result = session_store.delete_session("nonexistent")
        assert result is False

    def test_get_active_session(self, test_db):
        """Test finding active session within timeout."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        # Should find active session
        active = session_store.get_active_session("chat")
        assert active == session_id

        # Should not find for different agent
        active_other = session_store.get_active_session("chat_claude")
        assert active_other is None

    def test_complete_session(self, test_db):
        """Test marking session as completed."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")
        session_store.complete_session(session_id)

        session = session_store.get_session(session_id)
        assert session["status"] == "completed"

        # Completed session should not be found as active
        active = session_store.get_active_session("chat")
        assert active is None

    def test_complete_nonexistent_session(self, test_db):
        """Test completing non-existent session returns False."""
        from assistant import session_store

        result = session_store.complete_session("nonexistent")
        assert result is False

    def test_get_stats(self, test_db):
        """Test statistics retrieval."""
        from assistant import session_store

        # Create some sessions with turns
        s1 = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        s2 = session_store.create_session("chat_claude", "claude_sdk", "claude-sonnet-4")

        session_store.add_turn(s1, "user", "Test 1")
        session_store.add_turn(s1, "assistant", "Response 1", tokens=100, cost_usd=0.01)
        session_store.add_turn(s2, "user", "Test 2")
        session_store.add_turn(s2, "assistant", "Response 2", tokens=200, cost_usd=0.02)

        session_store.complete_session(s1)

        stats = session_store.get_stats()

        assert stats["total_sessions"] == 2
        assert stats["active_sessions"] == 1
        assert stats["completed_sessions"] == 1
        assert stats["total_turns"] == 4
        assert stats["total_tokens"] == 300
        assert stats["total_cost_usd"] == 0.03

    def test_auto_complete_stale_sessions(self, test_db):
        """Test auto-completing stale sessions."""
        from assistant import session_store
        from datetime import datetime, timedelta

        # Create a session
        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        # Manually set updated_at to be older than timeout
        old_time = (datetime.now() - timedelta(minutes=40)).isoformat()
        conn = session_store.get_connection()
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (old_time, session_id))
        conn.commit()
        conn.close()

        # Run auto-complete
        completed = session_store.auto_complete_stale_sessions()

        assert completed == 1
        session = session_store.get_session(session_id)
        assert session["status"] == "completed"


class TestSessionStoreEdgeCases:
    """Edge case tests."""

    def test_empty_session(self, test_db):
        """Test session with no turns."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session = session_store.get_session(session_id)

        assert session["turns"] == []
        assert session["total_tokens"] == 0
        assert session["total_cost_usd"] == 0.0

    def test_nonexistent_session(self, test_db):
        """Test accessing non-existent session."""
        from assistant import session_store

        session = session_store.get_session("nonexistent_id")
        assert session is None

        context = session_store.get_session_context("nonexistent_id")
        assert context == ""

    def test_special_characters_in_content(self, test_db):
        """Test content with special characters."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")

        special_content = "Test with emojis and \"quotes\" and 'apostrophes' and\nnewlines"
        session_store.add_turn(session_id, "user", special_content)

        session = session_store.get_session(session_id)
        assert session["turns"][0]["content"] == special_content

    def test_unicode_content(self, test_db):
        """Test content with unicode characters."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")

        unicode_content = "Umlaute: aou and Chinese: Zhongwen and Arabic: Arabi"
        session_store.add_turn(session_id, "user", unicode_content)

        session = session_store.get_session(session_id)
        assert session["turns"][0]["content"] == unicode_content

    def test_concurrent_sessions(self, test_db):
        """Test multiple concurrent sessions for different agents."""
        from assistant import session_store

        s1 = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        s2 = session_store.create_session("chat_claude", "claude_sdk", "claude-sonnet-4")

        session_store.add_turn(s1, "user", "Gemini question")
        session_store.add_turn(s2, "user", "Claude question")

        # Both should be retrievable
        assert session_store.get_session(s1) is not None
        assert session_store.get_session(s2) is not None

        # Each should be the active session for its agent
        assert session_store.get_active_session("chat") == s1
        assert session_store.get_active_session("chat_claude") == s2

    def test_empty_stats(self, test_db):
        """Test stats with no sessions."""
        from assistant import session_store

        stats = session_store.get_stats()

        assert stats["total_sessions"] == 0
        assert stats["active_sessions"] == 0
        assert stats["completed_sessions"] == 0
        assert stats["total_turns"] == 0
        assert stats["total_tokens"] == 0
        assert stats["total_cost_usd"] == 0.0

    def test_cleanup_when_under_limit(self, test_db):
        """Test cleanup does nothing when under limit."""
        from assistant import session_store

        session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        deleted = session_store.cleanup_old_sessions(max_sessions=10)

        assert deleted == 0
        assert len(session_store.get_sessions(limit=100)) == 2

    def test_multiple_turns_same_session(self, test_db):
        """Test adding many turns to same session."""
        from assistant import session_store

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        for i in range(20):
            session_store.add_turn(session_id, "user", f"Question {i}")
            session_store.add_turn(session_id, "assistant", f"Answer {i}", tokens=10, cost_usd=0.001)

        session = session_store.get_session(session_id)
        assert len(session["turns"]) == 40
        assert session["total_tokens"] == 200  # 20 * 10
        assert abs(session["total_cost_usd"] - 0.02) < 0.0001  # 20 * 0.001

    def test_session_id_format(self, test_db):
        """Test session ID follows expected format."""
        from assistant import session_store
        import re

        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")

        # Format: s_YYYYMMDD_HHMMSS_mmm (with milliseconds)
        pattern = r"^s_\d{8}_\d{6}_\d{3}$"
        assert re.match(pattern, session_id) is not None


class TestRWLockConcurrency:
    """Tests for Read-Write Lock concurrent access."""

    def test_concurrent_reads(self, test_db):
        """Test that multiple concurrent reads can proceed simultaneously."""
        import threading
        from assistant import session_store

        # Create some test data
        session_id = session_store.create_session("chat", "gemini", "gemini-2.5-pro")
        session_store.add_turn(session_id, "user", "Test message")

        results = []
        errors = []

        def read_session():
            try:
                session = session_store.get_session(session_id)
                if session:
                    results.append(session["id"])
                else:
                    errors.append("Session not found")
            except Exception as e:
                errors.append(str(e))

        # Start multiple concurrent readers
        threads = [threading.Thread(target=read_session) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # All reads should succeed
        assert len(errors) == 0
        assert len(results) == 10
        assert all(r == session_id for r in results)

    def test_read_write_interleaving(self, test_db):
        """Test that reads and writes interleave correctly."""
        import threading
        from assistant import session_store

        session_id = session_store.create_session("chat", "claude_sdk", "claude-sonnet-4")

        read_results = []
        write_results = []

        def read_session():
            for _ in range(5):
                session = session_store.get_session(session_id)
                if session:
                    read_results.append(len(session.get("turns", [])))

        def write_turn(turn_num):
            result = session_store.add_turn(session_id, "user", f"Message {turn_num}")
            if result:
                write_results.append(turn_num)

        # Start readers and writers concurrently
        readers = [threading.Thread(target=read_session) for _ in range(3)]
        writers = [threading.Thread(target=write_turn, args=(i,)) for i in range(5)]

        all_threads = readers + writers
        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join(timeout=10)

        # All writes should succeed
        assert len(write_results) == 5

        # Final session should have all turns
        final_session = session_store.get_session(session_id)
        assert len(final_session["turns"]) == 5

    def test_rwlock_basic_functionality(self, test_db):
        """Test RWLock basic acquire/release operations."""
        from assistant.session_store import RWLock, read_lock, write_lock

        rwlock = RWLock()

        # Test basic read lock
        with read_lock(rwlock):
            assert rwlock._readers == 1

        assert rwlock._readers == 0

        # Test basic write lock
        with write_lock(rwlock):
            assert rwlock._writer_active is True

        assert rwlock._writer_active is False

    def test_multiple_readers_allowed(self, test_db):
        """Test that multiple readers can hold the lock simultaneously."""
        import threading
        from assistant.session_store import RWLock

        rwlock = RWLock()
        reader_count = []
        barrier = threading.Barrier(3)

        def reader():
            rwlock.acquire_read()
            try:
                # Wait for all readers to acquire
                barrier.wait(timeout=2)
                reader_count.append(rwlock._readers)
                barrier.wait(timeout=2)
            finally:
                rwlock.release_read()

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # All readers should have seen count of 3
        assert all(c == 3 for c in reader_count)
