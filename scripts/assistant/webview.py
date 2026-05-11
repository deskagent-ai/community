# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Embedded WebView window for DeskAgent using pywebview.

This module provides an optional native window that embeds the WebUI,
instead of requiring a browser. Can be enabled/disabled via config.json.

Features:
- Saves window position and size on close
- Custom app icon
- Content zoom support

Note: pywebview requires running on the main thread, so we use a subprocess.
The inline script uses print() since it runs in a separate process where
system_log is not available.
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
    return get_state_dir() / ".webview_state.json"

# Track subprocess
_webview_process = None


def is_available() -> bool:
    """Check if pywebview is available."""
    return WEBVIEW_AVAILABLE


def load_window_state() -> dict:
    """Load saved window state (position, size, zoom)."""
    try:
        state_file = _get_window_state_file()
        if state_file.exists():
            return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        try:
            from ai_agent import system_log
            system_log(f"[WebView] Failed to load window state: {e}")
        except ImportError:
            pass
    return {}


def get_version() -> str:
    """Get version from version.json."""
    try:
        version_file = PROJECT_DIR / "version.json"
        if version_file.exists():
            data = json.loads(version_file.read_text(encoding="utf-8"))
            return data.get("version", "")
    except Exception as e:
        try:
            from ai_agent import system_log
            system_log(f"[WebView] Failed to read version.json: {e}")
        except ImportError:
            pass
    return ""


