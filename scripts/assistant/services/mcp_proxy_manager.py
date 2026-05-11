# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
MCP Proxy Manager - Startet und verwaltet den MCP Proxy Stack.

Der Manager startet zwei Prozesse:
1. FastMCP (Anonymization Proxy) auf internem Port (19001)
2. Filter Proxy auf externem Port (8766)

Claude SDK verbindet zum Filter Proxy, der per-Session Tool-Filtering
durchfuehrt und dann an FastMCP weiterleitet.

Architecture:
    Claude SDK -> Filter Proxy (8766) -> FastMCP (19001) -> MCP Tools
                       |
                  Filters tools/list
                  based on session filter

Features:
- Auto-Start beim ersten Bedarf
- Auto-Restart bei Crash
- Graceful Shutdown bei App-Ende
- TCP-basierte Health-Checks
- Per-Session Dynamic Tool Filtering (F1-F5)

Usage:
    from assistant.services.mcp_proxy_manager import ensure_proxy_running, get_proxy_url

    # Stellt sicher dass Proxy laeuft (startet/restarted bei Bedarf)
    ensure_proxy_running()

    # URL fuer Claude SDK (mit optionalem Filter)
    url = get_proxy_url(session_id="abc123", mcp_filter="outlook|billomat")
    # -> "http://localhost:8766/mcp?session=abc123&filter=outlook%7Cbillomat"
