# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP API Client - Stub-Modul für Nuitka-Builds.

Dieses Modul enthält KEINE Business-Logik, nur HTTP-Calls.
Die echte Logik bleibt geschützt in der kompilierten EXE.

Verfügbare Funktionen:
- load_config() - Konfiguration laden (cached)
- mcp_log() - Logging via API
- get_*_dir() - Pfad-Funktionen (config, temp, exports, data, workspace, logs)
- anonymize() / deanonymize() - PII-Anonymisierung (session-basiert)
- cleanup_session() - Session-Daten löschen
- get_task_context() - Task-Kontext für nested Agent-Calls
- is_anonymizer_available() - Prüft ob Presidio verfügbar ist
"""
import os
import sys
import requests
from pathlib import Path
from typing import Dict, Any, Optional

_BASE_URL = os.environ.get("DESKAGENT_API_URL", "http://localhost:8765")
_TIMEOUT = 5
_cache: Dict[str, Any] = {}


def _warn(message: str) -> None:
    """Print warning to stderr (visible in MCP logs)."""
    print(f"[_mcp_api] WARNING: {message}", file=sys.stderr)


def load_config() -> dict:
    """Load config from API (cached).

    Only caches non-empty results to avoid permanently caching
    error states (e.g. when API is not yet ready at startup).

    Returns:
        Merged config dict (apis.json + system.json).
        Empty dict on API error.
    """
    if "config" not in _cache:
        try:
            r = requests.get(f"{_BASE_URL}/api/mcp/config", timeout=_TIMEOUT)
            result = r.json() if r.ok else {}
            if result:
                _cache["config"] = result
            return result
        except Exception as e:
            _warn(f"API not reachable ({_BASE_URL}): {e}")
            return {}  # Do NOT cache empty results
    return _cache["config"]


def mcp_log(message: str, level: str = "info") -> None:
    """Log message via API (fire and forget).

    Args:
        message: Log message
        level: Log level (info, warning, error, debug)
    """
    try:
        requests.post(
            f"{_BASE_URL}/api/mcp/log",
            json={"message": message, "level": level},
            timeout=2
        )
    except Exception:
        pass  # Silent fail for logging


def _get_paths() -> dict:
    """Get all paths from API (cached).

    Only caches non-empty results to avoid permanently caching
    error states (e.g. when API is not yet ready at startup).

    Returns:
        Dict with path keys: workspace_dir, config_dir, temp_dir,
        exports_dir, data_dir, logs_dir.
        Empty dict on API error.
    """
    if "paths" not in _cache:
        try:
            r = requests.get(f"{_BASE_URL}/api/mcp/paths", timeout=_TIMEOUT)
            result = r.json() if r.ok else {}
            if result:
                _cache["paths"] = result
            return result
        except Exception as e:
            _warn(f"API not reachable ({_BASE_URL}): {e}")
            return {}  # Do NOT cache empty results
    return _cache["paths"]


def get_config_dir() -> Path:
    """Get config directory path.

    Resolution order:
    1. DESKAGENT_CONFIG_DIR env var (set by claude_desktop.py for subprocess MCPs)
    2. Backend API (/api/mcp/paths) when DeskAgent is running
    3. %APPDATA%/DeskAgent/config on Windows (stable per-user fallback)
    4. cwd/config as last resort
    """
    env = os.environ.get("DESKAGENT_CONFIG_DIR")
    if env:
        return Path(env)
    p = _get_paths().get("config_dir", "")
    if p:
        return Path(p)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "DeskAgent" / "config"
    return Path.cwd() / "config"


def get_temp_dir() -> Path:
    """Get temp directory path.

    Returns:
        Path to temp directory. Falls back to cwd/.temp on API error.
    """
    p = _get_paths().get("temp_dir", "")
    return Path(p) if p else Path.cwd() / ".temp"


def get_exports_dir() -> Path:
    """Get exports directory path.

    Returns:
        Path to exports directory. Falls back to cwd/exports on API error.
    """
    p = _get_paths().get("exports_dir", "")
    return Path(p) if p else Path.cwd() / "exports"


def get_data_dir() -> Path:
    """Get data/state directory path.

    Returns:
        Path to data directory. Falls back to cwd/.state on API error.
    """
    p = _get_paths().get("data_dir", "")
    return Path(p) if p else Path.cwd() / ".state"


def get_workspace_dir() -> Path:
    """Get workspace directory path.

    Returns:
        Path to workspace directory. Falls back to cwd/workspace on API error.
    """
    p = _get_paths().get("workspace_dir", "")
    return Path(p) if p else Path.cwd() / "workspace"


def get_logs_dir() -> Path:
    """Get logs directory path.

    Returns:
        Path to logs directory.

    Fallback chain (in order):
    1. API response (logs_dir from /api/mcp/paths)
    2. DESKAGENT_LOGS_DIR environment variable (set by paths.py)
    3. DESKAGENT_WORKSPACE_DIR/.logs (if workspace var is set)
    4. System temp directory (absolute last resort)
    """
    import tempfile

    # 1. Try API
    p = _get_paths().get("logs_dir", "")
    if p:
        return Path(p)

    # 2. Try DESKAGENT_LOGS_DIR env var (set by paths.py on startup)
    env_logs = os.environ.get("DESKAGENT_LOGS_DIR")
    if env_logs:
        logs_path = Path(env_logs)
        logs_path.mkdir(parents=True, exist_ok=True)
        return logs_path

    # 3. Try workspace-based path
    workspace = os.environ.get("DESKAGENT_WORKSPACE_DIR")
    if workspace:
        logs_path = Path(workspace) / ".logs"
        logs_path.mkdir(parents=True, exist_ok=True)
        return logs_path

    # 4. Last resort: temp directory (never creates .logs in wrong location)
    logs_path = Path(tempfile.gettempdir()) / "deskagent-logs"
    logs_path.mkdir(parents=True, exist_ok=True)
    return logs_path


# Alias für Rückwärtskompatibilität
get_state_dir = get_data_dir


def anonymize(text: str, session_id: str, lang: str = "de") -> str:
    """Anonymize text via API (session-based).

    Args:
        text: Text to anonymize
        session_id: Session ID for consistent mappings across calls
        lang: Language code (de, en)

    Returns:
        Anonymized text (mappings stored server-side).
        Returns original text on API error.
    """
    try:
        r = requests.post(
            f"{_BASE_URL}/api/mcp/anonymize",
            json={"text": text, "session_id": session_id, "lang": lang},
            timeout=30  # NER can be slow
        )
        if r.ok:
            return r.json().get("anonymized", text)
    except Exception:
        pass
    return text


def deanonymize(text: str, session_id: str) -> str:
    """De-anonymize text via API (session-based).

    Args:
        text: Anonymized text with placeholders
        session_id: Session ID to retrieve mappings

    Returns:
        Original text with placeholders replaced.
        Returns input text on API error.
    """
    try:
        r = requests.post(
            f"{_BASE_URL}/api/mcp/deanonymize",
            json={"text": text, "session_id": session_id},
            timeout=10
        )
        if r.ok:
            return r.json().get("text", text)
    except Exception:
        pass
    return text


def cleanup_session(session_id: str) -> None:
    """Delete session data after agent completes.

    Args:
        session_id: Session ID to clean up
    """
    try:
        requests.delete(
            f"{_BASE_URL}/api/mcp/session/{session_id}",
            timeout=5
        )
    except Exception:
        pass  # Silent fail for cleanup


def get_task_context() -> Optional[dict]:
    """Get current task context (for nested agent calls).

    Returns:
        Dict with task_id and parent_task_id keys,
        or None on API error.

    Example response:
        {"task_id": "task-123", "parent_task_id": null}
    """
    try:
        r = requests.get(f"{_BASE_URL}/api/mcp/task_context", timeout=_TIMEOUT)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None


def is_anonymizer_available() -> bool:
    """Check if anonymization is available via API.

    Returns:
        True if Presidio/spacy is loaded and ready.
    """
    try:
        r = requests.get(f"{_BASE_URL}/api/mcp/anonymizer/status", timeout=2)
        return r.ok and r.json().get("available", False)
    except Exception:
        return False


def log_tool_call(tool_name: str, direction: str, content: str, is_anonymized: bool = True) -> None:
    """Log tool call to anon_messages.log via API (fire and forget).

    Args:
        tool_name: Name of the tool being called
        direction: "CALL" (AI sends to tool) or "RESULT" (tool returns to AI)
        content: Arguments or result content
        is_anonymized: Whether content has been anonymized
    """
    try:
        requests.post(
            f"{_BASE_URL}/api/mcp/log_tool_call",
            json={
                "tool_name": tool_name,
                "direction": direction,
                "content": content,
                "is_anonymized": is_anonymized
            },
            timeout=2
        )
    except Exception:
        pass  # Silent fail for logging


def clear_cache() -> None:
    """Clear cached config and paths.

    Call this if config/paths might have changed.
    """
    _cache.clear()


def register_link(link_ref: str, web_link: str, session_id: Optional[str] = None) -> bool:
    """Register a link_ref -> web_link mapping (V2 Link Placeholder System).

    MCPs call this to register URLs without exposing them to the AI.
    The AI only sees {{LINK:ref}} placeholders. URLs are resolved at display time.

    Args:
        link_ref: The 8-char hash from make_link_ref()
        web_link: The full URL to the resource
        session_id: Session ID (from DESKAGENT_SESSION_ID env var if not provided)

    Returns:
        True if registration successful, False on error.

    Example:
        from _link_utils import make_link_ref
        ref = make_link_ref(msg_id, "email")
        web_link = msg.get("webLink", "")  # From Graph API response
        if web_link:
            register_link(ref, web_link)
    """
    # Get session_id from environment if not provided
    # ANON_SESSION_ID is set by claude_agent_sdk.py when starting the MCP proxy
    sid = session_id or os.environ.get("DESKAGENT_SESSION_ID") or os.environ.get("ANON_SESSION_ID", "default")

    # DEBUG: Log registration attempt
    mcp_log(f"[LinkRegistry] register_link({link_ref}, {web_link[:50]}...) session={sid}")

    try:
        r = requests.post(
            f"{_BASE_URL}/api/mcp/register-link",
            json={"session_id": sid, "link_ref": link_ref, "web_link": web_link},
            timeout=_TIMEOUT
        )
        success = r.ok and r.json().get("status") == "ok"
        mcp_log(f"[LinkRegistry] Result: {'OK' if success else 'FAILED'} (status={r.status_code})")
        return success
    except Exception as e:
        _warn(f"Failed to register link {link_ref}: {e}")
        mcp_log(f"[LinkRegistry] Exception: {e}")
        return False


def get_workspace_subdir(name: str) -> Path:
    """Get or create a subdirectory within workspace.

    Args:
        name: Subdirectory name or path (e.g., "exports/sepa")

    Returns:
        Path to the subdirectory (created if not exists).
        Falls back to cwd/name on API error.

    Example:
        get_workspace_subdir("exports/sepa") -> workspace/exports/sepa/
    """
    workspace = _get_paths().get("workspace_dir", "")
    if workspace:
        subdir = Path(workspace) / name
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir
    # Fallback
    subdir = Path.cwd() / name
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir
