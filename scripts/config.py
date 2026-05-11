# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Config-Verwaltung fuer DeskAgent.

Laedt und speichert Konfigurationen aus modularen JSON-Dateien:
- system.json: UI, Logging, Allgemeine Einstellungen
- backends.json: AI Backend-Definitionen
- apis.json: API-Keys und Credentials
- agents.json: Skills und Agents

Config-Merge:
1. deskagent/config/*.json (Defaults)
2. SHARED_DIR/config/*.json (Overrides)

Note: This module uses print() for early startup messages since system_log
may not be initialized yet (loaded during config init). Messages are prefixed
with [Config] to indicate this.
"""

from pathlib import Path
import json
import socket

from paths import DESKAGENT_DIR, PROJECT_DIR, get_config_dir, get_temp_dir


# Config file names (order matters for merge)
CONFIG_FILES = ["system.json", "backends.json", "apis.json", "agents.json", "categories.json"]

# Track which host-specific configs we've already logged (to avoid spam)
_logged_host_configs: set = set()

# CLI override paths (set via --backends, --apis parameters before load_config)
_cli_config_overrides: dict = {}


def set_cli_config_override(filename: str, path: str) -> None:
    """
    Setzt CLI-Override fuer eine Config-Datei.

    Args:
        filename: Config-Dateiname (z.B. "backends.json")
        path: Absoluter Pfad zur Override-Datei
    """
    _cli_config_overrides[filename] = path
    print(f"[Config] CLI override for {filename}: {path}")


# Temp-Pfade im User-Space (Rueckwaertskompatibilitaet)
TEMP_DIR = get_temp_dir()
CURRENT_EMAIL = TEMP_DIR / "current-email.json"
DRAFT_RESPONSE = TEMP_DIR / "draft-response.md"


def deep_merge(base: dict, override: dict) -> dict:
    """Deep-Merge von zwei Dicts. Override gewinnt bei Konflikten."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_single_config(filename: str) -> dict:
    """
    Laedt eine einzelne Config-Datei mit Deep-Merge:
    0. CLI-Override via --backends/--apis (hoechste Prioritaet)
    1. deskagent/config/<filename> (Default)
    2. config/<filename> (User-Override)
    3. config/<filename-without-ext>.<hostname>.json (Host-specific Override)

    Beispiel fuer system.json auf Host "ubuntu-8gb-hel1-1":
    - deskagent/config/system.json (Default)
    - config/system.json (User)
    - config/system.ubuntu-8gb-hel1-1.json (Host-specific)

    Fuer apis.json und backends.json: Prueft auch auf .enc (verschluesselt)
    """
    # 0. CLI-Override hat hoechste Prioritaet (ueberspringt alle anderen Quellen)
    if filename in _cli_config_overrides:
        cli_path = Path(_cli_config_overrides[filename])
        if cli_path.exists():
            try:
                config = json.loads(cli_path.read_text(encoding="utf-8"))
                return config
            except json.JSONDecodeError:
                print(f"[Config] Error parsing CLI override: {cli_path}")
        else:
            print(f"[Config] CLI override not found: {cli_path}")

    config = {}

    # 1. Default aus Produkt laden
    default_path = DESKAGENT_DIR / "config" / filename
    if default_path.exists():
        try:
            config = json.loads(default_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # 2. User-Override laden und mergen
    user_path = PROJECT_DIR / "config" / filename

    # Fuer apis.json und backends.json: Pruefe zuerst auf verschluesselte Version
    if filename in ("apis.json", "backends.json"):
        enc_name = filename.replace(".json", ".enc")
        enc_path = PROJECT_DIR / "config" / enc_name
        if enc_path.exists():
            try:
                user = _load_encrypted_config(enc_path)
                if user:
                    config = deep_merge(config, user)
                    return config
            except Exception:
                pass  # Fallback auf Klartext

    if user_path.exists():
        try:
            user = json.loads(user_path.read_text(encoding="utf-8"))
            config = deep_merge(config, user)
        except json.JSONDecodeError:
            pass

    # 3. Hostname-specific override (e.g., system.ubuntu-8gb-hel1-1.json)
    hostname = socket.gethostname()
    host_filename = filename.replace('.json', f'.{hostname}.json')
    host_path = PROJECT_DIR / "config" / host_filename

    if host_path.exists():
        try:
            host_config = json.loads(host_path.read_text(encoding="utf-8"))
            config = deep_merge(config, host_config)
            # Only log once per host-specific config file
            if host_filename not in _logged_host_configs:
                _logged_host_configs.add(host_filename)
                print(f"[Config] Loaded host-specific config: {host_filename}")
        except json.JSONDecodeError:
            print(f"[Config] Error parsing {host_filename}")

    return config


def _load_encrypted_config(enc_path: Path) -> dict:
    """
    Laedt verschluesselte Config-Datei.
    Benoetigt Company Key im Windows Credential Manager.
    """
    try:
        import keyring
        from cryptography.fernet import Fernet
        import base64
        import hashlib

        # Company Key aus Credential Manager holen
        company_key = keyring.get_password("deskagent", "company_key")
        if not company_key:
            print("[Config] Company Key nicht gefunden. Bitte mit --set-key setzen.")
            return None

        # Key ableiten (32 bytes fuer Fernet)
        key = base64.urlsafe_b64encode(
            hashlib.sha256(company_key.encode()).digest()
        )

        # Entschluesseln
        fernet = Fernet(key)
        encrypted_data = enc_path.read_bytes()
        decrypted = fernet.decrypt(encrypted_data)

        return json.loads(decrypted.decode("utf-8"))
    except ImportError:
        print("[Config] Fuer Verschluesselung: pip install keyring cryptography")
        return None
    except Exception as e:
        print(f"[Config] Entschluesselung fehlgeschlagen: {e}")
        return None


def _merge_apis_into_config(config: dict) -> dict:
    """
    Merged alle Eintraege aus apis.json in Config.
    Jeder Key in apis.json wird als Top-Level Key verfuegbar.
    """
    apis = config.get("apis", {})

    # Alle APIs aus apis.json in Config mergen
    for key, value in apis.items():
        if isinstance(value, dict):
            config[key] = deep_merge(config.get(key, {}), value)
        else:
            config[key] = value

    # Aufraeumen
    if "apis" in config:
        del config["apis"]

    return config


def load_config() -> dict:
    """
    Laedt Config aus mehreren Dateien mit Deep-Merge:

    Dateien (in Reihenfolge):
    - system.json: UI, Logging, Allgemeine Einstellungen
    - backends.json: AI Backend-Definitionen
    - apis.json: API-Keys und Credentials (kann verschluesselt sein)
    - agents.json: Skills und Agents

    Jede Datei wird geladen als:
    1. deskagent/config/<file> (Default)
    2. config/<file> (User-Override)
    """
    config = {}

    # Neue Struktur: Mehrere Config-Dateien
    product_config_dir = DESKAGENT_DIR / "config"
    user_config_dir = PROJECT_DIR / "config"

    has_new_structure = (
        (product_config_dir.exists() and any(
            (product_config_dir / f).exists() for f in CONFIG_FILES
        )) or
        (user_config_dir.exists() and any(
            (user_config_dir / f).exists() for f in CONFIG_FILES
        ))
    )

    if has_new_structure:
        # Neue Struktur: Lade alle Config-Dateien
        for filename in CONFIG_FILES:
            file_config = _load_single_config(filename)

            # apis.json wird separat behandelt (Keys in Backends mergen)
            if filename == "apis.json":
                config["apis"] = file_config
            else:
                config = deep_merge(config, file_config)

        # API-Keys in Backends mergen
        config = _merge_apis_into_config(config)
    else:
        # Fallback: config/config.json oder config.json (ohne modulare Struktur)
        user_config = PROJECT_DIR / "config" / "config.json"
        if not user_config.exists():
            user_config = PROJECT_DIR / "config.json"

        if user_config.exists():
            try:
                config = json.loads(user_config.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    return config


def save_user_config(config: dict) -> None:
    """Speichert Config im User-Space (config/config.json). LEGACY."""
    config_dir = get_config_dir()
    user_config = config_dir / "config.json"
    user_config.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def save_system_setting(key: str, value) -> None:
    """
    Speichert ein einzelnes Setting in config/system.json.

    Laedt die bestehende system.json, aktualisiert den Key und speichert.
    Erstellt die Datei falls sie nicht existiert.
    """
    config_dir = get_config_dir()
    system_file = config_dir / "system.json"

    # Bestehende Config laden oder leeres Dict
    config = {}
    if system_file.exists():
        try:
            config = json.loads(system_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # Setting aktualisieren (mit Dot-Notation Support)
    parts = key.split(".")
    target = config
    for part in parts[:-1]:
        if part not in target or not isinstance(target[part], dict):
            target[part] = {}
        target = target[part]
    target[parts[-1]] = value

    # Stale flat key entfernen falls vorhanden (z.B. "anonymization.enabled")
    if "." in key and key in config:
        del config[key]

    # Speichern
    system_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def load_apis_config() -> dict:
    """
    Laedt nur die apis.json Konfiguration (API-Keys, Credentials).

    Nuetzlich fuer MCP-Server die direkten Zugriff auf API-Konfigurationen brauchen
    ohne die gesamte Config zu laden.
    """
    return _load_single_config("apis.json")


def is_user_space_initialized() -> bool:
    """Prueft ob User-Space eingerichtet ist (modulare configs existieren)."""
    config_dir = PROJECT_DIR / "config"
    return config_dir.exists() and any(
        (config_dir / f).exists() for f in CONFIG_FILES
    )


# =============================================================================
# Content Mode: custom | both | standard
# =============================================================================
# - custom:   Nur User-Inhalte (agents/, skills/, knowledge/)
# - both:     User + Standard-Inhalte (User hat Prioritaet bei Namenskonflikten)
# - standard: Nur Standard-Inhalte (deskagent/agents/, deskagent/skills/)
# =============================================================================

# Runtime content mode (can be changed without config save)
_runtime_content_mode: str = None


def get_content_mode() -> str:
    """Aktuellen Content-Mode holen (custom, both, standard)."""
    global _runtime_content_mode
    if _runtime_content_mode:
        return _runtime_content_mode
    config = load_config()
    return config.get("content_mode", "custom")


def set_content_mode(mode: str) -> None:
    """Content-Mode zur Laufzeit setzen (ohne Config-Speicherung)."""
    global _runtime_content_mode
    if mode not in ("custom", "both", "standard"):
        raise ValueError(f"Invalid content mode: {mode}")
    _runtime_content_mode = mode


def get_agents_dirs() -> list:
    """
    Liste der Agent-Verzeichnisse basierend auf Content-Mode.

    Returns:
        Liste von (path, source) Tuples
        - source: "user" oder "standard"
    """
    mode = get_content_mode()
    user_dir = PROJECT_DIR / "agents"
    standard_dir = DESKAGENT_DIR / "agents"

    if mode == "standard":
        return [(standard_dir, "standard")] if standard_dir.exists() else []
    elif mode == "both":
        dirs = []
        if user_dir.exists():
            dirs.append((user_dir, "user"))
        if standard_dir.exists():
            dirs.append((standard_dir, "standard"))
        return dirs
    else:  # custom (default)
        if user_dir.exists() and any(user_dir.glob("*.md")):
            return [(user_dir, "user")]
        # Fallback zu Standard wenn keine User-Agents
        return [(standard_dir, "standard")] if standard_dir.exists() else []


def get_skills_dirs() -> list:
    """
    Liste der Skill-Verzeichnisse basierend auf Content-Mode.

    Returns:
        Liste von (path, source) Tuples
    """
    mode = get_content_mode()
    user_dir = PROJECT_DIR / "skills"
    standard_dir = DESKAGENT_DIR / "skills"

    if mode == "standard":
        return [(standard_dir, "standard")] if standard_dir.exists() else []
    elif mode == "both":
        dirs = []
        if user_dir.exists():
            dirs.append((user_dir, "user"))
        if standard_dir.exists():
            dirs.append((standard_dir, "standard"))
        return dirs
    else:  # custom (default)
        if user_dir.exists() and any(user_dir.glob("*.md")):
            return [(user_dir, "user")]
        return [(standard_dir, "standard")] if standard_dir.exists() else []


def get_available_agents() -> list:
    """Listet verfuegbare Agents (basierend auf Content-Mode)."""
    agents = []

    # User-Agents zuerst
    user_agents = PROJECT_DIR / "agents"
    if user_agents.exists():
        agents.extend([f.stem for f in user_agents.glob("*.md")])

    # Standard-Agents als Fallback (wenn keine User-Agents)
    if not agents:
        standard_agents = DESKAGENT_DIR / "agents"
        if standard_agents.exists():
            agents.extend([f.stem for f in standard_agents.glob("*.md")])

    return sorted(set(agents))


def get_available_skills() -> list:
    """Listet verfuegbare Skills (basierend auf Content-Mode)."""
    skills = []

    # User-Skills zuerst
    user_skills = PROJECT_DIR / "skills"
    if user_skills.exists():
        skills.extend([f.stem for f in user_skills.glob("*.md")])

    # Standard-Skills als Fallback (wenn keine User-Skills)
    if not skills:
        standard_skills = DESKAGENT_DIR / "skills"
        if standard_skills.exists():
            skills.extend([f.stem for f in standard_skills.glob("*.md")])

    return sorted(set(skills))


def get_all_agents_with_source() -> list:
    """
    Alle Agents mit Source-Info basierend auf Content-Mode.

    Returns:
        Liste von dicts: [{"name": "reply_email", "source": "user", "path": Path, "overrides_standard": bool}]
    """
    agents = []
    seen = {}  # name -> index in agents list

    # Sammle zuerst alle Standard-Namen (fuer Override-Detection)
    standard_names = set()
    for dir_path, source in get_agents_dirs():
        if source == "standard" and dir_path.exists():
            standard_names.update(f.stem for f in dir_path.glob("*.md"))

    for dir_path, source in get_agents_dirs():
        if not dir_path.exists():
            continue
        for f in dir_path.glob("*.md"):
            name = f.stem
            if name not in seen:  # User hat Prioritaet
                overrides_standard = (source == "user" and name in standard_names)
                agents.append({
                    "name": name,
                    "source": source,
                    "path": f,
                    "overrides_standard": overrides_standard
                })
                seen[name] = len(agents) - 1

    # Add plugin agents with prefix (only in custom/both mode, treated as "user")
    mode = get_content_mode()
    if mode in ("custom", "both"):
        try:
            from assistant.services.plugins import get_plugin_agents
            for plugin_name, plugin_agents in get_plugin_agents().items():
                for agent_name, agent_data in plugin_agents.items():
                    prefixed_name = f"{plugin_name}:{agent_name}"
                    if prefixed_name not in seen:
                        agents.append({
                            "name": prefixed_name,
                            "source": "user",  # Plugins count as custom/user content
                            "path": Path(agent_data.get("file_path", "")),
                            "overrides_standard": False
                        })
                        seen[prefixed_name] = len(agents) - 1
        except ImportError:
            pass  # Plugin system not available

    return sorted(agents, key=lambda x: x["name"])


def get_all_skills_with_source() -> list:
    """
    Alle Skills mit Source-Info basierend auf Content-Mode.

    Returns:
        Liste von dicts: [{"name": "translate", "source": "standard", "path": Path, "overrides_standard": bool}]
    """
    skills = []
    seen = {}  # name -> index in skills list

    # Sammle zuerst alle Standard-Namen (fuer Override-Detection)
    standard_names = set()
    for dir_path, source in get_skills_dirs():
        if source == "standard" and dir_path.exists():
            standard_names.update(f.stem for f in dir_path.glob("*.md"))

    for dir_path, source in get_skills_dirs():
        if not dir_path.exists():
            continue
        for f in dir_path.glob("*.md"):
            name = f.stem
            if name not in seen:  # User hat Prioritaet
                overrides_standard = (source == "user" and name in standard_names)
                skills.append({
                    "name": name,
                    "source": source,
                    "path": f,
                    "overrides_standard": overrides_standard
                })
                seen[name] = len(skills) - 1

    # Add plugin skills with prefix (only in custom/both mode, treated as "user")
    mode = get_content_mode()
    if mode in ("custom", "both"):
        try:
            from assistant.services.plugins import get_plugin_skills
            for plugin_name, plugin_skills in get_plugin_skills().items():
                for skill_name, skill_data in plugin_skills.items():
                    prefixed_name = f"{plugin_name}:{skill_name}"
                    if prefixed_name not in seen:
                        skills.append({
                            "name": prefixed_name,
                            "source": "user",  # Plugins count as custom/user content
                            "path": Path(skill_data.get("file_path", "")),
                            "overrides_standard": False
                        })
                        seen[prefixed_name] = len(skills) - 1
        except ImportError:
            pass  # Plugin system not available

    return sorted(skills, key=lambda x: x["name"])


def load_categories() -> dict:
    """
    Laedt Categories aus categories.json mit Deep-Merge.

    Merge-Reihenfolge (spaeter gewinnt):
    1. deskagent/config/categories.json (System-Default)
    2. config/categories.json (User-Override)

    Returns:
        Dict von category_id -> {label, icon, order}
    """
    categories = {}

    # System-Default laden
    system_path = DESKAGENT_DIR / "config" / "categories.json"
    if system_path.exists():
        try:
            categories = json.loads(system_path.read_text(encoding="utf-8"))
            # _comment Feld entfernen falls vorhanden
            categories.pop("_comment", None)
        except json.JSONDecodeError:
            pass

    # User-Override laden und mergen
    user_path = PROJECT_DIR / "config" / "categories.json"
    if user_path.exists():
        try:
            user_cats = json.loads(user_path.read_text(encoding="utf-8"))
            user_cats.pop("_comment", None)
            # Merge: User ueberschreibt System
            for cat_id, cat_data in user_cats.items():
                if cat_id in categories:
                    categories[cat_id].update(cat_data)
                else:
                    categories[cat_id] = cat_data
        except json.JSONDecodeError:
            pass

    return categories


# =============================================================================
# Internationalization (i18n)
# =============================================================================

def load_translations(language: str = None) -> dict:
    """Load translations for given language.

    Args:
        language: Language code (e.g., 'de', 'en'). If None, uses config setting.

    Returns:
        Dict of translation keys to translated strings.
        Falls back to German if requested language file not found.
    """
    if language is None:
        config = load_config()
        language = config.get("language", "de")

    i18n_dir = DESKAGENT_DIR / "i18n"
    i18n_file = i18n_dir / f"{language}.json"

    # Fallback to German if file not found
    if not i18n_file.exists():
        i18n_file = i18n_dir / "de.json"

    if not i18n_file.exists():
        return {}

    try:
        translations = json.loads(i18n_file.read_text(encoding="utf-8"))
        # Remove comment field
        translations.pop("_comment", None)
        return translations
    except json.JSONDecodeError:
        return {}


def get_localized(meta: dict, field: str, language: str = None) -> str:
    """Get localized field value with fallback to default.

    For agent/skill descriptions that support language suffix (e.g., description_en).

    Args:
        meta: Metadata dict containing the field
        field: Field name (e.g., 'description', 'input', 'output')
        language: Language code. If None, uses config setting.

    Returns:
        Localized value if available, otherwise default field value.

    Example:
        meta = {"description": "Deutsch", "description_en": "English"}
        get_localized(meta, "description", "en")  # Returns "English"
        get_localized(meta, "description", "de")  # Returns "Deutsch"
    """
    if language is None:
        config = load_config()
        language = config.get("language", "de")

    # For non-German languages, check for localized version
    if language != "de":
        localized_key = f"{field}_{language}"
        if localized_key in meta:
            return meta[localized_key]

    return meta.get(field, "")
