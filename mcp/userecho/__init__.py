#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
UserEcho MCP Server
===================
MCP Server für UserEcho API-Zugriff.
Ermöglicht das Lesen von Support-Tickets und Erstellen von Antworten.

API Dokumentation: https://userecho.com/dev/api/reference/
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config
from _link_utils import make_link_ref, LINK_TYPE_TICKET

mcp = FastMCP("userecho")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "support_agent",
    "color": "#e91e63"
}

# Integration schema for WebUI Integrations Hub
INTEGRATION_SCHEMA = {
    "name": "UserEcho",
    "icon": "support_agent",
    "color": "#e91e63",
    "config_key": "userecho",
    "auth_type": "api_key",
    "fields": [
        {
            "key": "subdomain",
            "label": "Subdomain",
            "type": "text",
            "required": True,
            "hint": "UserEcho Subdomain (z.B. 'support' aus support.userecho.com)",
        },
        {
            "key": "api_key",
            "label": "API Key",
            "type": "password",
            "required": True,
            "hint": "UserEcho API Key (Admin > API)",
        },
    ],
    "test_tool": "userecho_get_forums",
    "setup": {
        "description": "Support-Tickets",
        "requirement": "UserEcho API Key",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "UserEcho Subdomain und API-Key eintragen",
        ],
    },
}

# MCP-Level Flag: All tools in this MCP handle external/untrusted content
# Support tickets come from external users and may contain prompt injection attempts
IS_HIGH_RISK = True

# Note: With IS_HIGH_RISK=True, individual HIGH_RISK_TOOLS are not needed
# All tools will be sanitized by the anonymization proxy

# Read-only tools that only retrieve data without modifications
# Used by tool_mode: "read_only" to allow only safe operations
READ_ONLY_TOOLS = {
    "userecho_get_forums",
    "userecho_get_open_tickets",
    "userecho_get_tickets_by_status",
    "userecho_get_recent_new_tickets",
    "userecho_get_all_tickets",
    "userecho_get_ticket",
    "userecho_get_ticket_comments",
    "userecho_search_tickets",
}

# Destructive tools that modify, create, or delete data
DESTRUCTIVE_TOOLS = {
    "userecho_create_ticket_reply",
    "userecho_create_ticket_reply_draft",
    "userecho_update_ticket_status",
}

# Cache für Forums (ändern sich selten)
_forum_cache = {"data": None, "timestamp": 0}
FORUM_CACHE_TTL = 3600  # 1 Stunde


def get_config():
    """Lädt UserEcho-Konfiguration."""
    subdomain = os.environ.get("USERECHO_SUBDOMAIN")
    api_key = os.environ.get("USERECHO_API_KEY")

    if not subdomain or not api_key:
        config = load_config()
        userecho = config.get("userecho", {})
        subdomain = subdomain or userecho.get("subdomain")
        api_key = api_key or userecho.get("api_key")

    if not subdomain or not api_key:
        raise ValueError(
            "UserEcho nicht konfiguriert. Setze USERECHO_SUBDOMAIN und USERECHO_API_KEY "
            "oder konfiguriere in config.json unter 'userecho'."
        )

    return {
        "subdomain": subdomain,
        "api_key": api_key,
        "base_url": f"https://{subdomain}.userecho.com/api/v2"
    }


def is_configured() -> bool:
    """Prüft ob UserEcho API konfiguriert und aktiviert ist."""
    config = load_config()
    userecho = config.get("userecho", {})

    # Check enabled flag (default: True if not set)
    if userecho.get("enabled") is False:
        return False

    # Check if credentials are set
    subdomain = os.environ.get("USERECHO_SUBDOMAIN") or userecho.get("subdomain")
    api_key = os.environ.get("USERECHO_API_KEY") or userecho.get("api_key")

    return bool(subdomain and api_key)


