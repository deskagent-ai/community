# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Demo Mode module
==========================
"""

import json
import pytest
import tempfile
from pathlib import Path

# Add scripts to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.demo_mode import (
    is_demo_mode_enabled,
    load_mocks,
    get_mock_response,
    load_scenario,
    clear_cache,
    get_mock_metadata,
    _match_args,
    _select_weighted_response,
)


class TestIsDemoModeEnabled:
    """Tests for is_demo_mode_enabled()."""

    def test_disabled_by_default(self):
        """Demo mode should be disabled when not configured."""
        assert is_demo_mode_enabled({}) is False

    def test_enabled_via_config(self):
        """Demo mode can be enabled via config."""
        config = {"demo_mode": {"enabled": True}}
        assert is_demo_mode_enabled(config) is True

    def test_disabled_via_config(self):
        """Demo mode can be explicitly disabled via config."""
        config = {"demo_mode": {"enabled": False}}
        assert is_demo_mode_enabled(config) is False

    def test_env_override_enabled(self, monkeypatch):
        """Environment variable can enable demo mode."""
        monkeypatch.setenv("DESKAGENT_DEMO_MODE", "1")
        assert is_demo_mode_enabled({}) is True

    def test_env_override_disabled(self, monkeypatch):
        """Environment variable can disable demo mode."""
        monkeypatch.setenv("DESKAGENT_DEMO_MODE", "0")
        config = {"demo_mode": {"enabled": True}}
        assert is_demo_mode_enabled(config) is False


class TestLoadMocks:
    """Tests for load_mocks()."""

    def test_empty_directory(self, tmp_path, monkeypatch):
        """Loading from empty directory returns empty dict when no product mocks exist."""
        import ai_agent.demo_mode as dm
        # Mock product mocks dir to not exist
        monkeypatch.setattr(dm, "get_product_mocks_dir", lambda: tmp_path / "nonexistent_product")
        clear_cache()
        result = load_mocks(tmp_path)
        assert result == {}

    def test_nonexistent_directory(self, tmp_path, monkeypatch):
        """Loading from non-existent directory returns empty dict when no product mocks exist."""
        import ai_agent.demo_mode as dm
        # Mock product mocks dir to not exist
        monkeypatch.setattr(dm, "get_product_mocks_dir", lambda: tmp_path / "nonexistent_product")
        clear_cache()
        result = load_mocks(tmp_path / "nonexistent")
        assert result == {}

    def test_load_simple_mock(self, tmp_path):
        """Load a simple mock definition."""
        clear_cache()
        mock_file = tmp_path / "tools.json"
        mock_file.write_text(json.dumps({
            "test_tool": {"response": "Hello, World!"}
        }))

        result = load_mocks(tmp_path)
        assert "test_tool" in result
        assert result["test_tool"]["response"] == "Hello, World!"

    def test_merge_multiple_files(self, tmp_path):
        """Mocks from multiple files are merged."""
        clear_cache()
        (tmp_path / "file1.json").write_text(json.dumps({
            "tool_a": {"response": "A"}
        }))
        (tmp_path / "file2.json").write_text(json.dumps({
            "tool_b": {"response": "B"}
        }))

        result = load_mocks(tmp_path)
        assert "tool_a" in result
        assert "tool_b" in result

    def test_cache_works(self, tmp_path):
        """Second load uses cache."""
        clear_cache()
        mock_file = tmp_path / "tools.json"
        mock_file.write_text(json.dumps({
            "test_tool": {"response": "Original"}
        }))

        result1 = load_mocks(tmp_path)
        assert result1["test_tool"]["response"] == "Original"

        # Modify file - should still return cached version
        mock_file.write_text(json.dumps({
            "test_tool": {"response": "Modified"}
        }))

        result2 = load_mocks(tmp_path)
        assert result2["test_tool"]["response"] == "Original"  # Still cached

    def test_cache_clear(self, tmp_path):
        """Clear cache forces reload."""
        mock_file = tmp_path / "tools.json"
        mock_file.write_text(json.dumps({
            "test_tool": {"response": "Original"}
        }))

        clear_cache()
        result1 = load_mocks(tmp_path)

        # Modify file and clear cache
        mock_file.write_text(json.dumps({
            "test_tool": {"response": "Modified"}
        }))
        clear_cache()

        result2 = load_mocks(tmp_path)
        assert result2["test_tool"]["response"] == "Modified"


class TestGetMockResponse:
    """Tests for get_mock_response()."""

    def test_simple_response(self, tmp_path):
        """Get a simple mock response."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({
            "greet": {"response": "Hello!"}
        }))

        result = get_mock_response("greet", {}, tmp_path)
        assert result == "Hello!"

    def test_json_response(self, tmp_path):
        """Get a JSON mock response."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({
            "get_data": {"response_json": {"name": "Test", "value": 42}}
        }))

        result = get_mock_response("get_data", {}, tmp_path)
        parsed = json.loads(result)
        assert parsed["name"] == "Test"
        assert parsed["value"] == 42

    def test_missing_mock_error(self, tmp_path):
        """Missing mock returns error by default."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({}))

        result = get_mock_response("unknown_tool", {}, tmp_path, fallback="error")
        assert "[Demo Mode]" in result
        assert "unknown_tool" in result

    def test_missing_mock_none(self, tmp_path):
        """Missing mock can return None."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({}))

        result = get_mock_response("unknown_tool", {}, tmp_path, fallback="none")
        assert result is None

    def test_missing_mock_empty(self, tmp_path):
        """Missing mock can return empty string."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({}))

        result = get_mock_response("unknown_tool", {}, tmp_path, fallback="empty")
        assert result == ""


