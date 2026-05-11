# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
DeskAgent - System Tray + Hotkeys + HTTP Server
===================================================
- Right-click tray icon for menu
- Use hotkeys (if configured)
- HTTP API for Stream Deck: http://localhost:8765/skill/mail_reply
- Console + Tray notifications in parallel
"""

# === PATH SETUP ===
# Ensure scripts directory is on sys.path for 'paths' module import
# This is done once here, at package import time, so submodules don't need
# the try/except pattern for importing from paths.
import sys
from pathlib import Path
_scripts_dir = str(Path(__file__).parent.parent.resolve())
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# CRITICAL: Add embedded Python's Lib and site-packages for Nuitka builds
# This enables imports of email.mime, xml.dom, msal, google.genai, etc.
# Platform-aware: Windows uses Lib/site-packages, macOS/Linux venv uses lib/python3.X/site-packages
if getattr(sys, 'frozen', False) or '__compiled__' in dir():
    _exe_dir = Path(sys.executable).parent
    # macOS App Bundle: exe is in Contents/MacOS/, data in Contents/Resources/
    if sys.platform == 'darwin' and _exe_dir.name == "MacOS" and _exe_dir.parent.name == "Contents":
        _base_dir = _exe_dir.parent / 'Resources'
    else:
        _base_dir = _exe_dir

    if sys.platform == 'win32':
        _python_lib = _base_dir / 'python' / 'Lib'
        _python_site_packages = _python_lib / 'site-packages'
    else:
        # macOS/Linux venv: python/lib/python3.X/site-packages
        _python_lib_base = _base_dir / 'python' / 'lib'
        _python_lib = None
        _python_site_packages = None
        if _python_lib_base.is_dir():
            for _entry in _python_lib_base.iterdir():
                if _entry.name.startswith('python3') and _entry.is_dir():
                    _python_lib = _entry
                    _python_site_packages = _entry / 'site-packages'
                    break

    if _python_site_packages and _python_site_packages.is_dir() and str(_python_site_packages) not in sys.path:
        sys.path.insert(1, str(_python_site_packages))
    if _python_lib and _python_lib.is_dir() and str(_python_lib) not in sys.path:
        sys.path.insert(1, str(_python_lib))
# === END PATH SETUP ===

import argparse
import os
import re
import sys
import signal
import socket
import threading
import atexit

# pystray: cross-platform (Windows, macOS, Linux) - optional on non-Windows
HEADLESS_MODE = False
try:
    import pystray
except ImportError:
    if sys.platform == 'win32':
        print("Fehlende Module. Installiere mit:")
        print("  pip install pystray pillow")
        sys.exit(1)
    else:
        # macOS/Linux: run headless if pystray not installed
        HEADLESS_MODE = True
        pystray = None

# Handle imports for both package and direct execution
try:
    from paths import (
        PROJECT_DIR,
        DESKAGENT_DIR,
        get_state_dir,
        get_mcp_dir,
        get_knowledge_dir,
        get_agents_dir,
        get_skills_dir,
        load_config as load_config_from_paths,
        clear_temp_dir,
    )
except ImportError:
    # Direct execution: add parent to path
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from paths import (
        PROJECT_DIR,
        DESKAGENT_DIR,
        get_state_dir,
        get_mcp_dir,
        get_knowledge_dir,
        get_agents_dir,
        get_skills_dir,
        load_config as load_config_from_paths,
        clear_temp_dir,
    )

from .skills import load_config
from .tray import load_icon_image, create_menu, register_hotkeys
from .server import start_http_server, set_tray_icon, request_shutdown, perform_cleanup
from . import webview
from .voice_hotkey import register_voice_hotkey
from .browser_launcher import launch_browser_with_debugging, is_browser_with_debugging_running
from .state import (
    get_active_port,
    set_active_port,
    acquire_instance_lock,
    release_instance_lock,
    get_running_pid,
    kill_existing_instance,
    should_open_browser,
    record_browser_opened,
    has_recent_ui_heartbeat,
)

# Cache für Console-Logging-Status
_console_logging = True


def _load_user_preferences() -> dict:
    """
    Load user preferences from workspace/.state/preferences.json.
    Returns empty dict if file doesn't exist.
    """
    import json
    prefs_file = get_state_dir() / "preferences.json"
    if prefs_file.exists():
        try:
            with open(prefs_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def find_free_port(preferred: int = 8765) -> int:
    """
    Find a free port, preferring the specified one.
    If preferred port is in use, finds any available port.

    Args:
        preferred: Preferred port number

    Returns:
        Available port number
    """
    # Try preferred port first
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', preferred))
            return preferred
        except OSError:
            pass

    # Find any free port (fallback - allows parallel instances from different directories)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]


def discover_mcp_tools() -> dict[str, list[str]]:
    """
    Discover available MCP tools by parsing MCP server files.
    Returns dict: {server_name: [tool_names]}
    """
    from mcp_shared.constants import WINDOWS_ONLY_MCP

    mcp_dir = get_mcp_dir()
    tools_by_server = {}

    for mcp_file in sorted(mcp_dir.glob("*_mcp.py")):
        # Skip proxy (it wraps other servers)
        if mcp_file.name == "anonymization_proxy_mcp.py":
            continue

        server_name = mcp_file.stem.replace("_mcp", "")

        # Skip Windows-only MCP servers on non-Windows platforms
        if sys.platform != 'win32' and server_name in WINDOWS_ONLY_MCP:
            continue
        tools = []

        try:
            content = mcp_file.read_text(encoding="utf-8")
            # Find @mcp.tool() decorated functions
            # Pattern: @mcp.tool() followed by def function_name(
            pattern = r'@mcp\.tool\(\)\s*(?:async\s+)?def\s+(\w+)\s*\('
            matches = re.findall(pattern, content)
            tools = matches
        except Exception:
            pass

        if tools:
            tools_by_server[server_name] = tools

    return tools_by_server


def is_console_logging():
    """Prüft ob Console-Logging aktiviert ist."""
    global _console_logging
    return _console_logging


def log(message: str):
    """Gibt Nachricht auf Console aus, wenn Logging aktiviert."""
    if is_console_logging():
        # Keep print() for user-facing console output
        print(message)


def cleanup_on_exit():
    """Cleanup function called on exit."""
    import ai_agent
    ai_agent.system_log("[Exit] Cleaning up...")

    # Clean up orphan MCP processes from Claude Agent SDK
    try:
        from ai_agent.claude_agent_sdk import _cleanup_orphan_mcp_processes
        killed = _cleanup_orphan_mcp_processes()
        if killed > 0:
            ai_agent.system_log(f"[Exit] Cleaned up {killed} orphan MCP processes")
    except ImportError:
        pass  # Claude SDK not installed - skip MCP cleanup
    except Exception as e:
        ai_agent.system_log(f"[Exit] MCP cleanup failed: {e}")

    perform_cleanup()
    release_instance_lock()
    ai_agent.system_log("[Exit] Cleanup completed")


def signal_handler(signum, frame):
    """Handle shutdown signals (SIGINT, SIGTERM)."""
    import ai_agent
    ai_agent.system_log(f"[Signal] Received signal {signum}")
    request_shutdown()
    # Exit gracefully
    sys.exit(0)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DeskAgent - AI Desktop Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m assistant                    # Start with default port from config
  python -m assistant --port 5005        # Start on specific port
  python -m assistant --health           # Run health check only
  python -m assistant --no-webview       # Start without WebView window
  python -m assistant --shared-dir Z:\\Team\\AIAssistant
  python -m assistant --workspace-dir D:\\DeskAgent
  python -m assistant --backends C:\\test\\backends.json
  python -m assistant --apis C:\\test\\apis.json
        """
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="HTTP server port (overrides config, default: 8765)"
    )
    parser.add_argument(
        "--shared-dir",
        type=str,
        default=None,
        help="Shared content directory (config, agents, skills, knowledge)"
    )
    parser.add_argument(
        "--workspace-dir",
        type=str,
        default=None,
        help="Local workspace directory (logs, exports, state)"
    )
    parser.add_argument(
        "--backends",
        type=str,
        default=None,
        help="Path to backends.json (overrides default config)"
    )
    parser.add_argument(
        "--apis",
        type=str,
        default=None,
        help="Path to apis.json (overrides default config)"
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run health check and exit"
    )
    parser.add_argument(
        "--no-webview",
        action="store_true",
        help="Disable WebView window (browser only)"
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Run without system tray (headless mode for testing)"
    )
    return parser.parse_args()


