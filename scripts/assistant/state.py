# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Global state for DeskAgent.

This module holds shared state that needs to be accessed across modules.
"""

import os
import psutil
from pathlib import Path

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

# Global port (set at startup, used by hotkeys/tray)
_active_port = None


def get_active_port() -> int:
    """Get the currently active server port."""
    global _active_port
    return _active_port or 8765


def set_active_port(port: int):
    """Set the active server port."""
    global _active_port
    _active_port = port


# === PID File Management ===

def get_pid_file() -> Path:
    """Get PID file path.

    Uses get_data_dir() (workspace/.state/) instead of DESKAGENT_DIR
    because DESKAGENT_DIR may be read-only (e.g. macOS app bundle).
    """
    from paths import get_data_dir
    return get_data_dir() / "deskagent.pid"


def get_lock_file() -> Path:
    """Get lock file path (for single instance).

    Uses get_data_dir() (workspace/.state/) instead of DESKAGENT_DIR
    because DESKAGENT_DIR may be read-only (e.g. macOS app bundle).
    """
    from paths import get_data_dir
    return get_data_dir() / "deskagent.lock"


def write_pid_file():
    """Write current process PID to file."""
    pid_file = get_pid_file()
    try:
        pid_file.write_text(str(os.getpid()))
        system_log(f"[PID] Written to {pid_file}: {os.getpid()}")
    except Exception as e:
        system_log(f"[PID] Error writing PID file: {e}")


def remove_pid_file():
    """Remove PID file on shutdown."""
    pid_file = get_pid_file()
    try:
        if pid_file.exists():
            pid_file.unlink()
            system_log(f"[PID] Removed {pid_file}")
    except Exception as e:
        system_log(f"[PID] Error removing PID file: {e}")


def get_running_pid() -> int | None:
    """
    Get PID of running DeskAgent instance (if any).
    Returns None if no instance is running.
    Validates that the PID actually exists and is a Python process.
    """
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())

        # Validate PID exists and is a DeskAgent/Python process
        if psutil.pid_exists(pid):
            try:
                proc = psutil.Process(pid)
                # Check if it's a Python process (dev) or DeskAgent.exe (Nuitka build)
                proc_name = proc.name().lower()
                if "python" in proc_name or "deskagent" in proc_name:
                    return pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Stale PID file - clean it up
        system_log(f"[PID] Stale PID file detected (PID {pid} not running)")
        remove_pid_file()
        return None
    except Exception as e:
        system_log(f"[PID] Error reading PID file: {e}")
        return None


def is_instance_running() -> bool:
    """Check if another DeskAgent instance is running."""
    return get_running_pid() is not None


def acquire_instance_lock() -> bool:
    """
    Acquire single-instance lock.
    Returns True if lock acquired (no other instance running).
    Returns False if another instance is already running.
    """
    if is_instance_running():
        pid = get_running_pid()
        system_log(f"[Lock] Another DeskAgent instance is already running (PID {pid})")
        return False

    # Write PID file to claim instance
    write_pid_file()
    return True


def release_instance_lock():
    """Release single-instance lock."""
    remove_pid_file()


def kill_existing_instance(port: int = 8765) -> bool:
    """
    Kill any existing DeskAgent instance.
    Returns True if an instance was killed, False otherwise.

    Before terminating, notifies the old server to broadcast a restart
    message to all connected clients.
    """
    pid = get_running_pid()
    if pid is None:
        return False

    system_log(f"[PID] Stopping existing DeskAgent instance (PID {pid})...")

    # Notify the old server before killing (so clients see "restarting..." immediately)
    _notify_server_shutdown(port)

    try:
        proc = psutil.Process(pid)
        proc.terminate()  # Graceful termination first

        # Wait up to 3 seconds for graceful shutdown
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            # Force kill if not stopped
            system_log(f"[PID] Force killing PID {pid}...")
            proc.kill()
            proc.wait(timeout=2)

        # Clean up PID file
        remove_pid_file()

        # Wait a bit for resources to be released
        import time
        time.sleep(0.5)

        system_log(f"[PID] Stopped existing instance (PID {pid})")
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        system_log(f"[PID] Could not stop process {pid}: {e}")
        remove_pid_file()  # Clean up stale PID file
        return False


def _notify_server_shutdown(port: int):
    """Send shutdown notification to the old server so it can notify clients."""
    import requests

    try:
        url = f"http://localhost:{port}/shutdown-notify"
        # Short timeout - if server is unresponsive, don't block
        response = requests.post(url, timeout=1)
        if response.status_code == 200:
            system_log(f"[PID] Notified old server to broadcast restart")
            # Give clients a moment to receive the SSE event
            import time
            time.sleep(0.2)
    except Exception as e:
        # Server might already be dead or unresponsive - that's fine
        system_log(f"[PID] Could not notify old server (may be unresponsive): {e}")


# === Browser Tab Tracking ===
# Prevents opening duplicate browser tabs on restart

_BROWSER_STATE_FILE = "browser_state.json"
_BROWSER_REOPEN_THRESHOLD = 60  # seconds


def _get_browser_state_file() -> Path:
    """Get browser state file path."""
    from paths import get_state_dir
    return get_state_dir() / _BROWSER_STATE_FILE


def record_browser_opened(port: int):
    """Record that a browser tab was opened for the given port."""
    import json
    import time

    state_file = _get_browser_state_file()
    try:
        state = {
            "port": port,
            "timestamp": time.time(),
            "pid": os.getpid()
        }
        state_file.write_text(json.dumps(state), encoding='utf-8')
        system_log(f"[Browser] Recorded browser open for port {port}")
    except Exception as e:
        system_log(f"[Browser] Error recording browser state: {e}")


def should_open_browser(port: int) -> bool:
    """
    Check if a browser tab should be opened for the given port.

    Returns False if:
    - A UI heartbeat was received recently (tab is definitely open)
    - A browser was recently opened for the same port (within threshold)
    - Previous DeskAgent instance is still running
    """
    import json
    import time

    # First check: Did we receive a UI heartbeat recently?
    # This is the most reliable indicator that a tab is open
    if has_recent_ui_heartbeat():
        system_log("[Browser] Recent UI heartbeat detected - tab is open, skipping browser open")
        return False

    state_file = _get_browser_state_file()
    if not state_file.exists():
        return True  # No previous state, open browser

    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))
        prev_port = state.get("port")
        prev_timestamp = state.get("timestamp", 0)
        prev_pid = state.get("pid")

        # Different port = different instance, open browser
        if prev_port != port:
            system_log(f"[Browser] Different port ({prev_port} -> {port}), will open browser")
            return True

        # Check if previous instance is still running
        if prev_pid and psutil.pid_exists(prev_pid):
            try:
                proc = psutil.Process(prev_pid)
                if "python" in proc.name().lower():
                    # Previous instance still running - tab is likely still open
                    system_log(f"[Browser] Previous instance (PID {prev_pid}) still running, skipping browser open")
                    return False
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Check timestamp threshold
        elapsed = time.time() - prev_timestamp
        if elapsed < _BROWSER_REOPEN_THRESHOLD:
            system_log(f"[Browser] Browser opened {elapsed:.1f}s ago, skipping (threshold: {_BROWSER_REOPEN_THRESHOLD}s)")
            return False

        # Threshold exceeded, open browser
        system_log(f"[Browser] Last browser open was {elapsed:.1f}s ago, will open new tab")
        return True

    except Exception as e:
        system_log(f"[Browser] Error reading browser state: {e}")
        return True  # On error, open browser


# === UI Heartbeat Tracking ===
# Tracks active browser tabs via periodic heartbeats

_HEARTBEAT_STATE_FILE = "ui_heartbeat.json"
_HEARTBEAT_THRESHOLD = 30  # seconds - tab is considered active if heartbeat within this time


def _get_heartbeat_state_file() -> Path:
    """Get heartbeat state file path."""
    from paths import get_state_dir
    return get_state_dir() / _HEARTBEAT_STATE_FILE


def record_ui_heartbeat(client_id: str = None):
    """Record a heartbeat from a UI client (browser tab).

    Called by /api/ui/heartbeat endpoint.
    """
    import json
    import time

    state_file = _get_heartbeat_state_file()
    try:
        state = {
            "timestamp": time.time(),
            "client_id": client_id
        }
        state_file.write_text(json.dumps(state), encoding='utf-8')
    except Exception as e:
        system_log(f"[Heartbeat] Error recording heartbeat: {e}")


def has_recent_ui_heartbeat() -> bool:
    """Check if a UI client sent a heartbeat recently.

    Returns True if a heartbeat was received within HEARTBEAT_THRESHOLD seconds,
    indicating a browser tab is likely still open.
    """
    import json
    import time

    state_file = _get_heartbeat_state_file()
    if not state_file.exists():
        return False

    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))
        timestamp = state.get("timestamp", 0)
        elapsed = time.time() - timestamp

        if elapsed < _HEARTBEAT_THRESHOLD:
            system_log(f"[Heartbeat] Recent heartbeat {elapsed:.1f}s ago - tab likely open")
            return True
        return False
    except Exception as e:
        system_log(f"[Heartbeat] Error reading heartbeat state: {e}")
        return False


def clear_ui_heartbeat():
    """Clear the heartbeat state (e.g., on clean shutdown)."""
    state_file = _get_heartbeat_state_file()
    try:
        if state_file.exists():
            state_file.unlink()
    except Exception:
        pass


def clear_browser_state():
    """Clear the browser state (e.g., on clean shutdown)."""
    state_file = _get_browser_state_file()
    try:
        if state_file.exists():
            state_file.unlink()
    except Exception:
        pass
