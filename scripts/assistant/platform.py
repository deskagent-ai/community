# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Platform Abstraction Module
============================
Platform-specific implementations and detection for DeskAgent.
Handles differences between Windows, macOS, and Linux.
"""
import sys
import os

# Platform detection constants
IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')


def is_compiled() -> bool:
    """
    Check if running from Nuitka-compiled binary.

    Uses the robust detection from paths module which handles edge cases
    where Nuitka flags aren't set properly.
    """
    try:
        from paths import _is_compiled as paths_is_compiled
        return paths_is_compiled()
    except ImportError:
        # Fallback for edge cases where paths isn't available
        return getattr(sys, 'frozen', False) or '__compiled__' in dir()


def get_executable_dir() -> str:
    """Get the directory containing the executable or script."""
    if is_compiled():
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_python_executable() -> str:
    """
    Get path to Python interpreter for MCP subprocess spawning.

    In compiled mode, we use the bundled Python interpreter.
    In development mode, we use the current Python interpreter.
    """
    if is_compiled():
        app_dir = get_executable_dir()

        if IS_WINDOWS:
            # Use bundled python.exe for MCP servers (they need stdio)
            # pythonw.exe has no console and stdio doesn't work properly with MCP
            python_exe = os.path.join(app_dir, "python", "python.exe")
            if os.path.exists(python_exe):
                return python_exe
            # Fallback to pythonw.exe
            pythonw = os.path.join(app_dir, "python", "pythonw.exe")
            if os.path.exists(python_exe):
                return python_exe
        elif IS_MACOS:
            # macOS app bundle structure: Contents/MacOS/../Resources/python/venv/bin/python3
            python_exe = os.path.join(app_dir, "..", "Resources", "python", "venv", "bin", "python3")
            if os.path.exists(python_exe):
                return python_exe
        else:
            # Linux: bundled Python
            python_exe = os.path.join(app_dir, "python", "bin", "python3")
            if os.path.exists(python_exe):
                return python_exe

    # Fallback to current Python interpreter
    return sys.executable


def get_mcp_python_executable() -> str:
    """
    Get Python executable specifically for MCP servers.

    MCP servers communicate via stdio and REQUIRE python.exe (not pythonw.exe).
    pythonw.exe has no stdin/stdout handles which breaks MCP communication.
    """
    exe = get_python_executable()

    if IS_WINDOWS:
        # MCP servers need python.exe for stdio - pythonw.exe has no stdin/stdout
        # This is critical: pythonw.exe will cause "exit code 1" errors
        if exe.lower().endswith('pythonw.exe'):
            # Replace pythonw.exe with python.exe
            python_exe = exe[:-5] + '.exe'  # pythonw.exe -> python.exe
            if os.path.exists(python_exe):
                return python_exe

    return exe


def init_platform():
    """Initialize platform-specific features."""
    if IS_WINDOWS:
        _init_windows()
    elif IS_MACOS:
        _init_macos()
    else:
        _init_linux()


def _init_windows():
    """
    Windows-specific initialization.

    Features:
    - System tray icon (pystray)
    - Global hotkeys (keyboard)
    - COM automation (pywin32)
    - Windows-specific paths

    Note: First-run folder setup is done in assistant/__init__.py AFTER CLI args
    are parsed, so --workspace-dir and --shared-dir are respected.
    """
    # Set Windows-specific environment if needed
    if is_compiled():
        # Ensure bundled Python is in PATH for subprocess calls
        app_dir = get_executable_dir()
        python_dir = os.path.join(app_dir, "python")
        if os.path.exists(python_dir):
            current_path = os.environ.get('PATH', '')
            if python_dir not in current_path:
                os.environ['PATH'] = python_dir + os.pathsep + current_path


def _init_macos():
    """
    macOS-specific initialization.

    Features:
    - Menu bar app (future: rumps)
    - No global hotkeys (macOS restrictions)
    - macOS-specific paths

    Note: First-run folder setup is done in assistant/__init__.py AFTER CLI args
    are parsed, so --workspace-dir and --shared-dir are respected.
    """
    pass  # No macOS-specific init needed currently


def _init_linux():
    """
    Linux-specific initialization.

    Features:
    - Headless mode (no GUI)
    - Optional AppIndicator for desktop
    - Linux-specific paths

    Note: First-run folder setup is done in assistant/__init__.py AFTER CLI args
    are parsed, so --workspace-dir and --shared-dir are respected.
    """
    pass  # No Linux-specific init needed currently


def get_data_dir() -> str:
    """
    Get the application data directory.

    Returns platform-appropriate location:
    - Windows: %LOCALAPPDATA%/DeskAgent or app directory
    - macOS: ~/Library/Application Support/DeskAgent
    - Linux: ~/.local/share/deskagent
    """
    if is_compiled():
        # Compiled: use directory relative to executable
        return get_executable_dir()
    else:
        # Development: use current directory structure
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_config_dir() -> str:
    """
    Get the configuration directory.

    In compiled mode, config is in the app directory.
    In development mode, config is in the project root.
    """
    if is_compiled():
        return os.path.join(get_executable_dir(), "config")
    else:
        # Development: project root config
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(project_root, "config")


def supports_tray_icon() -> bool:
    """Check if the platform supports system tray icons."""
    if IS_WINDOWS:
        return True
    elif IS_MACOS:
        # macOS supports menu bar apps
        return True
    else:
        # Linux: depends on desktop environment
        # For now, assume headless
        return False


def supports_global_hotkeys() -> bool:
    """Check if the platform supports global hotkeys."""
    if IS_WINDOWS:
        return True
    elif IS_MACOS:
        # macOS has restrictions on global hotkeys
        return False
    else:
        # Linux: depends on X11/Wayland
        return False


def get_platform_info() -> dict:
    """Get information about the current platform."""
    return {
        "platform": sys.platform,
        "is_windows": IS_WINDOWS,
        "is_macos": IS_MACOS,
        "is_linux": IS_LINUX,
        "is_compiled": is_compiled(),
        "python_version": sys.version,
        "executable": sys.executable,
        "mcp_python": get_python_executable(),
    }