def main():
    """Startet den System Tray Assistenten mit Hotkeys und HTTP Server."""
    global _console_logging
    import os
    import ai_agent

    # Parse command line arguments FIRST (before init_system_log!)
    args = parse_args()

    # Set path environment variables from CLI args BEFORE initializing logging
    # This ensures logs go to the correct workspace directory
    if args.shared_dir or args.workspace_dir:
        if args.shared_dir:
            os.environ["DESKAGENT_SHARED_DIR"] = args.shared_dir
        if args.workspace_dir:
            os.environ["DESKAGENT_WORKSPACE_DIR"] = args.workspace_dir

        # Reload paths module to pick up new environment variables
        import importlib
        import paths as paths_module
        importlib.reload(paths_module)

    # First-run setup: Create user folders (config, agents, skills, workspace)
    # Must be AFTER CLI args are processed so --workspace-dir/--shared-dir are respected
    # and BEFORE init_system_log() so log folder exists
    try:
        from paths import ensure_first_run_setup
        from .platform import is_compiled
        if is_compiled():
            first_run = ensure_first_run_setup()
            if first_run:
                print("[Startup] First run - created user folders")
    except Exception as e:
        print(f"[Startup] Error during first-run setup: {e}")

    # Initialize system log AFTER path env vars are set
    ai_agent.init_system_log()

    # Log the path overrides (now goes to correct location)
    if args.shared_dir:
        ai_agent.system_log(f"[Config] Shared dir override: {args.shared_dir}")
    if args.workspace_dir:
        ai_agent.system_log(f"[Config] Workspace dir override: {args.workspace_dir}")

    # Health check mode
    if args.health:
        success = health_check()
        sys.exit(0 if success else 1)

    # === Kill existing instance and acquire lock ===
    # If another instance is running, stop it first (restart behavior)
    if get_running_pid() is not None:
        # Use port from args if specified, otherwise default
        shutdown_port = getattr(args, 'port', None) or 8765
        kill_existing_instance(port=shutdown_port)

    if not acquire_instance_lock():
        # Should not happen after kill, but just in case
        running_pid = get_running_pid()
        ai_agent.system_log(f"[Error] Another DeskAgent instance is already running (PID {running_pid})")
        ai_agent.system_log(f"[Error] Use stop.bat to terminate it first, or send shutdown request:")
        ai_agent.system_log(f"[Error] curl -X POST http://localhost:8765/shutdown")
        sys.exit(1)

    # Register cleanup handlers
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # CLI config file overrides (--backends, --apis)
    if args.backends or args.apis:
        from config import set_cli_config_override
        if args.backends:
            set_cli_config_override("backends.json", args.backends)
            ai_agent.system_log(f"[Config] CLI override: --backends={args.backends}")
        if args.apis:
            set_cli_config_override("apis.json", args.apis)
            ai_agent.system_log(f"[Config] CLI override: --apis={args.apis}")

    config = load_config()
    _console_logging = config.get("console_logging", True)

    # Clear temp folder on startup (default: True)
    if config.get("clear_temp_on_start", True):
        if clear_temp_dir():
            ai_agent.system_log("[Startup] .temp/ Ordner geleert")

    # Clear all ai_agent caches on startup for fresh state
    ai_agent.clear_all_caches()

    # Clean up old sessions on startup (#14 - prevents SQLite bloat)
    try:
        from . import session_store
        deleted = session_store.cleanup_old_sessions(max_sessions=100)
        if deleted > 0:
            ai_agent.system_log(f"[Startup] Cleaned up {deleted} old sessions")
    except Exception as e:
        ai_agent.system_log(f"[Startup] Session cleanup failed: {e}")

    # Find available port (CLI > config > default)
    if args.port:
        preferred_port = args.port
        ai_agent.system_log(f"[Config] Port override: {args.port}")
    else:
        preferred_port = config.get("server_port", 8765)
    port = find_free_port(preferred_port)
    set_active_port(port)
    os.environ["DESKAGENT_API_URL"] = f"http://localhost:{port}"

    if port != preferred_port:
        ai_agent.system_log(f"[Port] {preferred_port} belegt, verwende {port}")

    # Note: Logger is now centralized in ai_agent.logging module
    # No set_logger() call needed - modules import log() directly

    # Read version info
    version_str = ""
    try:
        import json as _json
        _vf = Path(__file__).parent.parent.parent / "version.json"
        _vi = _json.loads(_vf.read_text(encoding="utf-8"))
        version_str = f"v{_vi['version']} (build {_vi.get('build', '?')})"
    except Exception:
        version_str = ""

    # Startup banner - keep as print() for user-facing console output
    app_name = config.get('name', 'DeskAgent')
    print("\n" + "=" * 50)
    print(f"  {app_name} {version_str}")
    print("=" * 50)
    print("\nOptionen:")
    print("  - Rechtsklick auf Tray-Icon")
    print("  - Hotkeys (falls konfiguriert)")
    print(f"  - Web UI:              http://localhost:{port}/")
    print(f"  - Stream Deck Skills:  http://localhost:{port}/skill/<name>")
    print(f"  - Stream Deck Agents:  http://localhost:{port}/agent/<name>")

    # Discover and log available MCP tools
    mcp_tools = discover_mcp_tools()
    if mcp_tools:
        all_tools = []
        for server, tools in mcp_tools.items():
            all_tools.extend([f"{server}__{t}" for t in tools])
        ai_agent.system_log(f"[Startup] MCP Tools: {', '.join(all_tools)}")

    # Icon erstellen (nur auf Windows)
    icon = None
    if pystray and not HEADLESS_MODE:
        icon = pystray.Icon(
            "DeskAgent",
            load_icon_image(),
            "DeskAgent\nRechtsklick für Menü"
        )
        # Set tray icon reference for server
        set_tray_icon(icon)

    # System-wide voice input hotkey (register BEFORE menu creation)
    voice_config = config.get("voice_input", {})
    if voice_config.get("dictate_hotkey") or voice_config.get("agent_hotkey"):
        register_voice_hotkey(port, voice_config)

    # Browser integration (on-demand, not at startup)
    # Browser will be started automatically when needed by voice hotkey
    browser_config = config.get("browser_integration", {})
    if browser_config.get("enabled", True) and browser_config.get("auto_start") == "startup":
        browser_type = browser_config.get("browser", "chrome")
        debug_port = browser_config.get("port", 9222)

        # Skip if a browser tab is already open (detected via heartbeat)
        if has_recent_ui_heartbeat():
            ai_agent.system_log("[Browser] UI tab already open, skipping browser integration auto-start")
        # Check if browser with debugging is already running
        elif is_browser_with_debugging_running(debug_port):
            ai_agent.system_log(f"[Browser] Already running with debugging on port {debug_port}")
        else:
            # Check if browser process is already running (without debugging)
            browser_running = False
            try:
                import psutil
                browser_processes = {
                    "chrome": ["chrome.exe", "google-chrome"],
                    "edge": ["msedge.exe", "microsoft-edge"],
                    "vivaldi": ["vivaldi.exe", "vivaldi"],
                    "brave": ["brave.exe", "brave-browser"]
                }
                process_names = browser_processes.get(browser_type, [])
                for proc in psutil.process_iter(['name']):
                    if proc.info['name'] and proc.info['name'].lower() in [p.lower() for p in process_names]:
                        browser_running = True
                        break
            except Exception:
                pass

            if browser_running:
                ai_agent.system_log(f"[Browser] {browser_type} already running, skipping auto-start")
            else:
                ai_agent.system_log(f"[Browser] Auto-starting {browser_type} on port {debug_port}")
                launch_browser_with_debugging(
                    browser_type=browser_type,
                    port=debug_port,
                    url=f"http://localhost:{port}/"
                )

    # Menü setzen (after voice hotkey registration so it appears in menu)
    if icon:
        icon.menu = create_menu(icon)
        # Hotkeys registrieren
        register_hotkeys(icon)

    # HTTP Server starten (im Hintergrund)
    http_thread = threading.Thread(target=start_http_server, args=(port,), daemon=True)
    http_thread.start()

    # MCP Hub proxy (if claude_desktop.hub_enabled is true)
    try:
        from .services.mcp_proxy_manager import start_hub_if_enabled
        start_hub_if_enabled()
    except Exception as e:
        ai_agent.system_log(f"[Startup] MCP Hub start failed: {e}")

    # WebView window (optional, enabled by default)
    ui_config = config.get("ui", {})
    use_webview = ui_config.get("use_webview", True) and not args.no_webview

    # Log CLI mode flags
    if args.no_webview:
        ai_agent.system_log("[Config] WebView disabled via --no-webview")
    if args.no_tray:
        ai_agent.system_log("[Config] Headless mode via --no-tray")

    if use_webview and webview.is_available():
        import time
        time.sleep(0.5)  # Wait for HTTP server to be ready

        title = ui_config.get("title", config.get("name", "DeskAgent"))
        width = ui_config.get("webview_width", 450)
        height = ui_config.get("webview_height", 800)

        ai_agent.system_log(f"[WebView] Opening WebView window...")
        webview.create_window(port, title, width, height)
    elif use_webview and not webview.is_available():
        ai_agent.system_log("[WebView] pywebview not available. Install with: pip install pywebview")
        if should_open_browser(port):
            ai_agent.system_log(f"[Browser] Fallback: Opening browser at http://localhost:{port}/")
            import time
            import webbrowser
            time.sleep(0.5)
            webbrowser.open(f"http://localhost:{port}/")
            record_browser_opened(port)
        else:
            ai_agent.system_log("[Browser] Skipping browser open (tab likely already exists)")
    elif not use_webview:
        # WebView disabled - check user preferences for startup behavior
        user_prefs = _load_user_preferences()
        user_ui_prefs = user_prefs.get("ui", {})

        # Auto-open browser (user preference overrides system.json default)
        auto_open_browser = user_ui_prefs.get("auto_open_browser", ui_config.get("auto_open_browser", True))
        if auto_open_browser and should_open_browser(port):
            import time
            import webbrowser
            time.sleep(0.5)  # Wait for HTTP server to be ready
            url = f"http://localhost:{port}/"
            ai_agent.system_log(f"[Browser] Opening browser at {url}")
            webbrowser.open(url)
            record_browser_opened(port)
        elif auto_open_browser:
            ai_agent.system_log("[Browser] Skipping browser open (tab likely already exists)")

        # Auto-open Quick Access (user preference)
        auto_open_quick_access = user_ui_prefs.get("auto_open_quick_access", False)
        if auto_open_quick_access:
            from . import quickaccess
            if quickaccess.is_available():
                import time
                time.sleep(0.3)  # Additional delay after browser
                quickaccess_category = ui_config.get("quickaccess_category", "pinned")
                ai_agent.system_log(f"[Startup] Auto-opening Quick Access (category: {quickaccess_category})")
                quickaccess.create_window(port, category=quickaccess_category)
            else:
                ai_agent.system_log("[Startup] Quick Access auto-start skipped (pywebview not available)")

    ai_agent.system_log("[Startup] Running in background...")

    # Starten (with or without tray icon)
    if args.no_tray or HEADLESS_MODE or not icon:
        # Headless mode - just keep HTTP server running
        ai_agent.system_log("[Headless] Running without system tray (Ctrl+C to stop)")
        try:
            http_thread.join()
        except KeyboardInterrupt:
            ai_agent.system_log("[Shutdown] Interrupted by user")
            request_shutdown()
    else:
        icon.run()


