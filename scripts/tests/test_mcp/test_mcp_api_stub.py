# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for _mcp_api.py Stub Module.

Tests the HTTP client stub that MCPs use in Nuitka builds.
Uses mocking to test behavior without requiring a running server.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Add mcp directory to path for importing _mcp_api
MCP_DIR = SCRIPTS_DIR.parent / "mcp"
sys.path.insert(0, str(MCP_DIR))


class TestLoadConfig:
    """Tests for load_config() function."""

    def test_load_config_caches_result(self):
        """load_config() caches the result after first call."""
        # Import fresh
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"test_key": "test_value"}
            mock_get.return_value = mock_response

            # First call
            result1 = _mcp_api.load_config()
            # Second call
            result2 = _mcp_api.load_config()

            # Should only make one HTTP call (cached)
            assert mock_get.call_count == 1
            assert result1 == result2
            assert result1 == {"test_key": "test_value"}

    def test_load_config_returns_empty_dict_on_error(self):
        """load_config() returns empty dict on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.load_config()

            assert result == {}

    def test_load_config_returns_empty_dict_on_non_ok_response(self):
        """load_config() returns empty dict when response is not ok."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = False
            mock_get.return_value = mock_response

            result = _mcp_api.load_config()

            assert result == {}


class TestMcpLog:
    """Tests for mcp_log() function."""

    def test_mcp_log_sends_post_request(self):
        """mcp_log() sends a POST request to /api/mcp/log."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.return_value = Mock(ok=True)

            _mcp_api.mcp_log("[TEST] Test message", "info")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/mcp/log" in call_args[0][0]
            assert call_args[1]["json"]["message"] == "[TEST] Test message"
            assert call_args[1]["json"]["level"] == "info"

    def test_mcp_log_silent_on_error(self):
        """mcp_log() does not raise exception on error."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            # Should not raise
            _mcp_api.mcp_log("[TEST] Message")

    def test_mcp_log_uses_default_level(self):
        """mcp_log() defaults to 'info' level."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.return_value = Mock(ok=True)

            _mcp_api.mcp_log("[TEST] Default level")

            call_args = mock_post.call_args
            assert call_args[1]["json"]["level"] == "info"


class TestGetPathFunctions:
    """Tests for get_*_dir() functions."""

    def test_get_config_dir_returns_path(self):
        """get_config_dir() returns a Path object."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "config_dir": "E:/test/config",
                "workspace_dir": "E:/test/workspace"
            }
            mock_get.return_value = mock_response

            result = _mcp_api.get_config_dir()

            assert isinstance(result, Path)
            assert str(result) == "E:\\test\\config" or str(result) == "E:/test/config"

    def test_get_config_dir_fallback_on_error(self):
        """get_config_dir() returns fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_config_dir()

            assert isinstance(result, Path)
            assert "config" in str(result)

    def test_get_temp_dir_fallback_on_error(self):
        """get_temp_dir() returns fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_temp_dir()

            assert isinstance(result, Path)
            assert ".temp" in str(result)

    def test_get_exports_dir_fallback_on_error(self):
        """get_exports_dir() returns fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_exports_dir()

            assert isinstance(result, Path)
            assert "exports" in str(result)

    def test_get_data_dir_fallback_on_error(self):
        """get_data_dir() returns fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_data_dir()

            assert isinstance(result, Path)
            assert ".state" in str(result)

    def test_get_workspace_dir_fallback_on_error(self):
        """get_workspace_dir() returns fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_workspace_dir()

            assert isinstance(result, Path)
            assert "workspace" in str(result)

    def test_get_logs_dir_fallback_on_error(self):
        """get_logs_dir() returns fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_logs_dir()

            assert isinstance(result, Path)
            # Fallback is now temp/deskagent-logs (not .logs in cwd)
            assert "deskagent-logs" in str(result) or ".logs" in str(result)

    def test_get_state_dir_alias(self):
        """get_state_dir is an alias for get_data_dir."""
        import _mcp_api

        assert _mcp_api.get_state_dir == _mcp_api.get_data_dir

    def test_paths_are_cached(self):
        """get_*_dir() functions use cached paths."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "config_dir": "E:/test/config",
                "workspace_dir": "E:/test/workspace",
                "temp_dir": "E:/test/.temp",
                "exports_dir": "E:/test/exports",
                "data_dir": "E:/test/.state",
                "logs_dir": "E:/test/.logs"
            }
            mock_get.return_value = mock_response

            # Call multiple path functions
            _mcp_api.get_config_dir()
            _mcp_api.get_workspace_dir()
            _mcp_api.get_temp_dir()

            # Should only make one HTTP call (paths cached together)
            assert mock_get.call_count == 1


class TestAnonymization:
    """Tests for anonymize() and deanonymize() functions."""

    def test_anonymize_sends_correct_request(self):
        """anonymize() sends correct POST request."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"anonymized": "<PERSON_1>"}
            mock_post.return_value = mock_response

            result = _mcp_api.anonymize("Max Mustermann", "session-123", "de")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/mcp/anonymize" in call_args[0][0]
            assert call_args[1]["json"]["text"] == "Max Mustermann"
            assert call_args[1]["json"]["session_id"] == "session-123"
            assert call_args[1]["json"]["lang"] == "de"
            assert result == "<PERSON_1>"

    def test_anonymize_returns_original_on_error(self):
        """anonymize() returns original text on API error."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.side_effect = Exception("Timeout")

            original = "Max Mustermann"
            result = _mcp_api.anonymize(original, "session-1")

            assert result == original

    def test_anonymize_returns_original_on_non_ok_response(self):
        """anonymize() returns original text when response is not ok."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.ok = False
            mock_post.return_value = mock_response

            original = "Max Mustermann"
            result = _mcp_api.anonymize(original, "session-1")

            assert result == original

    def test_anonymize_uses_default_language(self):
        """anonymize() defaults to German language."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"anonymized": "test"}
            mock_post.return_value = mock_response

            _mcp_api.anonymize("Test", "session-1")

            call_args = mock_post.call_args
            assert call_args[1]["json"]["lang"] == "de"

    def test_deanonymize_sends_correct_request(self):
        """deanonymize() sends correct POST request."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"text": "Max Mustermann"}
            mock_post.return_value = mock_response

            result = _mcp_api.deanonymize("<PERSON_1>", "session-123")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/mcp/deanonymize" in call_args[0][0]
            assert call_args[1]["json"]["text"] == "<PERSON_1>"
            assert call_args[1]["json"]["session_id"] == "session-123"
            assert result == "Max Mustermann"

    def test_deanonymize_returns_original_on_error(self):
        """deanonymize() returns input text on API error."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.side_effect = Exception("Timeout")

            original = "<PERSON_1> wrote"
            result = _mcp_api.deanonymize(original, "session-1")

            assert result == original


class TestCleanupSession:
    """Tests for cleanup_session() function."""

    def test_cleanup_session_sends_delete_request(self):
        """cleanup_session() sends DELETE request."""
        import _mcp_api

        with patch("_mcp_api.requests.delete") as mock_delete:
            mock_delete.return_value = Mock(ok=True)

            _mcp_api.cleanup_session("session-to-delete")

            mock_delete.assert_called_once()
            call_args = mock_delete.call_args
            assert "/api/mcp/session/session-to-delete" in call_args[0][0]

    def test_cleanup_session_silent_on_error(self):
        """cleanup_session() does not raise exception on error."""
        import _mcp_api

        with patch("_mcp_api.requests.delete") as mock_delete:
            mock_delete.side_effect = Exception("Network error")

            # Should not raise
            _mcp_api.cleanup_session("session-123")


class TestGetTaskContext:
    """Tests for get_task_context() function."""

    def test_get_task_context_returns_dict(self):
        """get_task_context() returns dict when successful."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "task_id": "task-123",
                "parent_task_id": None
            }
            mock_get.return_value = mock_response

            result = _mcp_api.get_task_context()

            assert result == {"task_id": "task-123", "parent_task_id": None}

    def test_get_task_context_returns_none_on_error(self):
        """get_task_context() returns None on API error."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_task_context()

            assert result is None

    def test_get_task_context_returns_none_on_non_ok_response(self):
        """get_task_context() returns None when response is not ok."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = False
            mock_get.return_value = mock_response

            result = _mcp_api.get_task_context()

            assert result is None


