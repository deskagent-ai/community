# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Claude Desktop / Claude Code Integration
=========================================
Kernlogik fuer die Integration von DeskAgent als MCP Hub
in Claude Desktop und Claude Code.

Funktionen:
- desk_setup_claude_desktop - Konfiguriert Claude Desktop
- desk_check_claude_desktop - Prueft Konfigurationsstatus
- desk_remove_claude_desktop - Entfernt DeskAgent aus Config
- desk_setup_claude_code - Registriert in Claude Code
"""

import json
import os
import secrets
import sys
from pathlib import Path

from _mcp_api import load_config, mcp_log, get_config_dir


# =============================================================================
# Helper: Pfade
# =============================================================================

def _get_claude_desktop_config_path() -> Path:
    """Gibt den Pfad zur claude_desktop_config.json zurueck.

    Returns:
        Path zur Config-Datei (plattformabhaengig)
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        # Linux
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _get_claude_code_config_path() -> Path:
    """Gibt den Pfad zur ~/.claude.json zurueck.

    Returns:
        Path zur Claude Code User-Config
    """
    return Path.home() / ".claude.json"


# =============================================================================
# Helper: DeskAgent-Pfade ermitteln
# =============================================================================

def _get_deskagent_dir() -> Path:
    """Ermittelt das DeskAgent-Verzeichnis.

    Returns:
        Path zum deskagent/ Ordner
    """
    # desk/claude_desktop.py -> desk/ -> mcp/ -> deskagent/
    return Path(__file__).parent.parent.parent


def _get_scripts_dir() -> Path:
    """Ermittelt das Scripts-Verzeichnis.

    Returns:
        Path zum deskagent/scripts/ Ordner
    """
    return _get_deskagent_dir() / "scripts"


def _get_python_executable() -> Path:
    """Ermittelt den Pfad zum Python Executable.

    Prueft zuerst auf embedded Python (kompilierter Build),
    dann Fallback auf sys.executable.

    Returns:
        Path zum Python Executable
    """
    deskagent_dir = _get_deskagent_dir()

    if sys.platform == "win32":
        embedded = deskagent_dir / "python" / "python.exe"
        if embedded.exists():
            return embedded
    elif sys.platform == "darwin":
        embedded = deskagent_dir / "python" / "bin" / "python3"
        if embedded.exists():
            return embedded
    else:
        embedded = deskagent_dir / "python" / "bin" / "python3"
        if embedded.exists():
            return embedded

    return Path(sys.executable)


def _get_proxy_script_path() -> Path:
    """Ermittelt den Pfad zum anonymization_proxy_mcp.py.

    Returns:
        Path zum Proxy-Script
    """
    return _get_deskagent_dir() / "mcp" / "anonymization_proxy_mcp.py"


def _get_workspace_dir() -> Path:
    """Ermittelt das Workspace-Verzeichnis.

    Returns:
        Path zum workspace/ Ordner
    """
    env_path = os.environ.get("DESKAGENT_WORKSPACE_DIR")
    if env_path:
        return Path(env_path)
    return _get_deskagent_dir().parent / "workspace"


# =============================================================================
# Helper: Konfigurierte MCPs ermitteln
# =============================================================================

def _get_configured_mcp_names() -> list[str]:
    """Ermittelt welche MCPs fuer Claude Desktop verfuegbar sein sollen.

    Prioritaet:
    1. system.json -> claude_desktop.allowed_mcps (explizite Liste)
    2. Auto-Detection: Alle MCP-Ordner in deskagent/mcp/ die nicht
       in apis.json als enabled:false markiert sind

    Returns:
        Liste der MCP-Namen
    """
    # --- Prioritaet 1: Explizite Liste aus system.json ---
    system_config = load_config()
    claude_config = system_config.get("claude_desktop", {})
    explicit_list = claude_config.get("allowed_mcps")

    if explicit_list and isinstance(explicit_list, list):
        mcp_log(f"[claude_desktop] Explizite allowed_mcps: {explicit_list}")
        return explicit_list

    # --- Prioritaet 2: Auto-Detection ---
    return _auto_detect_mcps()


