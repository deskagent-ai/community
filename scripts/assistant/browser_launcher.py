# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Browser Launcher with Chrome DevTools Protocol support.

Automatically launches browser with remote debugging enabled for:
- Voice hotkey integration with Outlook Web
- Browser automation via CDP
- Active tab/URL detection
"""

import sys
import subprocess
import time
from pathlib import Path

# Import system_log for logging
try:
    from ai_agent import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available


def find_browser_executable(browser_type: str = "chrome") -> Path | None:
    """
    Find browser executable path.

    Args:
        browser_type: "chrome", "edge", "vivaldi", or "brave"

    Returns:
        Path to browser executable or None if not found
    """
    if sys.platform == 'win32':
        # Windows paths
        paths = {
            "chrome": [
                Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            ],
            "edge": [
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            ],
            "vivaldi": [
                Path(r"C:\Program Files\Vivaldi\Application\vivaldi.exe"),
                Path(r"C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe"),
                Path.home() / r"AppData\Local\Vivaldi\Application\vivaldi.exe",
            ],
            "brave": [
                Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
                Path(r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ],
        }
    elif sys.platform == 'darwin':
        # macOS paths
        paths = {
            "chrome": [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")],
            "edge": [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")],
            "vivaldi": [Path("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi")],
            "brave": [Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")],
        }
    else:
        # Linux paths
        paths = {
            "chrome": [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium")],
            "edge": [Path("/usr/bin/microsoft-edge")],
            "vivaldi": [Path("/usr/bin/vivaldi")],
            "brave": [Path("/usr/bin/brave-browser")],
        }

    for path in paths.get(browser_type, []):
        if path.exists():
            return path

    return None


def is_browser_with_debugging_running(port: int = 9222) -> bool:
    """
    Check if browser with remote debugging is already running.

    Args:
        port: Remote debugging port

    Returns:
        True if browser with debugging is running
    """
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        return result == 0
    except Exception:
        return False


def launch_browser_with_debugging(
    browser_type: str = "chrome",
    port: int = 9222,
    url: str = None,
    user_data_dir: str = None,
    headless: bool = False
) -> subprocess.Popen | None:
    """
    Launch browser with Chrome DevTools Protocol enabled.

    Args:
        browser_type: "chrome", "edge", "vivaldi", or "brave"
        port: Remote debugging port (default: 9222)
        url: Optional URL to open
        user_data_dir: Optional user data directory (None = use default profile)
        headless: Run in headless mode

    Returns:
        subprocess.Popen instance or None on error
    """
    # Check if already running
    if is_browser_with_debugging_running(port):
        system_log(f"[Browser] Already running with debugging on port {port}")
        return None

    # Find browser executable
    browser_exe = find_browser_executable(browser_type)
    if not browser_exe:
        system_log(f"[Browser] {browser_type} not found")
        return None

    system_log(f"[Browser] Found {browser_type} at: {browser_exe}")

    # Build command
    cmd = [
        str(browser_exe),
        f"--remote-debugging-port={port}",
    ]

    # Optional: Separate user data directory (recommended for automation)
    if user_data_dir:
        cmd.append(f"--user-data-dir={user_data_dir}")

    # Optional: Headless mode
    if headless:
        cmd.extend(["--headless", "--disable-gpu"])

    # Optional: Open URL
    if url:
        cmd.append(url)

    # Launch browser
    try:
        if sys.platform == 'win32':
            # Windows: Detached process, don't kill on parent exit
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            # Unix: Detached process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        system_log(f"[Browser] Launched {browser_type} (PID: {process.pid})")
        system_log(f"[Browser] Remote debugging: http://localhost:{port}")

        # Wait a bit for browser to start
        time.sleep(2)

        # Verify debugging port is open
        if is_browser_with_debugging_running(port):
            system_log(f"[Browser] Debugging port {port} is active")
        else:
            system_log(f"[Browser] Debugging port {port} not responding (might need more time)")

        return process

    except Exception as e:
        system_log(f"[Browser] Error launching: {e}")
        return None


def get_browser_tabs(port: int = 9222) -> list[dict]:
    """
    Get list of open browser tabs via CDP.

    Args:
        port: Remote debugging port

    Returns:
        List of tab info dicts with keys: id, url, title
    """
    try:
        import requests
        response = requests.get(f"http://localhost:{port}/json", timeout=2)
        if response.status_code == 200:
            tabs = response.json()
            return [
                {
                    "id": tab.get("id"),
                    "url": tab.get("url"),
                    "title": tab.get("title"),
                    "type": tab.get("type")
                }
                for tab in tabs
                if tab.get("type") == "page"
            ]
    except Exception as e:
        system_log(f"[Browser] Error getting tabs: {e}")

    return []


def get_active_tab_url(port: int = 9222) -> str | None:
    """
    Get URL of the currently active tab.

    Args:
        port: Remote debugging port

    Returns:
        URL string or None
    """
    tabs = get_browser_tabs(port)

    # CDP doesn't directly tell us which tab is active
    # Heuristic: First non-chrome:// URL is likely active
    for tab in tabs:
        url = tab.get("url", "")
        if url and not url.startswith("chrome://") and not url.startswith("edge://"):
            return url

    return None


def extract_outlook_message_id(url: str) -> str | None:
    """
    Extract message ID from Outlook Web URL.

    Supported formats:
    - https://outlook.office.com/mail/.../id/AAMkAG...
    - https://outlook.office365.com/mail/.../id/AAMkAG...

    Args:
        url: Outlook Web URL

    Returns:
        Message ID or None
    """
    if not url or "outlook.office" not in url:
        return None

    # Pattern: .../id/AAMkAG...
    import re
    match = re.search(r'/id/([A-Za-z0-9\-_]+)', url)
    if match:
        return match.group(1)

    return None


def is_outlook_web_url(url: str) -> bool:
    """
    Check if URL is Outlook Web.

    Args:
        url: URL to check

    Returns:
        True if Outlook Web
    """
    if not url:
        return False

    return "outlook.office" in url and "/mail" in url


if __name__ == "__main__":
    # Test browser launch - using print() for CLI test output
    print("Testing browser launcher...")

    # Try to find and launch Chrome
    process = launch_browser_with_debugging(
        browser_type="chrome",
        port=9222,
        url="https://outlook.office.com"
    )

    if process:
        print("\nBrowser launched successfully!")
        print("Waiting 5 seconds...")
        time.sleep(5)

        # Get tabs
        tabs = get_browser_tabs()
        print(f"\nOpen tabs: {len(tabs)}")
        for tab in tabs:
            print(f"  - {tab['title'][:50]}: {tab['url'][:80]}")

        # Get active tab
        active_url = get_active_tab_url()
        print(f"\nActive tab URL: {active_url}")

        # Check if Outlook
        if is_outlook_web_url(active_url):
            print("Outlook Web detected!")
            msg_id = extract_outlook_message_id(active_url)
            if msg_id:
                print(f"  Message ID: {msg_id}")
    else:
        print("Failed to launch browser")
