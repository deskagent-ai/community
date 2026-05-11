# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Quick Access modal window - compact always-on-top overlay.

Opens the existing WebUI in a small window (300x500) that triggers
the mobile CSS layout automatically. Can filter by category via URL.

Usage:
    from assistant import quickaccess
    quickaccess.toggle_window(port=8765)  # Toggle open/close
"""

import subprocess
import sys
import json
from pathlib import Path

from assistant.platform import get_python_executable

try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    webview = None
    WEBVIEW_AVAILABLE = False

# Path is set up by assistant/__init__.py
from paths import get_state_dir, PROJECT_DIR, DESKAGENT_DIR


def _get_window_state_file():
    """Get window state file path (dynamic to respect workspace overrides)."""
    return get_state_dir() / ".quickaccess_state.json"

# Track subprocess
_quickaccess_process = None


def is_available() -> bool:
    """Check if pywebview is available."""
    return WEBVIEW_AVAILABLE


def load_window_state() -> dict:
    """Load saved window state (position only - size is fixed)."""
    try:
        state_file = _get_window_state_file()
        if state_file.exists():
            return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        pass  # Corrupted or inaccessible state file - use defaults
    return {}


def create_window(port: int, title: str = "DeskAgent Quick Access", category: str = None):
    """
    Create and show the quick access window in a separate process.

    Args:
        port: HTTP server port to connect to
        title: Window title
        category: Optional category filter (e.g., "pinned")
    """
    global _quickaccess_process

    if not WEBVIEW_AVAILABLE:
        try:
            from ai_agent import system_log
            system_log("[QuickAccess] pywebview not installed. Install with: pip install pywebview")
        except ImportError:
            pass
        return

    # Kill existing process if running
    if _quickaccess_process is not None:
        try:
            _quickaccess_process.terminate()
        except OSError:
            pass  # Process already terminated
        _quickaccess_process = None

    # Load saved window state (position only)
    state = load_window_state()
    saved_x = state.get("x")
    saved_y = state.get("y")

    # Resolve icon path - use main DeskAgent icon (same as tray)
    icon_full_path = ""
    # Try DESKAGENT_DIR/icon.ico first (same as tray.py), then PROJECT_DIR
    for base_dir in [DESKAGENT_DIR, PROJECT_DIR]:
        for ext in [".ico", ".png"]:
            candidate = base_dir / f"icon{ext}"
            if candidate.exists():
                icon_full_path = str(candidate)
                break
        if icon_full_path:
            break

    # Build position string for script
    pos_x = f"{saved_x}" if saved_x is not None else "None"
    pos_y = f"{saved_y}" if saved_y is not None else "None"

    # Build URL with quickaccess flag and optional category filter
    url_params = "?quickaccess=1"
    if category:
        url_params += f"&category={category}"

    # Start webview in subprocess
    script = f'''
import webview
import json
import threading
import time
from pathlib import Path

STATE_DIR = Path(r"{get_state_dir()}")
STATE_FILE = STATE_DIR / ".quickaccess_state.json"
WINDOW_TITLE = "{title}"
ICON_PATH = r"{icon_full_path}"

def set_window_icon_win32():
    """Set window icon using win32gui (Windows workaround for pywebview)."""
    try:
        import win32gui
        import win32con
        import win32api

        # Retry a few times - window may take time to appear
        hwnd = None
        for _ in range(10):
            time.sleep(0.3)
            hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
            if hwnd:
                break

        if not hwnd or not ICON_PATH or not Path(ICON_PATH).exists():
            print(f"[QuickAccess] Icon setup failed: hwnd={{hwnd}}, path={{ICON_PATH}}")
            return

        icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
        try:
            # Load both sizes
            hicon_big = win32gui.LoadImage(0, ICON_PATH, win32con.IMAGE_ICON, 32, 32, icon_flags)
            hicon_small = win32gui.LoadImage(0, ICON_PATH, win32con.IMAGE_ICON, 16, 16, icon_flags)
            if hicon_big:
                win32api.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_big)
            if hicon_small:
                win32api.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_small)
            print(f"[QuickAccess] Icon set successfully")
        except Exception as e:
            print(f"[QuickAccess] LoadImage failed: {{e}}")
    except ImportError:
        print("[QuickAccess] win32gui not available")
    except Exception as e:
        print(f"[QuickAccess] Could not set icon: {{e}}")

def on_closing():
    """Save window position before closing."""
    try:
        state = {{
            "x": window.x,
            "y": window.y
        }}
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[QuickAccess] Could not save state: {{e}}")
    return True

import time as _time
_cache_bust = int(_time.time())

window = webview.create_window(
    title="{title}",
    url=f"http://localhost:{port}/{url_params}&_cb={{_cache_bust}}",
    width=280,
    height=500,
    x={pos_x},
    y={pos_y},
    resizable=True,
    min_size=(200, 300),
    text_select=False,
    on_top=True,
    confirm_close=False,
    easy_drag=True
)

window.events.closing += on_closing

# Start icon setter in background thread (Windows)
import sys
if sys.platform == 'win32' and ICON_PATH:
    threading.Thread(target=set_window_icon_win32, daemon=True).start()

webview.start(private_mode=True)
'''

    _quickaccess_process = subprocess.Popen(
        [get_python_executable(), "-c", script],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )


def destroy_window():
    """Destroy the quick access window process."""
    global _quickaccess_process
    if _quickaccess_process is not None:
        try:
            _quickaccess_process.terminate()
        except OSError:
            pass  # Process already terminated
        _quickaccess_process = None


def is_window_open() -> bool:
    """Check if window process is currently running."""
    global _quickaccess_process
    return _quickaccess_process is not None and _quickaccess_process.poll() is None


def toggle_window(port: int, title: str = "DeskAgent Quick Access", category: str = None) -> bool:
    """
    Toggle window: close if open, open if closed.

    Args:
        port: HTTP server port
        title: Window title
        category: Optional category filter

    Returns:
        True if window was opened, False if closed
    """
    if is_window_open():
        destroy_window()
        return False
    else:
        create_window(port, title, category)
        return True


# Track preprompt window process (separate from main quickaccess)
_preprompt_process = None


def create_preprompt_window(port: int, agent_name: str, title: str = "Pre-Prompt"):
    """
    Create and show a Pre-Prompt overlay window for adding context before running an agent.

    Args:
        port: HTTP server port to connect to
        agent_name: Name of the agent to run after context input
        title: Window title
    """
    global _preprompt_process

    if not WEBVIEW_AVAILABLE:
        try:
            from ai_agent import system_log
            system_log("[PrePrompt] pywebview not installed")
        except ImportError:
            pass
        return

    # Kill existing preprompt window if open
    if _preprompt_process is not None:
        try:
            _preprompt_process.terminate()
        except OSError:
            pass  # Process already terminated
        _preprompt_process = None

    # Resolve icon path - use main DeskAgent icon (same as tray)
    icon_full_path = ""
    for base_dir in [DESKAGENT_DIR, PROJECT_DIR]:
        for ext in [".ico", ".png"]:
            candidate = base_dir / f"icon{ext}"
            if candidate.exists():
                icon_full_path = str(candidate)
                break
        if icon_full_path:
            break

    # Build URL with preprompt parameter
    import urllib.parse
    encoded_agent = urllib.parse.quote(agent_name)
    url = f"http://localhost:{port}/?preprompt={encoded_agent}"

    # Start webview in subprocess with icon support
    script = f'''
import webview
import threading
import time
import sys

WINDOW_TITLE = "{title}"
ICON_PATH = r"{icon_full_path}"

def set_window_icon_win32():
    """Set window icon using win32gui (Windows workaround for pywebview)."""
    try:
        import win32gui
        import win32con
        import win32api

        hwnd = None
        for _ in range(10):
            time.sleep(0.3)
            hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
            if hwnd:
                break

        if not hwnd or not ICON_PATH:
            return

        from pathlib import Path
        if not Path(ICON_PATH).exists():
            return

        icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
        try:
            hicon_big = win32gui.LoadImage(0, ICON_PATH, win32con.IMAGE_ICON, 32, 32, icon_flags)
            hicon_small = win32gui.LoadImage(0, ICON_PATH, win32con.IMAGE_ICON, 16, 16, icon_flags)
            if hicon_big:
                win32api.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_big)
            if hicon_small:
                win32api.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_small)
        except OSError:
            pass  # Icon load failed - continue without custom icon
    except ImportError:
        pass  # win32gui not available
    except OSError:
        pass  # Window handle not accessible

window = webview.create_window(
    title=WINDOW_TITLE,
    url="{url}",
    width=450,
    height=380,
    resizable=False,
    text_select=True,
    on_top=True,
    confirm_close=False
)

# Start icon setter in background thread (Windows)
if sys.platform == 'win32' and ICON_PATH:
    threading.Thread(target=set_window_icon_win32, daemon=True).start()

webview.start(private_mode=True)
'''

    _preprompt_process = subprocess.Popen(
        [get_python_executable(), "-c", script],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )


def close_preprompt_window():
    """Close the preprompt window if open."""
    global _preprompt_process
    if _preprompt_process is not None:
        try:
            _preprompt_process.terminate()
        except OSError:
            pass  # Process already terminated
        _preprompt_process = None
