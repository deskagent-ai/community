# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for Mock LLM Backend
==========================

Tests the mock LLM infrastructure for cost-free testing.
"""

import json
import pytest
from pathlib import Path

# Add scripts to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.mock_llm import (
    MockLLMBackend,
    MockTracker,
    MockResponse,
    is_mock_mode_enabled,
    get_mock_llm_dir,
)


class TestIsMockModeEnabled:
    """Tests for is_mock_mode_enabled()."""

    def test_disabled_by_default(self):
        """Mock mode should be disabled when not configured."""
        assert is_mock_mode_enabled({}) is False

    def test_enabled_via_config(self):
        """Mock mode can be enabled via config."""
        config = {"mock_mode": {"enabled": True}}
        assert is_mock_mode_enabled(config) is True

    def test_disabled_via_config(self):
        """Mock mode can be explicitly disabled via config."""
        config = {"mock_mode": {"enabled": False}}
        assert is_mock_mode_enabled(config) is False

    def test_env_override_enabled(self, monkeypatch):
        """Environment variable can enable mock mode."""
        monkeypatch.setenv("DESKAGENT_MOCK_MODE", "1")
        assert is_mock_mode_enabled({}) is True

    def test_env_override_disabled(self, monkeypatch):
        """Environment variable can disable mock mode."""
        monkeypatch.setenv("DESKAGENT_MOCK_MODE", "0")
        config = {"mock_mode": {"enabled": True}}
        assert is_mock_mode_enabled(config) is False


class TestMockTracker:
    """Tests for MockTracker."""

    def test_record_call(self):
        """Recording a call stores data correctly."""
        tracker = MockTracker()
        tracker.record_call(
            prompt="Hello",
            agent_name="test",
            tools=[{"name": "tool_a"}],
            response="Hi there"
        )

        log = tracker.get_call_log()
        assert len(log) == 1
        assert log[0]["prompt"] == "Hello"
        assert log[0]["agent_name"] == "test"

    def test_get_sent_prompt(self):
        """get_sent_prompt returns the last prompt."""
        tracker = MockTracker()
        tracker.record_call(prompt="First")
        tracker.record_call(prompt="Second")

        assert tracker.get_sent_prompt() == "Second"

    def test_tool_tracking(self):
        """Tool calls are tracked correctly."""
        tracker = MockTracker()
        tracker.record_call(
            prompt="Test",
            tool_calls=[
                {"name": "tool_a", "arguments": {}},
                {"name": "tool_b", "arguments": {}}
            ]
        )

        assert tracker.tool_was_called("tool_a") is True
        assert tracker.tool_was_called("tool_b") is True
        assert tracker.tool_was_called("tool_c") is False
        assert tracker.get_tool_call_count() == 2
        assert tracker.get_tool_call_count("tool_a") == 1

    def test_set_mock_response(self):
        """Setting a mock response returns it once."""
        tracker = MockTracker()
        tracker.set_mock_response("Custom response")

        assert tracker.get_mock_response() == "Custom response"
        assert tracker.get_mock_response() is None  # Consumed

    def test_reset(self):
        """Reset clears all data."""
        tracker = MockTracker()
        tracker.record_call(prompt="Test")
        tracker.set_mock_response("Response")
        tracker.reset()

        assert tracker.get_call_log() == []
        assert tracker.get_mock_response() is None

    def test_available_tools(self):
        """Available tools are tracked."""
        tracker = MockTracker()
        tracker.record_call(
            prompt="Test",
            tools=[{"name": "tool_x"}, {"name": "tool_y"}]
        )

        tools = tracker.get_available_tools()
        assert "tool_x" in tools
        assert "tool_y" in tools


class TestMockTrackerAssertions:
    """Tests for MockTracker assertion helpers."""

    def test_assert_tool_called_success(self):
        """assert_tool_called passes when tool was called."""
        tracker = MockTracker()
        tracker.record_call(
            prompt="Test",
            tool_calls=[{"name": "my_tool", "arguments": {}}]
        )

        # Should not raise
        tracker.assert_tool_called("my_tool")

    def test_assert_tool_called_failure(self):
        """assert_tool_called raises when tool was not called."""
        tracker = MockTracker()
        tracker.record_call(prompt="Test")

        with pytest.raises(AssertionError, match="was not called"):
            tracker.assert_tool_called("missing_tool")

    def test_assert_tool_called_times(self):
        """assert_tool_called with times parameter."""
        tracker = MockTracker()
        tracker.record_call(
            prompt="Test",
            tool_calls=[
                {"name": "tool", "arguments": {}},
                {"name": "tool", "arguments": {}}
            ]
        )

        tracker.assert_tool_called("tool", times=2)

        with pytest.raises(AssertionError, match="called 2 times"):
            tracker.assert_tool_called("tool", times=1)

    def test_assert_tool_not_called(self):
        """assert_tool_not_called works correctly."""
        tracker = MockTracker()
        tracker.record_call(
            prompt="Test",
            tool_calls=[{"name": "used_tool", "arguments": {}}]
        )

        # Should not raise
        tracker.assert_tool_not_called("unused_tool")

        with pytest.raises(AssertionError, match="should not have been called"):
            tracker.assert_tool_not_called("used_tool")

    def test_assert_prompt_contains(self):
        """assert_prompt_contains works correctly."""
        tracker = MockTracker()
        tracker.record_call(prompt="Hello World")

        tracker.assert_prompt_contains("Hello")
        tracker.assert_prompt_contains("World")

        with pytest.raises(AssertionError, match="does not contain"):
            tracker.assert_prompt_contains("Goodbye")

    def test_assert_prompt_not_contains(self):
        """assert_prompt_not_contains works correctly."""
        tracker = MockTracker()
        tracker.record_call(prompt="Hello World")

        tracker.assert_prompt_not_contains("Goodbye")

        with pytest.raises(AssertionError, match="should not contain"):
            tracker.assert_prompt_not_contains("Hello")

    def test_assert_call_count(self):
        """assert_call_count works correctly."""
        tracker = MockTracker()
        tracker.record_call(prompt="First")
        tracker.record_call(prompt="Second")

        tracker.assert_call_count(2)

        with pytest.raises(AssertionError, match="Expected 3 calls"):
            tracker.assert_call_count(3)


class TestMockLLMBackend:
    """Tests for MockLLMBackend."""

    def test_basic_call(self, mock_backend):
        """Basic call returns AgentResponse."""
        response = mock_backend.call(prompt="Hello")

        assert response.success is True
        assert response.content is not None
        assert response.cost_usd == 0.0
        assert response.model is not None

    def test_default_response(self, mock_backend):
        """Default response is returned for unmatched prompts."""
        response = mock_backend.call(prompt="Some random text")

        assert response.success is True
        assert "[Mock]" in response.content

    def test_tracker_override_response(self, mock_backend, mock_tracker):
        """Tracker can override response."""
        mock_tracker.set_mock_response("Custom override response")

        response = mock_backend.call(prompt="Anything")

        assert response.content == "Custom override response"

    def test_calls_are_tracked(self, mock_backend, mock_tracker):
        """Calls are recorded in tracker."""
        mock_backend.call(prompt="Test prompt", agent_name="test_agent")

        mock_tracker.assert_prompt_contains("Test prompt")
        assert mock_tracker.get_call_log()[0]["agent_name"] == "test_agent"

    def test_streaming_callback(self, mock_backend):
        """Streaming callback is invoked."""
        chunks = []

        def on_chunk(token, is_thinking, full_response):
            chunks.append(token)

        mock_backend.call(prompt="Hello", on_chunk=on_chunk)

        assert len(chunks) > 0

    def test_reset(self, mock_backend, mock_tracker):
        """Reset clears backend state."""
        mock_backend.call(prompt="Test")
        mock_backend.reset()

        assert mock_tracker.get_call_log() == []


class TestMockLLMWithFiles:
    """Tests for MockLLMBackend with mock files."""

    def test_load_from_file(self, temp_mock_dir):
        """Load mock responses from JSON file."""
        llm_dir = temp_mock_dir["llm"]

        # Create mock file
        mock_data = {
            "responses": [
                {
                    "id": "test-response",
                    "match": {"prompt": {"$contains": "test"}},
                    "response": {
                        "content": "Test response from file",
                        "model": "mock-test"
                    }
                }
            ]
        }
        (llm_dir / "test.json").write_text(json.dumps(mock_data))

        backend = MockLLMBackend(mocks_dir=llm_dir)
        response = backend.call(prompt="This is a test")

        assert response.content == "Test response from file"
        assert response.model == "mock-test"

    def test_pattern_matching_contains(self, temp_mock_dir):
        """Pattern matching with $contains."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [
                {
                    "id": "email-match",
                    "match": {"prompt": {"$contains": "email"}},
                    "response": {"content": "Email response"}
                }
            ]
        }
        (llm_dir / "patterns.json").write_text(json.dumps(mock_data))

        backend = MockLLMBackend(mocks_dir=llm_dir)

        # Should match
        response = backend.call(prompt="Please read my email")
        assert response.content == "Email response"

        # Should not match - use default
        response = backend.call(prompt="Hello world")
        assert "[Mock]" in response.content

    def test_pattern_matching_regex(self, temp_mock_dir):
        """Pattern matching with $regex."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [
                {
                    "id": "number-match",
                    "match": {"prompt": {"$regex": r"\d{3}-\d{4}"}},
                    "response": {"content": "Phone number detected"}
                }
            ]
        }
        (llm_dir / "regex.json").write_text(json.dumps(mock_data))

        backend = MockLLMBackend(mocks_dir=llm_dir)

        # Should match
        response = backend.call(prompt="Call me at 123-4567")
        assert response.content == "Phone number detected"

        # Should not match
        response = backend.call(prompt="No numbers here")
        assert "[Mock]" in response.content

    def test_agent_name_matching(self, temp_mock_dir):
        """Pattern matching with agent name."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [
                {
                    "id": "agent-specific",
                    "match": {"agent": "special_agent"},
                    "response": {"content": "Special agent response"}
                }
            ]
        }
        (llm_dir / "agents.json").write_text(json.dumps(mock_data))

        backend = MockLLMBackend(mocks_dir=llm_dir)

        # Should match with correct agent
        response = backend.call(prompt="Hello", agent_name="special_agent")
        assert response.content == "Special agent response"

        # Should not match with different agent
        response = backend.call(prompt="Hello", agent_name="other_agent")
        assert "[Mock]" in response.content

    def test_tool_calls_in_response(self, temp_mock_dir):
        """Mock response can include tool calls."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [
                {
                    "id": "with-tools",
                    "match": {"prompt": {"$contains": "read email"}},
                    "response": {
                        "content": "Let me read that for you.",
                        "tool_calls": [
                            {"name": "outlook_get_email", "arguments": {"id": "123"}}
                        ]
                    }
                }
            ]
        }
        (llm_dir / "tools.json").write_text(json.dumps(mock_data))

        tracker = MockTracker()
        backend = MockLLMBackend(mocks_dir=llm_dir, tracker=tracker)

        response = backend.call(prompt="Please read email")

        assert response.success
        tracker.assert_tool_called("outlook_get_email")


class TestMockResponse:
    """Tests for MockResponse dataclass."""

    def test_default_values(self):
        """MockResponse has sensible defaults."""
        resp = MockResponse()

        assert resp.id == "default"
        assert "[Mock]" in resp.content
        assert resp.model == "mock-llm"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 20
        assert resp.is_default is False

    def test_custom_values(self):
        """MockResponse accepts custom values."""
        resp = MockResponse(
            id="custom",
            content="Custom content",
            model="custom-model",
            input_tokens=100,
            output_tokens=200,
            is_default=True
        )

        assert resp.id == "custom"
        assert resp.content == "Custom content"
        assert resp.model == "custom-model"
        assert resp.input_tokens == 100
        assert resp.is_default is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
