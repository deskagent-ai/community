# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Backend Mock Tests
==================

Tests all AI backends using mock LLM responses.
No API costs - tests backend routing, config parsing, and response structure.

Run with: pytest -m mock tests/test_ai_agent/test_backends_mock.py -v
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.backend_config import (
    get_agent_config,
    is_backend_available,
    get_default_backend,
    BACKEND_MODULES,
)
from ai_agent.mock_llm import MockLLMBackend, MockTracker


# =============================================================================
# Backend Lists
# =============================================================================

ALL_BACKENDS = [
    "claude_api",       # claude_api.py - Direct Anthropic API
    "claude_sdk",       # claude_agent_sdk.py - Claude Agent SDK
    "claude_cli",       # claude_cli.py - Claude Code CLI (subprocess)
    "gemini",           # gemini_adk.py - Google Gemini ADK
    "gemini_flash",     # gemini_adk.py - Gemini Flash variant
    "gemini_3",         # gemini_adk.py - Gemini 3.1 Pro Preview
    "gemini_3_flash",   # gemini_adk.py - Gemini 3.1 Flash Preview
    "openai",           # openai_api.py - OpenAI GPT API
    "ollama",           # ollama_native.py - Ollama local
    "qwen",             # qwen_agent.py - Qwen Agent framework
]

TOOL_CAPABLE_BACKENDS = [
    "claude_api", "claude_sdk", "gemini", "gemini_flash", "gemini_3", "gemini_3_flash", "openai"
]

STREAMING_BACKENDS = [
    "claude_api", "gemini", "gemini_flash", "gemini_3", "gemini_3_flash", "openai", "ollama"
]


# =============================================================================
# Test: Backend Configuration
# =============================================================================

@pytest.mark.mock
class TestBackendConfig:
    """Tests for backend configuration parsing."""

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_backend_config_exists(self, backend, mock_config):
        """Each backend should have a configuration."""
        config = get_agent_config(mock_config, backend)
        assert config is not None
        assert isinstance(config, dict)

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_backend_has_type(self, backend, mock_config):
        """Each backend config should have a type field."""
        config = get_agent_config(mock_config, backend)
        assert "type" in config
        backend_type = config["type"]
        # Type should be one of the known types
        assert backend_type in BACKEND_MODULES

    @pytest.mark.parametrize("backend", ["claude_api", "gemini", "openai"])
    def test_api_backends_have_key(self, backend, mock_config):
        """API-based backends should have api_key field."""
        config = get_agent_config(mock_config, backend)
        assert "api_key" in config

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_backend_availability_check(self, backend, mock_config):
        """is_backend_available should return boolean."""
        # Note: With mock keys, availability depends on backend logic
        result = is_backend_available(backend, mock_config)
        assert isinstance(result, bool)


@pytest.mark.mock
class TestDefaultBackend:
    """Tests for default backend resolution."""

    def test_default_from_config(self, mock_config):
        """Default backend comes from config or falls back to available."""
        default = get_default_backend(mock_config)
        # With mock api_keys, backend availability varies
        # The function should return a valid backend name from ai_backends
        assert default in mock_config["ai_backends"]

    def test_fallback_when_default_unavailable(self):
        """Fallback to available backend when default is unavailable."""
        config = {
            "default_ai": "nonexistent",
            "ai_backends": {
                "gemini": {
                    "type": "gemini_adk",
                    "api_key": "test"
                }
            }
        }
        default = get_default_backend(config)
        # Should fallback to gemini since nonexistent doesn't exist
        assert default in ["nonexistent", "gemini"]


# =============================================================================
# Test: Mock Backend Calls
# =============================================================================

@pytest.mark.mock
class TestMockBackendCalls:
    """Tests using MockLLMBackend for all backends."""

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_mock_call_succeeds(self, backend, mock_config):
        """Mock call should succeed for any backend."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        result = mock_backend.call(
            prompt="Hello",
            agent_name=backend
        )

        assert result.success is True
        assert result.cost_usd == 0.0  # Mock = no cost
        assert result.content is not None

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_mock_tracks_prompt(self, backend, mock_config):
        """Mock should track the prompt sent."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        test_prompt = f"Test prompt for {backend}"
        mock_backend.call(prompt=test_prompt, agent_name=backend)

        tracker.assert_prompt_contains(test_prompt)

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_mock_response_structure(self, backend, mock_config):
        """Mock response should have AgentResponse structure."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        result = mock_backend.call(prompt="Hello", agent_name=backend)

        # AgentResponse fields
        assert hasattr(result, "success")
        assert hasattr(result, "content")
        assert hasattr(result, "model")
        assert hasattr(result, "input_tokens")
        assert hasattr(result, "output_tokens")
        assert hasattr(result, "cost_usd")
        assert hasattr(result, "error")
        assert hasattr(result, "duration_seconds")

    @pytest.mark.parametrize("backend", STREAMING_BACKENDS)
    def test_mock_streaming_callback(self, backend, mock_config):
        """Mock should invoke streaming callbacks."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        chunks = []

        def on_chunk(token, is_thinking=False, full_response=""):
            chunks.append(token)

        mock_backend.call(
            prompt="Count 1 to 5",
            agent_name=backend,
            on_chunk=on_chunk
        )

        assert len(chunks) > 0