def api_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Führt API-Request gegen UserEcho aus.

    Args:
        endpoint: API-Endpunkt (ohne führenden Slash)
        method: HTTP-Methode (GET, POST, PUT, DELETE)
        data: Request-Body für POST/PUT

    Returns:
        JSON-Response als dict
    """
    config = get_config()

    # URL mit .json Format und access_token
    # API erwartet: https://[alias].userecho.com/api/v2/[command].json?access_token=...
    base_url = config['base_url']

    # .json vor Query-Parameter einfügen
    if "?" in endpoint:
        path, query = endpoint.split("?", 1)
        url = f"{base_url}/{path}.json?{query}&access_token={config['api_key']}"
    else:
        url = f"{base_url}/{endpoint}.json?access_token={config['api_key']}"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    body = None
    if data:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body}
    except urllib.error.URLError as e:
        return {"error": f"URL Error: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def format_date(date_str: str) -> str:
    """Formatiert ISO-Datum zu lesbarem Format."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return date_str


def get_status_name(status) -> str:
    """Konvertiert Status zu lesbarem Namen.

    Status kann sein:
    - int: Status ID
    - dict: Neues Format {"id": 20, "name": "Fertiggestellt"}
    """
    if isinstance(status, dict):
        return status.get("name", f"Status {status.get('id', '?')}")

    # Aktuelle Status-IDs aus UserEcho Helpdesk
    statuses = {
        1: "Neu",
        17: "Under review",
        18: "Planned",
        19: "Started",
        20: "Completed",
        # Legacy IDs (andere Foren)
        0: "Neu",
        2: "In Bearbeitung",
        3: "Beantwortet",
        4: "Geschlossen",
        5: "Abgelehnt",
        6: "Geplant",
        7: "Erledigt"
    }
    return statuses.get(status, f"Status {status}")


def get_type_name(topic_type) -> str:
    """Konvertiert Topic-Type zu lesbarem Namen.

    Type kann sein:
    - int: Legacy type ID
    - dict: Neues Format {"id": 6, "name": "Tickets"}
    """
    if isinstance(topic_type, dict):
        return topic_type.get("name", f"Typ {topic_type.get('id', '?')}")

    types = {
        1: "Idee",
        2: "Problem",
        3: "Frage",
        4: "Lob"
    }
    return types.get(topic_type, f"Typ {topic_type}")


# =============================================================================
# Forums
# =============================================================================