def _auto_detect_mcps() -> list[str]:
    """Erkennt automatisch alle verfuegbaren MCPs.

    Scannt deskagent/mcp/ und plugins/*/mcp/ nach MCP-Ordnern und schliesst aus:
    - MCPs die in apis.json als enabled:false markiert sind
    - Interne Ordner (__pycache__, etc.)
    - Plugin-MCPs die nicht konfiguriert sind (kein API-Key etc.)

    Returns:
        Liste der verfuegbaren MCP-Namen
    """
    # Alle System-MCP-Ordner scannen
    mcp_dir = _get_deskagent_dir() / "mcp"
    skip_dirs = {"__pycache__", "desk"}  # desk wird immer separat geladen
    all_mcps = []

    if mcp_dir.exists():
        for entry in mcp_dir.iterdir():
            if entry.is_dir() and entry.name not in skip_dirs and not entry.name.startswith(("_", ".")):
                all_mcps.append(entry.name)

    # Disabled MCPs aus apis.json ausschliessen
    disabled = _get_disabled_mcps()
    configured = [name for name in all_mcps if name not in disabled]

    # Plugin-MCPs scannen (plugins/*/mcp/)
    plugin_mcps = _detect_plugin_mcps(disabled)
    configured.extend(plugin_mcps)

    mcp_log(f"[claude_desktop] Auto-detected MCPs: {configured} (disabled: {disabled}, plugins: {plugin_mcps})")
    return configured


def _detect_plugin_mcps(disabled: set[str]) -> list[str]:
    """Erkennt konfigurierte Plugin-MCPs.

    Scannt plugins/ nach Unterordnern mit mcp/__init__.py und prueft
    ob sie konfiguriert sind (API-Key, Credentials, etc.).

    Args:
        disabled: Set von explizit deaktivierten MCP-Namen

    Returns:
        Liste der konfigurierten Plugin-MCP-Namen
    """
    plugins_dir = _get_deskagent_dir().parent / "plugins"
    if not plugins_dir.exists():
        return []

    plugin_mcps = []
    skip_dirs = {"__pycache__"}

    for entry in plugins_dir.iterdir():
        if not entry.is_dir() or entry.name in skip_dirs or entry.name.startswith(("_", ".")):
            continue

        # Plugin muss mcp/__init__.py haben
        mcp_init = entry / "mcp" / "__init__.py"
        if not mcp_init.exists():
            continue

        plugin_name = entry.name
        if plugin_name in disabled:
            mcp_log(f"[claude_desktop] Plugin MCP '{plugin_name}' is disabled")
            continue

        # Pruefen ob konfiguriert (API-Key etc.)
        if _is_plugin_configured(plugin_name):
            plugin_mcps.append(f"plugin:{plugin_name}")
            mcp_log(f"[claude_desktop] Plugin MCP '{plugin_name}' detected and configured")
        else:
            mcp_log(f"[claude_desktop] Plugin MCP '{plugin_name}' not configured, skipping")

    return plugin_mcps


def _is_plugin_configured(plugin_name: str) -> bool:
    """Prueft ob ein Plugin konfiguriert ist (API-Key oder Credentials).

    Args:
        plugin_name: Name des Plugins

    Returns:
        True wenn konfiguriert
    """
    config_dir = get_config_dir()
    apis_file = config_dir / "apis.json"
    if not apis_file.exists():
        return False

    try:
        content = apis_file.read_text(encoding="utf-8")
        apis = json.loads(content)
    except Exception:
        return False

    plugin_config = apis.get(plugin_name, {})
    if not isinstance(plugin_config, dict):
        return False
    if plugin_config.get("enabled") is False:
        return False

    return bool(plugin_config.get("api_key")) or \
           bool(plugin_config.get("username") and plugin_config.get("base_url"))


def _get_disabled_mcps() -> set[str]:
    """Liest aus apis.json welche MCPs explizit disabled sind.

    Returns:
        Set von MCP-Namen mit enabled:false
    """
    config_dir = get_config_dir()
    apis_file = config_dir / "apis.json"

    if not apis_file.exists():
        return set()

    try:
        content = apis_file.read_text(encoding="utf-8")
        apis = json.loads(content)
    except Exception:
        return set()

    disabled = set()
    for name, config in apis.items():
        if name.startswith("_") or not isinstance(config, dict):
            continue
        if config.get("enabled") is False:
            disabled.add(name)

    return disabled


# =============================================================================
# Helper: MCP-Eintrag generieren
# =============================================================================

def _build_mcp_entry(transport: str, filter_pattern: str) -> dict:
    """Generiert den MCP-Eintrag fuer die Claude Desktop Config.

    Args:
        transport: "stdio" oder "http"
        filter_pattern: MCP-Filter Pattern (z.B. "outlook|billomat|filesystem")

    Returns:
        Dict mit dem MCP-Server Eintrag
    """
    if transport == "http":
        return _build_http_entry()
    else:
        return _build_stdio_entry(filter_pattern)


def _build_stdio_entry(filter_pattern: str) -> dict:
    """Generiert einen stdio MCP-Eintrag.

    Args:
        filter_pattern: MCP-Filter fuer den Proxy

    Returns:
        Dict mit command, args und env
    """
    python_path = _get_python_executable()
    proxy_script = _get_proxy_script_path()
    scripts_dir = _get_scripts_dir()
    workspace_dir = _get_workspace_dir()
    config_dir = get_config_dir()

    entry = {
        "command": str(python_path),
        "args": [
            str(proxy_script),
            "--session", "claude-desktop"
        ],
        "env": {
            "PYTHONPATH": str(scripts_dir),
            "DESKAGENT_SCRIPTS_DIR": str(scripts_dir),
            "DESKAGENT_WORKSPACE_DIR": str(workspace_dir),
            "DESKAGENT_CONFIG_DIR": str(config_dir)
        }
    }

    # Filter-Pattern als Umgebungsvariable wenn gesetzt
    if filter_pattern:
        entry["env"]["ALLOWED_MCP_PATTERN"] = filter_pattern

    return entry


def _build_http_entry() -> dict:
    """Generiert einen HTTP (Streamable HTTP) MCP-Eintrag.

    Liest oder generiert den Auth-Token.

    Returns:
        Dict mit type, url und headers
    """
    token = _get_or_generate_auth_token()

    entry = {
        "type": "streamable-http",
        "url": "http://localhost:19001/mcp",
        "headers": {
            "Authorization": f"Bearer {token}"
        }
    }

    return entry


# =============================================================================
# Helper: Auth-Token
# =============================================================================

def _get_or_generate_auth_token() -> str:
    """Liest den bestehenden Auth-Token oder generiert einen neuen.

    Der Token wird in system.json unter claude_desktop.auth_token gespeichert.

    Returns:
        Auth-Token String
    """
    config = load_config()
    claude_config = config.get("claude_desktop", {})
    existing_token = claude_config.get("auth_token", "")

    if existing_token:
        return existing_token

    # Neuen Token generieren
    return _generate_auth_token()


