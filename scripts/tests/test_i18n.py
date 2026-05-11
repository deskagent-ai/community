# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""Tests for the i18n (internationalization) system.

Tests the translation loading, localization helpers, and UI integration.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestLoadTranslations:
    """Tests for load_translations() function."""

    def test_load_german_translations(self):
        """Should load German translations by default."""
        from config import load_translations

        translations = load_translations("de")

        assert isinstance(translations, dict)
        assert len(translations) > 0
        # Check some key translations exist
        assert "header.all" in translations
        assert translations["header.all"] == "Alle"
        assert "dialog.confirm" in translations
        assert translations["dialog.confirm"] == "Bestätigen"

    def test_load_english_translations(self):
        """Should load English translations."""
        from config import load_translations

        translations = load_translations("en")

        assert isinstance(translations, dict)
        assert len(translations) > 0
        # Check English translations
        assert "header.all" in translations
        assert translations["header.all"] == "All"
        assert "dialog.confirm" in translations
        assert translations["dialog.confirm"] == "Confirm"

    def test_fallback_to_german(self):
        """Should fall back to German for unknown language."""
        from config import load_translations

        translations = load_translations("fr")  # French not available

        assert isinstance(translations, dict)
        # Should have German translations as fallback
        assert translations.get("header.all") == "Alle"

    def test_default_language_from_config(self):
        """Should use language from config if not specified."""
        from config import load_translations

        # Default is German
        translations = load_translations()

        assert isinstance(translations, dict)
        assert len(translations) > 0

    def test_comment_field_removed(self):
        """Should remove _comment field from translations."""
        from config import load_translations

        translations = load_translations("de")

        assert "_comment" not in translations


class TestGetLocalized:
    """Tests for get_localized() function."""

    def test_get_german_field(self):
        """Should return German field when language is de."""
        from config import get_localized

        meta = {
            "description": "Deutsche Beschreibung",
            "description_en": "English description"
        }

        result = get_localized(meta, "description", "de")

        assert result == "Deutsche Beschreibung"

    def test_get_english_field(self):
        """Should return English field when available and language is en."""
        from config import get_localized

        meta = {
            "description": "Deutsche Beschreibung",
            "description_en": "English description"
        }

        result = get_localized(meta, "description", "en")

        assert result == "English description"

    def test_fallback_to_default_field(self):
        """Should fall back to default field if localized version missing."""
        from config import get_localized

        meta = {
            "description": "Deutsche Beschreibung"
            # No description_en
        }

        result = get_localized(meta, "description", "en")

        assert result == "Deutsche Beschreibung"

    def test_empty_string_for_missing_field(self):
        """Should return empty string if field completely missing."""
        from config import get_localized

        meta = {}

        result = get_localized(meta, "description", "de")

        assert result == ""

    def test_input_output_fields(self):
        """Should work with input and output fields."""
        from config import get_localized

        meta = {
            "input": ":mail: E-Mail",
            "input_en": ":mail: Email",
            "output": ":mail: Antwort",
            "output_en": ":mail: Reply"
        }

        assert get_localized(meta, "input", "de") == ":mail: E-Mail"
        assert get_localized(meta, "input", "en") == ":mail: Email"
        assert get_localized(meta, "output", "de") == ":mail: Antwort"
        assert get_localized(meta, "output", "en") == ":mail: Reply"


