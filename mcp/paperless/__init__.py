#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Paperless-ngx MCP Server
========================
MCP Server for Paperless-ngx Document Management System API.
Enables searching, uploading, and managing documents in Paperless-ngx.

API-Documentation: https://docs.paperless-ngx.com/api/

Authentication:
- Token Auth (preferred): Authorization: Token <token>
- Basic Auth: Authorization: Basic <base64(username:password)>
- Obtain token via POST /api/token/ with username/password
"""

import json
import base64
from pathlib import Path
from datetime import datetime
import urllib.request
import urllib.error
import urllib.parse
from mcp.server.fastmcp import FastMCP

# DeskAgent MCP API (provides config, paths, logging via HTTP)
from _mcp_api import load_config, get_temp_dir, get_exports_dir, mcp_log, register_link
from _link_utils import make_link_ref, LINK_TYPE_DOCUMENT

mcp = FastMCP("paperless")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "description",
    "color": "#607d8b"
}

# Integration schema for WebUI Integrations Hub
INTEGRATION_SCHEMA = {
    "name": "Paperless-ngx",
    "icon": "description",
    "color": "#607d8b",
    "config_key": "paperless",
    "auth_type": "api_key",
    "fields": [
        {
            "key": "url",
            "label": "Server URL",
            "type": "url",
            "required": True,
            "hint": "Paperless-ngx URL (z.B. http://localhost:8000)",
        },
        {
            "key": "token",
            "label": "API Token",
            "type": "password",
            "required": False,
            "hint": "Paperless API Token (Admin > Token) - oder Username/Password nutzen",
        },
        {
            "key": "username",
            "label": "Username",
            "type": "text",
            "required": False,
            "hint": "Alternative: Paperless Benutzername",
        },
        {
            "key": "password",
            "label": "Password",
            "type": "password",
            "required": False,
            "hint": "Alternative: Paperless Passwort",
        },
    ],
    "test_tool": "paperless_get_tags",
    "setup": {
        "description": "Dokumentenarchiv mit OCR",
        "requirement": "Paperless Server URL + Token",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Paperless URL und Token eintragen",
        ],
    },
}

# High-risk tools that return external content (for sanitization proxy)
HIGH_RISK_TOOLS = {
    "paperless_search_documents",
    "paperless_get_document",
    "paperless_get_document_content",
    "paperless_batch_get_document_contents",
    "paperless_find_similar_documents",
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    # Document operations
    "paperless_upload_document",
    "paperless_update_document",
    "paperless_delete_document",
    "paperless_bulk_edit_documents",
    "paperless_batch_classify_documents",
    # Metadata management
    "paperless_create_tag",
    "paperless_update_tag",
    "paperless_delete_tag",
    "paperless_create_correspondent",
    "paperless_delete_correspondent",
    "paperless_create_document_type",
    "paperless_delete_document_type",
    "paperless_create_storage_path",
    # Task management
    "paperless_acknowledge_tasks",
}

# Read-only tools that only retrieve data without modifications
# Used by tool_mode: "read_only" to allow only safe operations
READ_ONLY_TOOLS = {
    # Document reading
    "paperless_search_documents",
    "paperless_get_document",
    "paperless_get_document_content",
    "paperless_batch_get_document_contents",
    "paperless_download_document",
    "paperless_export_document_pdf",
    "paperless_batch_export_documents",
    "paperless_find_similar_documents",
    # Metadata reading
    "paperless_get_tags",
    "paperless_get_correspondents",
    "paperless_get_document_types",
    "paperless_get_storage_paths",
    "paperless_get_custom_fields",
    "paperless_get_document_custom_field",
    "paperless_get_saved_views",
    # Status/search
    "paperless_test_connection",
    "paperless_get_token",
    "paperless_get_task_status",
    "paperless_search_autocomplete",
}

# =============================================================================
# Configuration
# =============================================================================


def get_config() -> dict:
    """Load Paperless-ngx configuration from apis.json."""
    config = load_config()
    paperless = config.get("paperless", {})

    return {
        "url": paperless.get("url", "http://localhost:8000").rstrip("/"),
        "token": paperless.get("token", ""),
        "username": paperless.get("username", ""),
        "password": paperless.get("password", ""),
        "api_version": paperless.get("api_version", 5),
    }


def is_configured() -> bool:
    """Check if Paperless-ngx is configured and enabled."""
    config = load_config()
    paperless = config.get("paperless", {})

    # Check enabled flag (default: True if not set)
    if paperless.get("enabled") is False:
        return False

    # Need URL and either token or username/password
    url = paperless.get("url", "")
    token = paperless.get("token", "")
    username = paperless.get("username", "")
    password = paperless.get("password", "")

    return bool(url and (token or (username and password)))


# =============================================================================
# API Request Helper
# =============================================================================


def api_request(
    endpoint: str,
    method: str = "GET",
    data: dict = None,
    params: dict = None,
    file_path: str = None,
    raw_response: bool = False
) -> dict | bytes:
    """Execute Paperless-ngx API request.

    Args:
        endpoint: API endpoint (without /api/ prefix)
        method: HTTP method (GET, POST, PATCH, DELETE)
        data: JSON body data
        params: Query parameters
        file_path: Path to file for multipart upload
        raw_response: Return raw bytes instead of JSON

    Returns:
        JSON response dict or raw bytes if raw_response=True
    """
    config = get_config()

    # Build URL with query parameters
    url = f"{config['url']}/api/{endpoint}"
    if params:
        query_string = urllib.parse.urlencode(params)
        url = f"{url}?{query_string}"

    # Build headers with authentication
    headers = {
        "Accept": f"application/json; version={config['api_version']}",
    }

    # Prefer token auth, fallback to basic auth
    if config["token"]:
        headers["Authorization"] = f"Token {config['token']}"
    elif config["username"] and config["password"]:
        credentials = base64.b64encode(
            f"{config['username']}:{config['password']}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {credentials}"
    else:
        return {"error": "No authentication configured. Set token or username/password in apis.json"}

    try:
        if file_path:
            # Multipart file upload
            return _upload_file(url, headers, file_path, data or {})

        # Regular JSON request
        body = None
        if data:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")

        request = urllib.request.Request(url, data=body, headers=headers, method=method)

        with urllib.request.urlopen(request, timeout=60) as response:
            if raw_response:
                return response.read()

            content = response.read().decode("utf-8")
            if content:
                return json.loads(content)
            return {"success": True}

    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body[:500]}
    except urllib.error.URLError as e:
        return {"error": f"Connection error: {str(e.reason)}"}
    except Exception as e:
        return {"error": str(e)}


def _upload_file(url: str, headers: dict, file_path: str, form_data: dict) -> dict:
    """Upload file with multipart/form-data."""
    import mimetypes
    import uuid

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    # Build multipart body
    body_parts = []

    # Add form fields
    for key, value in form_data.items():
        if value is not None:
            # Handle multiple values (e.g., tags)
            if isinstance(value, list):
                for v in value:
                    body_parts.append(
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                        f"{v}\r\n"
                    )
            else:
                body_parts.append(
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    f"{value}\r\n"
                )

    # Add file
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_content = path.read_bytes()

    body_parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    )

    # Combine parts
    body = "".join(body_parts).encode("utf-8") + file_content + f"\r\n--{boundary}--\r\n".encode("utf-8")

    try:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read().decode("utf-8")
            if content:
                return json.loads(content)
            return {"success": True}
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            pass
        return {"error": f"HTTP {e.code}: {e.reason}", "details": error_body[:500]}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Connection & Authentication
# =============================================================================


@mcp.tool()
def paperless_test_connection() -> str:
    """Test connection to Paperless-ngx server.

    Verifies that the API is reachable and authentication is valid.

    Returns:
        Connection status and server info
    """
    config = get_config()

    # Try to get server statistics
    result = api_request("statistics/")

    if "error" in result:
        return json.dumps({
            "connected": False,
            "server": config["url"],
            "auth_type": "token" if config["token"] else "basic",
            "error": result["error"],
            "details": result.get("details", "")
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "connected": True,
        "server": config["url"],
        "auth_type": "token" if config["token"] else "basic",
        "statistics": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_get_token(username: str, password: str) -> str:
    """Obtain API token for Paperless-ngx.

    Use this to get a token that can be stored in apis.json for future requests.
    Token authentication is more secure than storing username/password.

    Args:
        username: Paperless-ngx username
        password: Paperless-ngx password

    Returns:
        API token for authentication
    """
    config = get_config()
    url = f"{config['url']}/api/token/"

    try:
        data = json.dumps({"username": username, "password": password}).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        request = urllib.request.Request(url, data=data, headers=headers, method="POST")

        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            token = result.get("token", "")

            return json.dumps({
                "success": True,
                "token": token,
                "hint": "Add this token to apis.json under paperless.token"
            }, indent=2, ensure_ascii=False)

    except urllib.error.HTTPError as e:
        return json.dumps({
            "error": f"HTTP {e.code}: {e.reason}",
            "hint": "Check username and password"
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)


# =============================================================================
# Documents
# =============================================================================


@mcp.tool()
def paperless_search_documents(
    query: str = "",
    correspondent_id: int = None,
    correspondent_isnull: bool = None,
    document_type_id: int = None,
    tag_ids: str = "",
    storage_path_id: int = None,
    created_after: str = "",
    created_before: str = "",
    added_after: str = "",
    added_before: str = "",
    ordering: str = "-created",
    page: int = 1,
    page_size: int = 25,
    compact: bool = False
) -> str:
    """Search and list documents in Paperless-ngx.

    Args:
        query: Full-text search query (optional)
        correspondent_id: Filter by correspondent ID
        correspondent_isnull: Filter documents without correspondent (True) or with (False)
        document_type_id: Filter by document type ID
        tag_ids: Comma-separated tag IDs (e.g., "1,2,3")
        storage_path_id: Filter by storage path ID
        created_after: Filter documents created after date (YYYY-MM-DD)
        created_before: Filter documents created before date (YYYY-MM-DD)
        added_after: Filter documents added after date (YYYY-MM-DD)
        added_before: Filter documents added before date (YYYY-MM-DD)
        ordering: Sort order (e.g., "-created", "title", "-added")
        page: Page number (default: 1)
        page_size: Results per page (default: 25, max: 100)
        compact: If True, return only essential fields (id, title, created, correspondent, tags)
                 without content - much faster for batch operations!

    Returns:
        JSON with documents and pagination info
    """
    params = {
        "page": page,
        "page_size": min(page_size, 100),
        "ordering": ordering,
    }

    if query:
        params["query"] = query
    if correspondent_id:
        params["correspondent__id"] = correspondent_id
    if correspondent_isnull is not None:
        params["correspondent__isnull"] = "true" if correspondent_isnull else "false"
    if document_type_id:
        params["document_type__id"] = document_type_id
    if tag_ids:
        # Multiple tags: add each as separate param
        for tag_id in tag_ids.split(","):
            params[f"tags__id__all"] = tag_id.strip()
    if storage_path_id:
        params["storage_path__id"] = storage_path_id
    if created_after:
        params["created__date__gte"] = created_after  # >= inklusiv
    if created_before:
        params["created__date__lte"] = created_before  # <= inklusiv
    if added_after:
        params["added__date__gte"] = added_after  # >= inklusiv
    if added_before:
        params["added__date__lte"] = added_before  # <= inklusiv

    result = api_request("documents/", params=params)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    # Format response
    config = get_config()
    documents = result.get("results", [])

    if compact:
        # Compact mode: only essential fields (no content!) - much smaller response
        compact_docs = []
        for doc in documents:
            doc_id = str(doc.get("id", ""))
            link_ref = make_link_ref(doc_id, LINK_TYPE_DOCUMENT)
            web_link = f"{config['url']}/documents/{doc_id}/details"
            register_link(link_ref, web_link)
            compact_docs.append({
                "id": doc.get("id"),
                "link_ref": link_ref,
                "title": doc.get("title"),
                "created": doc.get("created", "")[:10] if doc.get("created") else "",  # Just date
                "correspondent": doc.get("correspondent"),
                "tags": doc.get("tags", []),
                "document_type": doc.get("document_type"),
                "storage_path": doc.get("storage_path"),
            })
        return json.dumps({
            "count": result.get("count", 0),
            "page": page,
            "page_size": page_size,
            "total_pages": (result.get("count", 0) + page_size - 1) // page_size,
            "documents": compact_docs
        }, indent=2, ensure_ascii=False)

    # Full mode: Add URLs (API + Web UI) and link_ref
    for doc in documents:
        doc_id = doc.get("id")
        doc_id_str = str(doc_id) if doc_id else ""
        link_ref = make_link_ref(doc_id_str, LINK_TYPE_DOCUMENT)
        web_link = f"{config['url']}/documents/{doc_id}/details"
        register_link(link_ref, web_link)
        doc["link_ref"] = link_ref
        doc["download_url"] = f"{config['url']}/api/documents/{doc_id}/download/"
        doc["preview_url"] = f"{config['url']}/api/documents/{doc_id}/preview/"
        doc["thumb_url"] = f"{config['url']}/api/documents/{doc_id}/thumb/"
        # Web UI link (for reports/output)
        doc["details_url"] = f"{config['url']}/documents/{doc_id}/details"

    return json.dumps({
        "count": result.get("count", 0),
        "page": page,
        "page_size": page_size,
        "total_pages": (result.get("count", 0) + page_size - 1) // page_size,
        "documents": documents
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_get_document(doc_id: int) -> str:
    """Get detailed information about a specific document.

    Args:
        doc_id: Document ID

    Returns:
        JSON with document metadata, tags, correspondent, etc.
    """
    result = api_request(f"documents/{doc_id}/")

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    # Add URLs and link_ref
    config = get_config()
    doc_id_str = str(doc_id)
    link_ref = make_link_ref(doc_id_str, LINK_TYPE_DOCUMENT)
    web_link = f"{config['url']}/documents/{doc_id}/details"
    register_link(link_ref, web_link)
    result["link_ref"] = link_ref
    result["download_url"] = f"{config['url']}/api/documents/{doc_id}/download/"
    result["preview_url"] = f"{config['url']}/api/documents/{doc_id}/preview/"
    result["thumb_url"] = f"{config['url']}/api/documents/{doc_id}/thumb/"

    return json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_get_document_content(doc_id: int) -> str:
    """Get the text content (OCR result) of a document.

    Useful for reading the actual content of a document without downloading.

    Args:
        doc_id: Document ID

    Returns:
        Extracted text content of the document
    """
    result = api_request(f"documents/{doc_id}/")

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    config = get_config()
    doc_id_str = str(doc_id)
    link_ref = make_link_ref(doc_id_str, LINK_TYPE_DOCUMENT)
    web_link = f"{config['url']}/documents/{doc_id}/details"
    register_link(link_ref, web_link)
    return json.dumps({
        "id": doc_id,
        "link_ref": link_ref,
        "title": result.get("title", ""),
        "content": result.get("content", ""),
        "created": result.get("created", ""),
        "correspondent": result.get("correspondent", None),
        "document_type": result.get("document_type", None),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_batch_get_document_contents(
    document_ids: str,
    max_content_length: int = 0
) -> str:
    """Get text content (OCR) for multiple documents in one call.

    This is MUCH more efficient than calling paperless_get_document_content
    multiple times when you need to analyze several documents.

    Args:
        document_ids: Comma-separated document IDs (e.g., "105,107,93,54")
        max_content_length: Truncate content to this length (0 = no limit).
                           For classification, 3000 chars is usually enough.
                           This SIGNIFICANTLY reduces context window usage!

    Returns:
        JSON with all documents' content, title, created date, etc.
        If truncated, includes "truncated": true flag per document.
    """
    doc_ids = [int(d.strip()) for d in document_ids.split(",") if d.strip()]

    if not doc_ids:
        return json.dumps({"error": "No document IDs provided"}, indent=2)

    config = get_config()
    documents = []
    errors = []

    for doc_id in doc_ids:
        result = api_request(f"documents/{doc_id}/")

        if "error" in result:
            errors.append({"doc_id": doc_id, "error": result.get("error", "Unknown error")})
            continue

        content = result.get("content", "")
        truncated = False

        # Truncate content if max_content_length is set
        if max_content_length > 0 and len(content) > max_content_length:
            content = content[:max_content_length] + "..."
            truncated = True

        doc_id_str = str(doc_id)
        link_ref = make_link_ref(doc_id_str, LINK_TYPE_DOCUMENT)
        web_link = f"{config['url']}/documents/{doc_id}/details"
        register_link(link_ref, web_link)
        doc_data = {
            "id": doc_id,
            "link_ref": link_ref,
            "title": result.get("title", ""),
            "content": content,
            "created": result.get("created", "")[:10] if result.get("created") else "",
            "correspondent": result.get("correspondent", None),
            "tags": result.get("tags", []),
            "storage_path": result.get("storage_path", None),
        }

        if truncated:
            doc_data["truncated"] = True

        documents.append(doc_data)

    return json.dumps({
        "count": len(documents),
        "documents": documents,
        "errors": errors if errors else None
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_download_document(
    doc_id: int,
    save_path: str = "",
    original: bool = False
) -> str:
    """Download a document from Paperless-ngx.

    Args:
        doc_id: Document ID
        save_path: Target folder (default: exports/)
        original: Download original file instead of archived version

    Returns:
        Path to downloaded file
    """
    # Get document info for filename
    info = api_request(f"documents/{doc_id}/")
    if "error" in info:
        return json.dumps(info, indent=2, ensure_ascii=False)

    # Determine filename
    if original:
        filename = info.get("original_file_name", f"document_{doc_id}")
        endpoint = f"documents/{doc_id}/download/?original=true"
    else:
        filename = info.get("archived_file_name", f"document_{doc_id}.pdf")
        endpoint = f"documents/{doc_id}/download/"

    # Download file
    file_data = api_request(endpoint, raw_response=True)

    if isinstance(file_data, dict) and "error" in file_data:
        return json.dumps(file_data, indent=2, ensure_ascii=False)

    # Save file
    if save_path:
        save_dir = Path(save_path)
        if not save_dir.is_absolute():
            save_dir = get_exports_dir() / save_path
    else:
        save_dir = get_exports_dir()

    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / filename
    file_path.write_bytes(file_data)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "path": str(file_path.resolve()),
        "filename": filename,
        "size": len(file_data)
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_export_document_pdf(
    doc_id: int,
    save_path: str = ""
) -> str:
    """Export a document with standardized naming: YYYY-MM-DD-[Korrespondent]-[doc_id].pdf

    Downloads the document and saves it with a filename based on the document's
    creation date, correspondent, and Paperless document ID for uniqueness.

    Args:
        doc_id: Document ID to export
        save_path: Target folder (default: exports/)

    Returns:
        Path to exported file with standardized name
    """
    # Get document info
    info = api_request(f"documents/{doc_id}/")
    if "error" in info:
        return json.dumps(info, indent=2, ensure_ascii=False)

    # Get creation date
    created = info.get("created", "")
    if created:
        # Parse ISO date format (e.g., "2024-12-15T00:00:00+01:00")
        try:
            date_part = created.split("T")[0]  # Get just the date part
            date_obj = datetime.strptime(date_part, "%Y-%m-%d")
            date_str = date_obj.strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Get correspondent name
    correspondent_id = info.get("correspondent")
    correspondent_name = "Unknown"
    if correspondent_id:
        corr_result = api_request(f"correspondents/{correspondent_id}/")
        if "error" not in corr_result:
            correspondent_name = corr_result.get("name", "Unknown")

    # Sanitize correspondent name for filename (remove invalid characters)
    safe_correspondent = "".join(c for c in correspondent_name if c.isalnum() or c in " -_").strip()
    safe_correspondent = safe_correspondent.replace(" ", "_")
    if not safe_correspondent:
        safe_correspondent = "Unknown"

    # Build filename: YYYY-MM-DD-[Korrespondent]-[doc_id]
    filename = f"{date_str}-{safe_correspondent}-{doc_id}.pdf"

    # Determine save directory
    if save_path:
        save_dir = Path(save_path)
        if not save_dir.is_absolute():
            save_dir = get_exports_dir() / save_path
    else:
        save_dir = get_exports_dir()

    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / filename

    # Download file
    endpoint = f"documents/{doc_id}/download/"
    file_data = api_request(endpoint, raw_response=True)

    if isinstance(file_data, dict) and "error" in file_data:
        return json.dumps(file_data, indent=2, ensure_ascii=False)

    # Save file
    file_path.write_bytes(file_data)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "path": str(file_path.resolve()),
        "filename": filename,
        "date": date_str,
        "correspondent": correspondent_name,
        "size": len(file_data)
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_batch_export_documents(
    document_ids: str,
    base_path: str,
    category_map: str = ""
) -> str:
    """Export multiple documents efficiently in a single call.

    This is MUCH faster than calling paperless_export_document_pdf multiple times
    because it caches correspondent lookups and processes documents in batch.

    Args:
        document_ids: Comma-separated document IDs (e.g., "105,107,93,54")
        base_path: Base export directory (e.g., "E:/exports/steuerberater_2026-01")
        category_map: Optional JSON mapping doc_ids to subdirectories:
                      '{"105": "Eingangsrechnungen", "54": "Kontoauszuege"}'
                      Documents not in map go to base_path directly.

    Returns:
        JSON summary with exported files and any errors
    """
    doc_ids = [int(d.strip()) for d in document_ids.split(",") if d.strip()]

    if not doc_ids:
        return json.dumps({"error": "No document IDs provided"}, indent=2)

    # Parse category map
    categories = {}
    if category_map:
        try:
            categories = json.loads(category_map)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid category_map JSON"}, indent=2)

    # Cache for correspondents (avoid repeated API calls)
    correspondent_cache = {}

    # Batch fetch all correspondents first
    corr_result = api_request("correspondents/", params={"page_size": 1000})
    if "error" not in corr_result:
        for c in corr_result.get("results", []):
            correspondent_cache[c["id"]] = c.get("name", "Unknown")

    base_dir = Path(base_path)
    base_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    errors = []

    for doc_id in doc_ids:
        try:
            # Get document info
            info = api_request(f"documents/{doc_id}/")
            if "error" in info:
                errors.append({"doc_id": doc_id, "error": info.get("error", "Unknown error")})
                continue

            # Get date
            created = info.get("created", "")
            if created:
                try:
                    date_str = created.split("T")[0]
                except (ValueError, IndexError):
                    date_str = datetime.now().strftime("%Y-%m-%d")
            else:
                date_str = datetime.now().strftime("%Y-%m-%d")

            # Get correspondent from cache
            correspondent_id = info.get("correspondent")
            correspondent_name = correspondent_cache.get(correspondent_id, "Unknown") if correspondent_id else "Unknown"

            # Sanitize name
            safe_correspondent = "".join(c for c in correspondent_name if c.isalnum() or c in " -_").strip()
            safe_correspondent = safe_correspondent.replace(" ", "_") or "Unknown"

            # Determine target directory
            category = categories.get(str(doc_id), "")
            if category:
                target_dir = base_dir / category
            else:
                target_dir = base_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            # Build filename
            filename = f"{date_str}-{safe_correspondent}-{doc_id}.pdf"
            file_path = target_dir / filename

            # Download
            file_data = api_request(f"documents/{doc_id}/download/", raw_response=True)
            if isinstance(file_data, dict) and "error" in file_data:
                errors.append({"doc_id": doc_id, "error": file_data.get("error", "Download failed")})
                continue

            # Save
            file_path.write_bytes(file_data)

            exported.append({
                "doc_id": doc_id,
                "path": str(file_path),
                "category": category or "(root)",
                "size": len(file_data)
            })

        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})

    return json.dumps({
        "success": True,
        "exported_count": len(exported),
        "error_count": len(errors),
        "exported": exported,
        "errors": errors if errors else None,
        "base_path": str(base_dir)
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_upload_document(
    file_path: str,
    title: str = "",
    correspondent_id: int = None,
    document_type_id: int = None,
    storage_path_id: int = None,
    tag_ids: str = "",
    created: str = "",
    archive_serial_number: str = ""
) -> str:
    """Upload a document to Paperless-ngx for processing.

    The document will be consumed and OCR processed by Paperless-ngx.
    Use get_task_status() to monitor the consumption progress.

    Args:
        file_path: Path to the document file
        title: Document title (optional, detected from content if empty)
        correspondent_id: Correspondent ID to assign
        document_type_id: Document type ID to assign
        storage_path_id: Storage path ID to assign (folder/location)
        tag_ids: Comma-separated tag IDs to assign (e.g., "1,2,3")
        created: Document date in YYYY-MM-DD format
        archive_serial_number: Archive serial number (ASN)

    Returns:
        Task ID for monitoring consumption status
    """
    path = Path(file_path)
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}"}, indent=2)

    # Build form data
    form_data = {}
    if title:
        form_data["title"] = title
    if correspondent_id:
        form_data["correspondent"] = correspondent_id
    if document_type_id:
        form_data["document_type"] = document_type_id
    if storage_path_id:
        form_data["storage_path"] = storage_path_id
    if tag_ids:
        form_data["tags"] = [int(t.strip()) for t in tag_ids.split(",")]
    if created:
        form_data["created"] = created
    if archive_serial_number:
        form_data["archive_serial_number"] = archive_serial_number

    result = api_request("documents/post_document/", file_path=str(path), data=form_data)

    # Handle error responses
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    # Response contains task_id for monitoring
    # API may return just a string (task_id) or a dict with task_id
    if isinstance(result, str):
        task_id = result
    else:
        task_id = result.get("task_id", result.get("task", ""))

    return json.dumps({
        "success": True,
        "task_id": task_id,
        "filename": path.name,
        "message": f"Document uploaded. Use get_task_status('{task_id}') to monitor progress."
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_update_document(
    doc_id: int,
    title: str = None,
    correspondent_id: int = None,
    document_type_id: int = None,
    storage_path_id: int = None,
    tag_ids: str = None,
    created: str = None,
    archive_serial_number: str = None
) -> str:
    """Update document metadata.

    Only specified fields will be updated, others remain unchanged.

    Args:
        doc_id: Document ID to update
        title: New title
        correspondent_id: New correspondent ID (0 to clear)
        document_type_id: New document type ID (0 to clear)
        storage_path_id: New storage path ID (0 to clear)
        tag_ids: New tag IDs as comma-separated string (e.g., "1,2,3")
        created: New document date (YYYY-MM-DD)
        archive_serial_number: New ASN

    Returns:
        Updated document data
    """
    data = {}

    if title is not None:
        data["title"] = title
    if correspondent_id is not None:
        data["correspondent"] = correspondent_id if correspondent_id > 0 else None
    if document_type_id is not None:
        data["document_type"] = document_type_id if document_type_id > 0 else None
    if storage_path_id is not None:
        data["storage_path"] = storage_path_id if storage_path_id > 0 else None
    if tag_ids is not None:
        data["tags"] = [int(t.strip()) for t in tag_ids.split(",")] if tag_ids else []
    if created is not None:
        data["created"] = created
    if archive_serial_number is not None:
        data["archive_serial_number"] = archive_serial_number

    if not data:
        return json.dumps({"error": "No fields to update specified"}, indent=2)

    result = api_request(f"documents/{doc_id}/", method="PATCH", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "updated_fields": list(data.keys()),
        "document": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_delete_document(doc_id: int) -> str:
    """Delete a document from Paperless-ngx.

    WARNING: This permanently deletes the document and cannot be undone!

    Args:
        doc_id: Document ID to delete

    Returns:
        Confirmation of deletion
    """
    result = api_request(f"documents/{doc_id}/", method="DELETE")

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "message": "Document permanently deleted"
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Bulk Operations
# =============================================================================


@mcp.tool()
def paperless_bulk_edit_documents(
    document_ids: str,
    operation: str,
    value: str = ""
) -> str:
    """Perform bulk operations on multiple documents.

    Args:
        document_ids: Comma-separated document IDs (e.g., "1,2,3")
        operation: One of:
            - set_correspondent: Set correspondent (value = correspondent_id)
            - set_document_type: Set document type (value = document_type_id)
            - set_storage_path: Set storage path (value = storage_path_id)
            - add_tag: Add tag (value = tag_id)
            - remove_tag: Remove tag (value = tag_id)
            - delete: Delete documents (no value needed)
            - reprocess: Re-run OCR (no value needed)
        value: Value for the operation (ID as string)

    Returns:
        Operation result
    """
    doc_ids = [int(d.strip()) for d in document_ids.split(",")]

    data = {
        "documents": doc_ids,
        "method": operation,
    }

    # Add parameters based on operation
    if operation in ["set_correspondent", "set_document_type", "set_storage_path", "add_tag", "remove_tag"]:
        if not value:
            return json.dumps({"error": f"Operation '{operation}' requires a value"}, indent=2)
        data["parameters"] = {operation.replace("set_", "").replace("add_", "").replace("remove_", ""): int(value)}
    elif operation == "modify_tags":
        # Expects JSON: {"add_tags": [1,2], "remove_tags": [3]}
        try:
            data["parameters"] = json.loads(value)
        except json.JSONDecodeError:
            return json.dumps({"error": "modify_tags requires JSON value like {\"add_tags\": [1], \"remove_tags\": [2]}"}, indent=2)

    result = api_request("documents/bulk_edit/", method="POST", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "operation": operation,
        "affected_documents": len(doc_ids),
        "result": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_batch_classify_documents(classifications: str) -> str:
    """Classify multiple documents in a single call.

    This is optimized for auto-tagging workflows where each document needs:
    - A specific correspondent (may need to be created)
    - Specific tags
    - Optional storage path (may need to be created)

    The function will:
    1. Create any missing correspondents
    2. Create any missing storage paths
    3. Update each document with correspondent + tags + storage path

    Args:
        classifications: JSON array of classification objects:
            [
                {
                    "doc_id": 123,
                    "correspondent_name": "EnBW Energie",  # Will create if not exists
                    "correspondent_id": null,  # OR use existing ID (takes precedence)
                    "tag_ids": "7,3",  # Comma-separated tag IDs
                    "storage_path_name": "Privat",  # Optional: Will create if not exists
                    "storage_path_id": null,  # OR use existing ID (takes precedence)
                    "created": "2025-01-15",  # Optional: Document date (YYYY-MM-DD)
                    "title": "2025-065"  # Optional: New document title
                },
                ...
            ]

    Returns:
        Summary of updates performed
    """
    try:
        items = json.loads(classifications)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"}, indent=2)

    if not isinstance(items, list):
        return json.dumps({"error": "classifications must be a JSON array"}, indent=2)

    # First, get existing correspondents to avoid duplicates
    corr_result = api_request("correspondents/", params={"page_size": 1000})
    if "error" in corr_result:
        error_msg = f"Failed to get correspondents: {corr_result['error']}"
        if "details" in corr_result:
            error_msg += f" - {corr_result['details']}"
        return json.dumps({"error": error_msg}, indent=2)

    existing_correspondents = {
        c["name"].lower(): c["id"]
        for c in corr_result.get("results", [])
    }

    # Get existing storage paths
    sp_result = api_request("storage_paths/", params={"page_size": 1000})
    if "error" in sp_result:
        error_msg = f"Failed to get storage paths: {sp_result['error']}"
        if "details" in sp_result:
            error_msg += f" - {sp_result['details']}"
        return json.dumps({"error": error_msg}, indent=2)

    existing_storage_paths = {
        sp["name"].lower(): sp["id"]
        for sp in sp_result.get("results", [])
    }

    # Track results
    results = {
        "success": True,
        "documents_updated": 0,
        "correspondents_created": [],
        "storage_paths_created": [],
        "errors": [],
        "details": []
    }

    # Process each classification
    for item in items:
        doc_id = item.get("doc_id")
        correspondent_name = item.get("correspondent_name", "")
        correspondent_id = item.get("correspondent_id")
        tag_ids = item.get("tag_ids", "")
        storage_path_name = item.get("storage_path_name", "")
        storage_path_id = item.get("storage_path_id")
        created_date = item.get("created", "")
        new_title = item.get("title", "")

        if not doc_id:
            results["errors"].append({"error": "Missing doc_id", "item": item})
            continue

        # Resolve correspondent
        final_correspondent_id = correspondent_id
        if not final_correspondent_id and correspondent_name:
            # Check if exists (case-insensitive)
            final_correspondent_id = existing_correspondents.get(correspondent_name.lower())

            if not final_correspondent_id:
                # Create new correspondent
                create_result = api_request("correspondents/", method="POST", data={"name": correspondent_name})
                if "error" in create_result:
                    error_msg = f"Failed to create correspondent '{correspondent_name}': {create_result['error']}"
                    if "details" in create_result:
                        error_msg += f" - {create_result['details']}"
                    results["errors"].append({
                        "doc_id": doc_id,
                        "error": error_msg
                    })
                    continue
                final_correspondent_id = create_result.get("id")
                existing_correspondents[correspondent_name.lower()] = final_correspondent_id
                results["correspondents_created"].append({"name": correspondent_name, "id": final_correspondent_id})

        # Resolve storage path
        final_storage_path_id = storage_path_id
        if not final_storage_path_id and storage_path_name:
            # Check if exists (case-insensitive)
            final_storage_path_id = existing_storage_paths.get(storage_path_name.lower())

            if not final_storage_path_id:
                # Create new storage path (using name as path template)
                create_result = api_request("storage_paths/", method="POST", data={
                    "name": storage_path_name,
                    "path": storage_path_name  # Simple path = folder name
                })
                if "error" in create_result:
                    error_msg = f"Failed to create storage path '{storage_path_name}': {create_result['error']}"
                    if "details" in create_result:
                        error_msg += f" - {create_result['details']}"
                    results["errors"].append({
                        "doc_id": doc_id,
                        "error": error_msg
                    })
                    continue
                final_storage_path_id = create_result.get("id")
                existing_storage_paths[storage_path_name.lower()] = final_storage_path_id
                results["storage_paths_created"].append({"name": storage_path_name, "id": final_storage_path_id})

        # Build update data
        update_data = {}
        if final_correspondent_id:
            update_data["correspondent"] = final_correspondent_id
        if tag_ids:
            update_data["tags"] = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        if final_storage_path_id:
            update_data["storage_path"] = final_storage_path_id
        if created_date:
            update_data["created"] = created_date
        if new_title:
            update_data["title"] = new_title

        if not update_data:
            results["errors"].append({"doc_id": doc_id, "error": "Nothing to update"})
            continue

        # Update document
        update_result = api_request(f"documents/{doc_id}/", method="PATCH", data=update_data)
        if "error" in update_result:
            error_msg = f"Update failed: {update_result['error']}"
            if "details" in update_result:
                error_msg += f" - {update_result['details']}"
            results["errors"].append({
                "doc_id": doc_id,
                "error": error_msg
            })
        else:
            results["documents_updated"] += 1
            detail = {
                "doc_id": doc_id,
                "correspondent_id": final_correspondent_id,
                "storage_path_id": final_storage_path_id,
                "tags": update_data.get("tags", [])
            }
            if created_date:
                detail["created"] = created_date
            results["details"].append(detail)

    if results["errors"]:
        results["success"] = False

    return json.dumps(results, indent=2, ensure_ascii=False)


# =============================================================================
# Tags
# =============================================================================


@mcp.tool()
def paperless_get_tags() -> str:
    """List all tags in Paperless-ngx.

    Returns:
        JSON with all tags (id, name, color, document_count)
    """
    result = api_request("tags/", params={"page_size": 1000})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    tags = result.get("results", [])

    return json.dumps({
        "count": len(tags),
        "tags": [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "slug": t.get("slug"),
                "color": t.get("color"),
                "text_color": t.get("text_color"),
                "is_inbox_tag": t.get("is_inbox_tag", False),
                "document_count": t.get("document_count", 0),
            }
            for t in tags
        ]
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_create_tag(
    name: str,
    color: str = "#a6cee3",
    is_inbox_tag: bool = False,
    matching_algorithm: int = 0
) -> str:
    """Create a new tag.

    Args:
        name: Tag name
        color: Hex color code (e.g., "#a6cee3")
        is_inbox_tag: Mark as inbox tag (auto-assign to new docs)
        matching_algorithm: 0=None, 1=Any, 2=All, 3=Literal, 4=Regex, 5=Fuzzy

    Returns:
        Created tag data
    """
    data = {
        "name": name,
        "color": color,
        "is_inbox_tag": is_inbox_tag,
        "matching_algorithm": matching_algorithm,
    }

    result = api_request("tags/", method="POST", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "tag": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_update_tag(
    tag_id: int,
    name: str = None,
    color: str = None,
    is_inbox_tag: bool = None
) -> str:
    """Update an existing tag.

    Args:
        tag_id: Tag ID to update
        name: New name
        color: New hex color
        is_inbox_tag: New inbox tag status

    Returns:
        Updated tag data
    """
    data = {}
    if name is not None:
        data["name"] = name
    if color is not None:
        data["color"] = color
    if is_inbox_tag is not None:
        data["is_inbox_tag"] = is_inbox_tag

    if not data:
        return json.dumps({"error": "No fields to update"}, indent=2)

    result = api_request(f"tags/{tag_id}/", method="PATCH", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "tag": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_delete_tag(tag_id: int) -> str:
    """Delete a tag.

    Documents with this tag will have the tag removed.

    Args:
        tag_id: Tag ID to delete

    Returns:
        Deletion confirmation
    """
    result = api_request(f"tags/{tag_id}/", method="DELETE")

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "tag_id": tag_id,
        "message": "Tag deleted"
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Correspondents
# =============================================================================


@mcp.tool()
def paperless_get_correspondents() -> str:
    """List all correspondents in Paperless-ngx.

    Returns:
        JSON with all correspondents (id, name, document_count)
    """
    result = api_request("correspondents/", params={"page_size": 1000})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    correspondents = result.get("results", [])

    return json.dumps({
        "count": len(correspondents),
        "correspondents": [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "slug": c.get("slug"),
                "match": c.get("match"),
                "matching_algorithm": c.get("matching_algorithm"),
                "document_count": c.get("document_count", 0),
            }
            for c in correspondents
        ]
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_create_correspondent(
    name: str,
    match: str = "",
    matching_algorithm: int = 0
) -> str:
    """Create a new correspondent.

    Args:
        name: Correspondent name
        match: Match pattern for auto-assignment
        matching_algorithm: 0=None, 1=Any, 2=All, 3=Literal, 4=Regex, 5=Fuzzy

    Returns:
        Created correspondent data
    """
    data = {
        "name": name,
        "match": match,
        "matching_algorithm": matching_algorithm,
    }

    result = api_request("correspondents/", method="POST", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "correspondent": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_delete_correspondent(correspondent_id: int) -> str:
    """Delete a correspondent.

    Args:
        correspondent_id: Correspondent ID to delete

    Returns:
        Deletion confirmation
    """
    result = api_request(f"correspondents/{correspondent_id}/", method="DELETE")

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "correspondent_id": correspondent_id,
        "message": "Correspondent deleted"
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Document Types
# =============================================================================


@mcp.tool()
def paperless_get_document_types() -> str:
    """List all document types in Paperless-ngx.

    Returns:
        JSON with all document types (id, name, document_count)
    """
    result = api_request("document_types/", params={"page_size": 1000})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    doc_types = result.get("results", [])

    return json.dumps({
        "count": len(doc_types),
        "document_types": [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "slug": d.get("slug"),
                "match": d.get("match"),
                "matching_algorithm": d.get("matching_algorithm"),
                "document_count": d.get("document_count", 0),
            }
            for d in doc_types
        ]
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_create_document_type(
    name: str,
    match: str = "",
    matching_algorithm: int = 0
) -> str:
    """Create a new document type.

    Args:
        name: Document type name
        match: Match pattern for auto-assignment
        matching_algorithm: 0=None, 1=Any, 2=All, 3=Literal, 4=Regex, 5=Fuzzy

    Returns:
        Created document type data
    """
    data = {
        "name": name,
        "match": match,
        "matching_algorithm": matching_algorithm,
    }

    result = api_request("document_types/", method="POST", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "document_type": result
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_delete_document_type(document_type_id: int) -> str:
    """Delete a document type.

    Args:
        document_type_id: Document type ID to delete

    Returns:
        Deletion confirmation
    """
    result = api_request(f"document_types/{document_type_id}/", method="DELETE")

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "document_type_id": document_type_id,
        "message": "Document type deleted"
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Storage Paths
# =============================================================================


@mcp.tool()
def paperless_get_storage_paths() -> str:
    """List all storage paths in Paperless-ngx.

    Returns:
        JSON with all storage paths
    """
    result = api_request("storage_paths/", params={"page_size": 1000})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    paths = result.get("results", [])

    return json.dumps({
        "count": len(paths),
        "storage_paths": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "slug": p.get("slug"),
                "path": p.get("path"),
                "document_count": p.get("document_count", 0),
            }
            for p in paths
        ]
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_create_storage_path(
    name: str,
    path: str,
    matching_algorithm: int = 0,
    match: str = ""
) -> str:
    """Create a new storage path.

    Args:
        name: Storage path name
        path: Path template (supports placeholders like {correspondent}, {document_type})
        matching_algorithm: 0=None, 1=Any, 2=All, 3=Literal, 4=Regex, 5=Fuzzy
        match: Match pattern for auto-assignment

    Returns:
        Created storage path data
    """
    data = {
        "name": name,
        "path": path,
        "matching_algorithm": matching_algorithm,
        "match": match,
    }

    result = api_request("storage_paths/", method="POST", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "storage_path": result
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Tasks
# =============================================================================


@mcp.tool()
def paperless_get_task_status(task_id: str = "") -> str:
    """Check status of document consumption tasks.

    Args:
        task_id: Specific task ID to check (optional, shows all if empty)

    Returns:
        Task status and progress information
    """
    params = {}
    if task_id:
        params["task_id"] = task_id

    result = api_request("tasks/", params=params)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    # Format task list
    tasks = result if isinstance(result, list) else result.get("results", [result])

    formatted_tasks = []
    for task in tasks:
        formatted_tasks.append({
            "id": task.get("id") or task.get("task_id"),
            "status": task.get("status"),
            "task_file_name": task.get("task_file_name"),
            "date_created": task.get("date_created"),
            "date_done": task.get("date_done"),
            "result": task.get("result"),
            "acknowledged": task.get("acknowledged", False),
        })

    return json.dumps({
        "count": len(formatted_tasks),
        "tasks": formatted_tasks
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_acknowledge_tasks(task_ids: str = "") -> str:
    """Acknowledge completed tasks to clear them from the queue.

    Args:
        task_ids: Comma-separated task IDs to acknowledge (empty = all)

    Returns:
        Acknowledgment result
    """
    data = {}
    if task_ids:
        data["tasks"] = [int(t.strip()) for t in task_ids.split(",")]

    result = api_request("tasks/acknowledge/", method="POST", data=data)

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "message": "Tasks acknowledged"
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Search & Autocomplete
# =============================================================================


@mcp.tool()
def paperless_search_autocomplete(term: str, limit: int = 10) -> str:
    """Get autocomplete suggestions for search terms.

    Args:
        term: Partial search term
        limit: Maximum suggestions (default: 10)

    Returns:
        List of suggested search terms
    """
    result = api_request("search/autocomplete/", params={"term": term, "limit": limit})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    return json.dumps({
        "term": term,
        "suggestions": result if isinstance(result, list) else []
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_find_similar_documents(doc_id: int, limit: int = 10) -> str:
    """Find documents similar to a given document.

    Uses Paperless-ngx's "more like this" feature based on document content.

    Args:
        doc_id: Reference document ID
        limit: Maximum results (default: 10)

    Returns:
        List of similar documents
    """
    result = api_request("documents/", params={
        "more_like_id": doc_id,
        "page_size": limit
    })

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    config = get_config()
    documents = result.get("results", [])

    similar_docs = []
    for d in documents:
        d_id = d.get("id")
        d_id_str = str(d_id) if d_id else ""
        link_ref = make_link_ref(d_id_str, LINK_TYPE_DOCUMENT)
        web_link = f"{config['url']}/documents/{d_id}/details"
        register_link(link_ref, web_link)
        similar_docs.append({
            "id": d_id,
            "link_ref": link_ref,
            "title": d.get("title"),
            "correspondent": d.get("correspondent"),
            "document_type": d.get("document_type"),
            "created": d.get("created"),
            "score": d.get("__search_hit__", {}).get("score"),
        })

    return json.dumps({
        "reference_doc_id": doc_id,
        "similar_documents": similar_docs
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Custom Fields
# =============================================================================


@mcp.tool()
def paperless_get_custom_fields() -> str:
    """List all custom fields defined in Paperless-ngx.

    Returns:
        JSON with all custom fields (id, name, data_type)
    """
    result = api_request("custom_fields/", params={"page_size": 1000})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    fields = result.get("results", [])

    return json.dumps({
        "count": len(fields),
        "custom_fields": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "data_type": f.get("data_type"),
            }
            for f in fields
        ]
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_set_document_custom_field(doc_id: int, field_name: str, value: str) -> str:
    """Set a custom field value for a document.

    Args:
        doc_id: Document ID
        field_name: Name of the custom field (e.g., "Steuerberater")
        value: Value to set (for text fields: string, for boolean: "true"/"false")

    Returns:
        Success message or error
    """
    # 1. Get custom field ID by name
    fields_result = api_request("custom_fields/", params={"page_size": 1000})
    if "error" in fields_result:
        return json.dumps(fields_result, indent=2, ensure_ascii=False)

    fields = fields_result.get("results", [])
    field_id = None
    field_type = None
    for f in fields:
        if f.get("name", "").lower() == field_name.lower():
            field_id = f.get("id")
            field_type = f.get("data_type")
            break

    if not field_id:
        return json.dumps({
            "error": f"Custom field '{field_name}' not found",
            "available_fields": [f.get("name") for f in fields]
        }, indent=2, ensure_ascii=False)

    # 2. Get current document to preserve existing custom fields
    doc_result = api_request(f"documents/{doc_id}/")
    if "error" in doc_result:
        return json.dumps(doc_result, indent=2, ensure_ascii=False)

    current_fields = doc_result.get("custom_fields", [])

    # 3. Convert value based on field type
    converted_value = value
    if field_type == "boolean":
        converted_value = value.lower() in ("true", "1", "yes", "ja")
    elif field_type == "integer":
        try:
            converted_value = int(value)
        except ValueError:
            return json.dumps({"error": f"Invalid integer value: {value}"})
    elif field_type == "float":
        try:
            converted_value = float(value)
        except ValueError:
            return json.dumps({"error": f"Invalid float value: {value}"})

    # 4. Update or add the field
    field_found = False
    for cf in current_fields:
        if cf.get("field") == field_id:
            cf["value"] = converted_value
            field_found = True
            break

    if not field_found:
        current_fields.append({"field": field_id, "value": converted_value})

    # 5. Patch document
    patch_result = api_request(
        f"documents/{doc_id}/",
        method="PATCH",
        data={"custom_fields": current_fields}
    )

    if "error" in patch_result:
        return json.dumps(patch_result, indent=2, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "doc_id": doc_id,
        "field": field_name,
        "value": converted_value
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_bulk_set_custom_field(document_ids: str, field_name: str, value: str) -> str:
    """Set a custom field value for multiple documents efficiently.

    This is MUCH faster than calling paperless_set_document_custom_field multiple times
    because it caches the field lookup and processes documents in batch.

    Args:
        document_ids: Comma-separated document IDs (e.g., "105,107,93,54")
        field_name: Name of the custom field (e.g., "Steuerberater")
        value: Value to set for ALL documents

    Returns:
        Summary with success/error counts
    """
    doc_ids = [int(d.strip()) for d in document_ids.split(",") if d.strip()]

    if not doc_ids:
        return json.dumps({"error": "No document IDs provided"}, indent=2)

    # 1. Get custom field ID by name (ONE API call for all docs)
    fields_result = api_request("custom_fields/", params={"page_size": 1000})
    if "error" in fields_result:
        return json.dumps(fields_result, indent=2, ensure_ascii=False)

    fields = fields_result.get("results", [])
    field_id = None
    field_type = None
    for f in fields:
        if f.get("name", "").lower() == field_name.lower():
            field_id = f.get("id")
            field_type = f.get("data_type")
            break

    if not field_id:
        return json.dumps({
            "error": f"Custom field '{field_name}' not found",
            "available_fields": [f.get("name") for f in fields]
        }, indent=2, ensure_ascii=False)

    # 2. Convert value based on field type
    converted_value = value
    if field_type == "boolean":
        converted_value = value.lower() in ("true", "1", "yes", "ja")
    elif field_type == "integer":
        try:
            converted_value = int(value)
        except ValueError:
            return json.dumps({"error": f"Invalid integer value: {value}"})
    elif field_type == "float":
        try:
            converted_value = float(value)
        except ValueError:
            return json.dumps({"error": f"Invalid float value: {value}"})

    # 3. Update each document
    success_count = 0
    errors = []

    for doc_id in doc_ids:
        try:
            # Get current document custom fields
            doc_result = api_request(f"documents/{doc_id}/")
            if "error" in doc_result:
                errors.append({"doc_id": doc_id, "error": doc_result.get("error")})
                continue

            current_fields = doc_result.get("custom_fields", [])

            # Update or add the field
            field_found = False
            for cf in current_fields:
                if cf.get("field") == field_id:
                    cf["value"] = converted_value
                    field_found = True
                    break

            if not field_found:
                current_fields.append({"field": field_id, "value": converted_value})

            # Patch document
            patch_result = api_request(
                f"documents/{doc_id}/",
                method="PATCH",
                data={"custom_fields": current_fields}
            )

            if "error" in patch_result:
                errors.append({"doc_id": doc_id, "error": patch_result.get("error")})
            else:
                success_count += 1

        except Exception as e:
            errors.append({"doc_id": doc_id, "error": str(e)})

    return json.dumps({
        "success": True,
        "field": field_name,
        "value": converted_value,
        "updated_count": success_count,
        "error_count": len(errors),
        "errors": errors if errors else None
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def paperless_get_document_custom_field(doc_id: int, field_name: str) -> str:
    """Get a custom field value from a document.

    Args:
        doc_id: Document ID
        field_name: Name of the custom field (e.g., "Steuerberater")

    Returns:
        JSON with field value or null if not set
    """
    # 1. Get custom field ID by name
    fields_result = api_request("custom_fields/", params={"page_size": 1000})
    if "error" in fields_result:
        return json.dumps(fields_result, indent=2, ensure_ascii=False)

    fields = fields_result.get("results", [])
    field_id = None
    for f in fields:
        if f.get("name", "").lower() == field_name.lower():
            field_id = f.get("id")
            break

    if not field_id:
        return json.dumps({
            "error": f"Custom field '{field_name}' not found",
            "available_fields": [f.get("name") for f in fields]
        }, indent=2, ensure_ascii=False)

    # 2. Get document
    doc_result = api_request(f"documents/{doc_id}/")
    if "error" in doc_result:
        return json.dumps(doc_result, indent=2, ensure_ascii=False)

    # 3. Find field value
    current_fields = doc_result.get("custom_fields", [])
    for cf in current_fields:
        if cf.get("field") == field_id:
            return json.dumps({
                "doc_id": doc_id,
                "field": field_name,
                "value": cf.get("value")
            }, indent=2, ensure_ascii=False)

    return json.dumps({
        "doc_id": doc_id,
        "field": field_name,
        "value": None,
        "note": "Field not set on this document"
    }, indent=2, ensure_ascii=False)


# =============================================================================
# Saved Views
# =============================================================================


@mcp.tool()
def paperless_get_saved_views() -> str:
    """List all saved views (filters/searches) in Paperless-ngx.

    Returns:
        JSON with all saved views
    """
    result = api_request("saved_views/", params={"page_size": 1000})

    if "error" in result:
        return json.dumps(result, indent=2, ensure_ascii=False)

    views = result.get("results", [])

    return json.dumps({
        "count": len(views),
        "saved_views": [
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "show_on_dashboard": v.get("show_on_dashboard"),
                "show_in_sidebar": v.get("show_in_sidebar"),
                "filter_rules": v.get("filter_rules", []),
            }
            for v in views
        ]
    }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
