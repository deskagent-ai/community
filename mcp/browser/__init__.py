# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


#!/usr/bin/env python3
"""
Browser MCP Server
==================
MCP Server für Browser-Automation mit Playwright.

Features:
- URLs öffnen (webbrowser)
- Formulare ausfüllen (Playwright)
- Elemente klicken
- Seiteninhalte lesen

Setup:
    pip install playwright
    playwright install chromium

Unterstützte Browser (alle Chromium-basiert mit CDP):
- Chrome, Edge, Vivaldi, Brave

WICHTIG: Firefox und Safari werden NICHT unterstützt (kein CDP).

Chrome v136+ Fix:
    Ab Chrome v136 ist --user-data-dir erforderlich für Remote-Debugging.
    Der browser_start() verwendet automatisch ein separates Profil.
"""

from pathlib import Path
from mcp.server.fastmcp import FastMCP
import webbrowser
import json
import subprocess
import os
import asyncio
import time
from typing import Optional

from _mcp_api import load_config, mcp_log

mcp = FastMCP("browser")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "language",
    "color": "#ff9800"
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Browser",
    "icon": "language",
    "color": "#ff9800",
    "config_key": None,  # Keine Config noetig
    "auth_type": "none",
}

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "browser_status",
    "browser_get_tabs",
    "browser_get_page_info",
    "browser_get_forms",
    "browser_get_text",
}

# Destructive tools that perform actions or modify state
DESTRUCTIVE_TOOLS = {
    "browser_start",
    "browser_connect",
    "browser_open_url",
    "browser_open_url_new_tab",
    "browser_open_url_new_window",
    "browser_switch_tab",
    "browser_fill_field",
    "browser_fill_form",
    "browser_click",
    "browser_click_text",
    "browser_select",
    "browser_type",
    "browser_press_key",
    "browser_navigate",
    "browser_wait",
    "browser_screenshot",
    "browser_crop_image",
    "browser_execute_js",
}


def is_configured() -> bool:
    """Prüft ob Browser-Automation verfügbar ist.

    Browser ist lokal verfügbar.
    Kann über browser.enabled deaktiviert werden.
    """
    config = load_config()
    mcp_config = config.get("browser", {})

    if mcp_config.get("enabled") is False:
        return False

    return True


# Bekannte Browser-Pfade (alle Chromium-basiert mit CDP-Support)
BROWSER_PATHS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\{user}\AppData\Local\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "vivaldi": [
        r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
        r"C:\Users\{user}\AppData\Local\Vivaldi\Application\vivaldi.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Users\{user}\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}

# Playwright wird lazy importiert (optional dependency)
_playwright = None
_browser = None
_page = None

# WICHTIG: Explizit IPv4 verwenden, nicht "localhost"!
# localhost kann zu IPv6 (::1) auflösen, was zu ECONNREFUSED führt
# Siehe: https://github.com/microsoft/playwright/issues/31459
CDP_URL = "http://127.0.0.1:9222"
CDP_PORT = 9222

_browser_process = None


def _find_browser(browser_type: str = "vivaldi") -> str:
    """Findet den Browser-Pfad."""
    username = os.environ.get("USERNAME", "")
    paths = BROWSER_PATHS.get(browser_type, [])

    for path in paths:
        resolved = path.replace("{user}", username)
        if os.path.exists(resolved):
            return resolved

    # Fallback: Im PATH suchen
    import shutil
    exe_name = f"{browser_type}.exe"
    found = shutil.which(exe_name)
    if found:
        return found

    return None


def _is_browser_running_with_debugging() -> bool:
    """Prüft ob ein Browser mit Remote-Debugging läuft.

    Verwendet explizit IPv4 (127.0.0.1), da localhost zu IPv6 auflösen kann.
    """
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)  # 1 Sekunde Timeout
    try:
        # Explizit IPv4 verwenden!
        result = sock.connect_ex(('127.0.0.1', CDP_PORT))
        return result == 0
    except socket.error:
        return False
    finally:
        sock.close()