"""

import atexit
import socket
import subprocess
import sys
import time
from pathlib import Path

# =============================================================================
# Port Configuration
# =============================================================================
# External port (Claude SDK connects here via Filter Proxy)
PROXY_PORT = 8766
# Internal port default (FastMCP runs here, configurable via claude_desktop.port)
_DEFAULT_FASTMCP_PORT = 19001
PROXY_HOST = "localhost"

# Startup timeouts
FASTMCP_STARTUP_TIMEOUT = 60.0  # FastMCP kann beim ersten Start lange laden (~280 Tools)
FILTER_PROXY_STARTUP_TIMEOUT = 10.0  # Filter Proxy ist schnell

# Default transport (can be overridden in backends.json)
# Options: "inprocess" (SDK in-process), "stdio" (subprocess), "sse"/"streamable-http" (HTTP proxy)
# stdio is now default as it's simpler and avoids HTTP proxy startup/port issues
# inprocess is the most stable but requires claude-agent-sdk 0.1.27+
DEFAULT_MCP_TRANSPORT = "stdio"

# =============================================================================
# Global process handles
# =============================================================================
_fastmcp_process = None
_current_transport = None  # Track current transport for restart detection
_filter_proxy_process = None
_fastmcp_log_handle = None
_filter_proxy_log_handle = None
_atexit_registered = False


def _get_fastmcp_port() -> int:
    """Get FastMCP port from config (claude_desktop.port) or use default.

    Returns:
        Port number for FastMCP HTTP server.
    """
    try:
        from config import load_config
        config = load_config()
        return config.get("claude_desktop", {}).get("port", _DEFAULT_FASTMCP_PORT)
    except Exception:
        return _DEFAULT_FASTMCP_PORT


def _get_system_log():
    """Get system_log function with fallback to print."""
    try:
        from ai_agent import system_log
        return system_log
    except ImportError:
        return print


def get_mcp_transport() -> str:
    """Get MCP transport from claude_sdk backend config.

    Returns:
        Transport string: "inprocess", "stdio", "sse", or "streamable-http"

        - "inprocess": In-process SDK MCP (no network, most stable, requires SDK 0.1.27+)
        - "stdio": Direct subprocess, no proxy (old behavior before SDK 0.1.28)
        - "sse": SSE proxy (deprecated but stable)
        - "streamable-http": HTTP proxy (default, recommended)
    """
    try:
        # Use central config merge (system defaults + user overrides)
        from config import load_config
        config = load_config()
        claude_sdk = config.get("ai_backends", {}).get("claude_sdk", {})
        return claude_sdk.get("mcp_transport", DEFAULT_MCP_TRANSPORT)
    except Exception:
        pass

    return DEFAULT_MCP_TRANSPORT


def _start_fastmcp(transport_override: str | None = None) -> bool:
    """Start FastMCP (Anonymization Proxy) on internal port.

    Args:
        transport_override: Force a specific transport (e.g. "streamable-http" for hub mode).
                            If None, reads from backends.json config.

    Returns:
        True if started successfully, False otherwise.
    """
    global _fastmcp_process, _fastmcp_log_handle, _current_transport

    system_log = _get_system_log()

    # Get transport from override or config
    transport = transport_override or get_mcp_transport()

    # Check if already running with correct transport
    if _fastmcp_process is not None and _fastmcp_process.poll() is None:
        if _current_transport == transport:
            system_log(f"[MCP Proxy] FastMCP already running (transport: {transport})")
            return True
        else:
            system_log(f"[MCP Proxy] Transport changed ({_current_transport} -> {transport}), restarting...")
            stop_mcp_proxy()
            # Continue below to start with new transport

    # Update current transport
    _current_transport = transport

    # Get proxy script path
    try:
        from paths import get_mcp_dir
        proxy_script = get_mcp_dir() / "anonymization_proxy_mcp.py"
    except ImportError:
        proxy_script = Path(__file__).parent.parent.parent.parent / "mcp" / "anonymization_proxy_mcp.py"

    if not proxy_script.exists():
        system_log(f"[MCP Proxy] FastMCP script not found: {proxy_script}")
        return False

    # Build command - FastMCP with configured transport
    fastmcp_port = _get_fastmcp_port()
    cmd = [
        sys.executable,
        str(proxy_script),
        "--transport", transport,
        "--host", PROXY_HOST,
        "--port", str(fastmcp_port)
    ]

    system_log(f"[MCP Proxy] Starting FastMCP on port {fastmcp_port} (transport: {transport})")

    try:
        # Get log file path (paths module is always available in this context)
        from paths import get_logs_dir
        log_file = get_logs_dir() / "mcp_fastmcp.log"
        _fastmcp_log_handle = open(log_file, 'a', encoding='utf-8')

        _fastmcp_process = subprocess.Popen(
            cmd,
            stdout=_fastmcp_log_handle,
            stderr=subprocess.STDOUT
        )

        # Wait for FastMCP to be ready
        if _wait_for_port(fastmcp_port, FASTMCP_STARTUP_TIMEOUT, _fastmcp_process):
            system_log(f"[MCP Proxy] FastMCP ready on port {fastmcp_port}")
            return True
        else:
            system_log(f"[MCP Proxy] FastMCP failed to start within {FASTMCP_STARTUP_TIMEOUT}s")
            if _fastmcp_process and _fastmcp_process.poll() is not None:
                system_log(f"[MCP Proxy] FastMCP exited with code {_fastmcp_process.returncode}")
            return False

    except Exception as e:
        system_log(f"[MCP Proxy] Failed to start FastMCP: {e}")
        return False


def _start_filter_proxy() -> bool:
    """Start Filter Proxy on external port.

    Returns:
        True if started successfully, False otherwise.
    """
    global _filter_proxy_process, _filter_proxy_log_handle

    system_log = _get_system_log()

    # Check if already running
    if _filter_proxy_process is not None and _filter_proxy_process.poll() is None:
        system_log("[MCP Proxy] Filter Proxy already running")
        return True

    # Get filter proxy script path
    try:
        from paths import get_mcp_dir
        filter_script = get_mcp_dir() / "mcp_filter_proxy.py"
    except ImportError:
        filter_script = Path(__file__).parent.parent.parent.parent / "mcp" / "mcp_filter_proxy.py"

    if not filter_script.exists():
        system_log(f"[MCP Proxy] Filter Proxy script not found: {filter_script}")
        return False

    # Build command - Filter Proxy on external port, forwards to internal FastMCP port
    fastmcp_port = _get_fastmcp_port()
    cmd = [
        sys.executable,
        str(filter_script),
        "--proxy-port", str(PROXY_PORT),
        "--fastmcp-port", str(fastmcp_port)
    ]

    system_log(f"[MCP Proxy] Starting Filter Proxy on port {PROXY_PORT} -> {fastmcp_port}")

    try:
        # Get log file path (paths module is always available in this context)
        from paths import get_logs_dir
        log_file = get_logs_dir() / "mcp_filter_proxy.log"
        _filter_proxy_log_handle = open(log_file, 'a', encoding='utf-8')

        _filter_proxy_process = subprocess.Popen(
            cmd,
            stdout=_filter_proxy_log_handle,
            stderr=subprocess.STDOUT
        )

        # Wait for Filter Proxy to be ready
        if _wait_for_port(PROXY_PORT, FILTER_PROXY_STARTUP_TIMEOUT, _filter_proxy_process):
            system_log(f"[MCP Proxy] Filter Proxy ready on port {PROXY_PORT}")
            return True
        else:
            system_log(f"[MCP Proxy] Filter Proxy failed to start within {FILTER_PROXY_STARTUP_TIMEOUT}s")
            if _filter_proxy_process and _filter_proxy_process.poll() is not None:
                system_log(f"[MCP Proxy] Filter Proxy exited with code {_filter_proxy_process.returncode}")
            return False

    except Exception as e:
        system_log(f"[MCP Proxy] Failed to start Filter Proxy: {e}")
        return False


def _wait_for_port(port: int, timeout: float, process=None) -> bool:
    """Wait for a port to be ready via TCP connect.

    Args:
        port: Port number to check
        timeout: Maximum wait time in seconds
        process: Optional process to check if it died

    Returns:
        True if port is ready, False if timeout exceeded.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((PROXY_HOST, port), timeout=1):
                return True
        except (socket.error, OSError):
            pass

        # Check if process died
        if process and process.poll() is not None:
            return False

        time.sleep(0.5)

    return False


