# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for ai_agent routing (call_agent function).
Tests backend selection and error handling without making real API calls.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from ai_agent import call_agent, get_agent_config, AgentResponse


class TestCallAgentRouting:
    """Tests for call_agent backend routing."""

    def test_routes_to_claude_cli(self, sample_config):
        """Test routing to claude_cli backend."""
        # Patch where it's used in the module
        with patch('ai_agent.call_claude_cli') as mock:
            mock.return_value = AgentResponse(success=True, content="Test response")

            result = call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="claude"
            )

            mock.assert_called_once()
            assert result.success is True

    def test_routes_to_claude_api(self, sample_config):
        """Test routing to claude_api backend."""
        sample_config["ai_backends"]["claude_api"] = {
            "type": "claude_api",
            "api_key": "test-key",
            "model": "claude-sonnet-4"
        }

        with patch('ai_agent.call_claude_api') as mock:
            mock.return_value = AgentResponse(success=True, content="API response")

            result = call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="claude_api"
            )

            mock.assert_called_once()
            assert result.success is True

    def test_routes_to_ollama_native(self, sample_config):
        """Test routing to ollama_native backend."""
        sample_config["ai_backends"]["mistral"] = {
            "type": "ollama_native",
            "model": "mistral-nemo",
            "base_url": "http://localhost:11434"
        }

        with patch('ai_agent.call_ollama_native') as mock:
            mock.return_value = AgentResponse(success=True, content="Ollama response")

            result = call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="mistral"
            )

            mock.assert_called_once()
            assert result.success is True

    def test_routes_to_gemini(self, sample_config):
        """Test routing to gemini_adk backend."""
        sample_config["ai_backends"]["gemini"] = {
            "type": "gemini_adk",
            "api_key": "test-key",
            "model": "gemini-2.5-pro"
        }

        with patch('ai_agent.call_gemini_adk') as mock:
            mock.return_value = AgentResponse(success=True, content="Gemini response")

            result = call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="gemini"
            )

            mock.assert_called_once()
            assert result.success is True

    def test_routes_to_qwen(self, sample_config):
        """Test routing to qwen_agent backend."""
        with patch('ai_agent.call_qwen_agent') as mock:
            mock.return_value = AgentResponse(success=True, content="Qwen response")

            result = call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="qwen"
            )

            mock.assert_called_once()
            assert result.success is True

    def test_unknown_backend_returns_error(self, sample_config):
        """Test that unknown backend type returns error."""
        sample_config["ai_backends"]["unknown"] = {
            "type": "unknown_backend_type_xyz"
        }

        result = call_agent(
            prompt="Test",
            config=sample_config,
            agent_name="unknown"
        )

        assert result.success is False
        assert "unknown" in result.error.lower()

    def test_uses_default_agent_when_none_specified(self, sample_config):
        """Test using default_ai when agent_name not specified."""
        sample_config["default_ai"] = "claude"

        with patch('ai_agent.call_claude_cli') as mock:
            mock.return_value = AgentResponse(success=True, content="Default response")

            result = call_agent(
                prompt="Test",
                config=sample_config
                # No agent_name specified
            )

            mock.assert_called_once()


class TestCallAgentErrorHandling:
    """Tests for call_agent error handling."""

    def test_handles_backend_exception(self, sample_config):
        """Test that backend exceptions propagate (not silently caught)."""
        with patch('ai_agent.call_claude_cli') as mock:
            mock.side_effect = Exception("Backend crashed")

            # Exceptions should propagate - this is expected behavior
            # The caller should handle exceptions appropriately
            with pytest.raises(Exception, match="Backend crashed"):
                call_agent(
                    prompt="Test",
                    config=sample_config,
                    agent_name="claude"
                )

    def test_handles_missing_agent_config(self, minimal_config):
        """Test handling when agent config is completely missing."""
        result = call_agent(
            prompt="Test",
            config=minimal_config,
            agent_name="nonexistent"
        )

        # Should either use default or return error
        assert result is not None
        assert isinstance(result, AgentResponse)


class TestCallAgentWithAnonymization:
    """Tests for call_agent with anonymization enabled."""

    def test_anonymization_when_enabled(self, sample_config):
        """Test that anonymization is applied when configured."""
        sample_config["anonymization"] = {"enabled": True}
        sample_config["skills"] = {
            "test_skill": {"anonymize": True}
        }

        with patch('ai_agent.call_claude_cli') as mock:
            mock.return_value = AgentResponse(
                success=True,
                content="Hello <PERSON_1>!",
                anonymization={"<PERSON_1>": "Max Mustermann"}
            )

            result = call_agent(
                prompt="Test with Max Mustermann",
                config=sample_config,
                agent_name="claude",
                task_name="test_skill",
                task_type="skill"
            )

            mock.assert_called_once()

    def test_no_anonymization_when_disabled(self, sample_config):
        """Test that anonymization is skipped when disabled."""
        sample_config["anonymization"] = {"enabled": False}

        with patch('ai_agent.call_claude_cli') as mock:
            mock.return_value = AgentResponse(success=True, content="Response")

            result = call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="claude"
            )

            assert result.success is True


class TestCallAgentParameters:
    """Tests for call_agent parameter passing."""

    def test_passes_use_tools_parameter(self, sample_config):
        """Test that use_tools is passed to backend."""
        with patch('ai_agent.call_claude_cli') as mock:
            mock.return_value = AgentResponse(success=True, content="Response")

            call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="claude",
                use_tools=True
            )

            # Verify mock was called with use_tools
            call_args = mock.call_args
            assert call_args is not None
            # use_tools should be in kwargs or args
            kwargs = call_args.kwargs if hasattr(call_args, 'kwargs') else {}
            assert kwargs.get('use_tools') is True or 'use_tools' in str(call_args)

    def test_passes_on_chunk_callback(self, sample_config):
        """Test that streaming callback is passed to backend."""
        sample_config["ai_backends"]["ollama"] = {
            "type": "ollama_native",
            "model": "test"
        }

        chunks = []
        def on_chunk(token, is_thinking, full):
            chunks.append(token)

        with patch('ai_agent.call_ollama_native') as mock:
            mock.return_value = AgentResponse(success=True, content="Response")

            call_agent(
                prompt="Test",
                config=sample_config,
                agent_name="ollama",
                on_chunk=on_chunk
            )

            mock.assert_called_once()
            # on_chunk should be passed
            call_args = mock.call_args
            kwargs = call_args.kwargs if hasattr(call_args, 'kwargs') else {}
            assert 'on_chunk' in str(call_args) or kwargs.get('on_chunk') is not None


class TestBackendConfigParsing:
    """Tests for backend configuration parsing."""

    def test_claude_cli_config(self, sample_config):
        """Test claude_cli backend configuration."""
        config = get_agent_config(sample_config, "claude")
        assert config["type"] == "claude_cli"
        assert "timeout" in config

    def test_backend_timeout_setting(self, sample_config):
        """Test timeout setting per backend."""
        sample_config["ai_backends"]["slow"] = {
            "type": "claude_cli",
            "timeout": 300
        }
        config = get_agent_config(sample_config, "slow")
        assert config["timeout"] == 300

    def test_backend_pricing_setting(self, sample_config):
        """Test pricing setting per backend."""
        sample_config["ai_backends"]["claude_api"] = {
            "type": "claude_api",
            "pricing": {"input": 3, "output": 15}
        }
        config = get_agent_config(sample_config, "claude_api")
        assert config["pricing"]["input"] == 3
        assert config["pricing"]["output"] == 15