def create_window(port: int, title: str = "DeskAgent", width: int = 900, height: int = 1000, icon_path: str = None):
    """
    Create and show the webview window in a separate process.

    Args:
        port: HTTP server port to connect to
        title: Window title (version will be appended automatically)
        width: Window width (default, may be overridden by saved state)
        height: Window height (default, may be overridden by saved state)
        icon_path: Path to window icon (optional)
    """
    global _webview_process

    if not WEBVIEW_AVAILABLE:
        # Import system_log for logging
        try:
            from ai_agent import system_log
            system_log("[WebView] pywebview not installed. Install with: pip install pywebview")
        except ImportError:
            pass
        return

    # Kill existing process if running
    if _webview_process is not None:
        try:
            _webview_process.terminate()
            _webview_process.wait(timeout=2)  # Wait for clean exit
        except Exception as e:
            try:
                from ai_agent import system_log
                system_log(f"[WebView] Failed to terminate existing process: {e}")
            except ImportError:
                pass
        _webview_process = None

    # Append version to title
    version = get_version()
    if version:
        title = f"{title} v{version}"

    # Load saved window state
    state = load_window_state()
    saved_width = state.get("width", width)
    saved_height = state.get("height", height)
    saved_x = state.get("x")
    saved_y = state.get("y")
    saved_zoom = state.get("zoom", 1.0)

    # Resolve icon path - search in DESKAGENT_DIR first, then PROJECT_DIR
    if icon_path:
        icon_full_path = str(PROJECT_DIR / icon_path)
    else:
        icon_full_path = ""
        # Try DESKAGENT_DIR first (same as tray.py)
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

    # Start webview in subprocess (so it can run on main thread of that process)
    # OPTIMIZED: Minimal imports first, create window ASAP, lazy load everything else
    script = f'''
# === PHASE 1: Minimal imports + window creation (fastest possible) ===
import webview
import base64

# Loading HTML - inline, minimal
_html = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>DeskAgent</title>
<style>*{{{{margin:0;padding:0}}}}body{{{{font-family:system-ui;display:flex;align-items:center;
justify-content:center;min-height:100vh;background:#fff}}}}@media(prefers-color-scheme:dark){{{{
body{{{{background:#1a1a2e;color:#e5e5e5}}}}#s{{{{color:#a0a0a0}}}}.sp{{{{border-color:#3a3a4e}}}}}}}}
.c{{{{text-align:center}}}}.sp{{{{width:40px;height:40px;margin:0 auto 1rem;border:3px solid #e5e5e6;
border-top-color:#2196f3;border-radius:50%;animation:spin 1s linear infinite}}}}
@keyframes spin{{{{to{{{{transform:rotate(360deg)}}}}}}}}
.t{{{{font-size:1.5rem;font-weight:600;margin-bottom:.5rem}}}}#s{{{{color:#6e6e80;font-size:.9rem}}}}
</style></head><body><div class="c"><div class="sp"></div><div class="t">DeskAgent</div>
<div id="s">Starting...</div></div></body></html>"""
_url = "data:text/html;base64," + base64.b64encode(_html.encode()).decode()

# Minimal API stub (full implementation loaded later)
class Api:
    def __init__(self): self.window = None
    def zoom_in(self): pass
    def zoom_out(self): pass
    def zoom_reset(self): pass
    def get_zoom(self): return 1.0
    def select_files(self, **kw): return []
    def select_folder(self): return None
api = Api()

# Show window when first page is loaded (avoids flash of error page)
def _on_first_load():
    window.show()
    window.events.loaded -= _on_first_load  # Only once

# CREATE WINDOW IMMEDIATELY but hidden, show after load
window = webview.create_window(
    title="{title}", url=_url,
    width={saved_width}, height={saved_height}, x={pos_x}, y={pos_y},
    resizable=True, min_size=(400, 600), text_select=True, js_api=api,
    hidden=True
)
api.window = window
window.events.loaded += _on_first_load

# === PHASE 2: Background initialization (after window exists) ===
def _init_and_connect():
    import time
    import threading
    from pathlib import Path

    # Config
    STATE_DIR = Path(r"{get_state_dir()}")
    STATE_FILE = STATE_DIR / ".webview_state.json"
    ICON_PATH = r"{icon_full_path}"
    WINDOW_TITLE = "{title}"
    ZOOM = {saved_zoom}
    SERVER = "http://localhost:{port}"
    CACHE = int(time.time())

    # Upgrade API methods
    def zoom_in():
        nonlocal ZOOM
        ZOOM = min(ZOOM + 0.1, 2.0)
        try: window.evaluate_js(f"document.body.style.zoom='{{ZOOM}}'")
        except Exception: pass
        return ZOOM
    def zoom_out():
        nonlocal ZOOM
        ZOOM = max(ZOOM - 0.1, 0.5)
        try: window.evaluate_js(f"document.body.style.zoom='{{ZOOM}}'")
        except Exception: pass
        return ZOOM
    def zoom_reset():
        nonlocal ZOOM
        ZOOM = 1.0
        try: window.evaluate_js("document.body.style.zoom='1.0'")
        except Exception: pass
        return ZOOM
    def select_files(multiple=True, file_types=None):
        try:
            ft = None
            if file_types and file_types != ['*']:
                exts = ';'.join(f'*{{e}}' for e in file_types if e.startswith('.'))
                if exts: ft = (f'Files ({{exts}})', 'All (*.*)')
            return list(window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=multiple, file_types=ft) or [])
        except Exception: return []
    def select_folder():
        try:
            r = window.create_file_dialog(webview.FOLDER_DIALOG)
            return r[0] if r else None
        except Exception: return None

    api.zoom_in = zoom_in
    api.zoom_out = zoom_out
    api.zoom_reset = zoom_reset
    api.get_zoom = lambda: ZOOM
    api.select_files = select_files
    api.select_folder = select_folder

    # Event handlers
    def on_loaded():
        if ZOOM != 1.0:
            try: window.evaluate_js(f"document.body.style.zoom='{{ZOOM}}'")
            except Exception: pass
        try:
            window.evaluate_js(\"\"\"
document.addEventListener('keydown',e=>{{if(e.ctrlKey){{if(e.key==='+'||e.key==='='){{e.preventDefault();pywebview.api.zoom_in()}}
else if(e.key==='-'){{e.preventDefault();pywebview.api.zoom_out()}}else if(e.key==='0'){{e.preventDefault();pywebview.api.zoom_reset()}}}}}});
document.addEventListener('wheel',e=>{{if(e.ctrlKey){{e.preventDefault();e.deltaY<0?pywebview.api.zoom_in():pywebview.api.zoom_out()}}}},{{passive:false}})
\"\"\")
        except Exception: pass

    def on_closing():
        try:
            import json
            STATE_FILE.write_text(json.dumps({{"width":window.width,"height":window.height,"x":window.x,"y":window.y,"zoom":ZOOM}},indent=2),encoding="utf-8")
        except Exception: pass
        return True

    window.events.loaded += on_loaded
    window.events.closing += on_closing

    # Set icon (Windows)
    def set_icon():
        try:
            import sys
            if sys.platform != 'win32' or not ICON_PATH: return
            time.sleep(0.3)
            import win32gui, win32con, win32api
            hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
            if not hwnd or not Path(ICON_PATH).exists(): return
            flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
            try: win32api.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, win32gui.LoadImage(0,ICON_PATH,win32con.IMAGE_ICON,32,32,flags))
            except Exception: pass
            try: win32api.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, win32gui.LoadImage(0,ICON_PATH,win32con.IMAGE_ICON,16,16,flags))
            except Exception: pass
        except Exception: pass
    threading.Thread(target=set_icon, daemon=True).start()

    # Wait for server and navigate
    import urllib.request
    attempts = 0
    while attempts < 60:
        try:
            if urllib.request.urlopen(SERVER + "/status", timeout=2).status == 200:
                time.sleep(0.1)
                window.load_url(SERVER + "/?_cb=" + str(CACHE))
                return
        except Exception: pass
        attempts += 1
        try:
            if attempts > 5:
                window.evaluate_js(f'document.getElementById("s").textContent="Waiting... ({{attempts}})"')
            elif attempts > 2:
                window.evaluate_js('document.getElementById("s").textContent="Connecting..."')
        except Exception: pass
        time.sleep(0.4)
    window.load_url(SERVER + "/?_cb=" + str(CACHE))

# Start background init
import threading
threading.Thread(target=_init_and_connect, daemon=True).start()

# Start webview (blocks until closed)
webview.start(debug=False, private_mode=True)
'''

    _webview_process = subprocess.Popen(
        [get_python_executable(), "-c", script],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )


def show_window():
    """Show the webview window. Creates new one if not exists."""
    global _webview_process
    if _webview_process is None or _webview_process.poll() is not None:
        # Process not running, need to create new window
        # The tray menu handler will call create_window instead
        pass


def destroy_window():
    """Destroy the webview window process."""
    global _webview_process
    if _webview_process is not None:
        try:
            _webview_process.terminate()
        except Exception as e:
            try:
                from ai_agent import system_log
                system_log(f"[WebView] Failed to destroy window process: {e}")
            except ImportError:
                pass
        _webview_process = None


def is_window_open() -> bool:
    """Check if window process is currently running."""
    global _webview_process
    return _webview_process is not None and _webview_process.poll() is None


def toggle_window(port: int, title: str = "DeskAgent", width: int = 900, height: int = 1000, icon_path: str = None) -> bool:
    """
    Toggle window: close if open, open if closed.

    Args:
        port: HTTP server port
        title: Window title
        width: Window width
        height: Window height
        icon_path: Path to window icon

    Returns:
        True if window was opened, False if closed
    """
    if is_window_open():
        destroy_window()
        return False
    else:
        create_window(port, title, width, height, icon_path)
        return True


def set_zoom(zoom: float):
    """Set zoom level in saved state (applied on next window open)."""
    state = load_window_state()
    state["zoom"] = zoom
    try:
        _get_window_state_file().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        try:
            from ai_agent import system_log
            system_log(f"[WebView] Failed to save zoom state: {e}")
        except ImportError:
            pass