def health_check() -> bool:
    """
    Run health check without starting GUI.
    Returns True if all checks pass.
    """
    print("\n[Health Check] Starting...")

    try:
        # 1. Load config
        config = load_config()
        print(f"[OK] Config loaded: {config.get('name', 'DeskAgent')}")

        # 2. Check MCP tools
        mcp_tools = discover_mcp_tools()
        tool_count = sum(len(tools) for tools in mcp_tools.values())
        print(f"[OK] MCP tools discovered: {tool_count} tools from {len(mcp_tools)} servers")

        # 3. Count skills from config
        skills = config.get("skills", {})
        enabled_skills = [k for k, v in skills.items() if v.get("enabled", True)]
        print(f"[OK] Skills configured: {len(enabled_skills)}")

        # 4. Count agents from config
        agents = config.get("agents", {})
        enabled_agents = [k for k, v in agents.items() if v.get("enabled", True)]
        print(f"[OK] Agents configured: {len(enabled_agents)}")

        # 5. Test AI agent factory
        from ai_agent import call_agent
        print(f"[OK] AI agent factory available")

        # 6. Test port binding
        port = find_free_port(8765)
        print(f"[OK] Port available: {port}")

        # 7. Check knowledge files
        knowledge_dir = get_knowledge_dir()
        if knowledge_dir.exists():
            knowledge_files = list(knowledge_dir.glob("*.md"))
            print(f"[OK] Knowledge files: {len(knowledge_files)} (from {knowledge_dir})")
        else:
            print(f"[WARN] Knowledge directory not found")

        # 8. Check agent markdown files
        agents_dir = get_agents_dir()
        if agents_dir.exists():
            agent_files = list(agents_dir.glob("*.md"))
            print(f"[OK] Agent files: {len(agent_files)} (from {agents_dir})")
        else:
            print(f"[WARN] Agents directory not found")

        # 9. Check skill markdown files
        skills_dir = get_skills_dir()
        if skills_dir.exists():
            skill_files = list(skills_dir.glob("*.md"))
            print(f"[OK] Skill files: {len(skill_files)} (from {skills_dir})")
        else:
            print(f"[WARN] Skills directory not found")

        # 10. Test anonymization (presidio + spacy)
        try:
            from ai_agent.anonymizer import anonymize, is_available
            if is_available():
                test_text, _ = anonymize("Test mit max@example.com", config.get("anonymization", {}))
                print(f"[OK] Anonymization working")
            else:
                print(f"[WARN] Anonymization: spacy model not loaded")
        except Exception as e:
            print(f"[WARN] Anonymization not available: {e}")

        # 11. Test HTTP server can be imported
        from .server import start_http_server
        print(f"[OK] HTTP server module available")

        # 12. Check templates exist
        templates_dir = DESKAGENT_DIR / "scripts" / "templates"
        if templates_dir.exists():
            webui = templates_dir / "webui.html"
            if webui.exists():
                print(f"[OK] WebUI template found")
            else:
                print(f"[WARN] WebUI template missing")
        else:
            print(f"[WARN] Templates directory not found")

        print("\n[Health Check] All checks passed!")
        return True

    except Exception as e:
        print(f"\n[Health Check] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


# Export main for direct execution
if __name__ == "__main__":
    main()
