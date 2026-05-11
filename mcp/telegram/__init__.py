#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Telegram MCP Server
===================
MCP Server für Telegram Bot API.
Ermöglicht das Senden und Empfangen von Nachrichten über Telegram.

Features:
- Nachrichten senden (Text, Dokumente, Fotos)
- Chats auflisten und verwalten
- Neue Nachrichten abrufen
- Inline-Keyboards für interaktive Buttons
- Markdown-Formatierung
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, mcp_log

mcp = FastMCP("telegram")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "send",  # Material Design Icon
    "color": "#0088cc",  # Telegram blue
    "beta": True
}

# Integration schema for dynamic UI configuration
INTEGRATION_SCHEMA = {
    "name": "Telegram",
    "icon": "send",
    "color": "#0088cc",
    "config_key": "telegram",
    "auth_type": "api_key",
    "beta": True,  # Mark as beta feature
    "description": "Telegram Bot API fuer Nachrichten und Benachrichtigungen.",
    "fields": [
        {
            "key": "bot_token",
            "label": "Bot Token",
            "type": "password",
            "required": True,
            "hint": "Von @BotFather erhalten (Format: 123456789:ABC...)"
        },
        {
            "key": "bot_name",
            "label": "Bot Name",
            "type": "text",
            "required": False,
            "hint": "Anzeigename des Bots (z.B. 'MeinBot')"
        },
        {
            "key": "default_chat_id",
            "label": "Standard Chat-ID",
            "type": "text",
            "required": False,
            "hint": "Chat-ID für Standard-Nachrichten"
        },
        {
            "key": "allowed_chat_ids",
            "label": "Erlaubte Chat-IDs",
            "type": "text",
            "required": False,
            "hint": "Komma-getrennte Liste (leer = alle erlaubt)"
        },
    ],
    "test_tool": "telegram_test_connection",
    "docs_url": "https://core.telegram.org/bots#how-do-i-create-a-bot",
    "setup": {
        "description": "Telegram Bot Nachrichten",
        "requirement": "Telegram Bot Token",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Telegram Bot-Token eintragen",
        ],
    },
}

# Tools that return external/untrusted content (prompt injection risk)
HIGH_RISK_TOOLS = {
    "telegram_get_updates",
    "telegram_get_messages",
    "telegram_get_chat_info",
}

# Tools that modify data (for Dry-Run mode)
DESTRUCTIVE_TOOLS = {
    "telegram_send_message",
    "telegram_send_document",
    "telegram_send_photo",
    "telegram_delete_message",
}


def is_configured() -> bool:
    """Prüft ob Telegram MCP konfiguriert ist.

    Returns:
        True wenn Bot Token vorhanden, sonst False.
    """
    config = load_config()
    telegram_config = config.get("telegram", {})

    # Explizit deaktiviert?
    if telegram_config.get("enabled") is False:
        return False

    # Bot Token erforderlich
    bot_token = telegram_config.get("bot_token")
    return bool(bot_token)


def _get_bot_token() -> str:
    """Gibt den Bot Token aus der Konfiguration zurück."""
    config = load_config()
    return config.get("telegram", {}).get("bot_token", "")


def _get_allowed_chat_ids() -> list:
    """Gibt die Liste erlaubter Chat-IDs zurück (leer = alle erlaubt)."""
    config = load_config()
    return config.get("telegram", {}).get("allowed_chat_ids", [])


def _is_chat_allowed(chat_id: str) -> bool:
    """Prüft ob eine Chat-ID autorisiert ist.

    Returns:
        True wenn erlaubt oder keine Einschränkung konfiguriert.
    """
    allowed = _get_allowed_chat_ids()
    if not allowed:
        return True  # Keine Einschränkung
    return str(chat_id) in [str(cid) for cid in allowed]


