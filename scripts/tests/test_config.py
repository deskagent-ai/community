# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Unit Tests for save_system_setting() in config.py.

Covers:
- Basic functionality (create, preserve, overwrite)
- Dot-notation navigation (flat, 2-level, 3-level, 4-level)
- Stale key cleanup (bug debug-003 reproduction)
- Edge cases (empty config, corrupted JSON, unicode, sibling keys)
- Type consistency (bool, str, int, float, list, dict, None)
- Integration (full save/load cycle)
"""

import json

import pytest

from config import save_system_setting


# =============================================================================
# TestSaveSystemSettingBasic - Grundfunktionalitaet (3 Tests)
# =============================================================================

class TestSaveSystemSettingBasic:
    """Tests fuer grundlegende save_system_setting() Funktionalitaet."""

    def test_creates_json_if_not_exists(self, tmp_path, monkeypatch):
        """Erstellt system.json wenn sie nicht existiert."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)

        save_system_setting("developer_mode", True)

        system_file = tmp_path / "system.json"
        assert system_file.exists()
        config = json.loads(system_file.read_text(encoding="utf-8"))
        assert config["developer_mode"] is True

    def test_preserves_existing_config(self, tmp_path, monkeypatch):
        """Bestehende Keys bleiben beim Schreiben neuer Keys erhalten."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text(
            json.dumps({"existing_key": "original_value"}),
            encoding="utf-8",
        )

        save_system_setting("new_key", "new_value")

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["existing_key"] == "original_value"
        assert config["new_key"] == "new_value"

    def test_overwrites_existing_value(self, tmp_path, monkeypatch):
        """Vorhandener Key wird mit neuem Wert ueberschrieben."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text(
            json.dumps({"content_mode": "standard"}),
            encoding="utf-8",
        )

        save_system_setting("content_mode", "custom")

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["content_mode"] == "custom"


# =============================================================================
# TestDotNotation - Dot-Notation Navigation (5 Tests via parametrize)
# =============================================================================

class TestDotNotation:
    """Tests fuer Dot-Notation Key-Navigation in save_system_setting()."""

    @pytest.mark.parametrize(
        "key, value, expected_path",
        [
            pytest.param(
                "developer_mode",
                True,
                {"developer_mode": True},
                id="flat",
            ),
            pytest.param(
                "ui.theme",
                "dark",
                {"ui": {"theme": "dark"}},
                id="2-level",
            ),
            pytest.param(
                "anonymization.enabled",
                False,
                {"anonymization": {"enabled": False}},
                id="anonymization",
            ),
            pytest.param(
                "security.prompt_injection.enabled",
                True,
                {"security": {"prompt_injection": {"enabled": True}}},
                id="3-level",
            ),
            pytest.param(
                "a.b.c.d",
                42,
                {"a": {"b": {"c": {"d": 42}}}},
                id="4-level",
            ),
        ],
    )
    def test_dot_notation_depths(self, tmp_path, monkeypatch, key, value, expected_path):
        """Dot-Notation navigiert korrekt in verschachtelte Strukturen."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)

        save_system_setting(key, value)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config == expected_path


# =============================================================================
# TestStaleKeyCleanup - Bug-Reproduktion debug-003 (3 Tests)
# =============================================================================

class TestStaleKeyCleanup:
    """Tests fuer Stale-Key-Cleanup nach Dot-Notation-Fix."""

    def test_removes_stale_flat_key(self, tmp_path, monkeypatch):
        """Reproduziert Bug debug-003: Stale flat key neben nested key."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text(
            json.dumps({
                "anonymization": {"enabled": True},
                "anonymization.enabled": False,
            }),
            encoding="utf-8",
        )

        save_system_setting("anonymization.enabled", False)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["anonymization"]["enabled"] is False
        assert "anonymization.enabled" not in config

    def test_only_removes_matching_stale_key(self, tmp_path, monkeypatch):
        """Entfernt nur den stale Key der zum geschriebenen Key passt."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text(
            json.dumps({
                "anonymization": {"enabled": True},
                "anonymization.enabled": False,
                "other.stale.key": "should_remain",
            }),
            encoding="utf-8",
        )

        save_system_setting("anonymization.enabled", True)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["anonymization"]["enabled"] is True
        assert "anonymization.enabled" not in config
        # Andere stale keys bleiben unangetastet
        assert config["other.stale.key"] == "should_remain"

    def test_flat_key_write_no_cleanup(self, tmp_path, monkeypatch):
        """Flache Keys (ohne Dot) loesen keinen Cleanup aus."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text(
            json.dumps({
                "developer_mode": False,
                "anonymization.enabled": True,
            }),
            encoding="utf-8",
        )

        save_system_setting("developer_mode", True)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["developer_mode"] is True
        # Andere stale keys bleiben bei flat-key writes erhalten
        assert config["anonymization.enabled"] is True


