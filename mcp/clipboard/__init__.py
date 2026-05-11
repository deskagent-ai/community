#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Clipboard MCP Server
====================
MCP Server für Clipboard-Zugriff unter Windows.
Ermöglicht das Lesen und Schreiben der Zwischenablage.
"""

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Windows clipboard imports
import win32clipboard
import win32con

from _mcp_api import load_config

mcp = FastMCP("clipboard")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "content_paste",
    "color": "#9c27b0"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Zwischenablage",
    "icon": "content_paste",
    "color": "#9c27b0",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

# Tools that return external/untrusted content (prompt injection risk)
# These will be wrapped with sanitization by the anonymization proxy
HIGH_RISK_TOOLS = {
    "clipboard_get_clipboard",
}

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "clipboard_get_clipboard",
}

# Destructive tools that modify clipboard state
DESTRUCTIVE_TOOLS = {
    "clipboard_set_clipboard",
    "clipboard_append_clipboard",
    "clipboard_paste_clipboard",
}


def is_configured() -> bool:
    """Prüft ob Clipboard verfügbar ist.

    Clipboard ist ein lokaler Windows-Dienst.
    Kann über clipboard.enabled deaktiviert werden.
    """
    config = load_config()
    mcp_config = config.get("clipboard", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


@mcp.tool()
def clipboard_get_clipboard() -> str:
    """
    Liest den aktuellen Text aus der Zwischenablage.

    Returns:
        Der Text aus der Zwischenablage oder eine Fehlermeldung.
    """
    try:
        win32clipboard.OpenClipboard()
        try:
            # Try to get Unicode text first
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return data
            # Fallback to ANSI text
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                return data.decode('utf-8', errors='replace')
            else:
                return "Fehler: Kein Text in der Zwischenablage"
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return f"Fehler beim Lesen der Zwischenablage: {str(e)}"


@mcp.tool()
def clipboard_set_clipboard(text: str) -> str:
    """
    Schreibt Text in die Zwischenablage.

    Args:
        text: Der Text, der in die Zwischenablage geschrieben werden soll.

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            return f"OK: {len(text)} Zeichen in Zwischenablage geschrieben"
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        return f"Fehler beim Schreiben in die Zwischenablage: {str(e)}"


@mcp.tool()
def clipboard_append_clipboard(text: str) -> str:
    """
    Fügt Text an den bestehenden Inhalt der Zwischenablage an.

    Args:
        text: Der Text, der angehängt werden soll.

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    try:
        # Read current content
        current = clipboard_get_clipboard()
        if current.startswith("Fehler:"):
            current = ""

        # Append and write back
        new_content = current + text
        return clipboard_set_clipboard(new_content)
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
def clipboard_paste_clipboard() -> str:
    """
    Fügt den Inhalt der Zwischenablage in die aktive Anwendung ein (Ctrl+V).

    Simuliert Ctrl+V um den Text dort einzufügen, wo der Cursor gerade ist.
    Nützlich nach set_clipboard() um Text direkt in eine Anwendung einzufügen.

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    import time

    try:
        # Try pynput first (more reliable)
        try:
            from pynput.keyboard import Key, Controller
            kb = Controller()
            time.sleep(0.1)  # Small delay to ensure focus
            with kb.pressed(Key.ctrl):
                kb.press('v')
                kb.release('v')
            time.sleep(0.1)  # Wait for paste to complete
            return "OK: Ctrl+V gesendet - Text eingefügt"
        except ImportError:
            pass

        # Fallback to win32api
        import win32api
        import win32con
        time.sleep(0.1)
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord('V'), 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)
        return "OK: Ctrl+V gesendet - Text eingefügt"

    except Exception as e:
        return f"Fehler beim Einfügen: {str(e)}"


if __name__ == "__main__":
    mcp.run()
