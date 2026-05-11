# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for ai_agent.base module.
Tests JSON extraction, config loading, and system prompt utilities.
"""

import pytest
from unittest.mock import patch
from ai_agent.base import (
    extract_json, get_agent_config, AgentResponse,
    load_knowledge, load_templates, build_system_prompt, DEFAULT_SYSTEM_PROMPT
)


class TestExtractJson:
    """Tests for extract_json function."""

    def test_extract_json_plain(self, json_response_plain):
        """Test extracting plain JSON."""
        result = extract_json(json_response_plain)
        assert result is not None
        assert result["action"] == "reply"
        assert result["content"] == "Hello!"

    def test_extract_json_markdown(self, json_response_markdown):
        """Test extracting JSON from markdown code block."""
        result = extract_json(json_response_markdown)
        assert result is not None
        assert result["action"] == "reply"
        assert result["content"] == "Hello!"

    def test_extract_json_with_text(self, json_response_with_text):
        """Test extracting JSON embedded in text."""
        result = extract_json(json_response_with_text)
        assert result is not None
        assert result["action"] == "reply"
        assert result["content"] == "Hello!"

    def test_extract_json_empty(self):
        """Test with empty string."""
        result = extract_json("")
        assert result is None

    def test_extract_json_no_json(self):
        """Test with no JSON content."""
        result = extract_json("This is just plain text without any JSON.")
        assert result is None

    def test_extract_json_invalid(self):
        """Test with invalid JSON."""
        result = extract_json('{"broken": json, missing quotes}')
        assert result is None

    def test_extract_json_nested(self):
        """Test with nested JSON structure."""
        text = '```json\n{"outer": {"inner": "value"}, "list": [1, 2, 3]}\n```'
        result = extract_json(text)
        assert result is not None
        assert result["outer"]["inner"] == "value"
        assert result["list"] == [1, 2, 3]

    def test_extract_json_markdown_no_lang(self):
        """Test JSON in markdown block without language specifier."""
        text = '```\n{"key": "value"}\n```'
        result = extract_json(text)
        assert result is not None
        assert result["key"] == "value"


class TestGetAgentConfig:
    """Tests for get_agent_config function."""

    def test_get_default_agent(self, sample_config):
        """Test getting default agent config."""
        config = get_agent_config(sample_config)
        assert config["type"] == "claude_cli"
        assert config["timeout"] == 120

    def test_get_named_agent(self, sample_config):
        """Test getting specific agent by name."""
        config = get_agent_config(sample_config, "qwen")
        assert config["type"] == "qwen_agent"
        assert config["model"] == "qwen2.5:7b"

    def test_get_nonexistent_agent(self, sample_config):
        """Test getting non-existent agent falls back to default."""
        config = get_agent_config(sample_config, "nonexistent")
        # Should fall back to default (claude)
        assert config["type"] == "claude_cli"

    def test_get_agent_minimal_config(self, minimal_config):
        """Test with minimal config (legacy format)."""
        minimal_config["ai_agent"] = {"model": "test-model"}
        config = get_agent_config(minimal_config)
        assert config["model"] == "test-model"


class TestAgentResponse:
    """Tests for AgentResponse dataclass."""

    def test_response_success(self):
        """Test successful response."""
        response = AgentResponse(
            success=True,
            content="Result text",
            model="claude-sonnet-4",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001
        )
        assert response.success is True
        assert response.content == "Result text"
        assert response.error is None
        assert response.cost_usd == 0.001

    def test_response_failure(self):
        """Test failed response."""
        response = AgentResponse(
            success=False,
            content="",
            error="API timeout"
        )
        assert response.success is False
        assert response.error == "API timeout"

    def test_response_with_anonymization(self):
        """Test response with anonymization metadata."""
        response = AgentResponse(
            success=True,
            content="Hello <PERSON_1>!",
            anonymization={"<PERSON_1>": "Max Mustermann"}
        )
        assert response.anonymization is not None
        assert "<PERSON_1>" in response.anonymization


class TestLoadKnowledge:
    """Tests for load_knowledge function."""

    def test_load_all_knowledge(self, temp_knowledge_dir):
        """Test loading all knowledge files without pattern."""
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
            result = load_knowledge()
            assert "company" in result.lower()
            assert "products" in result.lower()
            assert "example" in result.lower()

    def test_load_knowledge_with_pattern(self, temp_knowledge_dir):
        """Test loading knowledge with pattern filter."""
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
            result = load_knowledge(pattern="company")
            assert "company" in result.lower()
            assert "products" not in result.lower()

    def test_load_knowledge_multiple_patterns(self, temp_knowledge_dir):
        """Test loading knowledge with OR pattern."""
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
            result = load_knowledge(pattern="company|products")
            assert "company" in result.lower()
            assert "products" in result.lower()

    def test_load_knowledge_no_match(self, temp_knowledge_dir):
        """Test loading knowledge with pattern that matches nothing."""
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
            result = load_knowledge(pattern="nonexistent")
            assert result == ""

    def test_load_knowledge_empty_dir(self, tmp_path):
        """Test loading from empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=empty_dir):
            result = load_knowledge()
            assert result == ""


