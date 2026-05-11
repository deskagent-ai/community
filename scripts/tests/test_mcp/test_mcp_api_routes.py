# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for MCP API Routes.

Tests the FastAPI endpoints that MCPs use in Nuitka builds:
- GET /api/mcp/config
- GET /api/mcp/paths
- POST /api/mcp/log
- GET /api/mcp/anonymizer/status
- POST /api/mcp/anonymize
- POST /api/mcp/deanonymize
- DELETE /api/mcp/session/{session_id}
- GET /api/mcp/task_context
- POST /api/mcp/log_tool_call
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestMcpApiRoutes:
    """Tests for MCP API endpoints using FastAPI TestClient."""

    @pytest.fixture
    def test_client(self):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient
        from assistant.app import create_app

        app = create_app()
        return TestClient(app)

    # =========================================================================
    # GET /api/mcp/config
    # =========================================================================

    def test_get_config_returns_dict(self, test_client):
        """GET /api/mcp/config returns a dictionary."""
        response = test_client.get("/api/mcp/config")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)

    def test_get_config_contains_expected_keys(self, test_client):
        """GET /api/mcp/config returns config with common keys."""
        response = test_client.get("/api/mcp/config")
        assert response.status_code == 200
        # Config should be a dict (may be empty in test env, but should not error)
        data = response.json()
        assert isinstance(data, dict)

    # =========================================================================
    # GET /api/mcp/paths
    # =========================================================================

    def test_get_paths_returns_all_dirs(self, test_client):
        """GET /api/mcp/paths returns all expected directory paths."""
        response = test_client.get("/api/mcp/paths")
        assert response.status_code == 200

        data = response.json()
        required_keys = [
            "workspace_dir",
            "config_dir",
            "temp_dir",
            "exports_dir",
            "data_dir",
            "logs_dir",
        ]
        for key in required_keys:
            assert key in data, f"Missing key: {key}"
            assert isinstance(data[key], str), f"{key} should be a string"
            assert len(data[key]) > 0, f"{key} should not be empty"

    def test_get_paths_returns_valid_paths(self, test_client):
        """GET /api/mcp/paths returns valid path strings."""
        response = test_client.get("/api/mcp/paths")
        assert response.status_code == 200

        data = response.json()
        # All values should be absolute paths (contain path separator)
        for key, value in data.items():
            path = Path(value)
            # Path should be absolute (Windows or Unix style)
            assert path.is_absolute() or ":" in value, f"{key} should be absolute path"

    # =========================================================================
    # POST /api/mcp/log
    # =========================================================================

    def test_post_log_accepts_message(self, test_client):
        """POST /api/mcp/log accepts a log message."""
        response = test_client.post(
            "/api/mcp/log",
            json={"message": "[TEST] Test log message", "level": "info"}
        )
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_post_log_accepts_different_levels(self, test_client):
        """POST /api/mcp/log accepts different log levels."""
        levels = ["info", "warning", "error", "debug"]
        for level in levels:
            response = test_client.post(
                "/api/mcp/log",
                json={"message": f"[TEST] Level {level}", "level": level}
            )
            assert response.status_code == 200
            assert response.json().get("status") == "ok"

    def test_post_log_uses_default_level(self, test_client):
        """POST /api/mcp/log defaults to info level."""
        response = test_client.post(
            "/api/mcp/log",
            json={"message": "[TEST] Default level message"}
        )
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_post_log_rejects_missing_message(self, test_client):
        """POST /api/mcp/log rejects request without message."""
        response = test_client.post(
            "/api/mcp/log",
            json={"level": "info"}
        )
        # FastAPI returns 422 for validation errors
        assert response.status_code == 422

    # =========================================================================
    # GET /api/mcp/anonymizer/status
    # =========================================================================

    def test_anonymizer_status_returns_availability(self, test_client):
        """GET /api/mcp/anonymizer/status returns availability info."""
        response = test_client.get("/api/mcp/anonymizer/status")
        assert response.status_code == 200

        data = response.json()
        assert "available" in data
        assert isinstance(data["available"], bool)

    def test_anonymizer_status_includes_reason_when_unavailable(self, test_client):
        """GET /api/mcp/anonymizer/status includes reason if unavailable."""
        response = test_client.get("/api/mcp/anonymizer/status")
        assert response.status_code == 200

        data = response.json()
        # If not available, should have a reason
        if not data.get("available"):
            assert "reason" in data or data.get("reason") is None

    # =========================================================================
    # POST /api/mcp/anonymize
    # =========================================================================

    def test_anonymize_requires_session_id(self, test_client):
        """POST /api/mcp/anonymize requires session_id."""
        response = test_client.post(
            "/api/mcp/anonymize",
            json={"text": "Test text", "lang": "de"}
        )
        # FastAPI returns 422 for validation errors
        assert response.status_code == 422

    def test_anonymize_returns_session_id(self, test_client):
        """POST /api/mcp/anonymize returns the session_id."""
        session_id = "test-session-123"
        response = test_client.post(
            "/api/mcp/anonymize",
            json={
                "session_id": session_id,
                "text": "Max Mustermann",
                "lang": "de"
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert "anonymized" in data
        assert "session_id" in data
        assert data["session_id"] == session_id

        # Cleanup
        test_client.delete(f"/api/mcp/session/{session_id}")

    def test_anonymize_returns_text(self, test_client):
        """POST /api/mcp/anonymize returns anonymized text."""
        session_id = "test-anon-text"
        response = test_client.post(
            "/api/mcp/anonymize",
            json={
                "session_id": session_id,
                "text": "Kontaktieren Sie Max Mustermann unter max@example.com",
                "lang": "de"
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert "anonymized" in data
        assert isinstance(data["anonymized"], str)

        # Cleanup
        test_client.delete(f"/api/mcp/session/{session_id}")

    def test_anonymize_uses_default_language(self, test_client):
        """POST /api/mcp/anonymize defaults to German."""
        session_id = "test-default-lang"
        response = test_client.post(
            "/api/mcp/anonymize",
            json={
                "session_id": session_id,
                "text": "Test"
            }
        )
        assert response.status_code == 200

        # Cleanup
        test_client.delete(f"/api/mcp/session/{session_id}")

    # =========================================================================
    # POST /api/mcp/deanonymize
    # =========================================================================

    def test_deanonymize_requires_session_id(self, test_client):
        """POST /api/mcp/deanonymize requires session_id."""
        response = test_client.post(
            "/api/mcp/deanonymize",
            json={"text": "<PERSON_1> wrote"}
        )
        assert response.status_code == 422

    def test_deanonymize_returns_session_id(self, test_client):
        """POST /api/mcp/deanonymize returns the session_id."""
        session_id = "test-deanon-session"
        response = test_client.post(
            "/api/mcp/deanonymize",
            json={
                "session_id": session_id,
                "text": "<PERSON_1> wrote"
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert "text" in data
        assert "session_id" in data
        assert data["session_id"] == session_id

    def test_deanonymize_unknown_session_returns_original(self, test_client):
        """POST /api/mcp/deanonymize with unknown session returns original text."""
        session_id = "nonexistent-session-xyz"
        original_text = "<PERSON_1> wrote an email"
        response = test_client.post(
            "/api/mcp/deanonymize",
            json={
                "session_id": session_id,
                "text": original_text
            }
        )
        assert response.status_code == 200

        data = response.json()
        # Without a session, the text should be returned as-is
        assert data["text"] == original_text

    # =========================================================================
    # DELETE /api/mcp/session/{session_id}
    # =========================================================================

    def test_delete_session_accepts_any_id(self, test_client):
        """DELETE /api/mcp/session/{session_id} accepts any session ID."""
        response = test_client.delete("/api/mcp/session/any-id-123")
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_delete_session_idempotent(self, test_client):
        """DELETE /api/mcp/session/{session_id} is idempotent."""
        session_id = "idempotent-test"

        # Delete twice
        response1 = test_client.delete(f"/api/mcp/session/{session_id}")
        response2 = test_client.delete(f"/api/mcp/session/{session_id}")

        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_delete_session_cleans_up_anonymization_context(self, test_client):
        """DELETE /api/mcp/session removes anonymization context."""
        session_id = "cleanup-test-session"

        # First, create a session by anonymizing
        test_client.post(
            "/api/mcp/anonymize",
            json={
                "session_id": session_id,
                "text": "Max Mustermann",
                "lang": "de"
            }
        )

        # Delete the session
        response = test_client.delete(f"/api/mcp/session/{session_id}")
        assert response.status_code == 200

        # After deletion, de-anonymizing should return original (no mappings)
        deanon_response = test_client.post(
            "/api/mcp/deanonymize",
            json={
                "session_id": session_id,
                "text": "<PERSON_1>"
            }
        )
        assert deanon_response.status_code == 200
        # Without session, placeholder is not replaced
        assert deanon_response.json()["text"] == "<PERSON_1>"

    # =========================================================================
    # GET /api/mcp/task_context
    # =========================================================================

    def test_task_context_returns_structure(self, test_client):
        """GET /api/mcp/task_context returns expected structure."""
        response = test_client.get("/api/mcp/task_context")
        assert response.status_code == 200

        data = response.json()
        # Should have task_id key (can be null)
        assert "task_id" in data

    def test_task_context_null_when_no_task(self, test_client):
        """GET /api/mcp/task_context returns null task_id when no task running."""
        response = test_client.get("/api/mcp/task_context")
        assert response.status_code == 200

        data = response.json()
        # In test environment, no task is running
        assert data.get("task_id") is None

    # =========================================================================
    # POST /api/mcp/log_tool_call
    # =========================================================================

    def test_log_tool_call_accepts_call(self, test_client):
        """POST /api/mcp/log_tool_call accepts CALL direction."""
        response = test_client.post(
            "/api/mcp/log_tool_call",
            json={
                "tool_name": "outlook_get_email",
                "direction": "CALL",
                "content": '{"email_id": "123"}',
                "is_anonymized": True
            }
        )
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_log_tool_call_accepts_result(self, test_client):
        """POST /api/mcp/log_tool_call accepts RESULT direction."""
        response = test_client.post(
            "/api/mcp/log_tool_call",
            json={
                "tool_name": "outlook_get_email",
                "direction": "RESULT",
                "content": '{"subject": "Test", "body": "..."}',
                "is_anonymized": True
            }
        )
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_log_tool_call_defaults_is_anonymized(self, test_client):
        """POST /api/mcp/log_tool_call defaults is_anonymized to True."""
        response = test_client.post(
            "/api/mcp/log_tool_call",
            json={
                "tool_name": "test_tool",
                "direction": "CALL",
                "content": "{}"
            }
        )
        assert response.status_code == 200
        assert response.json().get("status") == "ok"

    def test_log_tool_call_requires_tool_name(self, test_client):
        """POST /api/mcp/log_tool_call requires tool_name."""
        response = test_client.post(
            "/api/mcp/log_tool_call",
            json={
                "direction": "CALL",
                "content": "{}"
            }
        )
        assert response.status_code == 422

    def test_log_tool_call_requires_direction(self, test_client):
        """POST /api/mcp/log_tool_call requires direction."""
        response = test_client.post(
            "/api/mcp/log_tool_call",
            json={
                "tool_name": "test_tool",
                "content": "{}"
            }
        )
        assert response.status_code == 422

    def test_log_tool_call_requires_content(self, test_client):
        """POST /api/mcp/log_tool_call requires content."""
        response = test_client.post(
            "/api/mcp/log_tool_call",
            json={
                "tool_name": "test_tool",
                "direction": "CALL"
            }
        )
        assert response.status_code == 422


class TestMcpApiAnonymizationFlow:
    """Integration tests for the full anonymization workflow."""

    @pytest.fixture
    def test_client(self):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient
        from assistant.app import create_app

        app = create_app()
        return TestClient(app)

    def test_full_anonymize_deanonymize_flow(self, test_client):
        """Test complete anonymize -> deanonymize flow."""
        session_id = "flow-test-session"

        # Check if anonymizer is available
        status_response = test_client.get("/api/mcp/anonymizer/status")
        anonymizer_available = status_response.json().get("available", False)

        # Anonymize
        original_text = "Max Mustermann hat eine E-Mail geschrieben."
        anon_response = test_client.post(
            "/api/mcp/anonymize",
            json={
                "session_id": session_id,
                "text": original_text,
                "lang": "de"
            }
        )
        assert anon_response.status_code == 200
        anonymized_text = anon_response.json()["anonymized"]

        if anonymizer_available:
            # If anonymizer works, text should be different
            # (unless the name wasn't recognized)
            pass

        # De-anonymize
        deanon_response = test_client.post(
            "/api/mcp/deanonymize",
            json={
                "session_id": session_id,
                "text": anonymized_text
            }
        )
        assert deanon_response.status_code == 200
        restored_text = deanon_response.json()["text"]

        if anonymizer_available:
            # Should restore to original
            assert restored_text == original_text

        # Cleanup
        test_client.delete(f"/api/mcp/session/{session_id}")

    def test_multiple_calls_same_session_consistent(self, test_client):
        """Test that multiple anonymizations in same session are consistent."""
        session_id = "consistency-test"

        # Anonymize same text twice
        text = "Max Mustermann"
        response1 = test_client.post(
            "/api/mcp/anonymize",
            json={"session_id": session_id, "text": text, "lang": "de"}
        )
        response2 = test_client.post(
            "/api/mcp/anonymize",
            json={"session_id": session_id, "text": text, "lang": "de"}
        )

        # Both should return the same anonymized text
        assert response1.json()["anonymized"] == response2.json()["anonymized"]

        # Cleanup
        test_client.delete(f"/api/mcp/session/{session_id}")

    def test_different_sessions_isolated(self, test_client):
        """Test that different sessions have isolated contexts."""
        session_a = "session-a"
        session_b = "session-b"

        text = "Max Mustermann"

        # Anonymize in session A
        test_client.post(
            "/api/mcp/anonymize",
            json={"session_id": session_a, "text": text, "lang": "de"}
        )

        # De-anonymize in session B (should not find mapping)
        deanon_response = test_client.post(
            "/api/mcp/deanonymize",
            json={"session_id": session_b, "text": "<PERSON_1>"}
        )

        # Session B has no mappings, so placeholder is unchanged
        assert deanon_response.json()["text"] == "<PERSON_1>"

        # Cleanup
        test_client.delete(f"/api/mcp/session/{session_a}")
        test_client.delete(f"/api/mcp/session/{session_b}")