# =============================================================================
# TestEdgeCases - Randfaelle (4 Tests)
# =============================================================================

class TestEdgeCases:
    """Tests fuer Edge Cases in save_system_setting()."""

    def test_empty_config(self, tmp_path, monkeypatch):
        """Schreibt in leere (aber existierende) Config-Datei."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text("{}", encoding="utf-8")

        save_system_setting("anonymization.enabled", True)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config == {"anonymization": {"enabled": True}}

    def test_corrupted_json_recovers(self, tmp_path, monkeypatch):
        """Korruptes JSON wird durch neues Setting ersetzt."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text("{{invalid json!!", encoding="utf-8")

        save_system_setting("recovery_key", "works")

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["recovery_key"] == "works"

    def test_unicode_handling(self, tmp_path, monkeypatch):
        """Unicode-Werte werden korrekt gespeichert (ensure_ascii=False)."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)

        save_system_setting("greeting", "Gruesse aus Muenchen")

        raw = (tmp_path / "system.json").read_text(encoding="utf-8")
        config = json.loads(raw)
        assert config["greeting"] == "Gruesse aus Muenchen"
        # Verify actual file content is not escaped
        assert "Gruesse aus Muenchen" in raw

    def test_preserves_sibling_nested_keys(self, tmp_path, monkeypatch):
        """Geschwister-Keys in verschachtelter Struktur bleiben erhalten."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
        (tmp_path / "system.json").write_text(
            json.dumps({
                "anonymization": {
                    "enabled": True,
                    "language": "de",
                    "pii_types": ["PERSON", "EMAIL_ADDRESS"],
                },
            }),
            encoding="utf-8",
        )

        save_system_setting("anonymization.enabled", False)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        assert config["anonymization"]["enabled"] is False
        assert config["anonymization"]["language"] == "de"
        assert config["anonymization"]["pii_types"] == ["PERSON", "EMAIL_ADDRESS"]


# =============================================================================
# TestTypeConsistency - Typ-Erhaltung (8 Tests via parametrize)
# =============================================================================

class TestTypeConsistency:
    """Tests fuer korrekte Typ-Erhaltung beim Speichern."""

    @pytest.mark.parametrize(
        "value, expected_type",
        [
            pytest.param(True, bool, id="bool-true"),
            pytest.param(False, bool, id="bool-false"),
            pytest.param("hello", str, id="str"),
            pytest.param(42, int, id="int"),
            pytest.param(3.14, float, id="float"),
            pytest.param(["a", "b"], list, id="list"),
            pytest.param({"nested": "dict"}, dict, id="dict"),
            pytest.param(None, type(None), id="None"),
        ],
    )
    def test_preserves_python_types(self, tmp_path, monkeypatch, value, expected_type):
        """Gespeicherter Wert behaelt seinen Python-Typ nach Roundtrip."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)

        save_system_setting("test_key", value)

        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))
        result = config["test_key"]
        assert isinstance(result, expected_type), (
            f"Expected type {expected_type.__name__}, got {type(result).__name__}"
        )
        assert result == value


# =============================================================================
# TestIntegration - End-to-End (1 Test)
# =============================================================================

class TestIntegration:
    """Integration-Test: Mehrere Settings nacheinander speichern und laden."""

    def test_full_save_load_cycle(self, tmp_path, monkeypatch):
        """Simuliert realen Workflow: Mehrere Settings sequentiell speichern."""
        monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)

        # 1. Flat key (wie set_developer_mode)
        save_system_setting("developer_mode", True)

        # 2. Flat key (wie set_content_mode)
        save_system_setting("content_mode", "both")

        # 3. Dot-notation (wie set_anonymization_setting)
        save_system_setting("anonymization.enabled", False)

        # 4. Weiterer Dot-notation Key in gleicher Gruppe
        save_system_setting("anonymization.language", "en")

        # 5. Deep nested key
        save_system_setting("security.prompt_injection.enabled", True)

        # Finale Config verifizieren
        config = json.loads((tmp_path / "system.json").read_text(encoding="utf-8"))

        assert config["developer_mode"] is True
        assert config["content_mode"] == "both"
        assert config["anonymization"]["enabled"] is False
        assert config["anonymization"]["language"] == "en"
        assert config["security"]["prompt_injection"]["enabled"] is True

        # Keine stale flat keys
        assert "anonymization.enabled" not in config
        assert "anonymization.language" not in config
        assert "security.prompt_injection.enabled" not in config
