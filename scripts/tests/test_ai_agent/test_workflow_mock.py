# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Workflow Mock Tests
===================

End-to-end workflow tests using mock LLM responses.
Tests the complete agent workflow without API costs.

Run with: pytest -m mock tests/test_ai_agent/test_workflow_mock.py -v
"""

import json
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ai_agent.mock_llm import MockLLMBackend, MockTracker


# =============================================================================
# Test: Basic Workflow
# =============================================================================

@pytest.mark.mock
class TestBasicWorkflow:
    """Basic workflow tests with mock LLM."""

    def test_simple_prompt_response(self, mock_config, mock_tracker):
        """Simple prompt gets a response."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        result = mock_backend.call(prompt="Hello, how are you?")

        assert result.success is True
        assert len(result.content) > 0
        assert result.cost_usd == 0.0

    def test_agent_name_passed_through(self, mock_config, mock_tracker):
        """Agent name is tracked correctly."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        mock_backend.call(prompt="Test", agent_name="reply_email")

        log = mock_tracker.get_call_log()
        assert log[0]["agent_name"] == "reply_email"

    def test_multiple_calls_tracked(self, mock_config, mock_tracker):
        """Multiple calls are all tracked."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        mock_backend.call(prompt="First")
        mock_backend.call(prompt="Second")
        mock_backend.call(prompt="Third")

        mock_tracker.assert_call_count(3)

    def test_custom_response_override(self, mock_config, mock_tracker):
        """Custom response can be injected via tracker."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        mock_tracker.set_mock_response("Custom workflow response")
        result = mock_backend.call(prompt="Test")

        assert result.content == "Custom workflow response"


# =============================================================================
# Test: Tool Workflow
# =============================================================================

@pytest.mark.mock
class TestToolWorkflow:
    """Tests for workflows involving tool calls."""

    def test_tools_available_tracked(self, mock_config, mock_tracker):
        """Available tools are tracked."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        tools = [
            {"name": "outlook_get_selected_email"},
            {"name": "outlook_reply_to_email"},
            {"name": "billomat_get_client"}
        ]

        mock_backend.call(prompt="Read email", tools=tools)

        available = mock_tracker.get_available_tools()
        assert "outlook_get_selected_email" in available
        assert "outlook_reply_to_email" in available
        assert "billomat_get_client" in available

    def test_tool_calls_from_response(self, temp_mock_dir, mock_config, mock_tracker):
        """Tool calls in mock response are tracked."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [{
                "id": "email-workflow",
                "match": {"prompt": {"$contains": "email"}},
                "response": {
                    "content": "Reading your email...",
                    "tool_calls": [
                        {"name": "outlook_get_selected_email", "arguments": {}}
                    ]
                }
            }]
        }
        (llm_dir / "workflow.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(
            config=mock_config,
            mocks_dir=llm_dir,
            tracker=mock_tracker
        )

        mock_backend.call(prompt="Please read my email")

        mock_tracker.assert_tool_called("outlook_get_selected_email")

    def test_multiple_tool_calls(self, temp_mock_dir, mock_config, mock_tracker):
        """Multiple tool calls are all tracked."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [{
                "id": "multi-tool",
                "match": {"prompt": {"$contains": "invoice"}},
                "response": {
                    "content": "Creating invoice...",
                    "tool_calls": [
                        {"name": "billomat_get_client", "arguments": {"id": "123"}},
                        {"name": "billomat_create_invoice", "arguments": {}},
                        {"name": "outlook_send_email", "arguments": {}}
                    ]
                }
            }]
        }
        (llm_dir / "workflow.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(
            config=mock_config,
            mocks_dir=llm_dir,
            tracker=mock_tracker
        )

        mock_backend.call(prompt="Create invoice for client")

        mock_tracker.assert_tool_called("billomat_get_client")
        mock_tracker.assert_tool_called("billomat_create_invoice")
        mock_tracker.assert_tool_called("outlook_send_email")
        assert mock_tracker.get_tool_call_count() == 3


# =============================================================================
# Test: Agent-Specific Workflows
# =============================================================================