def start_mcp_proxy(transport_override: str | None = None) -> bool:
    """Start the MCP proxy (FastMCP only).

    NOTE: As of 2026-02-06, the Filter Proxy is no longer used.
    Claude SDK connects directly to FastMCP.

    Args:
        transport_override: Force a specific transport (e.g. "streamable-http" for hub mode).

    Returns:
        True if FastMCP started successfully, False otherwise.
    """
    global _atexit_registered

    system_log = _get_system_log()

    # Register atexit handler (only once)
    if not _atexit_registered:
        atexit.register(stop_mcp_proxy)
        _atexit_registered = True

    # Start FastMCP only (Filter Proxy is bypassed)
    if not _start_fastmcp(transport_override):
        system_log("[MCP Proxy] Failed to start FastMCP")
        return False

    system_log(f"[MCP Proxy] FastMCP ready on port {_get_fastmcp_port()} (direct connection)")
    return True


def _stop_fastmcp():
    """Stop FastMCP process."""
    global _fastmcp_process, _fastmcp_log_handle

    system_log = _get_system_log()

    if _fastmcp_process is None:
        return

    system_log("[MCP Proxy] Stopping FastMCP...")

    try:
        _fastmcp_process.terminate()
        try:
            _fastmcp_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _fastmcp_process.kill()
            _fastmcp_process.wait(timeout=2)
    except Exception as e:
        system_log(f"[MCP Proxy] Error stopping FastMCP: {e}")
    finally:
        _fastmcp_process = None
        if _fastmcp_log_handle:
            try:
                _fastmcp_log_handle.close()
            except Exception:
                pass
            _fastmcp_log_handle = None


def _stop_filter_proxy():
    """Stop Filter Proxy process."""
    global _filter_proxy_process, _filter_proxy_log_handle

    system_log = _get_system_log()

    if _filter_proxy_process is None:
        return

    system_log("[MCP Proxy] Stopping Filter Proxy...")

    try:
        _filter_proxy_process.terminate()
        try:
            _filter_proxy_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _filter_proxy_process.kill()
            _filter_proxy_process.wait(timeout=2)
    except Exception as e:
        system_log(f"[MCP Proxy] Error stopping Filter Proxy: {e}")
    finally:
        _filter_proxy_process = None
        if _filter_proxy_log_handle:
            try:
                _filter_proxy_log_handle.close()
            except Exception:
                pass
            _filter_proxy_log_handle = None


def stop_mcp_proxy():
    """Stop the full MCP proxy stack gracefully."""
    system_log = _get_system_log()
    system_log("[MCP Proxy] Stopping proxy stack...")

    # Stop Filter Proxy first (it depends on FastMCP)
    _stop_filter_proxy()

    # Then stop FastMCP
    _stop_fastmcp()

    system_log("[MCP Proxy] Stack stopped")


def ensure_proxy_running() -> bool:
    """Ensure FastMCP is running, restart if crashed.

    This is the main entry point for other modules. It:
    - Starts FastMCP if not running
    - Restarts if process died
    - Restarts if port is unresponsive

    Returns:
        True if FastMCP is running, False if start failed.
    """
    system_log = _get_system_log()

    # Check FastMCP only (Filter Proxy is bypassed)
    fastmcp_running = _fastmcp_process is not None and _fastmcp_process.poll() is None
    if fastmcp_running:
        fastmcp_responsive = _is_port_open(_get_fastmcp_port())
    else:
        fastmcp_responsive = False

    # If FastMCP is running and responsive, we're good
    if fastmcp_running and fastmcp_responsive:
        return True

    # Something is wrong - log status and restart
    if not fastmcp_running:
        system_log("[MCP Proxy] FastMCP process not running")
    elif not fastmcp_responsive:
        system_log("[MCP Proxy] FastMCP not responsive")

    # Stop and restart
    system_log("[MCP Proxy] Restarting FastMCP...")
    stop_mcp_proxy()
    return start_mcp_proxy()


