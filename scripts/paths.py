# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Zentrale Pfadverwaltung mit Parent-Folder-Suche.

Verzeichnisse:
- DESKAGENT_DIR: Produkt-Code (deskagent/)
- SHARED_DIR: Geteilte Inhalte (config, agents, skills, knowledge, mcp)
             Kann auf Netzwerk-Share liegen via DESKAGENT_SHARED_DIR oder shared_path.txt
- WORKSPACE_DIR: Lokaler Arbeitsordner (workspace/) - immer lokal
  - Hidden: .state/, .logs/, .temp/, .context/
  - Visible: exports/, sepa/

Lade-Logik:
1. Suche im SHARED_DIR (../agents/, ../skills/, etc.)
2. Fallback: deskagent/agents/, deskagent/skills/, etc.

Platform-specific locations:
- Windows: All folders relative to install directory
- macOS: User data in ~/Library/Application Support/DeskAgent/
- Linux: User data in ~/.local/share/deskagent/

Note: This module uses print() for early startup messages since system_log
may not be initialized yet (circular dependency). Messages are prefixed with
[Config] to indicate this.
"""

from pathlib import Path
import os
import sys

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

def _is_compiled() -> bool:
    """
    Check if running from Nuitka-compiled binary.

    Simple detection: Im Nuitka-Build sind .py Dateien eingebettet und
    existieren nicht mehr als physische Dateien. Wenn paths.py existiert
    und in der erwarteten Source-Struktur liegt, ist es Dev-Modus.

    Fallback-Checks fuer Edge-Cases:
    - sys.frozen / __compiled__ (Nuitka-Flags)
    - macOS App Bundle Struktur
    """
    # Primaerer Check: Existiert paths.py als physische Datei?
    # Im Nuitka-Build ist __file__ eingebettet, die .py existiert nicht
    paths_file = Path(__file__).resolve()
    source_file_exists = paths_file.exists() and paths_file.suffix == ".py"

    if source_file_exists:
        # Source-Datei existiert -> definitiv Dev-Modus
        return False

    # Fallback 1: Nuitka-spezifische Flags
    if getattr(sys, 'frozen', False):
        return True
    if hasattr(sys.modules.get('__main__', None), '__compiled__'):
        return True

    # Fallback 2: macOS App Bundle
    if IS_MACOS:
        exe_dir = Path(sys.executable).parent.resolve()
        if exe_dir.name == "MacOS" and exe_dir.parent.name == "Contents":
            return True

    # Fallback 3: Executable heisst DeskAgent
    exe_stem = Path(sys.executable).stem.lower()
    if 'deskagent' in exe_stem:
        return True

    # Fallback 4: DeskAgent.exe existiert im selben Ordner (Nuitka-Build mit python.exe)
    exe_dir = Path(sys.executable).parent.resolve()
    deskagent_exe = exe_dir / "DeskAgent.exe"
    if deskagent_exe.exists():
        return True

    # Source-Datei existiert nicht -> wir sind compiled
    # (wenn wir hier ankommen, hat source_file_exists bereits False ergeben)
    return not source_file_exists


def _is_macos_app_bundle() -> bool:
    """Check if running from a macOS .app bundle."""
    if not IS_MACOS:
        return False
    exe_dir = Path(sys.executable).parent.resolve()
    # In app bundle: /path/to/DeskAgent.app/Contents/MacOS/
    return exe_dir.name == "MacOS" and exe_dir.parent.name == "Contents"


def _get_app_bundle_resources() -> Path:
    """Get the Resources folder inside a macOS app bundle."""
    exe_dir = Path(sys.executable).parent.resolve()
    # /path/to/DeskAgent.app/Contents/MacOS/ -> /path/to/DeskAgent.app/Contents/Resources/
    return exe_dir.parent / "Resources"


def _get_deskagent_dir() -> Path:
    """
    Ermittelt DESKAGENT_DIR fuer Source und kompilierten Build.

    Source: deskagent/scripts/paths.py -> parent.parent = deskagent/

    Compiled builds:
    - Windows: EXE liegt in deskagent/ -> sys.executable.parent = deskagent/
    - macOS App Bundle: Bundled data in Contents/Resources/
    - Linux: Same as Windows

    Detection: Nuitka setzt sys.executable manchmal auf python statt DeskAgent,
    daher pruefen wir auch ob DeskAgent executable im selben Ordner existiert.
    Cross-Platform: Windows (.exe, .dll), macOS (.dylib), Linux (.so)
    """
    exe_dir = Path(sys.executable).parent.resolve()
    is_compiled = _is_compiled()

    if is_compiled:
        if IS_MACOS and _is_macos_app_bundle():
            # macOS App Bundle: data files are in Contents/Resources/
            result = _get_app_bundle_resources()
        else:
            # Windows/Linux: Use exe folder as DESKAGENT_DIR
            result = exe_dir
    else:
        # Source: paths.py is in deskagent/scripts/
        result = Path(__file__).parent.parent.resolve()

    return result

# DESKAGENT_DIR = Wo das Produkt liegt (deskagent/)
DESKAGENT_DIR = _get_deskagent_dir()

# PROJECT_ROOT = Parent von deskagent (fuer shared_path.txt Suche)
PROJECT_ROOT = DESKAGENT_DIR.parent.resolve()

# Set environment variable for MCP servers (cross-platform)
# This allows MCPs to find the scripts directory when started by Claude Code
os.environ["DESKAGENT_SCRIPTS_DIR"] = str(DESKAGENT_DIR / "scripts")


# =============================================================================
# Platform-specific directory helpers (must be defined before _get_workspace_dir)
# =============================================================================

def _get_macos_app_support_dir() -> Path:
    """
    Get macOS Application Support directory for DeskAgent.

    Returns ~/Library/Application Support/DeskAgent/
    Creates the directory if it doesn't exist.
    """
    app_support = Path.home() / "Library" / "Application Support" / "DeskAgent"
    return app_support


def _get_linux_data_dir() -> Path:
    """
    Get Linux XDG data directory for DeskAgent.

    Returns ~/.local/share/deskagent/
    Respects XDG_DATA_HOME if set.
    """
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base = Path(xdg_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "deskagent"


# =============================================================================
# Workspace and Shared directory resolution
# =============================================================================

def _get_workspace_dir() -> Path:
    """
    Ermittelt den Workspace-Ordner fuer lokale Daten.

    Prioritaet:
    1. Umgebungsvariable DESKAGENT_WORKSPACE_DIR
    2. Platform-spezifisch:
       - macOS (compiled): ~/Library/Application Support/DeskAgent/workspace/
       - Linux (compiled): ~/.local/share/deskagent/workspace/
       - Windows/Dev: PROJECT_ROOT/workspace

    Workspace enthaelt:
    - Hidden: .state/, .logs/, .temp/, .context/
    - Visible: exports/, sepa/
    """
    env_path = os.environ.get("DESKAGENT_WORKSPACE_DIR")
    if env_path:
        path = Path(env_path)
        try:
            # Erstelle falls nicht vorhanden
            path.mkdir(parents=True, exist_ok=True)
            return path.resolve()
        except OSError as e:
            print(f"[Config] DESKAGENT_WORKSPACE_DIR nicht verfuegbar: {env_path} ({e})")

    # Platform-spezifisch fuer kompilierte Builds
    if _is_compiled():
        if IS_MACOS:
            # macOS: Workspace inside Application Support
            return _get_macos_app_support_dir() / "workspace"
        elif IS_LINUX:
            # Linux: Workspace inside XDG data directory
            return _get_linux_data_dir() / "workspace"

    # Standard: PROJECT_ROOT/workspace (Windows compiled + all dev modes)
    return PROJECT_ROOT / "workspace"


# WORKSPACE_DIR = Lokaler Arbeitsordner (immer auf diesem Rechner, nie Netzwerk)
# Enthaelt: .state/, .logs/, .temp/, .context/, exports/, sepa/
WORKSPACE_DIR = _get_workspace_dir()

# LOCAL_DIR = Alias fuer Rueckwaertskompatibilitaet
LOCAL_DIR = WORKSPACE_DIR


def _get_shared_dir() -> Path:
    """
    Ermittelt den Shared-Ordner fuer geteilte Inhalte.

    Prioritaet:
    1. Umgebungsvariable DESKAGENT_SHARED_DIR
    2. Lokale Datei shared_path.txt (neben deskagent/, nicht darin!)
    3. Platform-spezifisch:
       - macOS (compiled): ~/Library/Application Support/DeskAgent/
       - Linux (compiled): ~/.local/share/deskagent/
       - Windows/Dev: Parent von deskagent (wie bisher)

    Beispiel shared_path.txt:
        \\\\server\\share\\team\\aiassistant
        oder
        Z:\\Team\\AIAssistant
    """
    # 1. Umgebungsvariable
    env_path = os.environ.get("DESKAGENT_SHARED_DIR")
    if env_path:
        path = Path(env_path)
        try:
            if path.exists():
                return path.resolve()
            print(f"[Config] DESKAGENT_SHARED_DIR nicht gefunden: {env_path}")
        except OSError as e:
            # Laufwerk existiert nicht (z.B. Netzlaufwerk nicht verbunden)
            print(f"[Config] Laufwerk nicht verfuegbar: {env_path} ({e})")

    # 2. Lokale Datei shared_path.txt (neben deskagent/, nicht darin - sonst Update-Probleme!)
    shared_path_file = PROJECT_ROOT / "shared_path.txt"
    if shared_path_file.exists():
        try:
            content = shared_path_file.read_text(encoding="utf-8").strip()
            # Erste nicht-leere, nicht-Kommentar Zeile
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    path = Path(line)
                    try:
                        if path.exists():
                            return path.resolve()
                        print(f"[Config] Shared-Pfad nicht gefunden: {line}")
                    except OSError as e:
                        # Laufwerk existiert nicht (z.B. Netzlaufwerk nicht verbunden)
                        print(f"[Config] Laufwerk nicht verfuegbar: {line} ({e})")
                    break
        except Exception as e:
            print(f"[Config] Fehler beim Lesen von shared_path.txt: {e}")

    # 3. Platform-spezifisch fuer kompilierte Builds
    if _is_compiled():
        if IS_MACOS:
            # macOS: Use Application Support (standard macOS location)
            return _get_macos_app_support_dir()
        elif IS_LINUX:
            # Linux: Use XDG data directory
            return _get_linux_data_dir()

    # 4. Standard: Parent von deskagent (Windows compiled + all dev modes)
    return DESKAGENT_DIR.parent.resolve()


# SHARED_DIR = Geteilte Inhalte (kann Netzwerk-Share sein)
#   -> config/, agents/, skills/, knowledge/, mcp/
SHARED_DIR = _get_shared_dir()

# PROJECT_DIR = Alias fuer Rueckwaertskompatibilitaet
PROJECT_DIR = SHARED_DIR


def get_agents_dir() -> Path:
    """Parent-Folder-Suche fuer agents/."""
    user_dir = PROJECT_DIR / "agents"
    if user_dir.exists() and any(user_dir.glob("*.md")):
        return user_dir
    # macOS App Bundle: DESKAGENT_DIR is read-only, always use user dir
    if IS_MACOS and _is_compiled():
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    return DESKAGENT_DIR / "agents"


def get_skills_dir() -> Path:
    """Parent-Folder-Suche fuer skills/."""
    user_dir = PROJECT_DIR / "skills"
    if user_dir.exists() and any(user_dir.glob("*.md")):
        return user_dir
    if IS_MACOS and _is_compiled():
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    return DESKAGENT_DIR / "skills"


def get_knowledge_dir() -> Path:
    """Parent-Folder-Suche fuer knowledge/."""
    user_dir = PROJECT_DIR / "knowledge"
    if user_dir.exists() and any(user_dir.glob("*.md")):
        return user_dir
    if IS_MACOS and _is_compiled():
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    return DESKAGENT_DIR / "knowledge"


def get_templates_dir() -> Path:
    """
    System-Templates (immer aus Produkt, nie User-ueberschreibbar).

    Templates sind System-Definitionen wie:
    - dialogs.md: QUESTION_NEEDED/CONFIRMATION_NEEDED Format

    Diese werden automatisch in den System-Prompt eingebettet.
    """
    return DESKAGENT_DIR / "templates"


def get_documentation_dir() -> Path:
    """
    Product documentation (in product folder, not user-overridable).

    Contains documentation files that can be loaded via @path syntax:
    - deskagent.md: MCP configuration, folder structure

    Reference in agents.json: "knowledge": "@deskagent/documentation/"
    """
    return DESKAGENT_DIR / "documentation"


def get_mcp_dir() -> Path:
    """MCP-Server im Produkt (Standard-MCPs)."""
    return DESKAGENT_DIR / "mcp"


def get_mcp_dirs() -> list:
    """
    Alle MCP-Verzeichnisse (Produkt + Custom).

    Returns:
        Liste von (path, source) Tuples:
        - ("user", SHARED_DIR/mcp) - Custom Company MCPs
        - ("product", DESKAGENT_DIR/mcp) - Standard MCPs
    """
    dirs = []

    # Custom MCPs im Shared-Ordner (Prioritaet)
    custom_mcp = SHARED_DIR / "mcp"
    if custom_mcp.exists() and any(custom_mcp.glob("*_mcp.py")):
        dirs.append((custom_mcp, "user"))

    # Standard MCPs im Produkt
    product_mcp = DESKAGENT_DIR / "mcp"
    if product_mcp.exists():
        dirs.append((product_mcp, "product"))

    return dirs


def get_workspace_dir() -> Path:
    """
    Dynamically get workspace directory (respects env var changes after module load).
    Use this instead of WORKSPACE_DIR constant when env vars might change at runtime.
    """
    return _get_workspace_dir()


def _ensure_workspace() -> Path:
    """Stellt sicher dass workspace/ existiert."""
    workspace = get_workspace_dir()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def get_logs_dir() -> Path:
    """Logs liegen lokal (hidden in workspace/.logs/).

    Setzt auch DESKAGENT_LOGS_DIR Environment-Variable fuer MCP-Subprozesse,
    damit diese den korrekten Pfad kennen auch ohne API-Zugriff.
    """
    workspace = _ensure_workspace()
    logs_dir = workspace / ".logs"
    logs_dir.mkdir(exist_ok=True)
    # Set env var for MCP subprocesses (they inherit environment)
    os.environ["DESKAGENT_LOGS_DIR"] = str(logs_dir)
    return logs_dir


def mcp_log(message: str):
    """
    Simple logging for MCP servers (separate processes).
    Writes directly to system.log without depending on ai_agent module.
    """
    try:
        from datetime import datetime
        log_file = get_logs_dir() / "system.log"
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def get_data_dir() -> Path:
    """State-Ordner lokal (API-Kosten, Watcher-State, etc.)."""
    workspace = _ensure_workspace()
    data_dir = workspace / ".state"
    data_dir.mkdir(exist_ok=True)
    return data_dir


# Alias fuer Klarheit
get_state_dir = get_data_dir


def get_temp_dir() -> Path:
    """Temp-Ordner lokal (hidden in workspace/.temp/)."""
    workspace = _ensure_workspace()
    temp_dir = workspace / ".temp"
    temp_dir.mkdir(exist_ok=True)
    return temp_dir


def clear_temp_dir() -> bool:
    """
    Loescht den Inhalt des .temp-Ordners.
    Erhalt bestimmte Cache-Dateien die zwischen Neustarts persistieren sollen.

    Returns:
        True wenn erfolgreich, False bei Fehler
    """
    _PRESERVE_FILES = {"proxy_tool_cache.json"}
    temp_dir = get_workspace_dir() / ".temp"
    if temp_dir.exists():
        try:
            for item in temp_dir.iterdir():
                if item.name in _PRESERVE_FILES:
                    continue
                if item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                else:
                    item.unlink()
            return True
        except Exception as e:
            print(f"[Temp] Fehler beim Loeschen: {e}")
            return False
    return True


def init_directories() -> dict:
    """
    Initialisiert alle Verzeichnisse fuer eine Neuinstallation.
    Wird vom Setup-Wizard aufgerufen oder automatisch beim ersten Start.

    On macOS/Linux compiled builds, creates folders in Application Support/XDG.
    On Windows, folders are created relative to install directory.

    Returns:
        Dict mit erstellten Ordnern und Status
    """
    result = {"created": [], "errors": [], "first_run": False}

    # Check if this is first run (no config folder exists)
    config_dir = SHARED_DIR / "config"
    if not config_dir.exists():
        result["first_run"] = True

    # Workspace erstellen (Subfolders werden on-demand erstellt)
    workspace = get_workspace_dir()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        result["created"].append(str(workspace))
    except Exception as e:
        result["errors"].append(f"workspace: {e}")

    # Workspace subfolders
    workspace_subfolders = [".logs", ".temp", ".state", ".context", "exports", "sepa"]
    for subfolder in workspace_subfolders:
        folder_path = workspace / subfolder
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
            result["created"].append(str(folder_path))
        except Exception as e:
            result["errors"].append(f"workspace/{subfolder}: {e}")

    # Sichtbare Shared-Ordner erstellen (damit User sie sieht)
    for folder in ["config", "agents", "skills", "knowledge"]:
        folder_path = SHARED_DIR / folder
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
            result["created"].append(str(folder_path))
        except Exception as e:
            result["errors"].append(f"{folder}: {e}")

    # Log initialization
    if result["first_run"]:
        print(f"[Config] First run detected - initialized directories in {SHARED_DIR}")

    return result


def ensure_first_run_setup() -> bool:
    """
    Ensure all required directories exist on first run.

    Called during app startup. On macOS/Linux, this creates the
    Application Support / XDG data directories if they don't exist.

    Returns:
        True if this was a first run (directories were created)
    """
    result = init_directories()
    return result.get("first_run", False)


def get_context_dir() -> Path:
    """Context-Ordner fuer Skills (hidden in workspace/.context/)."""
    workspace = _ensure_workspace()
    context_dir = workspace / ".context"
    context_dir.mkdir(exist_ok=True)
    return context_dir


def get_exports_dir() -> Path:
    """Exports-Ordner fuer PDFs, Reports, Downloads (visible in workspace/exports/)."""
    workspace = _ensure_workspace()
    exports_dir = workspace / "exports"
    exports_dir.mkdir(exist_ok=True)
    return exports_dir


def get_sepa_dir() -> Path:
    """SEPA-Ordner fuer pain.001 XML Dateien (visible in workspace/sepa/)."""
    workspace = _ensure_workspace()
    sepa_dir = workspace / "sepa"
    sepa_dir.mkdir(exist_ok=True)
    return sepa_dir


def get_config_dir() -> Path:
    """Config-Ordner im User-Space."""
    config_dir = PROJECT_DIR / "config"
    config_dir.mkdir(exist_ok=True)
    return config_dir


def get_embedded_python() -> Path:
    """
    Gibt den Pfad zum embedded Python zurueck.

    Im kompilierten Build:
        Windows: deskagent/python/python.exe
        macOS: DeskAgent.app/Contents/Resources/python/bin/python3
        Linux: deskagent/python/bin/python3

    Im Dev-Modus:
        sys.executable (aktueller Python Interpreter)

    Returns:
        Path zum Python Executable
    """
    if _is_compiled():
        if IS_WINDOWS:
            # Windows: embedded Python in deskagent/python/
            embedded = DESKAGENT_DIR / "python" / "python.exe"
            if embedded.exists():
                return embedded
            # Fallback to pythonw.exe (no console)
            pythonw = DESKAGENT_DIR / "python" / "pythonw.exe"
            if pythonw.exists():
                return pythonw
        elif IS_MACOS:
            # macOS App Bundle: venv at Contents/Resources/python/
            # DESKAGENT_DIR is already Contents/Resources/ for app bundles
            # Build creates venv directly at python/ (no venv/ subdirectory)
            venv_python = DESKAGENT_DIR / "python" / "bin" / "python3"
            if venv_python.exists():
                return venv_python
            # Fallback: check for python3 without version suffix
            venv_python_alt = DESKAGENT_DIR / "python" / "bin" / "python"
            if venv_python_alt.exists():
                return venv_python_alt
        elif IS_LINUX:
            # Linux: embedded Python in deskagent/python/
            embedded = DESKAGENT_DIR / "python" / "bin" / "python3"
            if embedded.exists():
                return embedded

    # Dev-Modus: nutze aktuellen Python Interpreter
    return Path(sys.executable)


def get_apis_config_path() -> Path:
    """Pfad zur apis.json Konfigurationsdatei."""
    return get_config_dir() / "apis.json"


# =============================================================================
# Rueckwaertskompatibilitaet: Re-exports aus config.py
# =============================================================================
# Diese Funktionen wurden nach config.py verschoben, werden aber hier
# re-exportiert fuer bestehenden Code der sie aus paths importiert.
# =============================================================================

def load_config():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import load_config as _load_config
    return _load_config()


def save_user_config(config: dict):
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import save_user_config as _save_user_config
    return _save_user_config(config)


def save_system_setting(key: str, value):
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import save_system_setting as _save_system_setting
    return _save_system_setting(key, value)


def load_apis_config():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import load_apis_config as _load_apis_config
    return _load_apis_config()


def is_user_space_initialized():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import is_user_space_initialized as _is_user_space_initialized
    return _is_user_space_initialized()


def get_content_mode():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_content_mode as _get_content_mode
    return _get_content_mode()


def set_content_mode(mode: str):
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import set_content_mode as _set_content_mode
    return _set_content_mode(mode)


def get_agents_dirs():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_agents_dirs as _get_agents_dirs
    return _get_agents_dirs()


def get_skills_dirs():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_skills_dirs as _get_skills_dirs
    return _get_skills_dirs()


def get_available_agents():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_available_agents as _get_available_agents
    return _get_available_agents()


def get_available_skills():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_available_skills as _get_available_skills
    return _get_available_skills()


def get_all_agents_with_source():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_all_agents_with_source as _get_all_agents_with_source
    return _get_all_agents_with_source()


def get_all_skills_with_source():
    """Re-export aus config.py fuer Rueckwaertskompatibilitaet."""
    from config import get_all_skills_with_source as _get_all_skills_with_source
    return _get_all_skills_with_source()