def _api_request(method: str, params: dict = None, files: dict = None) -> dict:
    """
    Sendet Request an Telegram Bot API.

    Args:
        method: API-Methode (z.B. 'sendMessage')
        params: Parameter als Dict
        files: Dateien für Multipart-Upload (optional)

    Returns:
        API-Response als Dict
    """
    bot_token = _get_bot_token()
    if not bot_token:
        return {"ok": False, "error": "Kein Bot Token konfiguriert"}

    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    try:
        if files:
            # Multipart upload for files
            import mimetypes
            from io import BytesIO

            boundary = '----WebKitFormBoundary' + ''.join([str(i) for i in range(16)])
            body = BytesIO()

            # Add regular params
            if params:
                for key, value in params.items():
                    body.write(f'--{boundary}\r\n'.encode())
                    body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                    body.write(f'{value}\r\n'.encode())

            # Add files
            for field_name, file_path in files.items():
                file_path = Path(file_path)
                if not file_path.exists():
                    return {"ok": False, "error": f"Datei nicht gefunden: {file_path}"}

                mime_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
                body.write(f'--{boundary}\r\n'.encode())
                body.write(f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"\r\n'.encode())
                body.write(f'Content-Type: {mime_type}\r\n\r\n'.encode())
                body.write(file_path.read_bytes())
                body.write(b'\r\n')

            body.write(f'--{boundary}--\r\n'.encode())

            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}'
            }

            req = urllib.request.Request(url, data=body.getvalue(), headers=headers)

        else:
            # Regular JSON request
            if params:
                data = json.dumps(params).encode('utf-8')
                headers = {'Content-Type': 'application/json'}
            else:
                data = None
                headers = {}

            req = urllib.request.Request(url, data=data, headers=headers)

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        mcp_log(f"[Telegram] HTTP {e.code}: {error_body}")
        return {"ok": False, "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        mcp_log(f"[Telegram] Error: {str(e)}")
        return {"ok": False, "error": str(e)}


@mcp.tool()
def telegram_test_connection() -> str:
    """
    Testet die Telegram Bot API Verbindung.

    Returns:
        Bot-Informationen oder Fehlermeldung.
    """
    result = _api_request("getMe")

    if result.get("ok"):
        bot = result.get("result", {})
        return f"OK: Bot '{bot.get('first_name')}' (@{bot.get('username')}) ist verbunden"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_send_message(
    chat_id: str,
    text: str,
    parse_mode: str = "Markdown",
    disable_notification: bool = False,
    reply_to_message_id: str = ""
) -> str:
    """
    Sendet eine Textnachricht an einen Telegram-Chat.

    Args:
        chat_id: Chat-ID oder Username (@channel_name)
        text: Nachrichtentext (max. 4096 Zeichen)
        parse_mode: Formatierung - "Markdown", "MarkdownV2" oder "HTML" (Standard: Markdown)
        disable_notification: Stumme Benachrichtigung (Standard: False)
        reply_to_message_id: Antwortet auf diese Nachricht (optional)

    Returns:
        Erfolgsmeldung mit Message-ID oder Fehlermeldung.
    """
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_notification": disable_notification
    }

    if reply_to_message_id:
        params["reply_to_message_id"] = reply_to_message_id

    result = _api_request("sendMessage", params)

    if result.get("ok"):
        msg = result.get("result", {})
        msg_id = msg.get("message_id")
        chat_title = msg.get("chat", {}).get("title") or msg.get("chat", {}).get("username") or chat_id
        return f"OK: Nachricht #{msg_id} gesendet an '{chat_title}'"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_send_document(
    chat_id: str,
    file_path: str,
    caption: str = "",
    parse_mode: str = "Markdown",
    disable_notification: bool = False
) -> str:
    """
    Sendet ein Dokument (PDF, DOCX, ZIP, etc.) an einen Telegram-Chat.

    Args:
        chat_id: Chat-ID oder Username (@channel_name)
        file_path: Pfad zur Datei (absolut oder relativ zum Workspace)
        caption: Bildunterschrift (optional, max. 1024 Zeichen)
        parse_mode: Formatierung - "Markdown", "MarkdownV2" oder "HTML" (Standard: Markdown)
        disable_notification: Stumme Benachrichtigung (Standard: False)

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    params = {
        "chat_id": chat_id,
        "disable_notification": str(disable_notification).lower()
    }

    if caption:
        params["caption"] = caption
        params["parse_mode"] = parse_mode

    result = _api_request("sendDocument", params, files={"document": file_path})

    if result.get("ok"):
        msg = result.get("result", {})
        msg_id = msg.get("message_id")
        doc_name = msg.get("document", {}).get("file_name", "Dokument")
        return f"OK: '{doc_name}' gesendet (Message #{msg_id})"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_send_photo(
    chat_id: str,
    file_path: str,
    caption: str = "",
    parse_mode: str = "Markdown",
    disable_notification: bool = False
) -> str:
    """
    Sendet ein Foto an einen Telegram-Chat.

    Args:
        chat_id: Chat-ID oder Username (@channel_name)
        file_path: Pfad zum Foto (JPG, PNG)
        caption: Bildunterschrift (optional, max. 1024 Zeichen)
        parse_mode: Formatierung - "Markdown", "MarkdownV2" oder "HTML" (Standard: Markdown)
        disable_notification: Stumme Benachrichtigung (Standard: False)

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    params = {
        "chat_id": chat_id,
        "disable_notification": str(disable_notification).lower()
    }

    if caption:
        params["caption"] = caption
        params["parse_mode"] = parse_mode

    result = _api_request("sendPhoto", params, files={"photo": file_path})

    if result.get("ok"):
        msg = result.get("result", {})
        msg_id = msg.get("message_id")
        return f"OK: Foto gesendet (Message #{msg_id})"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_get_updates(offset: int = 0, limit: int = 10) -> str:
    """
    Ruft neue Updates (Nachrichten, Callbacks) vom Bot ab.

    Args:
        offset: Update-ID Offset (0 = alle neuen Updates)
        limit: Maximale Anzahl Updates (1-100, Standard: 10)

    Returns:
        JSON-Array mit Updates oder Fehlermeldung.
    """
    params = {
        "offset": offset,
        "limit": limit,
        "timeout": 10
    }

    result = _api_request("getUpdates", params)

    if result.get("ok"):
        updates = result.get("result", [])

        # Format updates für bessere Lesbarkeit
        formatted_updates = []
        skipped_unauthorized = 0

        for update in updates:
            msg = update.get("message", {})
            if msg:
                chat_id = msg.get("chat", {}).get("id")

                # Filter: Nur autorisierte Chats
                if not _is_chat_allowed(chat_id):
                    skipped_unauthorized += 1
                    mcp_log(f"[Telegram] Unauthorized message from chat {chat_id} ignored")
                    continue

                formatted_updates.append({
                    "update_id": update.get("update_id"),
                    "message_id": msg.get("message_id"),
                    "from": {
                        "id": msg.get("from", {}).get("id"),
                        "first_name": msg.get("from", {}).get("first_name"),
                        "username": msg.get("from", {}).get("username")
                    },
                    "chat": {
                        "id": chat_id,
                        "type": msg.get("chat", {}).get("type"),
                        "title": msg.get("chat", {}).get("title")
                    },
                    "date": msg.get("date"),
                    "text": msg.get("text", "")
                })

        output = {"updates": formatted_updates, "count": len(formatted_updates)}
        if skipped_unauthorized:
            output["skipped_unauthorized"] = skipped_unauthorized
        return json.dumps(output, ensure_ascii=False, indent=2)
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_get_chat_info(chat_id: str) -> str:
    """
    Ruft Informationen über einen Chat ab.

    Args:
        chat_id: Chat-ID oder Username (@channel_name)

    Returns:
        Chat-Informationen als JSON oder Fehlermeldung.
    """
    result = _api_request("getChat", {"chat_id": chat_id})

    if result.get("ok"):
        chat = result.get("result", {})
        info = {
            "id": chat.get("id"),
            "type": chat.get("type"),
            "title": chat.get("title"),
            "username": chat.get("username"),
            "description": chat.get("description"),
            "member_count": chat.get("member_count")
        }
        return json.dumps(info, ensure_ascii=False, indent=2)
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_send_message_with_keyboard(
    chat_id: str,
    text: str,
    buttons: str,
    parse_mode: str = "Markdown"
) -> str:
    """
    Sendet eine Nachricht mit Inline-Keyboard-Buttons.

    Args:
        chat_id: Chat-ID oder Username (@channel_name)
        text: Nachrichtentext
        buttons: JSON-Array mit Buttons, z.B. [{"text": "Ja", "callback_data": "yes"}, {"text": "Nein", "callback_data": "no"}]
        parse_mode: Formatierung - "Markdown" oder "HTML" (Standard: Markdown)

    Returns:
        Erfolgsmeldung oder Fehlermeldung.

    Beispiel:
        telegram_send_message_with_keyboard(
            "123456",
            "Möchtest du fortfahren?",
            '[{"text": "✅ Ja", "callback_data": "yes"}, {"text": "❌ Nein", "callback_data": "no"}]'
        )
    """
    try:
        button_list = json.loads(buttons)

        # Buttons in Zeilen aufteilen (max. 8 Buttons pro Zeile empfohlen)
        keyboard = []
        row = []
        for btn in button_list:
            row.append(btn)
            if len(row) >= 2:  # 2 Buttons pro Zeile
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": {
                "inline_keyboard": keyboard
            }
        }

        result = _api_request("sendMessage", params)

        if result.get("ok"):
            msg_id = result.get("result", {}).get("message_id")
            return f"OK: Nachricht mit Keyboard gesendet (Message #{msg_id})"
        else:
            return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"

    except json.JSONDecodeError:
        return "Fehler: Ungültiges JSON-Format für Buttons"
    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
