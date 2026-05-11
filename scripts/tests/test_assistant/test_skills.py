# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Tests for assistant.skills module.
Tests skill loading and processing.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


class TestLoadSkill:
    """Tests for load_skill function."""

    def test_load_existing_skill(self, temp_skills_dir, monkeypatch):
        """Test loading an existing skill file."""
        from assistant import skills
        monkeypatch.setattr(skills, "get_skills_dir", lambda: temp_skills_dir)

        result = skills.load_skill("mail_reply")

        assert result is not None
        assert result["name"] == "Mail Reply"
        assert result["use_knowledge"] is True
        assert "content" in result

    def test_load_nonexistent_skill(self, temp_skills_dir, monkeypatch):
        """Test loading a non-existent skill returns None."""
        from assistant import skills
        monkeypatch.setattr(skills, "get_skills_dir", lambda: temp_skills_dir)

        result = skills.load_skill("nonexistent_skill")

        assert result is None

    def test_skill_parses_metadata(self, tmp_path, monkeypatch):
        """Test skill metadata is parsed correctly."""
        from assistant import skills

        # Create skill with specific metadata
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "test_skill.md").write_text(
            "name: Custom Name\nuse_knowledge: false\n\nContent here",
            encoding="utf-8"
        )
        monkeypatch.setattr(skills, "get_skills_dir", lambda: skills_dir)

        result = skills.load_skill("test_skill")

        assert result["name"] == "Custom Name"
        assert result["use_knowledge"] is False


class TestLoadKnowledge:
    """Tests for load_knowledge function."""

    def test_load_knowledge_files(self, temp_knowledge_dir, monkeypatch):
        """Test loading all knowledge files."""
        from assistant import skills
        monkeypatch.setattr(skills, "get_knowledge_dir", lambda: temp_knowledge_dir)

        result = skills.load_knowledge()

        assert "company.md" in result
        assert "products.md" in result
        assert "Example GmbH" in result

    def test_load_knowledge_empty_dir(self, tmp_path, monkeypatch):
        """Test loading from empty knowledge directory."""
        from assistant import skills

        # Create empty knowledge dir
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()
        monkeypatch.setattr(skills, "get_knowledge_dir", lambda: knowledge_dir)

        result = skills.load_knowledge()

        assert result == ""

    def test_load_knowledge_no_dir(self, tmp_path, monkeypatch):
        """Test loading when knowledge directory doesn't exist."""
        from assistant import skills
        nonexistent_dir = tmp_path / "nonexistent"
        monkeypatch.setattr(skills, "get_knowledge_dir", lambda: nonexistent_dir)

        result = skills.load_knowledge()

        assert result == ""


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_existing_config(self, tmp_path, monkeypatch, sample_config):
        """Test loading existing config.json."""
        import json
        from assistant import skills

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(sample_config), encoding="utf-8")
        # Patch the load_config_from_paths function that skills.load_config wraps
        monkeypatch.setattr(skills, "load_config_from_paths", lambda: sample_config)

        result = skills.load_config()

        assert result["default_ai"] == "claude"
        assert "ai_backends" in result

    def test_load_missing_config_returns_default(self, tmp_path, monkeypatch):
        """Test loading returns default when config.json missing."""
        from assistant import skills
        # Patch the load_config_from_paths function to return default
        monkeypatch.setattr(skills, "load_config_from_paths", lambda: {"timeout": 120})

        result = skills.load_config()

        assert result == {"timeout": 120}
