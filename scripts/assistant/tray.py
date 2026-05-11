# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
System tray icon and hotkey registration for DeskAgent.
"""

import sys
import threading

# Import system_log for background logging
try:
    from ai_agent.base import system_log
except ImportError:
    def system_log(msg): pass  # Fallback if not available

try:
    import pystray
    from PIL import Image
except ImportError:
    pystray = None
    Image = None

try:
    import keyboard
except ImportError:
    keyboard = None

from .skills import load_skill, load_config, process_skill
from ai_agent import log
from .agents import load_agent, process_agent
from . import webview
from . import quickaccess
from .state import get_active_port

# Voice hotkey imports (optional)
try:
    from .voice_hotkey import (
        is_voice_enabled, get_voice_hotkeys,
        disable_voice_hotkey, enable_voice_hotkey
    )
    _voice_available = True
except ImportError:
    _voice_available = False

# Path is set up by assistant/__init__.py
from paths import PROJECT_DIR, DESKAGENT_DIR, get_skills_dir, get_agents_dir


def load_icon_image():
    """Lädt Icon aus Datei oder erstellt Fallback."""
    # Suche zuerst in deskagent/, dann im Projektordner
    icon_path = DESKAGENT_DIR / "icon.ico"
    if not icon_path.exists():
        icon_path = DESKAGENT_DIR / "icon.png"
    if not icon_path.exists():
        icon_path = PROJECT_DIR / "icon.ico"
    if not icon_path.exists():
        icon_path = PROJECT_DIR / "icon.png"

    if icon_path.exists():
        try:
            return Image.open(icon_path)
        except Exception as e:
            system_log(f"[Tray] Icon konnte nicht geladen werden: {e}")

    # Fallback: Einfaches blaues Icon
    size = 64
    image = Image.new('RGB', (size, size), color=(41, 128, 185))
    return image


def make_skill_action(skill_name, hints, icon_ref):
    """Erstellt eine Action-Funktion für einen Skill."""
    def action(icon, item):
        threading.Thread(
            target=process_skill, args=(skill_name, hints, icon_ref)
        ).start()
    return action


def make_agent_action(agent_name, icon_ref):
    """Erstellt eine Action-Funktion für einen Agent."""
    def action(icon, item):
        threading.Thread(
            target=process_agent, args=(agent_name, icon_ref)
        ).start()
    return action


def open_webview_window(icon, item):
    """Opens the WebView window."""
    config = load_config()
    port = get_active_port()  # Use actual running port
    ui_config = config.get("ui", {})
    title = ui_config.get("title", config.get("name", "DeskAgent"))
    width = ui_config.get("webview_width", 900)
    height = ui_config.get("webview_height", 1000)

    if webview.is_available():
        webview.create_window(port, title, width, height)
    else:
        # Fallback: open in browser
        import webbrowser
        webbrowser.open(f"http://localhost:{port}/")


def open_quickaccess_window(icon, item):
    """Opens the Quick Access overlay window."""
    config = load_config()
    port = get_active_port()
    ui_config = config.get("ui", {})
    category = ui_config.get("quickaccess_category", "pinned")

    if quickaccess.is_available():
        quickaccess.create_window(port, category=category)
    else:
        # Fallback: open in browser with category filter
        import webbrowser
        webbrowser.open(f"http://localhost:{port}/?category={category}")


def open_in_browser(icon, item):
    """Opens the web UI in the default browser."""
    import webbrowser
    port = get_active_port()
    webbrowser.open(f"http://localhost:{port}/")


def _create_voice_menu():
    """Create the Voice Input submenu showing available hotkeys."""
    if not _voice_available or not is_voice_enabled():
        return None

    hotkeys = get_voice_hotkeys()
    if not hotkeys:
        return None

    voice_items = []

    # Show configured hotkeys (info only, not clickable actions)
    if 'dictate' in hotkeys:
        voice_items.append(pystray.MenuItem(
            f"Dictate: {hotkeys['dictate']}",
            lambda icon, item: None,  # No action, just info
            enabled=False
        ))

    if 'dictate_enter' in hotkeys:
        voice_items.append(pystray.MenuItem(
            f"Dictate + Enter: {hotkeys['dictate_enter']}",
            lambda icon, item: None,
            enabled=False
        ))

    # Agent hotkeys (multiple possible)
    if 'agents' in hotkeys:
        for agent_name, hotkey in hotkeys['agents'].items():
            voice_items.append(pystray.MenuItem(
                f"Agent ({agent_name}): {hotkey}",
                lambda icon, item: None,
                enabled=False
            ))

    if voice_items:
        voice_items.append(pystray.Menu.SEPARATOR)
        voice_items.append(pystray.MenuItem(
            "Disable Hotkeys",
            lambda icon, item: disable_voice_hotkey()
        ))

    return pystray.Menu(*voice_items) if voice_items else None


def create_menu(icon):
    """Erstellt das Kontextmenü mit Skills und Agents."""
    menu_items = []

    # Quick Access window (resizable - can be used as compact or full view)
    menu_items.append(pystray.MenuItem("Open Quick Access", open_quickaccess_window))
    menu_items.append(pystray.MenuItem("Open in Browser", open_in_browser))
    menu_items.append(pystray.Menu.SEPARATOR)

    # Voice Input submenu (if available)
    if _voice_available and is_voice_enabled():
        voice_menu = _create_voice_menu()
        if voice_menu:
            menu_items.append(pystray.MenuItem("🎤 Voice Input", voice_menu))
            menu_items.append(pystray.Menu.SEPARATOR)

    # Skills Submenu - alle aus skills/ Ordner (User-Space oder Demo)
    skills_dir = get_skills_dir()
    if skills_dir.exists():
        skill_items = []
        for skill_file in sorted(skills_dir.glob("*.md")):
            skill_name = skill_file.stem
            skill = load_skill(skill_name)
            display_name = skill["name"] if skill else skill_name
            skill_items.append(
                pystray.MenuItem(
                    display_name,
                    make_skill_action(skill_name, "", icon)
                )
            )
        if skill_items:
            menu_items.append(
                pystray.MenuItem("Skills", pystray.Menu(*skill_items))
            )

    # Agents Submenu - alle aus agents/ Ordner (User-Space oder Demo)
    agents_dir = get_agents_dir()
    if agents_dir.exists():
        agent_items = []
        for agent_file in sorted(agents_dir.glob("*.md")):
            agent_name = agent_file.stem
            agent = load_agent(agent_name)
            display_name = agent["name"] if agent else agent_name
            agent_items.append(
                pystray.MenuItem(
                    display_name,
                    make_agent_action(agent_name, icon)
                )
            )
        if agent_items:
            menu_items.append(
                pystray.MenuItem("Agents", pystray.Menu(*agent_items))
            )

    menu_items.append(pystray.Menu.SEPARATOR)
    menu_items.append(pystray.MenuItem("Beenden", lambda icon, item: icon.stop()))

    return pystray.Menu(*menu_items)


def process_skill_with_copy(skill_name: str, hints: str = "", icon=None):
    """Führt Skill mit Clipboard-Inhalt aus."""
    process_skill(skill_name, hints, icon)


def register_hotkeys(icon):
    """Registriert Hotkeys aus config.json."""
    if not keyboard:
        return

    config = load_config()

    # Skill Hotkeys (from embedded hotkey property)
    skills_config = config.get("skills", {})
    skill_hotkeys = [(name, cfg) for name, cfg in skills_config.items() if cfg.get("hotkey")]
    if skill_hotkeys:
        log("\nSkill Hotkeys:")
        for skill_name, cfg in skill_hotkeys:
            key = cfg.get("hotkey", "")
            hints = cfg.get("hints", "")
            skill = load_skill(skill_name)
            display_name = skill["name"] if skill else skill_name
            key_display = key.upper()
            log(f"  {key_display:20} {display_name}")

            keyboard.add_hotkey(
                key,
                lambda s=skill_name, h=hints: threading.Thread(
                    target=process_skill_with_copy, args=(s, h, icon)
                ).start()
            )

    # Agent Hotkeys (from embedded hotkey property)
    agents_config = config.get("agents", {})
    agent_hotkeys = [(name, cfg) for name, cfg in agents_config.items() if cfg.get("hotkey")]
    if agent_hotkeys:
        log("\nAgent Hotkeys:")
        for agent_name, cfg in agent_hotkeys:
            key = cfg.get("hotkey", "")
            agent = load_agent(agent_name)
            display_name = agent["name"] if agent else agent_name
            key_display = key.upper()
            log(f"  {key_display:20} {display_name} (MCP)")

            keyboard.add_hotkey(
                key,
                lambda a=agent_name: threading.Thread(
                    target=process_agent, args=(a, icon)
                ).start()
            )

    # WebView window hotkey (toggle: open/close)
    ui_config = config.get("ui", {})
    webview_hotkey = ui_config.get("webview_hotkey", "alt+space")
    if webview_hotkey:
        log("\nUI Hotkeys:")
        key_display = webview_hotkey.upper()
        log(f"  {key_display:20} Toggle Window")

        def toggle_webview():
            port = get_active_port()  # Use actual running port
            title = ui_config.get("title", config.get("name", "DeskAgent"))
            width = ui_config.get("webview_width", 900)
            height = ui_config.get("webview_height", 1000)
            if webview.is_available():
                webview.toggle_window(port, title, width, height)
            else:
                import webbrowser
                webbrowser.open(f"http://localhost:{port}/")

        keyboard.add_hotkey(webview_hotkey, toggle_webview)

    # Quick Access window hotkey (toggle: open/close)
    quickaccess_hotkey = ui_config.get("quickaccess_hotkey", "alt+q")
    if quickaccess_hotkey:
        key_display = quickaccess_hotkey.upper()
        log(f"  {key_display:20} Quick Access")
        quickaccess_category = ui_config.get("quickaccess_category", "pinned")

        def toggle_quickaccess():
            port = get_active_port()
            if quickaccess.is_available():
                quickaccess.toggle_window(port, category=quickaccess_category)
            else:
                import webbrowser
                webbrowser.open(f"http://localhost:{port}/?category={quickaccess_category}")

        keyboard.add_hotkey(quickaccess_hotkey, toggle_quickaccess)
