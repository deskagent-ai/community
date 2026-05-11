# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for V2 Link Placeholder System - Registry API.
Tests link registration, retrieval, and session management.
"""

import pytest


class TestLinkRegistryAPI:
    """Tests for link registry functions in mcp_api.py."""

    def test_register_and_get_link(self):
        """Test basic register and get flow."""
        from assistant.routes.mcp_api import (
            _link_sessions,
            get_link_map_for_session,
            clear_link_session
        )

        # Clear any existing test session
        clear_link_session("test-session-1")

        # Register a link directly in the storage (simulating API call)
        session_id = "test-session-1"
        if session_id not in _link_sessions:
            _link_sessions[session_id] = {}
        _link_sessions[session_id]["abc12345"] = "https://example.com/mail/123"

        # Get link map
        link_map = get_link_map_for_session(session_id)
        assert link_map == {"abc12345": "https://example.com/mail/123"}

        # Cleanup
        clear_link_session(session_id)
        assert get_link_map_for_session(session_id) == {}

    def test_multiple_links_same_session(self):
        """Test multiple links in same session."""
        from assistant.routes.mcp_api import (
            _link_sessions,
            get_link_map_for_session,
            clear_link_session
        )

        session_id = "test-session-2"
        clear_link_session(session_id)

        # Register multiple links
        _link_sessions[session_id] = {
            "mail001": "https://mail/1",
            "event01": "https://calendar/1",
            "doc0001": "https://docs/1",
        }

        link_map = get_link_map_for_session(session_id)
        assert len(link_map) == 3
        assert link_map["mail001"] == "https://mail/1"
        assert link_map["event01"] == "https://calendar/1"
        assert link_map["doc0001"] == "https://docs/1"

        clear_link_session(session_id)

    def test_session_isolation(self):
        """Test that sessions are isolated from each other."""
        from assistant.routes.mcp_api import (
            _link_sessions,
            get_link_map_for_session,
            clear_link_session
        )

        session_a = "test-session-a"
        session_b = "test-session-b"
        clear_link_session(session_a)
        clear_link_session(session_b)

        # Register links in different sessions
        _link_sessions[session_a] = {"linkA": "https://a"}
        _link_sessions[session_b] = {"linkB": "https://b"}

        # Check isolation
        map_a = get_link_map_for_session(session_a)
        map_b = get_link_map_for_session(session_b)

        assert "linkA" in map_a
        assert "linkB" not in map_a
        assert "linkB" in map_b
        assert "linkA" not in map_b

        clear_link_session(session_a)
        clear_link_session(session_b)

    def test_get_nonexistent_session(self):
        """Test getting links for non-existent session returns empty dict."""
        from assistant.routes.mcp_api import get_link_map_for_session

        link_map = get_link_map_for_session("nonexistent-session-xyz")
        assert link_map == {}

    def test_clear_nonexistent_session(self):
        """Test clearing non-existent session doesn't raise error."""
        from assistant.routes.mcp_api import clear_link_session

        # Should not raise
        clear_link_session("nonexistent-session-xyz")

    def test_idempotent_registration(self):
        """Test that registering same link_ref twice overwrites."""
        from assistant.routes.mcp_api import (
            _link_sessions,
            get_link_map_for_session,
            clear_link_session
        )

        session_id = "test-session-3"
        clear_link_session(session_id)

        # Register link
        _link_sessions[session_id] = {}
        _link_sessions[session_id]["link001"] = "https://first.com"

        # Overwrite with new URL
        _link_sessions[session_id]["link001"] = "https://second.com"

        link_map = get_link_map_for_session(session_id)
        assert link_map["link001"] == "https://second.com"
        assert len(link_map) == 1  # Still only one entry

        clear_link_session(session_id)


class TestSessionStoreLinkMap:
    """Tests for link_map persistence in session_store."""

    @pytest.fixture
    def test_db(self, tmp_path, monkeypatch):
        """Set up test database in temp directory."""
        from assistant import session_store

        # Point to temp database
        test_db_path = tmp_path / "test_datastore.db"
        monkeypatch.setattr(session_store, "_db_path", test_db_path)

        # Clear any existing connections
        session_store._db_path = test_db_path

        yield test_db_path

    def test_complete_session_with_link_map(self, test_db):
        """Test storing link_map when completing session."""
        from assistant import session_store

        # Create session
        session_id = session_store.create_session("test_agent", "claude_sdk")

        # Complete with link_map
        link_map = {"abc123": "https://mail/1", "def456": "https://mail/2"}
        session_store.complete_session(session_id, link_map=link_map)

        # Get session and verify link_map
        session = session_store.get_session(session_id)
        assert session is not None
        assert session["link_map"] == link_map

    def test_get_link_map_function(self, test_db):
        """Test dedicated get_link_map function."""
        from assistant import session_store

        # Create and complete session with link_map
        session_id = session_store.create_session("test_agent", "claude_sdk")
        link_map = {"xyz789": "https://docs/1"}
        session_store.complete_session(session_id, link_map=link_map)

        # Get link_map using dedicated function
        retrieved = session_store.get_link_map(session_id)
        assert retrieved == link_map

    def test_update_link_map(self, test_db):
        """Test updating link_map during session."""
        from assistant import session_store

        # Create session
        session_id = session_store.create_session("test_agent", "claude_sdk")

        # Update link_map
        link_map = {"aaa": "https://1", "bbb": "https://2"}
        result = session_store.update_link_map(session_id, link_map)
        assert result is True

        # Verify
        retrieved = session_store.get_link_map(session_id)
        assert retrieved == link_map

    def test_session_without_link_map(self, test_db):
        """Test session created without link_map has empty dict."""
        from assistant import session_store

        session_id = session_store.create_session("test_agent", "claude_sdk")
        session_store.complete_session(session_id)

        session = session_store.get_session(session_id)
        assert session["link_map"] == {}

    def test_link_map_nonexistent_session(self, test_db):
        """Test get_link_map for non-existent session returns empty dict."""
        from assistant import session_store

        link_map = session_store.get_link_map("nonexistent-session-id")
        assert link_map == {}