@pytest.mark.mock
class TestAgentWorkflows:
    """Tests for specific agent workflows."""

    def test_reply_email_workflow(self, temp_mock_dir, mock_config, mock_tracker):
        """Reply email workflow simulation."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [{
                "id": "reply-email",
                "match": {"agent": "reply_email"},
                "response": {
                    "content": "Here's my draft reply:\n\nSehr geehrter Herr Kunde,\nvielen Dank...",
                    "tool_calls": [
                        {"name": "outlook_get_selected_email", "arguments": {}}
                    ]
                }
            }]
        }
        (llm_dir / "agents.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(
            config=mock_config,
            mocks_dir=llm_dir,
            tracker=mock_tracker
        )

        result = mock_backend.call(
            prompt="Beantworte die ausgewaehlte E-Mail",
            agent_name="reply_email"
        )

        assert result.success
        assert "Sehr geehrter" in result.content
        mock_tracker.assert_tool_called("outlook_get_selected_email")

    def test_create_offer_workflow(self, temp_mock_dir, mock_config, mock_tracker):
        """Create offer workflow simulation."""
        llm_dir = temp_mock_dir["llm"]

        mock_data = {
            "responses": [{
                "id": "create-offer",
                "match": {"agent": "create_offer"},
                "response": {
                    "content": "Angebot wurde erstellt.",
                    "tool_calls": [
                        {"name": "billomat_search_clients", "arguments": {}},
                        {"name": "billomat_create_offer", "arguments": {}}
                    ]
                }
            }]
        }
        (llm_dir / "agents.json").write_text(json.dumps(mock_data))

        mock_backend = MockLLMBackend(
            config=mock_config,
            mocks_dir=llm_dir,
            tracker=mock_tracker
        )

        result = mock_backend.call(
            prompt="Erstelle ein Angebot",
            agent_name="create_offer"
        )

        assert result.success
        mock_tracker.assert_tool_called("billomat_search_clients")
        mock_tracker.assert_tool_called("billomat_create_offer")


# =============================================================================
# Test: Streaming Workflow
# =============================================================================

@pytest.mark.mock
class TestStreamingWorkflow:
    """Tests for streaming response workflow."""

    def test_streaming_chunks_received(self, mock_config, mock_tracker):
        """Streaming callback receives chunks."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        chunks = []
        full_responses = []

        def on_chunk(token, is_thinking=False, full_response=""):
            chunks.append(token)
            full_responses.append(full_response)

        mock_backend.call(prompt="Hello", on_chunk=on_chunk)

        assert len(chunks) > 0
        # Full response should grow with each chunk
        assert len(full_responses[-1]) >= len(full_responses[0])

    def test_streaming_thinking_flag(self, mock_config, mock_tracker):
        """Streaming callback receives thinking flag."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        thinking_values = []

        def on_chunk(token, is_thinking=False, full_response=""):
            thinking_values.append(is_thinking)

        mock_backend.call(prompt="Hello", on_chunk=on_chunk)

        # Mock doesn't simulate thinking, all should be False
        assert all(t is False for t in thinking_values)


# =============================================================================
# Test: Error Scenarios
# =============================================================================

@pytest.mark.mock
class TestErrorScenarios:
    """Tests for error handling in workflows."""

    def test_empty_prompt(self, mock_config, mock_tracker):
        """Empty prompt is handled."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        result = mock_backend.call(prompt="")

        assert result.success is True
        assert result.content is not None

    def test_very_long_prompt(self, mock_config, mock_tracker):
        """Very long prompt is handled."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        long_prompt = "Test " * 10000  # ~50KB
        result = mock_backend.call(prompt=long_prompt)

        assert result.success is True

    def test_special_characters_prompt(self, mock_config, mock_tracker):
        """Special characters in prompt are handled."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        special_prompt = "Test with \n\t special chars: <>&\"' and unicode: "
        result = mock_backend.call(prompt=special_prompt)

        assert result.success is True


# =============================================================================
# Test: Metrics and Tracking
# =============================================================================

@pytest.mark.mock
class TestMetricsTracking:
    """Tests for metrics and performance tracking."""

    def test_duration_tracked(self, mock_config, mock_tracker):
        """Duration is tracked."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        result = mock_backend.call(prompt="Test")

        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0

    def test_model_reported(self, mock_config, mock_tracker):
        """Model name is reported."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        result = mock_backend.call(prompt="Test")

        assert result.model is not None
        assert len(result.model) > 0

    def test_tokens_reported(self, mock_config, mock_tracker):
        """Token counts are reported."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        result = mock_backend.call(prompt="Test")

        assert result.input_tokens is not None
        assert result.output_tokens is not None

    def test_zero_cost(self, mock_config, mock_tracker):
        """Cost is always zero in mock mode."""
        mock_backend = MockLLMBackend(config=mock_config, tracker=mock_tracker)

        result = mock_backend.call(prompt="Test")

        assert result.cost_usd == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "mock"])