# =============================================================================
# Test: Tool Tracking
# =============================================================================

@pytest.mark.mock
class TestToolTracking:
    """Tests for tool call tracking in mock mode."""

    def test_track_available_tools(self, mock_config):
        """Available tools should be tracked."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        tools = [
            {"name": "outlook_get_email"},
            {"name": "billomat_create_invoice"}
        ]

        mock_backend.call(
            prompt="Test",
            tools=tools
        )

        available = tracker.get_available_tools()
        assert "outlook_get_email" in available
        assert "billomat_create_invoice" in available

    def test_track_tool_calls(self, temp_mock_dir, mock_config):
        """Tool calls from mock response should be tracked."""
        import json

        llm_dir = temp_mock_dir["llm"]
        mock_data = {
            "responses": [{
                "id": "with-tool",
                "match": {"prompt": {"$contains": "email"}},
                "response": {
                    "content": "Reading email...",
                    "tool_calls": [{"name": "outlook_get_email", "arguments": {}}]
                }
            }]
        }
        (llm_dir / "tools.json").write_text(json.dumps(mock_data))

        tracker = MockTracker()
        mock_backend = MockLLMBackend(
            config=mock_config,
            mocks_dir=llm_dir,
            tracker=tracker
        )

        mock_backend.call(prompt="Read my email")

        tracker.assert_tool_called("outlook_get_email")
        assert tracker.get_tool_call_count("outlook_get_email") == 1


# =============================================================================
# Test: Cost Tracking
# =============================================================================

@pytest.mark.mock
class TestCostTracking:
    """Tests for cost tracking in mock mode."""

    @pytest.mark.parametrize("backend", ALL_BACKENDS)
    def test_mock_cost_is_zero(self, backend, mock_config):
        """Mock mode should report zero cost."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        result = mock_backend.call(prompt="Test", agent_name=backend)

        assert result.cost_usd == 0.0

    def test_mock_tokens_reported(self, mock_config):
        """Mock should report token counts."""
        tracker = MockTracker()
        mock_backend = MockLLMBackend(config=mock_config, tracker=tracker)

        result = mock_backend.call(prompt="Test")

        # Mock should report some token counts
        assert result.input_tokens is not None
        assert result.output_tokens is not None
        assert result.input_tokens >= 0
        assert result.output_tokens >= 0


# =============================================================================
# Test: Pattern Matching
# =============================================================================

@pytest.mark.mock
class TestPatternMatching:
    """Tests for mock response pattern matching."""

    def test_contains_matching(self, temp_mock_dir, mock_config):
        """$contains pattern matching works."""
        import json

        llm_dir = temp_mock_dir["llm"]
        mock_data = {
            "responses": [{
                "id": "greeting",
                "match": {"prompt": {"$contains": "hello"}},
                "response": {"content": "Hi there!"}
            }]
        }
        (llm_dir / "patterns.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(config=mock_config, mocks_dir=llm_dir)

        # Should match
        result = mock_backend.call(prompt="Say hello to me")
        assert result.content == "Hi there!"

    def test_regex_matching(self, temp_mock_dir, mock_config):
        """$regex pattern matching works."""
        import json

        llm_dir = temp_mock_dir["llm"]
        mock_data = {
            "responses": [{
                "id": "date",
                "match": {"prompt": {"$regex": r"\d{4}-\d{2}-\d{2}"}},
                "response": {"content": "Date detected!"}
            }]
        }
        (llm_dir / "patterns.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(config=mock_config, mocks_dir=llm_dir)

        # Should match
        result = mock_backend.call(prompt="Meeting on 2025-01-15")
        assert result.content == "Date detected!"

    def test_agent_matching(self, temp_mock_dir, mock_config):
        """Agent name matching works."""
        import json

        llm_dir = temp_mock_dir["llm"]
        mock_data = {
            "responses": [{
                "id": "reply-email",
                "match": {"agent": "reply_email"},
                "response": {"content": "Email agent active"}
            }]
        }
        (llm_dir / "patterns.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(config=mock_config, mocks_dir=llm_dir)

        # Should match with correct agent
        result = mock_backend.call(prompt="Test", agent_name="reply_email")
        assert result.content == "Email agent active"

        # Should not match with wrong agent
        result = mock_backend.call(prompt="Test", agent_name="other")
        assert "[Mock]" in result.content

    def test_default_fallback(self, temp_mock_dir, mock_config):
        """Default response is used when no pattern matches."""
        import json

        llm_dir = temp_mock_dir["llm"]
        mock_data = {
            "responses": [
                {
                    "id": "specific",
                    "match": {"prompt": {"$contains": "specific"}},
                    "response": {"content": "Specific match"}
                },
                {
                    "id": "default",
                    "match": {"$default": True},
                    "response": {"content": "Default response"}
                }
            ]
        }
        (llm_dir / "patterns.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(config=mock_config, mocks_dir=llm_dir)

        # Should use default
        result = mock_backend.call(prompt="Something else")
        assert result.content == "Default response"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "mock"])