@mcp.tool()
def userecho_get_forums() -> str:
    """Listet alle verfügbaren Foren/Kategorien.

    Returns:
        Liste der Foren mit ID, Name und Beschreibung
    """
    import time
    global _forum_cache

    # Cache prüfen
    if _forum_cache["data"] and (time.time() - _forum_cache["timestamp"]) < FORUM_CACHE_TTL:
        forums = _forum_cache["data"]
    else:
        result = api_request("forums")
        if "error" in result:
            return f"Fehler: {result['error']}"

        forums = result.get("data", [])
        _forum_cache = {"data": forums, "timestamp": time.time()}

    if not forums:
        return "Keine Foren gefunden."

    lines = ["📁 **Verfügbare Foren:**\n"]
    for forum in forums:
        forum_id = forum.get("id")
        name = forum.get("name", "Unbenannt")
        desc = forum.get("description", "")
        topic_count = forum.get("topic_count", 0)
        forum_type = forum.get("type", {}).get("name", "")

        lines.append(f"- **{name}** (ID: {forum_id})")
        if desc:
            lines.append(f"  {desc}")
        lines.append(f"  Topics: {topic_count} | Type: {forum_type}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Topics (Support Tickets)
# =============================================================================

@mcp.tool()
def userecho_get_open_tickets(forum_id: int = None, limit: int = 20, max_age_days: int = None) -> str:
    """Holt alle offenen Support-Tickets.

    Args:
        forum_id: Forum-ID (optional, sonst alle Foren)
        limit: Maximale Anzahl (Standard: 20)
        max_age_days: Maximales Alter in Tagen (optional, z.B. 180 für 6 Monate)

    Returns:
        Liste offener Tickets mit Status, Autor und Datum

    Tipp: Nutze userecho_get_tickets_by_status("planned") für alle Planned-Tickets.
    """
    from datetime import datetime, timedelta

    # Status-IDs für offene Tickets (is_type_opened=true):
    # 1=Neu, 17=Under review, 18=Planned, 19=Started
    # Status 20=Completed ist geschlossen
    params = f"?filter__status__in=1,17,18,19&limit=100&order_by=-created"

    # Age filter setup
    cutoff_date = None
    if max_age_days:
        cutoff_date = datetime.now() - timedelta(days=max_age_days)

    def filter_by_age(tickets):
        """Filter tickets by age if max_age_days is set."""
        if not cutoff_date:
            return tickets[:limit]
        filtered = []
        for ticket in tickets:
            created_str = ticket.get("created", "")
            if created_str:
                try:
                    created_str_clean = created_str.replace("T", " ").split(".")[0]
                    created_date = datetime.strptime(created_str_clean[:19], "%Y-%m-%d %H:%M:%S")
                    if created_date >= cutoff_date:
                        filtered.append(ticket)
                except (ValueError, TypeError):
                    pass  # Skip tickets with invalid date format
            if len(filtered) >= limit:
                break
        return filtered

    if forum_id:
        endpoint = f"forums/{forum_id}/topics{params}"
        result = api_request(endpoint)
        if "error" in result:
            return f"Fehler: {result['error']}"
        tickets = filter_by_age(result.get("data", []))
        return format_ticket_list(tickets)
    else:
        # Alle Foren durchsuchen
        forums_result = api_request("forums")
        if "error" in forums_result:
            return f"Fehler: {forums_result['error']}"

        forums = forums_result.get("data", [])
        all_tickets = []

        for forum in forums:
            fid = forum.get("id")
            result = api_request(f"forums/{fid}/topics{params}")
            if "error" not in result:
                tickets = result.get("data", [])
                for t in tickets:
                    t["_forum_name"] = forum.get("name", "")
                all_tickets.extend(tickets)

        # Nach Datum sortieren
        all_tickets.sort(key=lambda x: x.get("created", ""), reverse=True)
        all_tickets = filter_by_age(all_tickets)

        return format_ticket_list(all_tickets, show_forum=True)


@mcp.tool()
def userecho_get_tickets_by_status(status: str, forum_id: int = 1, limit: int = 50) -> str:
    """Holt alle Tickets mit einem bestimmten Status.

    Perfekt um z.B. alle "Planned" Feature-Requests zu sehen.

    Args:
        status: Status-Name: "new", "review", "planned", "started", "completed"
                           oder deutsch: "neu", "geplant", "gestartet", "fertig"
        forum_id: Forum-ID (Standard: 1 = Community Forum)
        limit: Maximale Anzahl (Standard: 50)

    Returns:
        Liste aller Tickets mit dem angegebenen Status
    """
    # Status-Namen die wir suchen (lokale Filterung weil API-Filter unzuverlässig)
    status_names = {
        "new": ["new", "neu"],
        "neu": ["new", "neu"],
        "review": ["under review", "review"],
        "under review": ["under review", "review"],
        "planned": ["planned", "geplant"],
        "geplant": ["planned", "geplant"],
        "started": ["started", "gestartet"],
        "gestartet": ["started", "gestartet"],
        "completed": ["completed", "fertig", "fertiggestellt"],
        "fertig": ["completed", "fertig", "fertiggestellt"],
        "done": ["completed", "fertig", "fertiggestellt"]
    }

    status_lower = status.lower().strip()
    if status_lower not in status_names:
        return f"Ungültiger Status '{status}'. Erlaubt: new, review, planned, started, completed"

    target_names = status_names[status_lower]

    # Alle Tickets holen (ohne Server-Filter, da API unzuverlässig)
    params = f"?limit=100&order_by=-created"
    endpoint = f"forums/{forum_id}/topics{params}"

    result = api_request(endpoint)
    if "error" in result:
        return f"Fehler: {result['error']}"

    all_tickets = result.get("data", [])

    # Lokal nach Status-Name filtern
    filtered = []
    for ticket in all_tickets:
        ticket_status = ticket.get("status", {})
        if isinstance(ticket_status, dict):
            status_name = ticket_status.get("name", "").lower()
        else:
            status_name = get_status_name(ticket_status).lower()

        if any(target.lower() in status_name or status_name in target.lower() for target in target_names):
            filtered.append(ticket)
            if len(filtered) >= limit:
                break

    if not filtered:
        return f"Keine Tickets mit Status '{status}' gefunden."

    return format_ticket_list(filtered)


@mcp.tool()
def userecho_get_recent_new_tickets(forum_id: int = 1, max_age_days: int = 14, limit: int = 10) -> str:
    """Holt NUR neue Tickets der letzten X Tage (für Daily Check).

    Findet Tickets die:
    - Status "Neu" (ID 1) haben UND
    - Nicht älter als max_age_days sind

    Perfekt für den Daily Check um nur wirklich neue Anfragen zu sehen.

    Args:
        forum_id: Forum-ID (Standard: 1 = Community Forum)
        max_age_days: Maximales Alter in Tagen (Standard: 14)
        limit: Maximale Anzahl (Standard: 10)

    Returns:
        Kompakte Liste neuer Tickets (eine Zeile pro Ticket)
    """
    from datetime import datetime, timedelta

    # Hole Tickets mit Status "Neu" (ID 1)
    params = f"?filter__status__in=1&limit=50&order_by=-created"
    endpoint = f"forums/{forum_id}/topics{params}"

    result = api_request(endpoint)
    if "error" in result:
        return f"Fehler: {result['error']}"

    all_tickets = result.get("data", [])
    recent_tickets = []
    now = datetime.now()
    cutoff = now - timedelta(days=max_age_days)

    for ticket in all_tickets:
        created_str = ticket.get("created", "")
        if not created_str:
            continue

        try:
            created_str_clean = created_str.replace("T", " ").split(".")[0]
            created_date = datetime.strptime(created_str_clean[:19], "%Y-%m-%d %H:%M:%S")

            if created_date > cutoff:
                age_days = (now - created_date).days
                ticket["_age_days"] = age_days
                recent_tickets.append(ticket)
        except (ValueError, TypeError):
            continue  # Skip tickets with invalid date format

        if len(recent_tickets) >= limit:
            break

    if not recent_tickets:
        return "✅ Keine neuen Support-Tickets (Status: Neu, letzte 14 Tage)."

    # Kompakte Ausgabe für Daily Check (eine Zeile pro Ticket)
    lines = [f"🎫 **{len(recent_tickets)} neue Tickets:**\n"]
    for ticket in recent_tickets:
        ticket_id = str(ticket.get("id", ""))
        link_ref = make_link_ref(ticket_id, LINK_TYPE_TICKET)
        title = ticket.get("header", "Ohne Titel")[:50]  # Truncate
        age_days = ticket.get("_age_days", 0)
        comment_count = ticket.get("comment_count", 0)

        # Age format
        if age_days == 0:
            age_str = "Heute"
        elif age_days == 1:
            age_str = "Gestern"
        else:
            age_str = f"{age_days} Tage"

        # Last action indicator
        if comment_count == 0:
            action = "⏳ Keine Antwort"
        else:
            action = f"{comment_count} Kommentar(e)"

        web_link = userecho_get_ticket_url(ticket_id)
        lines.append(f"- [{title}]({web_link}) | Ref: {link_ref} | {age_str} | {action}")

    return "\n".join(lines)


def userecho_get_ticket_url(ticket_id: int) -> str:
    """Gibt die Browser-URL für ein Ticket zurück."""
    try:
        config = get_config()
        return f"https://{config['subdomain']}.userecho.com/topics/{ticket_id}/"
    except (ValueError, KeyError):
        return f"#ticket-{ticket_id}"


@mcp.tool()
def userecho_get_all_tickets(forum_id: int = None, status: str = None, limit: int = 50) -> str:
    """Holt Tickets mit optionalem Status-Filter.

    Args:
        forum_id: Forum-ID (optional, Standard: alle Foren)
        status: Status-Filter: "new", "review", "planned", "started", "completed" (optional)
        limit: Maximale Anzahl (Standard: 50)

    Returns:
        Liste der Tickets
    """
    # Aktuelle Status-IDs aus UserEcho:
    # 1=New, 17=Under review, 18=Planned, 19=Started, 20=Completed
    status_map = {
        "new": 1,
        "review": 17,
        "planned": 18,
        "started": 19,
        "completed": 20,
        # Legacy aliases
        "open": 1,
        "progress": 19,
        "closed": 20,
        "done": 20
    }

    params = f"?limit={limit}&order_by=-created"
    if status and status.lower() in status_map:
        params += f"&filter__status__in={status_map[status.lower()]}"

    if forum_id:
        endpoint = f"forums/{forum_id}/topics{params}"
        result = api_request(endpoint)
        if "error" in result:
            return f"Fehler: {result['error']}"
        tickets = result.get("data", [])
    else:
        forums_result = api_request("forums")
        if "error" in forums_result:
            return f"Fehler: {forums_result['error']}"

        forums = forums_result.get("data", [])
        tickets = []

        for forum in forums:
            fid = forum.get("id")
            result = api_request(f"forums/{fid}/topics{params}")
            if "error" not in result:
                for t in result.get("data", []):
                    t["_forum_name"] = forum.get("name", "")
                tickets.extend(result.get("data", []))

        tickets.sort(key=lambda x: x.get("created", ""), reverse=True)
        tickets = tickets[:limit]

    return format_ticket_list(tickets, show_forum=not forum_id)


def format_ticket_list(tickets: list, show_forum: bool = False) -> str:
    """Formatiert Ticket-Liste für Ausgabe."""
    if not tickets:
        return "Keine Tickets gefunden."

    lines = [f"📋 **{len(tickets)} Tickets:**\n"]

    for ticket in tickets:
        ticket_id = str(ticket.get("id", ""))
        link_ref = make_link_ref(ticket_id, LINK_TYPE_TICKET)
        title = ticket.get("header", "Ohne Titel")
        status = get_status_name(ticket.get("status", 0))
        topic_type = get_type_name(ticket.get("type", 0))
        created = format_date(ticket.get("created"))
        author = ticket.get("author", {})
        author_name = author.get("name", "Unbekannt")
        comments_count = ticket.get("comments_count", 0)
        # Prefer URL from API response, fallback to generated URL
        web_link = ticket.get("url") or userecho_get_ticket_url(ticket_id)

        lines.append(f"### [{ticket_id}] [{title}]({web_link})")
        lines.append(f"- **Link Ref:** {link_ref}")
        lines.append(f"- **Status:** {status} | **Typ:** {topic_type}")
        lines.append(f"- **Von:** {author_name} | **Erstellt:** {created}")
        lines.append(f"- **Kommentare:** {comments_count}")

        if show_forum and "_forum_name" in ticket:
            lines.append(f"- **Forum:** {ticket['_forum_name']}")

        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def userecho_get_ticket(ticket_id: int) -> str:
    """Holt vollständige Details eines Tickets inkl. Beschreibung.

    Args:
        ticket_id: Die Ticket/Topic-ID

    Returns:
        Vollständige Ticket-Details mit Beschreibung
    """
    result = api_request(f"topics/{ticket_id}")
    if "error" in result:
        return f"Fehler: {result['error']}"

    ticket = result.get("data", {})
    if not ticket:
        return f"Ticket {ticket_id} nicht gefunden."

    ticket_id_str = str(ticket_id)
    link_ref = make_link_ref(ticket_id_str, LINK_TYPE_TICKET)
    title = ticket.get("header", "Ohne Titel")
    status = get_status_name(ticket.get("status", 0))
    topic_type = get_type_name(ticket.get("type", 0))
    created = format_date(ticket.get("created"))
    updated = format_date(ticket.get("updated"))
    description = ticket.get("description", "Keine Beschreibung")
    author = ticket.get("author", {})
    author_name = author.get("name", "Unbekannt")
    author_email = author.get("email", "")
    votes = ticket.get("votes", 0)
    comments_count = ticket.get("comments_count", 0)
    web_link = ticket.get("url") or userecho_get_ticket_url(ticket_id)

    lines = [
        f"# Ticket #{ticket_id}: [{title}]({web_link})",
        "",
        f"**Link Ref:** {link_ref}",
        f"**Status:** {status}",
        f"**Typ:** {topic_type}",
        f"**Von:** {author_name}" + (f" ({author_email})" if author_email else ""),
        f"**Erstellt:** {created}",
        f"**Aktualisiert:** {updated}",
        f"**Votes:** {votes} | **Kommentare:** {comments_count}",
        f"**Web Link:** {web_link}",
    ]

    lines.extend([
        "",
        "---",
        "## Beschreibung",
        "",
        description,
        ""
    ])

    return "\n".join(lines)


# =============================================================================
# Comments (Antworten)
# =============================================================================

@mcp.tool()
def userecho_get_ticket_comments(ticket_id: int) -> str:
    """Holt alle Kommentare/Antworten zu einem Ticket.

    Args:
        ticket_id: Die Ticket/Topic-ID

    Returns:
        Liste aller Kommentare chronologisch
    """
    result = api_request(f"topics/{ticket_id}/comments?order_by=created")
    if "error" in result:
        return f"Fehler: {result['error']}"

    comments = result.get("data", [])
    if not comments:
        return f"Keine Kommentare zu Ticket #{ticket_id}."

    lines = [f"💬 **{len(comments)} Kommentare zu Ticket #{ticket_id}:**\n"]

    for i, comment in enumerate(comments, 1):
        author = comment.get("author", {})
        author_name = author.get("name", "Unbekannt")
        is_official = comment.get("is_official", False)
        created = format_date(comment.get("created"))
        text = comment.get("text", "")

        badge = " 🏢 [Offiziell]" if is_official else ""
        lines.append(f"### Kommentar {i}{badge}")
        lines.append(f"**Von:** {author_name} | **Datum:** {created}")
        lines.append("")
        lines.append(text)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def userecho_create_ticket_reply(ticket_id: int, text: str, is_official: bool = True) -> str:
    """Erstellt eine Antwort auf ein Support-Ticket.

    Args:
        ticket_id: Die Ticket/Topic-ID
        text: Der Antwort-Text
        is_official: Als offizielle Antwort markieren (Standard: True)

    Returns:
        Bestätigung der erstellten Antwort
    """
    data = {
        "text": text,
        "is_official": is_official
    }

    result = api_request(f"topics/{ticket_id}/comments", method="POST", data=data)
    if "error" in result:
        return f"Fehler beim Erstellen der Antwort: {result['error']}"

    comment = result.get("data", {})
    comment_id = comment.get("id", "?")

    return f"✅ Antwort erstellt (Kommentar #{comment_id}) auf Ticket #{ticket_id}"


@mcp.tool()
def userecho_create_ticket_reply_draft(ticket_id: int, text: str) -> str:
    """Erstellt einen Antwort-Entwurf für ein Ticket (wird NICHT gesendet, nur angezeigt).

    Zeigt den Entwurf zur Überprüfung an. Nutze userecho_create_ticket_reply() zum tatsächlichen Senden.

    Args:
        ticket_id: Die Ticket/Topic-ID
        text: Der Antwort-Text

    Returns:
        Der formatierte Entwurf zur Überprüfung
    """
    # Ticket-Details holen für Kontext
    ticket_result = api_request(f"topics/{ticket_id}")
    ticket = ticket_result.get("data", {})
    title = ticket.get("header", f"Ticket #{ticket_id}")
    author = ticket.get("author", {}).get("name", "Unbekannt")

    lines = [
        "📝 **ENTWURF - Nicht gesendet!**",
        "",
        f"**Ticket:** #{ticket_id} - {title}",
        f"**An:** {author}",
        "",
        "---",
        "## Antwort-Entwurf:",
        "",
        text,
        "",
        "---",
        "",
        f"⚠️ Zum Senden nutze: `userecho_create_ticket_reply({ticket_id}, '<text>')`"
    ]

    return "\n".join(lines)


# =============================================================================
# Ticket-Status ändern
# =============================================================================

@mcp.tool()
def userecho_update_ticket_status(ticket_id: int, status: str, forum_id: int = 3) -> str:
    """Ändert den Status eines Tickets.

    Args:
        ticket_id: Die Ticket/Topic-ID
        status: Neuer Status: "new", "review", "planned", "started", "completed"
        forum_id: Forum-ID (Standard: 3 = Helpdesk)

    Returns:
        Bestätigung der Statusänderung
    """
    # Aktuelle Status-IDs aus UserEcho:
    # 1=New, 17=Under review, 18=Planned, 19=Started, 20=Completed
    status_map = {
        "new": 1,
        "review": 17,
        "planned": 18,
        "started": 19,
        "completed": 20,
        # Legacy aliases
        "open": 1,
        "progress": 19,
        "closed": 20,
        "done": 20
    }

    status_lower = status.lower()
    if status_lower not in status_map:
        return f"Ungültiger Status '{status}'. Erlaubt: {', '.join(status_map.keys())}"

    # API erwartet PUT /forums/{forum_id}/topics mit id im Body
    data = {"id": ticket_id, "status": status_map[status_lower]}
    result = api_request(f"forums/{forum_id}/topics", method="PUT", data=data)

    if "error" in result:
        return f"Fehler beim Ändern des Status: {result['error']}"

    return f"✅ Ticket #{ticket_id} Status geändert zu: {get_status_name(status_map[status_lower])}"


# =============================================================================
# Suche
# =============================================================================

@mcp.tool()
def userecho_search_tickets(query: str, limit: int = 20) -> str:
    """Sucht Tickets nach Suchbegriff.

    Args:
        query: Suchbegriff
        limit: Maximale Anzahl (Standard: 20)

    Returns:
        Gefundene Tickets
    """
    # Suche über alle Foren mit Filter
    forums_result = api_request("forums")
    if "error" in forums_result:
        return f"Fehler: {forums_result['error']}"

    forums = forums_result.get("data", [])
    all_tickets = []
    query_lower = query.lower()

    for forum in forums:
        fid = forum.get("id")
        result = api_request(f"forums/{fid}/topics?limit=100&order_by=-created")
        if "error" not in result:
            for ticket in result.get("data", []):
                title = ticket.get("header", "").lower()
                desc = ticket.get("description", "").lower()
                if query_lower in title or query_lower in desc:
                    ticket["_forum_name"] = forum.get("name", "")
                    all_tickets.append(ticket)

    all_tickets = all_tickets[:limit]

    if not all_tickets:
        return f"Keine Tickets gefunden für '{query}'."

    return format_ticket_list(all_tickets, show_forum=True)


# =============================================================================
# Hauptprogramm
# =============================================================================

if __name__ == "__main__":
    mcp.run()