def telegram_delete_message(chat_id: str, message_id: str) -> str:
    """
    Löscht eine Nachricht in einem Chat.

    Args:
        chat_id: Chat-ID
        message_id: Nachricht-ID

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    params = {
        "chat_id": chat_id,
        "message_id": message_id
    }

    result = _api_request("deleteMessage", params)

    if result.get("ok"):
        return f"OK: Nachricht #{message_id} gelöscht"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_edit_message(
    chat_id: str,
    message_id: str,
    text: str,
    parse_mode: str = "Markdown"
) -> str:
    """
    Bearbeitet eine bereits gesendete Nachricht.

    Args:
        chat_id: Chat-ID
        message_id: Nachricht-ID
        text: Neuer Text
        parse_mode: Formatierung - "Markdown" oder "HTML" (Standard: Markdown)

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode
    }

    result = _api_request("editMessageText", params)

    if result.get("ok"):
        return f"OK: Nachricht #{message_id} bearbeitet"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


@mcp.tool()
def telegram_answer_callback_query(callback_query_id: str, text: str = "", show_alert: bool = False) -> str:
    """
    Antwortet auf eine Callback-Query von einem Inline-Button.

    Args:
        callback_query_id: ID der Callback-Query (aus Updates)
        text: Antworttext (optional, max. 200 Zeichen)
        show_alert: Als Alert anzeigen statt als Toast (Standard: False)

    Returns:
        Erfolgsmeldung oder Fehlermeldung.
    """
    params = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert
    }

    if text:
        params["text"] = text

    result = _api_request("answerCallbackQuery", params)

    if result.get("ok"):
        return "OK: Callback beantwortet"
    else:
        return f"Fehler: {result.get('error', 'Unbekannter Fehler')}"


if __name__ == "__main__":
    mcp.run()