class TestTranslationFiles:
    """Tests for translation file structure and consistency."""

    @pytest.fixture
    def i18n_dir(self):
        """Get the i18n directory path."""
        from paths import DESKAGENT_DIR
        return DESKAGENT_DIR / "i18n"

    @pytest.fixture
    def german_translations(self, i18n_dir):
        """Load German translations."""
        with open(i18n_dir / "de.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            data.pop("_comment", None)
            return data

    @pytest.fixture
    def english_translations(self, i18n_dir):
        """Load English translations."""
        with open(i18n_dir / "en.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            data.pop("_comment", None)
            return data

    def test_translation_files_exist(self, i18n_dir):
        """Both translation files should exist."""
        assert (i18n_dir / "de.json").exists(), "German translation file missing"
        assert (i18n_dir / "en.json").exists(), "English translation file missing"

    def test_translation_files_valid_json(self, i18n_dir):
        """Translation files should be valid JSON."""
        for lang in ["de", "en"]:
            file_path = i18n_dir / f"{lang}.json"
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)  # Should not raise
                assert isinstance(data, dict)

    def test_same_keys_in_both_languages(self, german_translations, english_translations):
        """Both translation files should have the same keys."""
        german_keys = set(german_translations.keys())
        english_keys = set(english_translations.keys())

        missing_in_english = german_keys - english_keys
        missing_in_german = english_keys - german_keys

        assert not missing_in_english, f"Keys missing in English: {missing_in_english}"
        assert not missing_in_german, f"Keys missing in German: {missing_in_german}"

    def test_no_empty_translations(self, german_translations, english_translations):
        """No translation value should be empty."""
        for key, value in german_translations.items():
            assert value.strip(), f"Empty German translation for key: {key}"

        for key, value in english_translations.items():
            assert value.strip(), f"Empty English translation for key: {key}"

    def test_key_naming_convention(self, german_translations):
        """Keys should follow dot notation naming convention."""
        for key in german_translations.keys():
            # Keys should be lowercase with dots and underscores
            assert key == key.lower(), f"Key not lowercase: {key}"
            # Should have at least one dot (category.name)
            assert "." in key, f"Key missing category prefix: {key}"

    def test_minimum_translation_count(self, german_translations):
        """Should have a reasonable number of translations."""
        # We expect at least 100 translations
        assert len(german_translations) >= 100, \
            f"Too few translations: {len(german_translations)}"

    def test_required_categories_present(self, german_translations):
        """Essential translation categories should be present."""
        required_prefixes = [
            "header.",
            "dialog.",
            "prompt.",
            "result.",
            "settings.",
            "status.",
        ]

        for prefix in required_prefixes:
            matching_keys = [k for k in german_translations.keys() if k.startswith(prefix)]
            assert len(matching_keys) > 0, f"No translations for category: {prefix}"


class TestUIBuilderIntegration:
    """Tests for i18n integration in UI builder."""

    def test_build_web_ui_includes_translations(self):
        """build_web_ui should inject translations into HTML."""
        from assistant.services.ui_builder import build_web_ui

        html = build_web_ui()

        # Check that LANG and T are defined
        assert "const LANG = " in html
        assert "const T = " in html
        # Should have actual translations, not placeholder
        assert "{{LANGUAGE}}" not in html
        assert "{{TRANSLATIONS}}" not in html

    @patch('assistant.services.ui_builder._load_ui_preferences')
    @patch('assistant.services.ui_builder.load_config')
    def test_build_web_ui_german_by_default(self, mock_load_config, mock_load_prefs):
        """Should use German language by default."""
        from assistant.services.ui_builder import build_web_ui

        mock_load_prefs.return_value = {}
        mock_load_config.return_value = {
            "language": "de",
            "ui": {},
            "ai_backends": {},
            "default_ai": "claude"
        }

        html = build_web_ui()

        # Language should be German
        assert "const LANG = 'de'" in html
        # Should have German translation in the JSON
        assert '"Bestätigen"' in html  # dialog.confirm

    @patch('assistant.services.ui_builder._load_ui_preferences')
    @patch('assistant.services.ui_builder.load_config')
    def test_build_web_ui_respects_language_config(self, mock_load_config, mock_load_prefs):
        """Should use language from config."""
        mock_load_config.return_value = {
            "language": "en",
            "ui": {},
            "ai_backends": {},
            "default_ai": "claude"
        }
        # Prefs must not override the language from config
        mock_load_prefs.return_value = {}

        from assistant.services.ui_builder import build_web_ui

        # Need to reload with mocked config
        html = build_web_ui()

        # Should reflect English language
        assert "const LANG = 'en'" in html


class TestJavaScriptTranslationHelper:
    """Tests for the JavaScript t() function definition."""

    def test_t_function_defined_in_utils(self):
        """t() function should be defined in webui-utils.js."""
        from paths import DESKAGENT_DIR

        utils_path = DESKAGENT_DIR / "scripts" / "templates" / "js" / "webui-utils.js"

        with open(utils_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "function t(key, params)" in content
        assert "T[key]" in content  # Uses T global

    def test_translation_script_in_html(self):
        """HTML should define LANG and T globals before utils.js."""
        from paths import DESKAGENT_DIR

        html_path = DESKAGENT_DIR / "scripts" / "templates" / "webui.html"

        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check order: LANG/T definition should come before utils.js include
        lang_pos = content.find("const LANG = ")
        t_pos = content.find("const T = ")
        utils_pos = content.find("webui-utils.js")

        assert lang_pos > 0, "LANG not defined in HTML"
        assert t_pos > 0, "T not defined in HTML"
        assert utils_pos > 0, "webui-utils.js not included"
        assert lang_pos < utils_pos, "LANG should be defined before utils.js"
        assert t_pos < utils_pos, "T should be defined before utils.js"


class TestAgentLocalization:
    """Tests for agent/skill description localization."""

    def test_skill_list_uses_localization(self):
        """_build_skill_list should use get_localized for descriptions."""
        # Verify the import and usage in ui_builder
        from assistant.services.ui_builder import _build_skill_list

        # The function should accept config with language
        config = {
            "language": "en",
            "ui": {},
            "ai_backends": {},
            "default_ai": "claude"
        }

        # Should not raise
        skills = _build_skill_list(config)
        assert isinstance(skills, list)

    def test_agent_list_uses_localization(self):
        """_build_agent_list should use get_localized for descriptions."""
        from assistant.services.ui_builder import _build_agent_list

        config = {
            "language": "en",
            "ui": {},
            "ai_backends": {},
            "default_ai": "claude"
        }

        # Should not raise
        agents = _build_agent_list(config)
        assert isinstance(agents, list)