class TestVariantMatching:
    """Tests for argument-based variant matching."""

    def test_exact_match(self, tmp_path):
        """Variant with exact arg match is selected."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({
            "get_email": {
                "variants": [
                    {"match_args": {"id": "123"}, "response": "Email 123"},
                    {"match_args": {"id": "456"}, "response": "Email 456"},
                ],
                "fallback_response": "Unknown email"
            }
        }))

        result = get_mock_response("get_email", {"id": "123"}, tmp_path)
        assert result == "Email 123"

        result = get_mock_response("get_email", {"id": "456"}, tmp_path)
        assert result == "Email 456"

    def test_fallback_when_no_match(self, tmp_path):
        """Fallback is used when no variant matches."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({
            "get_email": {
                "variants": [
                    {"match_args": {"id": "123"}, "response": "Email 123"}
                ],
                "fallback_response": "Unknown email"
            }
        }))

        result = get_mock_response("get_email", {"id": "999"}, tmp_path)
        assert result == "Unknown email"

    def test_regex_match(self):
        """Regex matcher works."""
        assert _match_args({"name": {"$regex": "^Test"}}, {"name": "TestCase"}) is True
        assert _match_args({"name": {"$regex": "^Test"}}, {"name": "OtherCase"}) is False

    def test_contains_match(self):
        """Contains matcher works."""
        assert _match_args({"text": {"$contains": "hello"}}, {"text": "Say hello world"}) is True
        assert _match_args({"text": {"$contains": "hello"}}, {"text": "Goodbye"}) is False

    def test_exists_match(self):
        """Exists matcher works."""
        assert _match_args({"key": {"$exists": True}}, {"key": "value"}) is True
        assert _match_args({"key": {"$exists": True}}, {}) is False
        assert _match_args({"key": {"$exists": False}}, {}) is True


class TestWeightedResponses:
    """Tests for weighted response selection."""

    def test_single_response(self):
        """Single response is always selected."""
        responses = [{"response": "Only one", "weight": 1}]
        result = _select_weighted_response(responses)
        assert result["response"] == "Only one"

    def test_weighted_distribution(self):
        """Higher weight means higher selection probability."""
        responses = [
            {"response": "Rare", "weight": 1},
            {"response": "Common", "weight": 100},
        ]

        # Run many times and check distribution
        results = [_select_weighted_response(responses)["response"] for _ in range(100)]
        common_count = results.count("Common")

        # Common should be selected much more often
        assert common_count > 80  # Should be ~99 times

    def test_empty_list(self):
        """Empty list returns None."""
        assert _select_weighted_response([]) is None


class TestLoadScenario:
    """Tests for load_scenario()."""

    def test_load_existing_scenario(self, tmp_path):
        """Load an existing scenario file."""
        clear_cache()
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        (scenarios_dir / "reply_email.json").write_text(json.dumps({
            "outlook_get_selected_email": {"response": "Mock email content"}
        }))

        result = load_scenario("reply_email", tmp_path)
        assert "outlook_get_selected_email" in result

    def test_missing_scenario(self, tmp_path):
        """Missing scenario returns empty dict."""
        clear_cache()
        result = load_scenario("nonexistent_agent", tmp_path)
        assert result == {}


class TestMockMetadata:
    """Tests for mock metadata and delay."""

    def test_get_metadata(self, tmp_path):
        """Get metadata from mock definition."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({
            "slow_tool": {
                "response": "Done",
                "metadata": {"delay_ms": 500}
            }
        }))

        metadata = get_mock_metadata("slow_tool", tmp_path)
        assert metadata["delay_ms"] == 500

    def test_missing_metadata(self, tmp_path):
        """Missing metadata returns empty dict."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({
            "fast_tool": {"response": "Done"}
        }))

        metadata = get_mock_metadata("fast_tool", tmp_path)
        assert metadata == {}

    def test_missing_tool_metadata(self, tmp_path):
        """Missing tool returns empty metadata."""
        clear_cache()
        (tmp_path / "tools.json").write_text(json.dumps({}))

        metadata = get_mock_metadata("nonexistent", tmp_path)
        assert metadata == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
