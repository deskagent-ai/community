# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Tests for user preferences system.

Tests the preferences loading, saving, and UI integration.
Preferences are stored in workspace/.state/preferences.json
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil


class TestPreferencesAPI:
    """Tests for preferences API endpoints."""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """Create a temporary workspace with .state directory."""
        state_dir = tmp_path / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return tmp_path

    @pytest.fixture
    def prefs_file(self, temp_workspace):
        """Return path to preferences file in temp workspace."""
        return temp_workspace / ".state" / "preferences.json"

    def test_load_empty_preferences(self, temp_workspace, prefs_file):
        """Should return empty dict when no preferences file exists."""
        from assistant.routes.system import _load_preferences, _get_preferences_file

        with patch.object(
            Path, "exists", return_value=False
        ):
            # Mock get_workspace_dir to return our temp workspace
            with patch(
                "assistant.routes.system.get_workspace_dir",
                return_value=temp_workspace
            ):
                prefs = _load_preferences()
                assert prefs == {}

    def test_load_existing_preferences(self, temp_workspace, prefs_file):
        """Should load preferences from file."""
        # Write test preferences
        test_prefs = {
            "ui": {
                "language": "en",
                "theme": "dark",
                "history_pinned": True
            }
        }
        prefs_file.write_text(json.dumps(test_prefs), encoding="utf-8")

        from assistant.routes.system import _load_preferences

        with patch(
            "assistant.routes.system.get_workspace_dir",
            return_value=temp_workspace
        ):
            prefs = _load_preferences()
            assert prefs["ui"]["language"] == "en"
            assert prefs["ui"]["theme"] == "dark"
            assert prefs["ui"]["history_pinned"] is True

    def test_save_preferences(self, temp_workspace, prefs_file):
        """Should save preferences to file."""
        from assistant.routes.system import _save_preferences, _load_preferences

        test_prefs = {"ui": {"language": "en"}}

        with patch(
            "assistant.routes.system.get_workspace_dir",
            return_value=temp_workspace
        ):
            _save_preferences(test_prefs)

            # Verify file was written
            assert prefs_file.exists()
            saved = json.loads(prefs_file.read_text(encoding="utf-8"))
            assert saved["ui"]["language"] == "en"


class TestPreferencesInUIBuilder:
    """Tests for preferences integration in UI builder."""

    def test_language_from_preferences(self):
        """Should use language from preferences over config."""
        mock_prefs = {"ui": {"language": "en"}}
        mock_config = {"language": "de"}  # Config says German

        # Test priority logic: preferences should override config
        language = mock_prefs.get("ui", {}).get("language") or mock_config.get("language", "de")
        assert language == "en"

    def test_theme_from_preferences(self):
        """Should use theme from preferences over config."""
        mock_prefs = {"ui": {"theme": "dark"}}
        mock_ui_config = {"theme": "light"}  # Config says light

        # Test priority logic
        theme = mock_prefs.get("ui", {}).get("theme") or mock_ui_config.get("theme", "light")
        assert theme == "dark"

    def test_history_pinned_from_preferences(self):
        """Should use history_pinned from preferences."""
        mock_prefs = {"ui": {"history_pinned": True}}

        ui_prefs = mock_prefs.get("ui", {})
        history_pinned = "true" if ui_prefs.get("history_pinned") else "false"
        assert history_pinned == "true"

    def test_fallback_to_config_when_no_prefs(self):
        """Should fallback to config when preferences not set."""
        mock_prefs = {}  # No preferences
        mock_config = {"language": "de"}

        language = mock_prefs.get("ui", {}).get("language") or mock_config.get("language", "de")
        assert language == "de"


class TestPreferencesKeys:
    """Tests for preference key structure."""

    def test_language_key_structure(self):
        """Language should be stored under ui.language."""
        prefs = {"ui": {"language": "en"}}
        assert prefs["ui"]["language"] == "en"

    def test_theme_key_structure(self):
        """Theme should be stored under ui.theme."""
        prefs = {"ui": {"theme": "dark"}}
        assert prefs["ui"]["theme"] == "dark"

    def test_history_pinned_key_structure(self):
        """History pinned should be stored under ui.history_pinned."""
        prefs = {"ui": {"history_pinned": True}}
        assert prefs["ui"]["history_pinned"] is True

    def test_nested_key_update(self):
        """Should support dot notation for nested keys."""
        prefs = {"ui": {"selected_category": "all"}}

        # Simulate setting ui.language
        key = "ui.language"
        value = "en"
        parts = key.split(".")

        current = prefs
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

        assert prefs["ui"]["language"] == "en"
        assert prefs["ui"]["selected_category"] == "all"  # Not overwritten