class TestIsAnonymizerAvailable:
    """Tests for is_anonymizer_available() function."""

    def test_is_anonymizer_available_returns_true(self):
        """is_anonymizer_available() returns True when available."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"available": True}
            mock_get.return_value = mock_response

            result = _mcp_api.is_anonymizer_available()

            assert result is True

    def test_is_anonymizer_available_returns_false(self):
        """is_anonymizer_available() returns False when not available."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"available": False}
            mock_get.return_value = mock_response

            result = _mcp_api.is_anonymizer_available()

            assert result is False

    def test_is_anonymizer_available_returns_false_on_error(self):
        """is_anonymizer_available() returns False on API error."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.is_anonymizer_available()

            assert result is False

    def test_is_anonymizer_available_returns_false_on_non_ok(self):
        """is_anonymizer_available() returns False when response is not ok."""
        import _mcp_api

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = False
            mock_get.return_value = mock_response

            result = _mcp_api.is_anonymizer_available()

            assert result is False


class TestLogToolCall:
    """Tests for log_tool_call() function."""

    def test_log_tool_call_sends_correct_request(self):
        """log_tool_call() sends correct POST request."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.return_value = Mock(ok=True)

            _mcp_api.log_tool_call(
                tool_name="outlook_get_email",
                direction="CALL",
                content='{"id": "123"}',
                is_anonymized=True
            )

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/mcp/log_tool_call" in call_args[0][0]
            json_body = call_args[1]["json"]
            assert json_body["tool_name"] == "outlook_get_email"
            assert json_body["direction"] == "CALL"
            assert json_body["content"] == '{"id": "123"}'
            assert json_body["is_anonymized"] is True

    def test_log_tool_call_silent_on_error(self):
        """log_tool_call() does not raise exception on error."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            # Should not raise
            _mcp_api.log_tool_call(
                tool_name="test",
                direction="CALL",
                content="{}"
            )

    def test_log_tool_call_defaults_is_anonymized(self):
        """log_tool_call() defaults is_anonymized to True."""
        import _mcp_api

        with patch("_mcp_api.requests.post") as mock_post:
            mock_post.return_value = Mock(ok=True)

            _mcp_api.log_tool_call(
                tool_name="test",
                direction="CALL",
                content="{}"
            )

            call_args = mock_post.call_args
            assert call_args[1]["json"]["is_anonymized"] is True


class TestClearCache:
    """Tests for clear_cache() function."""

    def test_clear_cache_empties_cache(self):
        """clear_cache() removes all cached data."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        # Populate cache
        _mcp_api._cache["config"] = {"test": True}
        _mcp_api._cache["paths"] = {"workspace_dir": "/test"}

        assert len(_mcp_api._cache) > 0

        _mcp_api.clear_cache()

        assert len(_mcp_api._cache) == 0

    def test_clear_cache_forces_new_api_call(self):
        """clear_cache() forces new API call on next load_config()."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {"key": "value1"}
            mock_get.return_value = mock_response

            # First call
            result1 = _mcp_api.load_config()
            assert mock_get.call_count == 1

            # Clear cache
            _mcp_api.clear_cache()

            # Update mock response
            mock_response.json.return_value = {"key": "value2"}

            # Second call should make new request
            result2 = _mcp_api.load_config()
            assert mock_get.call_count == 2


class TestGetWorkspaceSubdir:
    """Tests for get_workspace_subdir() function."""

    def test_get_workspace_subdir_creates_directory(self, tmp_path):
        """get_workspace_subdir() creates the subdirectory."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        with patch("_mcp_api.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.ok = True
            mock_response.json.return_value = {
                "workspace_dir": str(tmp_path / "workspace")
            }
            mock_get.return_value = mock_response

            result = _mcp_api.get_workspace_subdir("exports/sepa")

            assert result.exists()
            assert result.is_dir()
            assert "exports" in str(result)
            assert "sepa" in str(result)

    def test_get_workspace_subdir_fallback(self, tmp_path, monkeypatch):
        """get_workspace_subdir() uses fallback on API error."""
        import importlib
        import _mcp_api
        importlib.reload(_mcp_api)

        _mcp_api.clear_cache()

        # Change cwd to tmp_path for fallback
        monkeypatch.chdir(tmp_path)

        with patch("_mcp_api.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            result = _mcp_api.get_workspace_subdir("test/subdir")

            assert result.exists()
            assert "test" in str(result)
            assert "subdir" in str(result)


class TestEnvironmentVariable:
    """Tests for DESKAGENT_API_URL environment variable."""

    def test_uses_default_url(self):
        """Uses default URL when env var not set."""
        import importlib
        import os

        # Remove env var if set
        old_value = os.environ.pop("DESKAGENT_API_URL", None)

        try:
            import _mcp_api
            importlib.reload(_mcp_api)

            assert _mcp_api._BASE_URL == "http://localhost:8765"
        finally:
            # Restore env var
            if old_value:
                os.environ["DESKAGENT_API_URL"] = old_value

    def test_uses_custom_url_from_env(self):
        """Uses custom URL from DESKAGENT_API_URL env var."""
        import importlib
        import os

        old_value = os.environ.get("DESKAGENT_API_URL")
        os.environ["DESKAGENT_API_URL"] = "http://custom:9000"

        try:
            import _mcp_api
            importlib.reload(_mcp_api)

            assert _mcp_api._BASE_URL == "http://custom:9000"
        finally:
            # Restore env var
            if old_value:
                os.environ["DESKAGENT_API_URL"] = old_value
            else:
                os.environ.pop("DESKAGENT_API_URL", None)