async def _get_playwright():
    """Lazy import von Playwright (async).

    WICHTIG: Diese Funktion prüft ob die Playwright-Instanz noch gültig ist.
    Bei Verwendung mit asyncio.run() wird die Verbindung nach jedem Aufruf
    ungültig, da der Event Loop beendet wird.
    """
    global _playwright, _browser, _page
    if _playwright is not None:
        # Check if playwright is still valid (may be invalidated by asyncio.run())
        try:
            # Try to access internal state - will fail if connection closed
            if hasattr(_playwright, '_connection') and _playwright._connection is not None:
                # Connection exists, check if it's still alive
                if hasattr(_playwright._connection, '_transport'):
                    transport = _playwright._connection._transport
                    if transport is None or (hasattr(transport, 'is_closing') and transport.is_closing()):
                        _log("Playwright connection closed, recreating...")
                        _playwright = None
                        _browser = None
                        _page = None
            else:
                _log("Playwright connection invalid, recreating...")
                _playwright = None
                _browser = None
                _page = None
        except Exception as e:
            _log(f"Playwright validation failed ({e}), recreating...")
            _playwright = None
            _browser = None
            _page = None

    if _playwright is None:
        try:
            from playwright.async_api import async_playwright
            _playwright = await async_playwright().start()
        except ImportError:
            raise ImportError("Playwright nicht installiert. Run: pip install playwright && playwright install chromium")
    return _playwright


async def _connect_browser():
    """Verbindet mit laufendem Browser (Chrome/Vivaldi mit --remote-debugging-port=9222).

    WICHTIG: Diese Funktion verwendet explizit IPv4 (127.0.0.1) statt localhost,
    da localhost auf manchen Systemen zu IPv6 (::1) auflöst, was ECONNREFUSED verursacht.
    Siehe: https://github.com/microsoft/playwright/issues/31459

    Returns:
        Tuple von (browser, page) - page ist der zuletzt ausgewählte Tab
        oder der erste Tab wenn noch keiner ausgewählt wurde.
    """
    global _browser, _page, _playwright

    # Prüfe ob bestehende Verbindung noch gültig ist
    if _browser is not None and _page is not None:
        try:
            # Test if page is still responsive (Chrome v143+ may have stale pages)
            await _page.evaluate("1")  # Minimaler JS-Test statt title()
            return _browser, _page
        except Exception as e:
            # Page/Connection invalid - reset and reconnect
            _log(f"Cached connection invalid ({type(e).__name__}), reconnecting...")
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None
            _page = None
            # WICHTIG: Playwright-Instanz NICHT stoppen!

    # Neue Verbindung aufbauen
    pw = await _get_playwright()
    try:
        # Expliziter Timeout von 10 Sekunden für Verbindung
        _browser = await pw.chromium.connect_over_cdp(
            CDP_URL,
            timeout=10000  # 10 Sekunden
        )
        # Chrome v143+: Bei CDP sind existierende Pages oft stale/invalid.
        # Strategie: Neue Context+Page erstellen für saubere Verbindung.
        try:
            new_context = await _browser.new_context()
            _page = await new_context.new_page()
            _log(f"Created fresh context and page")
        except Exception as ctx_err:
            # Fallback: Versuche existierende Pages
            _log(f"new_context failed ({ctx_err}), trying existing pages...")
            _page = None
            for ctx in _browser.contexts:
                for pg in ctx.pages:
                    try:
                        _ = await pg.title()
                        _page = pg
                        _log(f"Found valid existing page: {pg.url}")
                        break
                    except Exception:
                        continue
                if _page:
                    break
            if not _page:
                raise Exception(f"No valid page available: {ctx_err}")

        _log(f"Connected to browser, page: {_page.url}")
        return _browser, _page
    except Exception as e:
        # Reset nur Browser-State, nicht Playwright
        _browser = None
        _page = None
        raise ConnectionError(
            f"Kann nicht mit Browser verbinden ({CDP_URL}). "
            f"Starte Chrome/Vivaldi mit: --remote-debugging-port=9222\n"
            f"Fehler: {e}"
        )


# ============================================================================
# URL Opening (webbrowser - kein Playwright nötig)
# ============================================================================

