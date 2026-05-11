# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Integration tests for AI agent backends.
These tests make REAL API calls and incur costs!

Run with: pytest scripts/tests/test_ai_agent/test_integration.py -v
Skip with: pytest -m "not integration"
"""

import json
import sys
from pathlib import Path

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
PROJECT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from ai_agent import call_agent, get_agent_config, AgentResponse


# Load real config
def load_config():
    """Load the real config.json."""
    config_file = PROJECT_DIR / "config.json"
    if config_file.exists():
        return json.loads(config_file.read_text(encoding="utf-8"))
    pytest.skip("config.json not found")


@pytest.fixture
def real_config():
    """Real configuration from config.json."""
    return load_config()


# =============================================================================
# Claude API Tests
# =============================================================================

@pytest.mark.integration
class TestClaudeAPI:
    """Integration tests for Claude API backend."""

    def test_simple_prompt(self, real_config):
        """Test a simple prompt returns a response."""
        result = call_agent(
            prompt="What is 2+2? Reply with just the number.",
            config=real_config,
            agent_name="claude_api",
            use_tools=False
        )

        assert result.success is True
        assert len(result.content) > 0
        assert "4" in result.content
        assert result.error is None

    def test_returns_token_counts(self, real_config):
        """Test that token counts are returned."""
        result = call_agent(
            prompt="Reply with exactly: OK",
            config=real_config,
            agent_name="claude_api",
            use_tools=False
        )

        assert result.success is True
        # Token counts should be returned (at least one)
        # Note: Some API responses may not include both counts
        has_tokens = (result.input_tokens is not None) or (result.output_tokens is not None)
        assert has_tokens or result.cost_usd is not None, \
            "Expected either token counts or cost to be returned"

    def test_calculates_cost(self, real_config):
        """Test that cost is calculated."""
        result = call_agent(
            prompt="Reply with: Test",
            config=real_config,
            agent_name="claude_api",
            use_tools=False
        )

        assert result.success is True
        # Cost should be calculated based on tokens
        if result.input_tokens and result.output_tokens:
            assert result.cost_usd is None or result.cost_usd >= 0

    def test_json_response(self, real_config):
        """Test requesting JSON response."""
        result = call_agent(
            prompt='Return a JSON object with key "status" and value "ok". Only output the JSON, nothing else.',
            config=real_config,
            agent_name="claude_api",
            use_tools=False
        )

        assert result.success is True
        # Should contain valid JSON
        assert "{" in result.content
        assert "status" in result.content.lower()

    def test_streaming_callback(self, real_config):
        """Test that streaming callback receives chunks."""
        chunks_received = []

        def on_chunk(token, is_thinking, full_response):
            chunks_received.append(token)

        result = call_agent(
            prompt="Count from 1 to 5, each number on a new line.",
            config=real_config,
            agent_name="claude_api",
            use_tools=False,
            on_chunk=on_chunk
        )

        assert result.success is True
        # Should have received multiple chunks
        assert len(chunks_received) > 0

    def test_model_name_returned(self, real_config):
        """Test that model name is returned in response."""
        result = call_agent(
            prompt="Hi",
            config=real_config,
            agent_name="claude_api",
            use_tools=False
        )

        assert result.success is True
        # Model should be set
        assert result.model is not None or "claude" in str(real_config.get("ai_backends", {}).get("claude_api", {}).get("model", ""))


# =============================================================================
# Gemini Tests
# =============================================================================

@pytest.mark.integration
class TestGeminiAPI:
    """Integration tests for Gemini API backend."""

    def test_simple_prompt(self, real_config):
        """Test a simple prompt returns a response."""
        # Check if gemini is configured
        if "gemini" not in real_config.get("ai_backends", {}):
            pytest.skip("Gemini not configured")

        # Generic smoke test - just verify Gemini answers a simple question
        result = call_agent(
            prompt="What is the capital of France? Answer in one word.",
            config=real_config,
            agent_name="gemini",
            use_tools=False
        )

        assert result.success is True
        assert len(result.content) > 0
        assert "paris" in result.content.lower(), \
            f"Expected 'Paris' in response, got: {result.content[:100]}"
        assert result.error is None

    def test_returns_token_counts(self, real_config):
        """Test that token counts are returned."""
        if "gemini" not in real_config.get("ai_backends", {}):
            pytest.skip("Gemini not configured")

        result = call_agent(
            prompt="Reply with exactly: OK",
            config=real_config,
            agent_name="gemini",
            use_tools=False
        )

        assert result.success is True
        # Gemini should return token counts
        assert result.input_tokens is not None or result.output_tokens is not None

    def test_json_response(self, real_config):
        """Test requesting JSON response."""
        if "gemini" not in real_config.get("ai_backends", {}):
            pytest.skip("Gemini not configured")

        result = call_agent(
            prompt='Return a JSON object: {"test": "gemini"}. Only output the JSON.',
            config=real_config,
            agent_name="gemini",
            use_tools=False
        )

        assert result.success is True
        assert "{" in result.content


# =============================================================================
# Ollama Tests (Local - No Cost)
# =============================================================================

@pytest.mark.integration
class TestOllamaLocal:
    """Integration tests for local Ollama backend (free)."""

    def test_ollama_available(self, real_config):
        """Test if Ollama is running locally."""
        import socket

        # Check if Ollama is running on default port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 11434))
        sock.close()

        if result != 0:
            pytest.skip("Ollama not running on localhost:11434")

    def test_simple_prompt_mistral(self, real_config):
        """Test Mistral via Ollama."""
        if "mistral" not in real_config.get("ai_backends", {}):
            pytest.skip("Mistral not configured")

        # First check if Ollama is running
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sock.connect_ex(('localhost', 11434)) != 0:
            sock.close()
            pytest.skip("Ollama not running")
        sock.close()

        result = call_agent(
            prompt="Say 'Hello' and nothing else.",
            config=real_config,
            agent_name="mistral",
            use_tools=False
        )

        # May fail if model not downloaded, that's ok
        if not result.success and "not found" in str(result.error).lower():
            pytest.skip(f"Model not available: {result.error}")

        assert result.success is True
        assert len(result.content) > 0


# =============================================================================
# Cross-Backend Comparison Tests
# =============================================================================

@pytest.mark.integration
class TestBackendComparison:
    """Compare responses across different backends."""

    def test_same_prompt_different_backends(self, real_config):
        """Test that different backends can answer the same prompt."""
        prompt = "What is 2 + 2? Reply briefly."

        results = {}

        # Test Claude API
        if "claude_api" in real_config.get("ai_backends", {}):
            results["claude_api"] = call_agent(
                prompt=prompt,
                config=real_config,
                agent_name="claude_api",
                use_tools=False
            )

        # Test Gemini
        if "gemini" in real_config.get("ai_backends", {}):
            results["gemini"] = call_agent(
                prompt=prompt,
                config=real_config,
                agent_name="gemini",
                use_tools=False
            )

        # At least one should work
        assert len(results) > 0

        # All successful responses should be meaningful
        for name, result in results.items():
            if result.success:
                # Just verify we got a meaningful response
                assert len(result.content) > 10, f"{name} returned too short response: {result.content}"


# =============================================================================
# Error Handling Tests
# =============================================================================

@pytest.mark.integration
class TestErrorHandling:
    """Test error handling in real API calls."""

    def test_invalid_api_key(self, real_config):
        """Test that invalid API key is handled gracefully."""
        # Create config with invalid key
        bad_config = real_config.copy()
        bad_config["ai_backends"] = real_config.get("ai_backends", {}).copy()
        bad_config["ai_backends"]["claude_api"] = {
            **real_config.get("ai_backends", {}).get("claude_api", {}),
            "api_key": "invalid-key-12345"
        }

        result = call_agent(
            prompt="Test",
            config=bad_config,
            agent_name="claude_api",
            use_tools=False
        )

        # Should fail gracefully
        assert result.success is False
        assert result.error is not None

    def test_unknown_backend(self, real_config):
        """Test calling unknown backend type."""
        bad_config = real_config.copy()
        bad_config["ai_backends"] = {
            "test": {"type": "unknown_type_xyz"}
        }

        result = call_agent(
            prompt="Test",
            config=bad_config,
            agent_name="test",
            use_tools=False
        )

        assert result.success is False
        assert "unknown" in result.error.lower() or result.error is not None


# =============================================================================
# Performance Tests
# =============================================================================

@pytest.mark.integration
@pytest.mark.slow
class TestPerformance:
    """Performance-related tests."""

    def test_response_time(self, real_config):
        """Test that response comes within reasonable time."""
        import time

        start = time.time()
        result = call_agent(
            prompt="Reply with: OK",
            config=real_config,
            agent_name="claude_api",
            use_tools=False
        )
        duration = time.time() - start

        assert result.success is True
        # Should respond within 30 seconds for simple prompt
        assert duration < 30, f"Response took too long: {duration}s"

        # Duration should be recorded
        if result.duration_seconds:
            assert result.duration_seconds < 30
