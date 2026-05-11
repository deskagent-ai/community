#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
ecoDMS MCP Server
=================
MCP Server für ecoDMS Document Management System API.
Ermöglicht das Archivieren, Suchen und Verwalten von Dokumenten.

API-Dokumentation: https://www.ecodms.de/en/ecodms-api

Authentifizierung:
- ecoDMS verwendet Session-basierte Authentifizierung
- Erst /connect/{archive_id} aufrufen → Session erstellen
- Session für alle weiteren Requests verwenden
- Am Ende /disconnect aufrufen
"""

import json
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth
from mcp.server.fastmcp import FastMCP

# DeskAgent MCP API (provides config, paths, logging via HTTP)
from _mcp_api import load_config, get_temp_dir, mcp_log

mcp = FastMCP("ecodms")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "inventory_2",
    "color": "#009688"
}

# Integration schema for WebUI Integrations Hub
INTEGRATION_SCHEMA = {
    "name": "ecoDMS",
    "icon": "inventory_2",
    "color": "#009688",
    "config_key": "ecodms",
    "auth_type": "credentials",
    "fields": [
        {
            "key": "url",
            "label": "Server URL",
            "type": "url",
            "required": True,
            "hint": "ecoDMS Server URL (z.B. http://localhost:8180)",
            "default": "http://localhost:8180",
        },
        {
            "key": "username",
            "label": "Username",
            "type": "text",
            "required": True,
            "default": "ecodms",
        },
        {
            "key": "password",
            "label": "Password",
            "type": "password",
            "required": True,
        },
        {
            "key": "archive_id",
            "label": "Archive ID",
            "type": "text",
            "required": False,
            "default": "1",
            "hint": "Optional: ecoDMS Archive ID (Standard: 1)",
        },
    ],
    "test_tool": "ecodms_test_connection",
    "setup": {
        "description": "Dokumentenarchiv",
        "requirement": "ecoDMS Server + Credentials",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "ecoDMS Zugangsdaten eintragen",
        ],
    },
}

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "ecodms_get_folders",
    "ecodms_get_document_types",
    "ecodms_get_statuses",
    "ecodms_get_roles",
    "ecodms_get_classify_attributes",
    "ecodms_search_documents",
    "ecodms_get_document_info",
    "ecodms_download_document",
    "ecodms_get_thumbnail",
    "ecodms_test_connection",
    "ecodms_close_connection",
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    "ecodms_upload_document",
    "ecodms_classify_document",
    "ecodms_archive_file",
}

# =============================================================================
# Session Management
# =============================================================================

# Module-level session object for maintaining authentication state
_session: requests.Session = None
_connected: bool = False


def get_config():
    """Lädt ecoDMS-Konfiguration."""
    config = load_config()
    ecodms = config.get("ecodms", {})

    return {
        "url": ecodms.get("url", "http://localhost:8180"),
        "username": ecodms.get("username", "ecodms"),
        "password": ecodms.get("password", "ecodms"),
        "api_key": ecodms.get("api_key", ""),
        "archive_id": ecodms.get("archive_id", "1")
    }


def is_configured() -> bool:
    """Prüft ob ecoDMS konfiguriert und aktiviert ist."""
    config = load_config()
    ecodms = config.get("ecodms", {})

    # Check enabled flag (default: True if not set)
    if ecodms.get("enabled") is False:
        return False

    # ecoDMS needs url and credentials configured
    url = ecodms.get("url", "")
    username = ecodms.get("username", "")
    return bool(url and username)


def ensure_connected() -> dict:
    """Stellt sicher, dass eine Verbindung besteht.

    Versucht zwei Authentifizierungsmethoden:
    1. Session-basiert: /connect/{archive_id} (für ältere ecoDMS)
    2. Direct Basic Auth: Auth auf jeder Request (für neuere ecoDMS)
    """
    global _session, _connected

    if _connected and _session:
        return {"connected": True}

    config = get_config()

    # Create new session with Basic Auth configured
    _session = requests.Session()
    _session.auth = HTTPBasicAuth(config['username'], config['password'])

    # Add API key header if configured (for multi-factor auth)
    if config.get('api_key'):
        _session.headers['apikey'] = config['api_key']
        mcp_log(f"[ecoDMS] API key configured: {config['api_key'][:10]}...")

    # Method 1: Try session-based connect (older ecoDMS versions)
    url = f"{config['url']}/api/connect/{config['archive_id']}"
    mcp_log(f"[ecoDMS] Trying session connect: {url}")

    try:
        mcp_log(f"[ecoDMS] Request headers: {dict(_session.headers)}")
        response = _session.get(url, timeout=30)
        mcp_log(f"[ecoDMS] Response status: {response.status_code}")

        if response.status_code == 200:
            _connected = True
            mcp_log("[ecoDMS] Session connect successful")
            return {"connected": True, "method": "session"}
        else:
            mcp_log(f"[ecoDMS] Session connect failed: {response.status_code}")
            mcp_log(f"[ecoDMS] Response: {response.text[:200]}")

            # Method 2: Try direct Basic Auth (newer ecoDMS versions)
            # Test with classifyAttributes endpoint (doesn't consume API connects)
            test_url = f"{config['url']}/api/classifyAttributes"
            mcp_log(f"[ecoDMS] Trying direct auth: {test_url}")

            test_response = _session.get(test_url, timeout=30)
            mcp_log(f"[ecoDMS] Direct auth response: {test_response.status_code}")

            if test_response.status_code == 200:
                _connected = True
                mcp_log("[ecoDMS] Direct auth successful")
                return {"connected": True, "method": "direct"}
            else:
                _connected = False
                mcp_log(f"[ecoDMS] Direct auth failed: {test_response.text[:200]}")
                return {"error": f"HTTP {test_response.status_code}: {test_response.text[:500]}"}

    except Exception as e:
        _connected = False
        return {"error": str(e)}


def disconnect():
    """Trennt die Verbindung zum ecoDMS-Server."""
    global _session, _connected

    if _session and _connected:
        config = get_config()
        try:
            _session.get(f"{config['url']}/api/disconnect", timeout=10)
        except (requests.RequestException, OSError):
            pass

    _session = None
    _connected = False


def api_request(
    endpoint: str,
    method: str = "GET",
    data: dict = None,
    file_data: bytes = None,
    filename: str = ""
) -> dict:
    """Führt ecoDMS API-Request aus (mit automatischer Session-Verwaltung)."""
    global _session

    # Ensure we have a connection
    conn_result = ensure_connected()
    if "error" in conn_result:
        return conn_result

    config = get_config()
    url = f"{config['url']}/api/{endpoint}"

    headers = {"Accept": "application/json"}

    try:
        if file_data:
            # File upload - multipart/form-data
            files = {"file": (filename, file_data, "application/octet-stream")}
            response = _session.request(method, url, files=files, timeout=60)
        elif data:
            headers["Content-Type"] = "application/json"
            response = _session.request(method, url, json=data, headers=headers, timeout=60)
        else:
            response = _session.request(method, url, headers=headers, timeout=60)

        if response.status_code == 200:
            if response.content:
                return response.json()
            return {"success": True}
        else:
            return {"error": f"HTTP {response.status_code}: {response.text[:500]}"}

    except Exception as e:
        return {"error": str(e)}


def download_file(endpoint: str) -> bytes:
    """Lädt Datei von ecoDMS herunter."""
    global _session

    # Ensure we have a connection
    conn_result = ensure_connected()
    if "error" in conn_result:
        raise Exception(conn_result["error"])

    config = get_config()
    url = f"{config['url']}/api/{endpoint}"

    response = _session.get(url, timeout=120)
    response.raise_for_status()
    return response.content


# =============================================================================
# Archive Information
# =============================================================================

@mcp.tool()
def ecodms_get_folders() -> str:
    """Listet alle Ordner/Ablagen im ecoDMS-Archiv.

    Returns:
        JSON mit allen verfügbaren Ordnern
    """
    result = api_request("folders")

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_get_document_types() -> str:
    """Listet alle Dokumenttypen im ecoDMS-Archiv.

    Returns:
        JSON mit allen verfügbaren Dokumenttypen
    """
    result = api_request("types")

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_get_statuses() -> str:
    """Listet alle Status-Werte im ecoDMS-Archiv.

    Returns:
        JSON mit allen verfügbaren Status-Werten
    """
    result = api_request("status")

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_get_roles() -> str:
    """Listet alle Rollen/Berechtigungen im ecoDMS-Archiv.

    Returns:
        JSON mit allen verfügbaren Rollen
    """
    result = api_request("roles")

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_get_classify_attributes() -> str:
    """Holt alle Klassifizierungs-Attribute (Dokumentfelder).

    Diese Attribute werden für die Dokumentklassifizierung benötigt.

    Returns:
        JSON mit allen verfügbaren Klassifizierungs-Attributen
    """
    result = api_request("classifyAttributes")

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


# =============================================================================
# Document Operations
# =============================================================================

@mcp.tool()
def ecodms_search_documents(
    query: str = "",
    folder_id: str = "",
    doc_type: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    attribute: str = "",
    operator: str = "contains",
    limit: int = 50
) -> str:
    """Sucht Dokumente im ecoDMS-Archiv.

    Die Suche verwendet Filter mit Attribut/Operator/Wert.
    Mehrere Filter werden mit AND verknüpft.

    HINWEIS: ecoDMS unterstützt KEINE LIKE/Wildcard-Suche!
    Nur exakte Vergleiche sind möglich.

    Args:
        query: Suchtext für Bemerkung-Feld - EXAKTE Übereinstimmung (optional)
        folder_id: Ordner-ID filtern (optional)
        doc_type: Dokumenttyp filtern (optional)
        status: Status-ID filtern (optional)
        date_from: Ab Datum YYYY-MM-DD für cdate (optional)
        date_to: Bis Datum YYYY-MM-DD für cdate (optional)
        attribute: Benutzerdefiniertes Attribut zum Suchen (optional)
        operator: Suchoperator: = != < > <= >= (Standard: =)
        limit: Max. Anzahl Ergebnisse (Standard: 50, nicht verwendet da API kein Limit unterstützt)

    Returns:
        JSON mit gefundenen Dokumenten
    """
    # Build filter array - ecoDMS expects array of filter objects
    # Supported operators: = != < > <= >= (NO LIKE support!)
    filters = []

    # Map user-friendly operators to ecoDMS SQL operators
    op_map = {
        "contains": "=",  # No LIKE support, fallback to exact match
        "equals": "=",
        "=": "=",
        "!=": "!=",
        "<": "<",
        ">": ">",
        "<=": "<=",
        ">=": ">=",
        "greaterOrEqual": ">=",
        "lessOrEqual": "<=",
    }
    mapped_op = op_map.get(operator, "=")

    if query:
        filters.append({
            "classifyAttribut": "bemerkung",
            "searchOperator": mapped_op,
            "searchValue": query
        })

    if folder_id:
        filters.append({
            "classifyAttribut": "folder",
            "searchOperator": "=",
            "searchValue": folder_id
        })

    if doc_type:
        filters.append({
            "classifyAttribut": "docart",
            "searchOperator": "=",
            "searchValue": doc_type
        })

    if status:
        filters.append({
            "classifyAttribut": "status",
            "searchOperator": "=",
            "searchValue": status
        })

    if date_from:
        filters.append({
            "classifyAttribut": "cdate",
            "searchOperator": ">=",
            "searchValue": date_from
        })

    if date_to:
        filters.append({
            "classifyAttribut": "cdate",
            "searchOperator": "<=",
            "searchValue": date_to
        })

    if attribute and query:
        # Custom attribute search overrides default bemerkung search
        filters = [{
            "classifyAttribut": attribute,
            "searchOperator": mapped_op,
            "searchValue": query
        }]

    mcp_log(f"[ecoDMS] Search filters: {filters}")

    # POST filter array directly (not wrapped in object)
    result = api_request("searchDocuments", "POST", filters if filters else [])

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    # Format output
    config = get_config()
    documents = result if isinstance(result, list) else result.get("documents", [])

    # Add URLs to each document
    for doc in documents:
        doc_id = doc.get("docId", doc.get("id", ""))
        if doc_id:
            doc["thumbnail_url"] = f"{config['url']}/api/thumbnail/{doc_id}/page/1/height/200"
            doc["download_url"] = f"{config['url']}/api/document/{doc_id}"

    return json.dumps({
        "count": len(documents),
        "documents": documents
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_get_document_info(doc_id: str) -> str:
    """Holt Metadaten eines Dokuments.

    Args:
        doc_id: Dokument-ID

    Returns:
        JSON mit Dokumentmetadaten
    """
    result = api_request(f"documentInfo/{doc_id}")

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_download_document(doc_id: str, save_path: str = "") -> str:
    """Lädt ein Dokument aus ecoDMS herunter.

    WICHTIG: Jeder Download verbraucht 1 API-Connect!

    Args:
        doc_id: Dokument-ID
        save_path: Zielordner (Standard: .temp)

    Returns:
        Pfad zur heruntergeladenen Datei
    """
    # First get document info for filename
    info_result = api_request(f"documentInfo/{doc_id}")

    if "error" in info_result:
        return f"Fehler: {info_result['error']}"

    # Get original filename
    filename = info_result.get("filename", f"document_{doc_id}.pdf")

    # Download file
    try:
        file_data = download_file(f"document/{doc_id}")
    except Exception as e:
        return f"Fehler beim Download: {str(e)}"

    # Save file
    if save_path:
        save_path_obj = Path(save_path)
        if not save_path_obj.is_absolute():
            temp_dir = get_temp_dir() / save_path
        else:
            temp_dir = save_path_obj
    else:
        temp_dir = get_temp_dir()

    temp_dir.mkdir(parents=True, exist_ok=True)

    file_path = temp_dir / filename
    file_path.write_bytes(file_data)

    return str(file_path.resolve())


@mcp.tool()
def ecodms_upload_document(
    file_path: str,
    version_controlled: bool = False
) -> str:
    """Lädt ein Dokument in ecoDMS hoch (Archivierung).

    WICHTIG: Jeder Upload verbraucht 1 API-Connect!

    Das Dokument wird zunächst unklassifiziert hochgeladen.
    Nutze danach ecodms_classify_document() zur Klassifizierung.

    Args:
        file_path: Pfad zur Datei
        version_controlled: Versionierung aktivieren (Standard: False)

    Returns:
        JSON mit Dokument-ID des archivierten Dokuments
    """
    path = Path(file_path)

    if not path.exists():
        return json.dumps({"error": f"Datei nicht gefunden: {file_path}"}, indent=2)

    filename = path.name
    file_data = path.read_bytes()

    version_flag = "true" if version_controlled else "false"
    endpoint = f"uploadFile/{version_flag}"

    result = api_request(endpoint, "POST", file_data=file_data, filename=filename)

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    doc_id = result.get("docId", result.get("id", ""))

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "filename": filename,
        "message": f"Dokument archiviert. Nutze ecodms_classify_document({doc_id}, ...) zur Klassifizierung."
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_classify_document(
    doc_id: str,
    folder_id: str = "",
    doc_type: str = "",
    status: str = "",
    bemerkung: str = "",
    custom_attributes: str = ""
) -> str:
    """Klassifiziert ein Dokument in ecoDMS.

    Args:
        doc_id: Dokument-ID (aus ecodms_upload_document)
        folder_id: Ziel-Ordner ID
        doc_type: Dokumenttyp (z.B. "Rechnung", "Vertrag")
        status: Status-Wert
        bemerkung: Bemerkung/Beschreibung
        custom_attributes: JSON-String mit zusätzlichen Attributen {"dyn_feld": "wert"}

    Returns:
        Bestätigung der Klassifizierung
    """
    config = get_config()

    classify_data = {
        "archiveName": config["archive_id"],
        "docId": doc_id
    }

    classify_attrs = {}

    if folder_id:
        classify_attrs["folder"] = folder_id
    if doc_type:
        classify_attrs["docart"] = doc_type
    if status:
        classify_attrs["status"] = status
    if bemerkung:
        classify_attrs["bemerkung"] = bemerkung

    # Parse custom attributes
    if custom_attributes:
        try:
            custom = json.loads(custom_attributes)
            classify_attrs.update(custom)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Ungültiges JSON für custom_attributes: {e}"}, indent=2)

    if classify_attrs:
        classify_data["classifyAttributes"] = classify_attrs

    result = api_request("classifyDocument", "POST", classify_data)

    if "error" in result:
        return json.dumps({"error": result["error"]}, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "message": "Dokument erfolgreich klassifiziert"
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_archive_file(
    file_path: str,
    folder_id: str = "",
    doc_type: str = "",
    status: str = "",
    bemerkung: str = "",
    version_controlled: bool = False
) -> str:
    """Archiviert und klassifiziert eine Datei in einem Schritt.

    Kombiniert ecodms_upload_document und ecodms_classify_document.
    WICHTIG: Verbraucht 1 API-Connect!

    Args:
        file_path: Pfad zur Datei
        folder_id: Ziel-Ordner ID
        doc_type: Dokumenttyp
        status: Status-Wert
        bemerkung: Bemerkung/Beschreibung
        version_controlled: Versionierung aktivieren

    Returns:
        Bestätigung mit Dokument-ID
    """
    # Upload
    upload_result = json.loads(ecodms_upload_document(file_path, version_controlled))

    if "error" in upload_result:
        return json.dumps(upload_result, indent=2, ensure_ascii=False)

    doc_id = upload_result.get("doc_id")

    if not doc_id:
        return json.dumps({"error": "Keine Dokument-ID erhalten"}, indent=2)

    # Classify
    classify_result = json.loads(ecodms_classify_document(
        doc_id=doc_id,
        folder_id=folder_id,
        doc_type=doc_type,
        status=status,
        bemerkung=bemerkung
    ))

    if "error" in classify_result:
        return json.dumps({
            "warning": "Dokument hochgeladen aber Klassifizierung fehlgeschlagen",
            "doc_id": doc_id,
            "error": classify_result["error"]
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "filename": upload_result.get("filename"),
        "folder_id": folder_id,
        "doc_type": doc_type,
        "message": "Dokument erfolgreich archiviert und klassifiziert"
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_get_thumbnail(doc_id: str, page: int = 1, height: int = 200) -> str:
    """Generiert URL für Dokument-Vorschaubild.

    Thumbnails verbrauchen KEINE API-Connects und sind ideal
    um Dokumente vor dem Download zu prüfen.

    Args:
        doc_id: Dokument-ID
        page: Seitennummer (Standard: 1)
        height: Höhe in Pixel (Standard: 200)

    Returns:
        URL zum Thumbnail-Bild
    """
    config = get_config()

    thumbnail_url = f"{config['url']}/api/thumbnail/{doc_id}/page/{page}/height/{height}"

    return json.dumps({
        "doc_id": doc_id,
        "page": page,
        "height": height,
        "url": thumbnail_url,
        "hint": "URL erfordert Basic Auth. Thumbnail-Abruf verbraucht keine API-Connects."
    }, indent=2)


@mcp.tool()
def ecodms_close_connection() -> str:
    """Trennt die Verbindung zum ecoDMS-Server.

    Sollte am Ende einer Session aufgerufen werden um Ressourcen freizugeben.

    Returns:
        Bestätigung der Trennung
    """
    config = get_config()
    disconnect()

    return json.dumps({
        "disconnected": True,
        "server": config["url"],
        "message": "Verbindung getrennt"
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def ecodms_test_connection() -> str:
    """Testet die Verbindung zum ecoDMS-Server.

    Versucht zwei Authentifizierungsmethoden:
    1. Session-basiert: /connect/{archive_id}
    2. Direct Basic Auth auf Endpoints

    Returns:
        Verbindungsstatus und Server-Info
    """
    global _connected

    config = get_config()

    # Debug: Show what config is being used
    mcp_log(f"[ecoDMS] Config: url={config['url']}, user={config['username']}, archive={config['archive_id']}")

    # Disconnect any existing session first
    disconnect()

    # Try to connect
    result = ensure_connected()

    if "error" in result:
        return json.dumps({
            "connected": False,
            "server": config["url"],
            "username": config["username"],
            "archive_id": config["archive_id"],
            "error": result["error"]
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "connected": True,
        "server": config["url"],
        "username": config["username"],
        "archive_id": config["archive_id"],
        "auth_method": result.get("method", "unknown"),
        "message": "Verbindung erfolgreich"
    }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