@mcp.tool()
def browser_open_url(url: str) -> str:
    """
    Öffnet eine URL im Standard-Browser.

    Args:
        url: Die zu öffnende URL (z.B. https://example.com)

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    try:
        if not url.startswith(('http://', 'https://', 'file://')):
            url = 'https://' + url
        webbrowser.open_new_tab(url)
        return f"OK: URL geöffnet: {url}"
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
def browser_open_url_new_tab(url: str) -> str:
    """Öffnet URL in neuem Tab."""
    return browser_open_url(url)


@mcp.tool()
def browser_open_url_new_window(url: str) -> str:
    """Öffnet URL in neuem Fenster."""
    try:
        if not url.startswith(('http://', 'https://', 'file://')):
            url = 'https://' + url
        webbrowser.open_new(url)
        return f"OK: URL in neuem Fenster geöffnet: {url}"
    except Exception as e:
        return f"Fehler: {str(e)}"


# ============================================================================
# Browser starten
# ============================================================================

def _log(msg: str):
    """Log to system.log via mcp_log."""
    mcp_log(f"[Browser] {msg}")


@mcp.tool()
def browser_start(browser_type: str = "chrome", url: Optional[str] = None) -> str:
    """
    Startet einen Browser mit Remote-Debugging-Unterstützung.

    Args:
        browser_type: Browser-Typ: "chrome", "edge", "vivaldi" oder "brave" (Standard: chrome)
        url: Optionale Start-URL

    Returns:
        Status und Verbindungsinfo.
    """
    global _browser_process

    _log(f"browser_start called: type={browser_type}, url={url}")

    # Prüfen ob bereits ein Browser mit Debugging läuft
    if _is_browser_running_with_debugging():
        _log(f"Browser already running on port {CDP_PORT}")
        return f"OK: Browser mit Remote-Debugging läuft bereits auf Port {CDP_PORT}"

    # Browser-Pfad finden
    browser_path = _find_browser(browser_type)
    if not browser_path:
        available = [b for b in BROWSER_PATHS.keys() if _find_browser(b)]
        _log(f"Browser {browser_type} not found. Available: {available}")
        return f"Fehler: {browser_type} nicht gefunden. Verfügbar: {', '.join(available) or 'keine'}"

    _log(f"Found browser at: {browser_path}")

    # Separates User-Data-Dir für Remote Debugging (Chrome v136+ erforderlich)
    import tempfile
    user_data_dir = os.path.join(tempfile.gettempdir(), "deskagent-browser")
    os.makedirs(user_data_dir, exist_ok=True)

    _log(f"Using user-data-dir: {user_data_dir}")

    # Browser starten mit allen erforderlichen Flags für Chrome v136+
    args = [
        browser_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={user_data_dir}",  # Separates Profil (Chrome v136+ erforderlich)
        "--remote-allow-origins=*",  # CDP-Verbindungen erlauben
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        args.append(url)

    _log(f"Starting browser with args: {' '.join(args[:3])}...")  # Log first 3 args

    try:
        _browser_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        _log(f"Browser process started, PID: {_browser_process.pid}")

        # Warten bis Browser bereit ist
        for i in range(50):  # max 5 Sekunden (Chrome v136 braucht länger)
            time.sleep(0.1)
            if _is_browser_running_with_debugging():
                _log(f"Browser ready after {(i+1)*0.1:.1f}s on port {CDP_PORT}")
                return f"OK: {browser_type} gestartet mit Remote-Debugging auf Port {CDP_PORT}"

        _log(f"Browser started but port {CDP_PORT} not responding after 5s")
        return f"Warnung: {browser_type} gestartet, aber Port {CDP_PORT} antwortet noch nicht. Profil: {user_data_dir}"

    except Exception as e:
        _log(f"Error starting browser: {e}")
        return f"Fehler beim Starten von {browser_type}: {str(e)}"


@mcp.tool()
async def browser_status() -> str:
    """
    Zeigt den Status der Browser-Verbindung.

    Returns:
        Ob ein Browser mit Remote-Debugging erreichbar ist.
    """
    if _is_browser_running_with_debugging():
        try:
            _, page = await _connect_browser()
            # Chrome v143+: page.title() kann fehlschlagen
            try:
                title = await page.title()
            except Exception:
                title = "(Titel nicht verfügbar)"
            return f"OK: Verbunden\nURL: {page.url}\nTitel: {title}"
        except Exception as e:
            return f"Browser läuft auf Port {CDP_PORT}, aber Verbindung fehlgeschlagen: {e}"
    else:
        return f"Kein Browser mit Remote-Debugging auf Port {CDP_PORT} erreichbar.\nStarte mit: browser_start()"


# ============================================================================
# Playwright-basierte Browser-Automation
# ============================================================================

@mcp.tool()
async def browser_connect() -> str:
    """
    Verbindet mit laufendem Browser (Chrome/Vivaldi).

    Der Browser muss mit Remote-Debugging gestartet sein:
        chrome.exe --remote-debugging-port=9222

    Returns:
        Verbindungsstatus und aktuelle URL.
    """
    try:
        _, page = await _connect_browser()
        url = page.url if page else "keine Seite"
        # Chrome v143+: page.title() kann fehlschlagen obwohl page existiert
        try:
            title = await page.title() if page else "kein Titel"
        except Exception:
            title = "(Titel nicht verfügbar)"
        return f"OK: Verbunden mit Browser\nURL: {url}\nTitel: {title}"
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
async def browser_get_tabs() -> str:
    """
    Listet alle offenen Browser-Tabs auf.

    Returns:
        Liste der Tabs mit Index, Titel und URL.
    """
    try:
        browser, _ = await _connect_browser()
        tabs = []
        for ctx_idx, context in enumerate(browser.contexts):
            for page_idx, page in enumerate(context.pages):
                title = await page.title()
                tabs.append({
                    "index": len(tabs),
                    "context": ctx_idx,
                    "page": page_idx,
                    "title": title,
                    "url": page.url
                })
        return json.dumps(tabs, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
async def browser_switch_tab(tab_index: int) -> str:
    """
    Wechselt zum Tab mit dem angegebenen Index.

    Args:
        tab_index: Tab-Index aus browser_get_tabs()

    Returns:
        Neuer aktiver Tab.
    """
    global _page
    try:
        browser, _ = await _connect_browser()
        current_idx = 0
        for context in browser.contexts:
            for page in context.pages:
                if current_idx == tab_index:
                    _page = page
                    await page.bring_to_front()
                    title = await page.title()
                    return f"OK: Gewechselt zu Tab {tab_index}\nURL: {page.url}\nTitel: {title}"
                current_idx += 1
        return f"Fehler: Tab {tab_index} nicht gefunden (max: {current_idx - 1})"
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
async def browser_get_page_info() -> str:
    """
    Gibt Informationen zur aktuellen Seite zurück.

    Returns:
        URL, Titel und sichtbarer Text der Seite.
    """
    try:
        _, page = await _connect_browser()
        title = await page.title()
        info = {
            "url": page.url,
            "title": title,
        }
        return json.dumps(info, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
async def browser_get_forms() -> str:
    """
    Findet alle Formulare und deren Felder auf der aktuellen Seite.

    Returns:
        Liste der Formulare mit ihren Input-Feldern.
    """
    try:
        _, page = await _connect_browser()

        forms = await page.evaluate("""() => {
            const forms = [];

            // Alle form-Elemente
            document.querySelectorAll('form').forEach((form, formIdx) => {
                const fields = [];
                form.querySelectorAll('input, select, textarea').forEach(el => {
                    if (el.type !== 'hidden') {
                        fields.push({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || 'text',
                            name: el.name || null,
                            id: el.id || null,
                            placeholder: el.placeholder || null,
                            label: el.labels?.[0]?.textContent?.trim() || null,
                            value: el.value || '',
                            selector: el.id ? '#' + el.id : (el.name ? `[name="${el.name}"]` : null)
                        });
                    }
                });
                forms.push({
                    index: formIdx,
                    id: form.id || null,
                    action: form.action || null,
                    fields: fields
                });
            });

            // Auch inputs außerhalb von forms finden
            const standaloneFields = [];
            document.querySelectorAll('input:not(form input), select:not(form select), textarea:not(form textarea)').forEach(el => {
                if (el.type !== 'hidden') {
                    standaloneFields.push({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || 'text',
                        name: el.name || null,
                        id: el.id || null,
                        placeholder: el.placeholder || null,
                        label: el.labels?.[0]?.textContent?.trim() || null,
                        value: el.value || '',
                        selector: el.id ? '#' + el.id : (el.name ? `[name="${el.name}"]` : null)
                    });
                }
            });

            if (standaloneFields.length > 0) {
                forms.push({
                    index: -1,
                    id: 'standalone',
                    action: null,
                    fields: standaloneFields
                });
            }

            return forms;
        }""")

        return json.dumps(forms, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
async def browser_fill_field(selector: str, value: str) -> str:
    """
    Füllt ein einzelnes Formularfeld aus.

    Args:
        selector: CSS-Selector (z.B. '#username', '[name="email"]', '.input-field')
        value: Der einzutragende Wert

    Returns:
        Erfolgsmeldung.
    """
    try:
        _, page = await _connect_browser()
        await page.fill(selector, value)
        return f"OK: Feld '{selector}' ausgefüllt mit: {value}"
    except Exception as e:
        return f"Fehler beim Ausfüllen von '{selector}': {str(e)}"


@mcp.tool()
async def browser_fill_form(fields: str) -> str:
    """
    Füllt mehrere Formularfelder auf einmal aus.

    Args:
        fields: JSON-String mit Selector-Value-Paaren, z.B.:
                {"#name": "Max Mustermann", "[name='iban']": "DE123...", "#betrag": "100.00"}

    Returns:
        Zusammenfassung der ausgefüllten Felder.
    """
    try:
        _, page = await _connect_browser()
        field_dict = json.loads(fields)

        results = []
        for selector, value in field_dict.items():
            try:
                await page.fill(selector, str(value))
                results.append(f"✓ {selector}: {value}")
            except Exception as e:
                results.append(f"✗ {selector}: {str(e)}")

        return "Formular ausgefüllt:\n" + "\n".join(results)
    except json.JSONDecodeError:
        return "Fehler: 'fields' muss gültiges JSON sein, z.B.: {\"#name\": \"Wert\"}"
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
async def browser_click(selector: str) -> str:
    """
    Klickt auf ein Element.

    Args:
        selector: CSS-Selector des Elements (z.B. '#submit', 'button[type="submit"]')

    Returns:
        Erfolgsmeldung.
    """
    try:
        _, page = await _connect_browser()
        await page.click(selector)
        return f"OK: Klick auf '{selector}'"
    except Exception as e:
        return f"Fehler beim Klicken auf '{selector}': {str(e)}"


@mcp.tool()
async def browser_click_text(text: str) -> str:
    """
    Klickt auf ein Element anhand seines Textes.

    Args:
        text: Sichtbarer Text des Elements (z.B. 'Absenden', 'Weiter')

    Returns:
        Erfolgsmeldung.
    """
    try:
        _, page = await _connect_browser()
        await page.click(f"text={text}")
        return f"OK: Klick auf Element mit Text '{text}'"
    except Exception as e:
        return f"Fehler beim Klicken auf '{text}': {str(e)}"


@mcp.tool()
async def browser_select(selector: str, value: str) -> str:
    """
    Wählt eine Option in einem Dropdown/Select-Feld.

    Args:
        selector: CSS-Selector des Select-Elements
        value: Der zu wählende Wert (value-Attribut oder sichtbarer Text)

    Returns:
        Erfolgsmeldung.
    """
    try:
        _, page = await _connect_browser()
        # Versuche erst nach value, dann nach label
        try:
            await page.select_option(selector, value=value)
        except (ValueError, TimeoutError):
            await page.select_option(selector, label=value)
        return f"OK: '{value}' ausgewählt in '{selector}'"
    except Exception as e:
        return f"Fehler bei Select '{selector}': {str(e)}"


@mcp.tool()
async def browser_type(selector: str, text: str, delay: int = 50) -> str:
    """
    Tippt Text zeichenweise in ein Feld (simuliert echtes Tippen).

    Args:
        selector: CSS-Selector des Elements
        text: Der zu tippende Text
        delay: Verzögerung zwischen Tasten in ms (Standard: 50)

    Returns:
        Erfolgsmeldung.
    """
    try:
        _, page = await _connect_browser()
        await page.type(selector, text, delay=delay)
        return f"OK: Text getippt in '{selector}'"
    except Exception as e:
        return f"Fehler beim Tippen in '{selector}': {str(e)}"


@mcp.tool()
async def browser_press_key(key: str) -> str:
    """
    Drückt eine Taste (z.B. Enter, Tab, Escape).

    Args:
        key: Taste (z.B. 'Enter', 'Tab', 'Escape', 'ArrowDown')

    Returns:
        Erfolgsmeldung.
    """
    try:
        _, page = await _connect_browser()
        await page.keyboard.press(key)
        return f"OK: Taste '{key}' gedrückt"
    except Exception as e:
        return f"Fehler bei Taste '{key}': {str(e)}"


@mcp.tool()
async def browser_wait(selector: str, timeout: int = 5000) -> str:
    """
    Wartet bis ein Element sichtbar ist.

    Args:
        selector: CSS-Selector des Elements
        timeout: Max. Wartezeit in ms (Standard: 5000)

    Returns:
        Erfolgsmeldung wenn gefunden.
    """
    try:
        _, page = await _connect_browser()
        await page.wait_for_selector(selector, timeout=timeout)
        return f"OK: Element '{selector}' gefunden"
    except Exception:
        return f"Timeout: Element '{selector}' nicht gefunden nach {timeout}ms"


@mcp.tool()
async def browser_screenshot(path: Optional[str] = None) -> str:
    """
    Macht einen Screenshot der aktuellen Seite.

    Args:
        path: Optionaler Dateipfad (Standard: screenshot.png im aktuellen Verzeichnis)

    Returns:
        Pfad zum Screenshot.
    """
    try:
        _, page = await _connect_browser()
        if path is None:
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "browser_screenshot.png")
        await page.screenshot(path=path)
        return f"OK: Screenshot gespeichert: {path}"
    except Exception as e:
        return f"Fehler beim Screenshot: {str(e)}"


@mcp.tool()
def browser_crop_image(
    source: str,
    output: str,
    region: str
) -> str:
    """
    Schneidet einen Bereich aus einem Bild aus.

    Nützlich um nur relevante Bereiche aus Screenshots zu extrahieren.

    Args:
        source: Pfad zum Quellbild
        output: Pfad für das beschnittene Bild
        region: Bereich als "left,top,right,bottom" (Pixel) oder
                "bottom:150" für die unteren 150 Pixel,
                "top:100" für die oberen 100 Pixel

    Returns:
        Erfolgs- oder Fehlermeldung.

    Beispiele:
        browser_crop_image("screenshot.png", "cropped.png", "0,500,800,600")
        browser_crop_image("screenshot.png", "bottom.png", "bottom:150")
    """
    try:
        from PIL import Image

        img = Image.open(source)
        w, h = img.size

        # Spezielle Syntax für einfache Fälle
        if region.startswith("bottom:"):
            pixels = int(region.split(":")[1])
            box = (0, h - pixels, w, h)
        elif region.startswith("top:"):
            pixels = int(region.split(":")[1])
            box = (0, 0, w, pixels)
        elif region.startswith("left:"):
            pixels = int(region.split(":")[1])
            box = (0, 0, pixels, h)
        elif region.startswith("right:"):
            pixels = int(region.split(":")[1])
            box = (w - pixels, 0, w, h)
        else:
            # Standard: left,top,right,bottom
            parts = [int(x.strip()) for x in region.split(",")]
            if len(parts) != 4:
                return "Fehler: region muss 4 Werte haben (left,top,right,bottom)"
            box = tuple(parts)

        cropped = img.crop(box)
        cropped.save(output)

        return f"OK: Bild beschnitten: {source} → {output} (Region: {box}, Größe: {cropped.size})"
    except FileNotFoundError:
        return f"Fehler: Datei nicht gefunden: {source}"
    except Exception as e:
        return f"Fehler beim Beschneiden: {str(e)}"


@mcp.tool()
async def browser_navigate(url: str) -> str:
    """
    Navigiert zu einer URL im verbundenen Browser.

    Args:
        url: Ziel-URL

    Returns:
        Neue URL und Titel.
    """
    try:
        _, page = await _connect_browser()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        await page.goto(url)
        title = await page.title()
        return f"OK: Navigiert zu {url}\nTitel: {title}"
    except Exception as e:
        return f"Fehler bei Navigation: {str(e)}"


@mcp.tool()
async def browser_get_text(selector: str) -> str:
    """
    Liest den Text eines Elements.

    Args:
        selector: CSS-Selector des Elements

    Returns:
        Textinhalt des Elements.
    """
    try:
        _, page = await _connect_browser()
        text = await page.text_content(selector)
        return text or "(kein Text)"
    except Exception as e:
        return f"Fehler beim Lesen von '{selector}': {str(e)}"


@mcp.tool()
async def browser_execute_js(script: str) -> str:
    """
    Führt JavaScript im Browser-Kontext aus.

    Args:
        script: JavaScript-Code (z.B. "document.title" oder "return 1+1")

    Returns:
        Rückgabewert des Scripts als JSON.
    """
    try:
        _, page = await _connect_browser()
        result = await page.evaluate(script)
        return json.dumps(result, indent=2, ensure_ascii=False) if result else "OK (kein Rückgabewert)"
    except Exception as e:
        return f"JS-Fehler: {str(e)}"


if __name__ == "__main__":
    mcp.run()