def _generate_auth_token() -> str:
    """Generiert einen neuen Auth-Token und speichert ihn in system.json.

    Returns:
        Neu generierter Token
    """
    token = secrets.token_urlsafe(32)

    config_dir = get_config_dir()
    system_file = config_dir / "system.json"

    try:
        if system_file.exists():
            content = system_file.read_text(encoding="utf-8")
            system_config = json.loads(content)
        else:
            system_config = {}

        # claude_desktop Sektion erstellen/aktualisieren
        if "claude_desktop" not in system_config:
            system_config["claude_desktop"] = {}

        system_config["claude_desktop"]["auth_token"] = token

        # Zurueckschreiben
        system_file.write_text(
            json.dumps(system_config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        mcp_log(f"[claude_desktop] Auth-Token generiert und in system.json gespeichert")

    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler beim Speichern des Auth-Tokens: {e}")

    return token


# =============================================================================
# Helper: Config lesen/schreiben
# =============================================================================

def _read_config(config_path: Path) -> dict:
    """Liest eine JSON-Config Datei.

    Args:
        config_path: Pfad zur Config-Datei

    Returns:
        Geparster Config-Dict oder leeres Dict
    """
    if not config_path.exists():
        return {}

    try:
        content = config_path.read_text(encoding="utf-8")
        return json.loads(content)
    except json.JSONDecodeError as e:
        mcp_log(f"[claude_desktop] JSON-Fehler in {config_path}: {e}")
        return {}
    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler beim Lesen von {config_path}: {e}")
        return {}


def _write_config(config_path: Path, config: dict) -> bool:
    """Schreibt eine JSON-Config Datei.

    Erstellt das Elternverzeichnis falls noetig.

    Args:
        config_path: Pfad zur Config-Datei
        config: Config-Dict zum Schreiben

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return True
    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler beim Schreiben von {config_path}: {e}")
        return False


# =============================================================================
# Tool-Funktionen
# =============================================================================

def desk_setup_claude_desktop(transport: str = "stdio") -> str:
    """Konfiguriert Claude Desktop um DeskAgent als MCP Hub zu nutzen.

    Liest die bestehende Claude Desktop Config, fuegt DeskAgent als MCP-Server
    hinzu und schreibt die Config zurueck. Bereits konfigurierte MCPs werden
    automatisch als Filter-Pattern eingetragen.

    Args:
        transport: "stdio" (standalone, kein laufender DeskAgent noetig)
                   oder "http" (benoetigt laufenden DeskAgent auf Port 19001)

    Returns:
        Zusammenfassung der Konfiguration oder Fehlermeldung
    """
    try:
        # Validierung
        if transport not in ("stdio", "http"):
            return "ERROR: transport muss 'stdio' oder 'http' sein."

        # 1. Config-Pfad finden
        config_path = _get_claude_desktop_config_path()
        mcp_log(f"[claude_desktop] Config-Pfad: {config_path}")

        # 2. Bestehende Config lesen oder leere erstellen
        config = _read_config(config_path)

        # 3. Konfigurierte MCPs ermitteln
        configured_mcps = _get_configured_mcp_names()
        filter_pattern = "|".join(configured_mcps) if configured_mcps else ""

        # 4. DeskAgent MCP-Eintrag generieren
        entry = _build_mcp_entry(transport, filter_pattern)

        # 5. In Config eintragen
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        config["mcpServers"]["deskagent"] = entry

        # 6. Config schreiben
        if not _write_config(config_path, config):
            return "ERROR: Config konnte nicht geschrieben werden."

        mcp_log(f"[claude_desktop] DeskAgent als MCP Hub eingetragen (transport={transport})")

        # 7. Zusammenfassung
        lines = [
            "DeskAgent wurde als MCP Hub in Claude Desktop eingetragen.",
            "",
            f"Config: {config_path}",
            f"Transport: {transport}",
        ]

        # Quelle der MCP-Liste anzeigen
        explicit = claude_config.get("allowed_mcps") if isinstance(
            (claude_config := load_config().get("claude_desktop", {})), dict
        ) else None
        if explicit and isinstance(explicit, list):
            source = "system.json → claude_desktop.allowed_mcps"
        else:
            source = "Auto-Detection"

        if filter_pattern:
            lines.append(f"MCPs ({source}): {filter_pattern}")
        else:
            lines.append(f"MCPs: alle (kein Filter, {source})")

        if transport == "stdio":
            lines.append(f"Python: {_get_python_executable()}")
            lines.append(f"Proxy: {_get_proxy_script_path()}")
        elif transport == "http":
            lines.append("URL: http://localhost:19001/mcp")
            lines.append("Auth: Bearer Token (in system.json gespeichert)")

        lines.append("")
        lines.append("Bitte Claude Desktop neu starten damit die Aenderungen wirksam werden.")
        lines.append("")
        lines.append("Tipp: MCPs anpassen via system.json → claude_desktop.allowed_mcps")

        return "\n".join(lines)

    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler bei Setup: {e}")
        return f"ERROR: {e}"


def desk_check_claude_desktop() -> str:
    """Prueft ob DeskAgent in Claude Desktop konfiguriert ist.

    Liest die Claude Desktop Config und prueft ob ein 'deskagent' Eintrag
    in mcpServers vorhanden ist.

    Returns:
        Status-Information (konfiguriert/nicht konfiguriert, Transport, Pfade)
    """
    try:
        config_path = _get_claude_desktop_config_path()

        # Pruefen ob Config-Datei existiert
        if not config_path.exists():
            return (
                "DeskAgent ist NICHT in Claude Desktop konfiguriert.\n"
                f"\nClaude Desktop Config existiert nicht: {config_path}\n"
                "\nNutze desk_setup_claude_desktop() zum Einrichten."
            )

        # Config lesen
        config = _read_config(config_path)
        mcp_servers = config.get("mcpServers", {})

        if "deskagent" not in mcp_servers:
            existing = list(mcp_servers.keys()) if mcp_servers else []
            lines = [
                "DeskAgent ist NICHT in Claude Desktop konfiguriert.",
                f"\nConfig: {config_path}",
            ]
            if existing:
                lines.append(f"Vorhandene MCP-Server: {', '.join(existing)}")
            lines.append("\nNutze desk_setup_claude_desktop() zum Einrichten.")
            return "\n".join(lines)

        # DeskAgent ist konfiguriert - Details anzeigen
        entry = mcp_servers["deskagent"]

        # Transport-Typ erkennen
        if "command" in entry:
            transport = "stdio"
            details = [
                f"Command: {entry.get('command', '?')}",
                f"Args: {' '.join(entry.get('args', []))}",
            ]
            env = entry.get("env", {})
            if env:
                details.append(f"PYTHONPATH: {env.get('PYTHONPATH', '?')}")
                if "ALLOWED_MCP_PATTERN" in env:
                    details.append(f"MCP-Filter: {env['ALLOWED_MCP_PATTERN']}")
        elif "url" in entry:
            transport = "http"
            details = [
                f"URL: {entry.get('url', '?')}",
                f"Type: {entry.get('type', '?')}",
                f"Auth: {'Ja (Bearer Token)' if entry.get('headers', {}).get('Authorization') else 'Nein'}",
            ]
        else:
            transport = "unbekannt"
            details = [f"Eintrag: {json.dumps(entry, indent=2)}"]

        lines = [
            "DeskAgent ist in Claude Desktop konfiguriert.",
            f"\nConfig: {config_path}",
            f"Transport: {transport}",
            "",
        ]
        lines.extend(details)

        return "\n".join(lines)

    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler bei Check: {e}")
        return f"ERROR: {e}"


def desk_remove_claude_desktop() -> str:
    """Entfernt DeskAgent aus der Claude Desktop Konfiguration.

    Liest die Config, entfernt den 'deskagent' Eintrag aus mcpServers
    und schreibt die Config zurueck.

    Returns:
        Bestaetigung oder Fehlermeldung
    """
    try:
        config_path = _get_claude_desktop_config_path()

        if not config_path.exists():
            return (
                "Claude Desktop Config existiert nicht.\n"
                f"Pfad: {config_path}\n"
                "Nichts zu entfernen."
            )

        config = _read_config(config_path)
        mcp_servers = config.get("mcpServers", {})

        if "deskagent" not in mcp_servers:
            return (
                "DeskAgent ist nicht in Claude Desktop konfiguriert.\n"
                f"Config: {config_path}\n"
                "Nichts zu entfernen."
            )

        # DeskAgent-Eintrag entfernen
        del mcp_servers["deskagent"]

        # Config zurueckschreiben
        if not _write_config(config_path, config):
            return "ERROR: Config konnte nicht geschrieben werden."

        mcp_log("[claude_desktop] DeskAgent aus Claude Desktop Config entfernt")

        return (
            "DeskAgent wurde aus der Claude Desktop Konfiguration entfernt.\n"
            f"\nConfig: {config_path}\n"
            "\nBitte Claude Desktop neu starten damit die Aenderungen wirksam werden."
        )

    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler bei Remove: {e}")
        return f"ERROR: {e}"


def desk_setup_claude_code(scope: str = "user") -> str:
    """Registriert DeskAgent MCP in Claude Code.

    Schreibt den MCP-Eintrag in ~/.claude.json (user scope)
    oder .mcp.json im aktuellen Verzeichnis (project scope).

    Args:
        scope: "user" fuer globale Config (~/.claude.json)
               oder "project" fuer Projekt-Config (.mcp.json im CWD)

    Returns:
        Zusammenfassung der Konfiguration oder Fehlermeldung
    """
    try:
        # Validierung
        if scope not in ("user", "project"):
            return "ERROR: scope muss 'user' oder 'project' sein."

        # Config-Pfad bestimmen
        if scope == "user":
            config_path = _get_claude_code_config_path()
        else:
            config_path = Path.cwd() / ".mcp.json"

        mcp_log(f"[claude_desktop] Claude Code Config-Pfad ({scope}): {config_path}")

        # Bestehende Config lesen
        config = _read_config(config_path)

        # Konfigurierte MCPs ermitteln
        configured_mcps = _get_configured_mcp_names()
        filter_pattern = "|".join(configured_mcps) if configured_mcps else ""

        # MCP-Eintrag generieren (stdio fuer Claude Code)
        entry = _build_stdio_entry(filter_pattern)

        # In Config eintragen
        if scope == "user":
            # ~/.claude.json hat eine andere Struktur: "mcpServers" auf Top-Level
            if "mcpServers" not in config:
                config["mcpServers"] = {}
            config["mcpServers"]["deskagent"] = entry
        else:
            # .mcp.json: Standard MCP Config Format
            if "mcpServers" not in config:
                config["mcpServers"] = {}
            config["mcpServers"]["deskagent"] = entry

        # Config schreiben
        if not _write_config(config_path, config):
            return "ERROR: Config konnte nicht geschrieben werden."

        mcp_log(f"[claude_desktop] DeskAgent in Claude Code registriert (scope={scope})")

        lines = [
            f"DeskAgent wurde in Claude Code registriert (scope: {scope}).",
            "",
            f"Config: {config_path}",
        ]

        # Quelle der MCP-Liste anzeigen
        explicit = load_config().get("claude_desktop", {}).get("allowed_mcps")
        source = "system.json → claude_desktop.allowed_mcps" if explicit else "Auto-Detection"

        if filter_pattern:
            lines.append(f"MCPs ({source}): {filter_pattern}")
        else:
            lines.append(f"MCPs: alle (kein Filter, {source})")

        lines.append(f"Python: {_get_python_executable()}")
        lines.append(f"Proxy: {_get_proxy_script_path()}")

        if scope == "user":
            lines.append("\nDie Aenderung gilt fuer alle Claude Code Projekte.")
        else:
            lines.append(f"\nDie Aenderung gilt nur fuer dieses Projekt ({Path.cwd()}).")
        lines.append("\nTipp: MCPs anpassen via system.json → claude_desktop.allowed_mcps")

        return "\n".join(lines)

    except Exception as e:
        mcp_log(f"[claude_desktop] Fehler bei Claude Code Setup: {e}")
        return f"ERROR: {e}"