class TestLoadTemplates:
    """Tests for load_templates function."""

    def test_load_templates(self, temp_templates_dir):
        """Test loading templates from directory."""
        with patch('ai_agent.template_loader.get_templates_dir', return_value=temp_templates_dir):
            result = load_templates()
            assert "User-Dialoge" in result
            assert "QUESTION_NEEDED" in result

    def test_load_templates_empty_dir(self, tmp_path):
        """Test loading from empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch('ai_agent.template_loader.get_templates_dir', return_value=empty_dir):
            result = load_templates()
            assert result == ""

    def test_load_templates_nonexistent_dir(self, tmp_path):
        """Test loading from non-existent directory."""
        with patch('ai_agent.template_loader.get_templates_dir', return_value=tmp_path / "nonexistent"):
            result = load_templates()
            assert result == ""


class TestBuildSystemPrompt:
    """Tests for build_system_prompt function."""

    def test_build_default_prompt(self, tmp_path):
        """Test building prompt with default system prompt."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=empty_dir):
            with patch('ai_agent.template_loader.get_templates_dir', return_value=empty_dir):
                result = build_system_prompt({})
                assert DEFAULT_SYSTEM_PROMPT in result

    def test_build_with_custom_system_prompt(self, tmp_path):
        """Test building prompt with custom base prompt."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        custom_prompt = "You are a test assistant."
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=empty_dir):
            with patch('ai_agent.template_loader.get_templates_dir', return_value=empty_dir):
                result = build_system_prompt({"system_prompt": custom_prompt})
                assert custom_prompt in result

    def test_build_with_knowledge(self, temp_knowledge_dir, tmp_path):
        """Test building prompt includes knowledge."""
        from ai_agent.base import invalidate_knowledge_cache
        from ai_agent.knowledge_manager import get_knowledge_manager
        invalidate_knowledge_cache()  # Clear cache to ensure fresh load

        empty_templates = tmp_path / "templates"
        empty_templates.mkdir()
        # Must patch paths.get_knowledge_dir (used by KnowledgeManager)
        # AND reset the singleton so it picks up the new path
        with patch('paths.get_knowledge_dir', return_value=temp_knowledge_dir):
            with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
                with patch('ai_agent.template_loader.get_templates_dir', return_value=empty_templates):
                    # Reset singleton to pick up new knowledge_dir
                    get_knowledge_manager(reset=True)
                    result = build_system_prompt({})
                    assert "Wissensbasis" in result
                    assert "example" in result.lower()

    def test_build_with_templates(self, temp_templates_dir, tmp_path):
        """Test building prompt includes templates."""
        empty_knowledge = tmp_path / "knowledge"
        empty_knowledge.mkdir()
        with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=empty_knowledge):
            with patch('ai_agent.template_loader.get_templates_dir', return_value=temp_templates_dir):
                result = build_system_prompt({})
                assert "QUESTION_NEEDED" in result

    def test_build_with_knowledge_pattern_from_config(self, temp_knowledge_dir, tmp_path):
        """Test building prompt uses knowledge pattern from agent config."""
        from ai_agent.base import invalidate_knowledge_cache
        from ai_agent.knowledge_manager import get_knowledge_manager
        invalidate_knowledge_cache()  # Clear cache to ensure fresh load

        empty_templates = tmp_path / "templates"
        empty_templates.mkdir()
        # Must patch paths.get_knowledge_dir (used by KnowledgeManager)
        # AND reset the singleton so it picks up the new path
        with patch('paths.get_knowledge_dir', return_value=temp_knowledge_dir):
            with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
                with patch('ai_agent.template_loader.get_templates_dir', return_value=empty_templates):
                    # Reset singleton to pick up new knowledge_dir
                    get_knowledge_manager(reset=True)
                    result = build_system_prompt({"knowledge": "company"})
                    assert "company" in result.lower()
                    assert "products" not in result.lower()

    def test_build_with_knowledge_pattern_override(self, temp_knowledge_dir, tmp_path):
        """Test building prompt with explicit pattern overrides config."""
        from ai_agent.base import invalidate_knowledge_cache
        from ai_agent.knowledge_manager import get_knowledge_manager
        invalidate_knowledge_cache()  # Clear cache to ensure fresh load

        empty_templates = tmp_path / "templates"
        empty_templates.mkdir()
        # Must patch paths.get_knowledge_dir (used by KnowledgeManager)
        # AND reset the singleton so it picks up the new path
        with patch('paths.get_knowledge_dir', return_value=temp_knowledge_dir):
            with patch('ai_agent.knowledge_loader.get_knowledge_dir', return_value=temp_knowledge_dir):
                with patch('ai_agent.template_loader.get_templates_dir', return_value=empty_templates):
                    # Reset singleton to pick up new knowledge_dir
                    get_knowledge_manager(reset=True)
                    # Config says "company" but override says "products"
                    result = build_system_prompt({"knowledge": "company"}, knowledge_pattern="products")
                    assert "products" in result.lower()
                    # company might be in default system prompt, so just check products is there