def _is_port_open(port: int) -> bool:
    """Check if a port accepts connections."""
    try:
        with socket.create_connection((PROXY_HOST, port), timeout=1):
            return True
    except (socket.error, OSError):
        return False


def get_proxy_url(session_id: str = None, mcp_filter: str = None) -> str:
    """Get HTTP URL for Claude SDK (connects directly to FastMCP).

    NOTE: As of 2026-02-06, we bypass the Filter Proxy and connect directly
    to FastMCP. The Filter Proxy was causing HTTP 400 errors that broke
    CLI initialization (see debug-20260206-sdk-initialize-timeout.md).

    Tool filtering is now handled directly in FastMCP via query parameters.

    Args:
        session_id: Optional session ID for anonymization isolation.
        mcp_filter: Optional MCP filter pattern (regex like "outlook|billomat").

    Returns:
        URL string like "http://localhost:19001/mcp?session=abc123&filter=outlook"
    """
    # Connect directly to FastMCP (bypass Filter Proxy)
    url = f"http://{PROXY_HOST}:{_get_fastmcp_port()}/mcp"
    params = []
    if session_id:
        params.append(f"session={session_id}")
    if mcp_filter:
        # URL-encode the filter pattern
        import urllib.parse
        params.append(f"filter={urllib.parse.quote(mcp_filter)}")
    if params:
        url += "?" + "&".join(params)
    return url


def is_proxy_running() -> bool:
    """Check if FastMCP is running via TCP connect.

    Returns:
        True if FastMCP accepts connections, False otherwise.
    """
    return _is_port_open(_get_fastmcp_port())


def get_proxy_status() -> dict:
    """Get detailed proxy stack status.

    Returns:
        Dict with status information for both components.
    """
    fastmcp_running = _fastmcp_process is not None and _fastmcp_process.poll() is None
    filter_running = _filter_proxy_process is not None and _filter_proxy_process.poll() is None

    return {
        "fastmcp": {
            "process_running": fastmcp_running,
            "port_open": _is_port_open(_get_fastmcp_port()),
            "port": _get_fastmcp_port(),
            "pid": _fastmcp_process.pid if fastmcp_running else None
        },
        "filter_proxy": {
            "process_running": filter_running,
            "port_open": _is_port_open(PROXY_PORT),
            "port": PROXY_PORT,
            "pid": _filter_proxy_process.pid if filter_running else None
        },
        "host": PROXY_HOST,
        "external_port": PROXY_PORT,
        "url": get_proxy_url()
    }


def clear_session_filter(session_id: str) -> None:
    """Clear filter for a session (call when agent ends).

    This is a convenience function that calls into the Filter Proxy
    to clean up session state. Called by claude_agent_sdk.py after
    agent completion.

    Args:
        session_id: Session ID to clean up
    """
    # Import here to avoid circular imports
    try:
        # Try to import from the filter proxy module directly
        # This works if the filter proxy is running in the same process (testing)
        # or if we're just clearing local state
        import sys
        mcp_dir = Path(__file__).parent.parent.parent.parent / "mcp"
        if str(mcp_dir) not in sys.path:
            sys.path.insert(0, str(mcp_dir))

        from mcp_filter_proxy import clear_session_filter as _clear
        _clear(session_id)
    except ImportError:
        # Filter proxy runs in separate process - session will timeout via TTL
        pass


def start_hub_if_enabled() -> bool:
    """Start MCP Hub proxy if claude_desktop.hub_enabled is True.

    Called at DeskAgent startup. Reads config and starts the HTTP proxy
    in the background if hub mode is enabled. Does nothing if not configured.

    Returns:
        True if hub was started, False if not enabled or start failed.
    """
    system_log = _get_system_log()

    try:
        from config import load_config
        config = load_config()
    except Exception as e:
        system_log(f"[MCP Hub] Failed to load config: {e}")
        return False

    claude_config = config.get("claude_desktop", {})
    if not claude_config.get("hub_enabled", False):
        return False

    port = claude_config.get("port", _DEFAULT_FASTMCP_PORT)
    system_log(f"[MCP Hub] hub_enabled=true, starting HTTP proxy on port {port}...")

    # Hub always uses streamable-http transport (regardless of backends.json setting)
    success = start_mcp_proxy(transport_override="streamable-http")
    if success:
        system_log(f"[MCP Hub] Proxy running on port {port}")
    else:
        system_log("[MCP Hub] Failed to start proxy")

    return success


# =============================================================================
# Legacy compatibility
# =============================================================================
# Keep old variable name for backwards compatibility
_proxy_process = None  # Alias for external code checking process state
_log_handle = None
