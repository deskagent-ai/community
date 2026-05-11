#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
LinkedIn MCP Server.

Funktionen:
- Posts erstellen und teilen (persönlich & Unternehmensseite)
- Nachrichten abrufen
- Unternehmensseiten verwalten
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import requests
from pathlib import Path
from functools import wraps

from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, get_config_dir, mcp_log

# MCP initialisieren
mcp = FastMCP("linkedin")

# UI Metadaten
TOOL_METADATA = {
    "icon": "share",
    "color": "#0A66C2",  # LinkedIn Blau
    "beta": True
}

# Tools die externe Inhalte zurückgeben (Prompt Injection Schutz)
HIGH_RISK_TOOLS = {
    "linkedin_get_messages",
    "linkedin_get_post_comments",
    "linkedin_get_company_posts",
}

# Tools die Daten modifizieren (Dry-Run Modus)
DESTRUCTIVE_TOOLS = {
    "linkedin_create_post",
    "linkedin_create_company_post",
    "linkedin_delete_post",
    "linkedin_send_message",
}

# Integration Schema for WebUI Integrationen tab
INTEGRATION_SCHEMA = {
    "name": "LinkedIn",
    "icon": "share",
    "color": "#0A66C2",
    "config_key": "linkedin",
    "auth_type": "oauth",
    "beta": True,  # Mark as beta feature
    "oauth": {
        "custom_auth": False,  # Uses generic OAuth flow
        "token_file": ".linkedin_token.json",
        "auth_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "scopes": ["openid", "profile", "w_member_social"],
        "scope_separator": " ",
        "config_keys": ["client_id", "client_secret"],
        "token_auth_method": "body",  # LinkedIn requires credentials in body
    },
    "setup": {
        "description": "LinkedIn Posts und Nachrichten",
        "requirement": "LinkedIn Account",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "LinkedIn verbinden",
        ],
    },
}

# OAuth Plugin Configuration - LEGACY, kept for compatibility
# TODO: Remove after full migration to INTEGRATION_SCHEMA
AUTH_CONFIG = {
    "type": "oauth2",
    "display_name": "LinkedIn",
    "auth_url": "https://www.linkedin.com/oauth/v2/authorization",
    "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
    "scopes": ["openid", "profile", "w_member_social"],
    "config_keys": ["client_id", "client_secret"],
    "token_file": ".linkedin_token.json",
    "scope_separator": " ",
    "token_auth_method": "body",  # LinkedIn requires credentials in body
}

# LinkedIn API Endpoints
API_BASE = "https://api.linkedin.com/v2"
API_REST = "https://api.linkedin.com/rest"

# Cache für API-Responses
_cache = {}
_cache_time = 0
CACHE_TTL = 300  # 5 Minuten


def get_config():
    """Lädt LinkedIn-Konfiguration."""
    config = load_config()
    return config.get("linkedin", {})


def _log(msg: str):
    """Log message to system.log via mcp_log."""
    mcp_log(f"[LinkedIn] {msg}")


def get_access_token() -> str | None:
    """
    Holt Access Token aus OAuth-Token-Datei oder Fallback aus apis.json.

    Returns:
        Access Token oder None wenn nicht vorhanden
    """
    # 1. Try OAuth token file first (new system)
    try:
        config_dir = get_config_dir()
        token_file = config_dir / AUTH_CONFIG["token_file"]
        _log(f"Token path: {token_file}")
        _log(f"Token exists: {token_file.exists()}")
        if token_file.exists():
            token_data = json.loads(token_file.read_text(encoding="utf-8"))
            access_token = token_data.get("access_token")
            if access_token:
                _log("Token loaded from OAuth file")
                return access_token
    except Exception as e:
        _log(f"Error loading token: {e}")

    # 2. Fallback to apis.json (legacy)
    config = get_config()
    return config.get("access_token")


def is_configured() -> bool:
    """Prüft ob LinkedIn MCP aktiviert und konfiguriert ist."""
    config = get_config()

    # Explizit deaktiviert?
    if config.get("enabled") is False:
        return False

    # Access Token vorhanden (OAuth file oder legacy)?
    access_token = get_access_token()
    return bool(access_token)


def linkedin_tool(func):
    """Decorator für einheitliches Error Handling."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            return f"Fehler: HTTP {e.code} - {error_body[:500]}"
        except Exception as e:
            return f"Fehler: {str(e)}"
    return wrapper


def api_request(
    endpoint: str,
    method: str = "GET",
    data: dict = None,
    use_rest_api: bool = False,
    api_version: str = "202601"
) -> dict:
    """
    HTTP Request an LinkedIn API.

    Args:
        endpoint: API-Endpoint (ohne Basis-URL)
        method: HTTP-Methode
        data: Request-Body (für POST/PUT)
        use_rest_api: True für neue REST API, False für v2 API
        api_version: API-Version für REST API Header
    """
    access_token = get_access_token()

    if not access_token:
        return {"error": "Kein Access Token konfiguriert. Bitte über WebUI Settings → Integrations verbinden."}

    base_url = API_REST if use_rest_api else API_BASE
    url = f"{base_url}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    # REST API benötigt Version Header
    if use_rest_api:
        headers["LinkedIn-Version"] = api_version

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_text = response.read().decode("utf-8")
            if response_text:
                return json.loads(response_text)
            return {"success": True}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        try:
            error_json = json.loads(error_body)
            return {"error": f"HTTP {e.code}", "details": error_json}
        except (json.JSONDecodeError, ValueError):
            return {"error": f"HTTP {e.code}: {error_body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def get_cached(key: str, fetch_fn):
    """Cache mit TTL."""
    global _cache, _cache_time

    if time.time() - _cache_time > CACHE_TTL:
        _cache = {}

    if key not in _cache:
        _cache[key] = fetch_fn()
        _cache_time = time.time()

    return _cache[key]


# =============================================================================
# Profil-Tools
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_get_profile() -> str:
    """
    Gibt das eigene LinkedIn-Profil zurück.

    Returns:
        JSON mit Profil-Informationen (ID, Name, Headline)
    """
    result = api_request("me", use_rest_api=True)

    if "error" in result:
        return f"Fehler: {result['error']}"

    profile = {
        "id": result.get("id"),
        "firstName": result.get("firstName", {}).get("localized", {}).get("de_DE") or
                     result.get("firstName", {}).get("localized", {}).get("en_US"),
        "lastName": result.get("lastName", {}).get("localized", {}).get("de_DE") or
                    result.get("lastName", {}).get("localized", {}).get("en_US"),
        "headline": result.get("headline", {}).get("localized", {}).get("de_DE") or
                    result.get("headline", {}).get("localized", {}).get("en_US"),
        "vanityName": result.get("vanityName"),
    }

    return json.dumps(profile, ensure_ascii=False, indent=2)


@mcp.tool()
@linkedin_tool
def linkedin_get_person_id() -> str:
    """
    Gibt die eigene LinkedIn Person-ID zurück (URN-Format).

    Benötigt für Posts und andere API-Aufrufe.

    Returns:
        Person-URN, z.B. "urn:li:person:ABC123"
    """
    # Versuche zuerst userinfo Endpoint (OpenID Connect)
    result = api_request("userinfo", use_rest_api=False)

    if "error" not in result:
        # userinfo gibt 'sub' als Person-ID zurück
        person_id = result.get("sub")
        if person_id:
            return f"urn:li:person:{person_id}"

    # Fallback: REST API /me Endpoint
    result = api_request("me", use_rest_api=True)

    if "error" in result:
        return f"Fehler: {result['error']}"

    person_id = result.get("id")
    if person_id:
        return f"urn:li:person:{person_id}"

    return "Fehler: Keine Person-ID gefunden"


# =============================================================================
# Post-Tools (Persönlich)
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_create_post(text: str, visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen neuen LinkedIn-Post auf dem persönlichen Profil.

    Args:
        text: Der Text des Posts (max. 3000 Zeichen)
        visibility: Sichtbarkeit - "PUBLIC" (alle), "CONNECTIONS" (nur Kontakte)

    Returns:
        Post-ID bei Erfolg, Fehlermeldung sonst
    """
    if len(text) > 3000:
        return "Fehler: Text darf maximal 3000 Zeichen haben"

    # Person-ID abrufen (zuerst userinfo, dann REST API)
    me = api_request("userinfo", use_rest_api=False)
    person_id = me.get("sub") if "error" not in me else None

    if not person_id:
        # Fallback: REST API /me Endpoint
        me = api_request("me", use_rest_api=True)
        if "error" in me:
            return f"Fehler beim Abrufen der Person-ID: {me['error']}"
        person_id = me.get("id")

    if not person_id:
        return "Fehler: Keine Person-ID gefunden"

    person_urn = f"urn:li:person:{person_id}"

    # Post erstellen (UGC Post API)
    post_data = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get("id", "")
    # Generate post URL (format: urn:li:share:123456 -> https://www.linkedin.com/feed/update/urn:li:share:123456)
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Post erfolgreich erstellt. ID: {post_id}\nLink: {post_url}"


@mcp.tool()
@linkedin_tool
def linkedin_create_post_with_link(text: str, url: str, title: str = "", description: str = "", visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen LinkedIn-Post mit Link-Preview.

    Args:
        text: Der Text des Posts
        url: Die URL die geteilt werden soll
        title: Optionaler Titel für den Link
        description: Optionale Beschreibung für den Link
        visibility: "PUBLIC" oder "CONNECTIONS"

    Returns:
        Post-ID bei Erfolg
    """
    # Person-ID abrufen (zuerst userinfo, dann REST API)
    me = api_request("userinfo", use_rest_api=False)
    person_id = me.get("sub") if "error" not in me else None

    if not person_id:
        me = api_request("me", use_rest_api=True)
        if "error" in me:
            return f"Fehler: {me['error']}"
        person_id = me.get("id")

    if not person_id:
        return "Fehler: Keine Person-ID gefunden"

    person_urn = f"urn:li:person:{person_id}"

    post_data = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "ARTICLE",
                "media": [{
                    "status": "READY",
                    "originalUrl": url,
                    "title": {"text": title} if title else None,
                    "description": {"text": description} if description else None
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    # None-Werte entfernen
    media = post_data["specificContent"]["com.linkedin.ugc.ShareContent"]["media"][0]
    if media.get("title") is None:
        del media["title"]
    if media.get("description") is None:
        del media["description"]

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get('id', '')
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Post mit Link erfolgreich erstellt. ID: {post_id}\nLink: {post_url}"


def _register_image_upload(person_urn: str) -> dict:
    """
    Registriert einen Bild-Upload bei LinkedIn.

    Returns:
        Dict mit 'upload_url' und 'asset' (URN) oder 'error'
    """
    register_data = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent"
            }]
        }
    }

    result = api_request("assets?action=registerUpload", method="POST", data=register_data)

    if "error" in result:
        return {"error": result.get("error")}

    value = result.get("value", {})
    upload_mechanism = value.get("uploadMechanism", {})
    upload_request = upload_mechanism.get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})

    return {
        "upload_url": upload_request.get("uploadUrl"),
        "asset": value.get("asset")
    }


def _upload_image_binary(upload_url: str, image_path: str) -> dict:
    """
    Lädt das Bild zur registrierten URL hoch.

    Args:
        upload_url: Die von LinkedIn bereitgestellte Upload-URL
        image_path: Lokaler Pfad zur Bilddatei

    Returns:
        Dict mit 'success' oder 'error'
    """
    import os
    from pathlib import Path

    path = Path(image_path)
    if not path.exists():
        return {"error": f"Datei nicht gefunden: {image_path}"}

    # MIME-Type bestimmen
    ext = path.suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif"
    }
    content_type = mime_types.get(ext, "application/octet-stream")

    access_token = get_access_token()
    if not access_token:
        return {"error": "Kein Access Token"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": content_type
    }

    try:
        with open(image_path, "rb") as f:
            image_data = f.read()

        response = requests.put(upload_url, headers=headers, data=image_data, timeout=60)

        if response.status_code in [200, 201]:
            return {"success": True}
        else:
            return {"error": f"Upload fehlgeschlagen: HTTP {response.status_code}"}

    except Exception as e:
        return {"error": f"Upload-Fehler: {str(e)}"}


@mcp.tool()
@linkedin_tool
def linkedin_create_post_with_image(text: str, image_path: str, visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen LinkedIn-Post mit Bild.

    Args:
        text: Der Post-Text (max. 3000 Zeichen)
        image_path: Lokaler Pfad zur Bilddatei (JPG, PNG, GIF)
        visibility: "PUBLIC" (alle) oder "CONNECTIONS" (nur Kontakte)

    Returns:
        Post-ID und Link bei Erfolg, Fehlermeldung sonst
    """
    if len(text) > 3000:
        return "Fehler: Text darf maximal 3000 Zeichen haben"

    # Person-ID abrufen
    me = api_request("userinfo", use_rest_api=False)
    person_id = me.get("sub") if "error" not in me else None

    if not person_id:
        me = api_request("me", use_rest_api=True)
        if "error" in me:
            return f"Fehler beim Abrufen der Person-ID: {me['error']}"
        person_id = me.get("id")

    if not person_id:
        return "Fehler: Keine Person-ID gefunden"

    person_urn = f"urn:li:person:{person_id}"

    # 1. Upload registrieren
    register_result = _register_image_upload(person_urn)
    if "error" in register_result:
        return f"Fehler bei Upload-Registrierung: {register_result['error']}"

    upload_url = register_result.get("upload_url")
    asset_urn = register_result.get("asset")

    if not upload_url or not asset_urn:
        return "Fehler: Keine Upload-URL erhalten"

    # 2. Bild hochladen
    upload_result = _upload_image_binary(upload_url, image_path)
    if "error" in upload_result:
        return f"Fehler beim Bild-Upload: {upload_result['error']}"

    # 3. Post mit Bild erstellen
    post_data = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "IMAGE",
                "media": [{
                    "status": "READY",
                    "media": asset_urn
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler beim Post erstellen: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get("id", "")
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Post mit Bild erfolgreich erstellt. ID: {post_id}\nLink: {post_url}"


def _register_video_upload(person_urn: str, file_size: int) -> dict:
    """
    Registriert einen Video-Upload bei LinkedIn.

    Args:
        person_urn: Die Person-URN des Uploaders
        file_size: Dateigröße in Bytes

    Returns:
        Dict mit 'upload_url' und 'asset' (URN) oder 'error'
    """
    register_data = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
            "owner": person_urn,
            "serviceRelationships": [{
                "relationshipType": "OWNER",
                "identifier": "urn:li:userGeneratedContent"
            }],
            "supportedUploadMechanism": ["SYNCHRONOUS_UPLOAD"],
            "fileSize": file_size
        }
    }

    result = api_request("assets?action=registerUpload", method="POST", data=register_data)

    if "error" in result:
        return {"error": result.get("error")}

    value = result.get("value", {})
    upload_mechanism = value.get("uploadMechanism", {})
    upload_request = upload_mechanism.get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest", {})

    return {
        "upload_url": upload_request.get("uploadUrl"),
        "asset": value.get("asset")
    }


def _upload_video_binary(upload_url: str, video_path: str) -> dict:
    """
    Lädt das Video zur registrierten URL hoch.

    Args:
        upload_url: Die von LinkedIn bereitgestellte Upload-URL
        video_path: Lokaler Pfad zur Videodatei

    Returns:
        Dict mit 'success' oder 'error'
    """
    from pathlib import Path

    path = Path(video_path)
    if not path.exists():
        return {"error": f"Datei nicht gefunden: {video_path}"}

    # MIME-Type bestimmen
    ext = path.suffix.lower()
    mime_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".webm": "video/webm"
    }
    content_type = mime_types.get(ext, "video/mp4")

    access_token = get_access_token()
    if not access_token:
        return {"error": "Kein Access Token"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": content_type
    }

    try:
        with open(video_path, "rb") as f:
            video_data = f.read()

        response = requests.put(upload_url, headers=headers, data=video_data, timeout=300)

        if response.status_code in [200, 201]:
            return {"success": True}
        else:
            return {"error": f"Upload fehlgeschlagen: HTTP {response.status_code}"}

    except Exception as e:
        return {"error": f"Upload-Fehler: {str(e)}"}


@mcp.tool()
@linkedin_tool
def linkedin_create_post_with_video(text: str, video_path: str, visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen LinkedIn-Post mit Video.

    Args:
        text: Der Post-Text (max. 3000 Zeichen)
        video_path: Lokaler Pfad zur Videodatei (MP4, MOV, AVI, WEBM - max. 200MB)
        visibility: "PUBLIC" (alle) oder "CONNECTIONS" (nur Kontakte)

    Returns:
        Post-ID und Link bei Erfolg, Fehlermeldung sonst
    """
    import os
    from pathlib import Path

    if len(text) > 3000:
        return "Fehler: Text darf maximal 3000 Zeichen haben"

    path = Path(video_path)
    if not path.exists():
        return f"Fehler: Video-Datei nicht gefunden: {video_path}"

    file_size = path.stat().st_size
    max_size = 200 * 1024 * 1024  # 200 MB

    if file_size > max_size:
        return f"Fehler: Video zu groß ({file_size / 1024 / 1024:.1f} MB). Maximum: 200 MB"

    # Person-ID abrufen
    me = api_request("userinfo", use_rest_api=False)
    person_id = me.get("sub") if "error" not in me else None

    if not person_id:
        me = api_request("me", use_rest_api=True)
        if "error" in me:
            return f"Fehler beim Abrufen der Person-ID: {me['error']}"
        person_id = me.get("id")

    if not person_id:
        return "Fehler: Keine Person-ID gefunden"

    person_urn = f"urn:li:person:{person_id}"

    # 1. Upload registrieren
    register_result = _register_video_upload(person_urn, file_size)
    if "error" in register_result:
        return f"Fehler bei Upload-Registrierung: {register_result['error']}"

    upload_url = register_result.get("upload_url")
    asset_urn = register_result.get("asset")

    if not upload_url or not asset_urn:
        return "Fehler: Keine Upload-URL erhalten"

    # 2. Video hochladen
    upload_result = _upload_video_binary(upload_url, video_path)
    if "error" in upload_result:
        return f"Fehler beim Video-Upload: {upload_result['error']}"

    # 3. Post mit Video erstellen
    post_data = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "VIDEO",
                "media": [{
                    "status": "READY",
                    "media": asset_urn
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler beim Post erstellen: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get("id", "")
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Post mit Video erfolgreich erstellt. ID: {post_id}\nLink: {post_url}"


@mcp.tool()
@linkedin_tool
def linkedin_delete_post(post_id: str) -> str:
    """
    Löscht einen eigenen LinkedIn-Post.

    Args:
        post_id: Die vollständige Post-ID (URN oder ID-String)

    Returns:
        Erfolgsmeldung oder Fehler
    """
    # URN normalisieren
    if not post_id.startswith("urn:"):
        post_id = f"urn:li:share:{post_id}"

    encoded_id = urllib.parse.quote(post_id, safe="")
    result = api_request(f"ugcPosts/{encoded_id}", method="DELETE")

    if "error" in result:
        return f"Fehler: {result['error']}"

    return "Post erfolgreich gelöscht"


# =============================================================================
# Unternehmensseiten-Tools
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_get_organizations() -> str:
    """
    Listet alle Unternehmensseiten auf, für die der User Admin-Rechte hat.

    Returns:
        JSON-Liste der Organisationen mit ID und Name
    """
    # Organisationen abrufen, bei denen User Admin ist
    result = api_request(
        "organizationalEntityAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED",
        use_rest_api=True
    )

    if "error" in result:
        return f"Fehler: {result['error']}"

    organizations = []
    for element in result.get("elements", []):
        org_urn = element.get("organizationalTarget")
        if org_urn:
            # Org-Details abrufen
            org_id = org_urn.split(":")[-1]
            org_details = api_request(f"organizations/{org_id}", use_rest_api=True)

            organizations.append({
                "urn": org_urn,
                "id": org_id,
                "name": org_details.get("localizedName", "Unbekannt"),
                "vanityName": org_details.get("vanityName"),
            })

    if not organizations:
        return "Keine Unternehmensseiten gefunden, für die Sie Admin-Rechte haben."

    return json.dumps(organizations, ensure_ascii=False, indent=2)


@mcp.tool()
@linkedin_tool
def linkedin_create_company_post(organization_id: str, text: str, visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen Post auf einer Unternehmensseite.

    Args:
        organization_id: Die Organisations-ID (Zahl oder vollständige URN)
        text: Der Text des Posts (max. 3000 Zeichen)
        visibility: "PUBLIC" oder "LOGGED_IN" (nur LinkedIn-Mitglieder)

    Returns:
        Post-ID bei Erfolg
    """
    if len(text) > 3000:
        return "Fehler: Text darf maximal 3000 Zeichen haben"

    # URN normalisieren
    if not organization_id.startswith("urn:"):
        org_urn = f"urn:li:organization:{organization_id}"
    else:
        org_urn = organization_id

    post_data = {
        "author": org_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get('id', '')
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Unternehmens-Post erfolgreich erstellt. ID: {post_id}\nLink: {post_url}"


@mcp.tool()
@linkedin_tool
def linkedin_create_company_post_with_image(organization_id: str, text: str, image_path: str, visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen Post mit Bild auf einer Unternehmensseite.

    Args:
        organization_id: Die Organisations-ID (Zahl oder vollständige URN)
        text: Der Text des Posts (max. 3000 Zeichen)
        image_path: Lokaler Pfad zur Bilddatei (JPG, PNG, GIF)
        visibility: "PUBLIC" oder "LOGGED_IN"

    Returns:
        Post-ID und Link bei Erfolg
    """
    if len(text) > 3000:
        return "Fehler: Text darf maximal 3000 Zeichen haben"

    # URN normalisieren
    if not organization_id.startswith("urn:"):
        org_urn = f"urn:li:organization:{organization_id}"
    else:
        org_urn = organization_id

    # 1. Upload registrieren (für Organization)
    register_result = _register_image_upload(org_urn)
    if "error" in register_result:
        return f"Fehler bei Upload-Registrierung: {register_result['error']}"

    upload_url = register_result.get("upload_url")
    asset_urn = register_result.get("asset")

    if not upload_url or not asset_urn:
        return "Fehler: Keine Upload-URL erhalten"

    # 2. Bild hochladen
    upload_result = _upload_image_binary(upload_url, image_path)
    if "error" in upload_result:
        return f"Fehler beim Bild-Upload: {upload_result['error']}"

    # 3. Post mit Bild erstellen
    post_data = {
        "author": org_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "IMAGE",
                "media": [{
                    "status": "READY",
                    "media": asset_urn
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get("id", "")
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Unternehmens-Post mit Bild erstellt. ID: {post_id}\nLink: {post_url}"


@mcp.tool()
@linkedin_tool
def linkedin_create_company_post_with_video(organization_id: str, text: str, video_path: str, visibility: str = "PUBLIC") -> str:
    """
    Erstellt einen Post mit Video auf einer Unternehmensseite.

    Args:
        organization_id: Die Organisations-ID (Zahl oder vollständige URN)
        text: Der Text des Posts (max. 3000 Zeichen)
        video_path: Lokaler Pfad zur Videodatei (MP4, MOV - max. 200MB)
        visibility: "PUBLIC" oder "LOGGED_IN"

    Returns:
        Post-ID und Link bei Erfolg
    """
    from pathlib import Path

    if len(text) > 3000:
        return "Fehler: Text darf maximal 3000 Zeichen haben"

    path = Path(video_path)
    if not path.exists():
        return f"Fehler: Video-Datei nicht gefunden: {video_path}"

    file_size = path.stat().st_size
    max_size = 200 * 1024 * 1024

    if file_size > max_size:
        return f"Fehler: Video zu groß ({file_size / 1024 / 1024:.1f} MB). Maximum: 200 MB"

    # URN normalisieren
    if not organization_id.startswith("urn:"):
        org_urn = f"urn:li:organization:{organization_id}"
    else:
        org_urn = organization_id

    # 1. Upload registrieren
    register_result = _register_video_upload(org_urn, file_size)
    if "error" in register_result:
        return f"Fehler bei Upload-Registrierung: {register_result['error']}"

    upload_url = register_result.get("upload_url")
    asset_urn = register_result.get("asset")

    if not upload_url or not asset_urn:
        return "Fehler: Keine Upload-URL erhalten"

    # 2. Video hochladen
    upload_result = _upload_video_binary(upload_url, video_path)
    if "error" in upload_result:
        return f"Fehler beim Video-Upload: {upload_result['error']}"

    # 3. Post mit Video erstellen
    post_data = {
        "author": org_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": text
                },
                "shareMediaCategory": "VIDEO",
                "media": [{
                    "status": "READY",
                    "media": asset_urn
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        }
    }

    result = api_request("ugcPosts", method="POST", data=post_data)

    if "error" in result:
        return f"Fehler: {result.get('error')} - {result.get('details', '')}"

    post_id = result.get("id", "")
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return f"Unternehmens-Post mit Video erstellt. ID: {post_id}\nLink: {post_url}"


@mcp.tool()
@linkedin_tool
def linkedin_get_company_posts(organization_id: str, count: int = 10) -> str:
    """
    Ruft die letzten Posts einer Unternehmensseite ab.

    Args:
        organization_id: Die Organisations-ID
        count: Anzahl der Posts (max. 50)

    Returns:
        JSON-Liste der Posts
    """
    if not organization_id.startswith("urn:"):
        org_urn = f"urn:li:organization:{organization_id}"
    else:
        org_urn = organization_id

    encoded_urn = urllib.parse.quote(org_urn, safe="")
    result = api_request(
        f"ugcPosts?q=authors&authors=List({encoded_urn})&count={min(count, 50)}",
    )

    if "error" in result:
        return f"Fehler: {result['error']}"

    posts = []
    for element in result.get("elements", []):
        content = element.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
        posts.append({
            "id": element.get("id"),
            "text": content.get("shareCommentary", {}).get("text", ""),
            "created": element.get("created", {}).get("time"),
            "lifecycleState": element.get("lifecycleState"),
        })

    return json.dumps(posts, ensure_ascii=False, indent=2)


# =============================================================================
# Nachrichten-Tools (Messaging API - eingeschränkt)
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_get_messages(count: int = 20) -> str:
    """
    Ruft die letzten LinkedIn-Nachrichten ab.

    HINWEIS: Die Messaging API ist stark eingeschränkt und erfordert
    spezielle Genehmigung von LinkedIn (Marketing Developer Platform).

    Args:
        count: Anzahl der Nachrichten (max. 50)

    Returns:
        JSON-Liste der Konversationen oder Fehlermeldung
    """
    # Conversations abrufen
    result = api_request(
        f"conversations?count={min(count, 50)}",
        use_rest_api=True
    )

    if "error" in result:
        # Häufiger Fehler: Keine Berechtigung
        if "403" in str(result.get("error", "")):
            return ("Fehler: Keine Berechtigung für Messaging API. "
                   "Die LinkedIn Messaging API erfordert spezielle Genehmigung. "
                   "Beantragen Sie Zugang über LinkedIn Developer Platform.")
        return f"Fehler: {result['error']}"

    conversations = []
    for conv in result.get("elements", []):
        conversations.append({
            "id": conv.get("id"),
            "lastActivity": conv.get("lastActivityAt"),
            "participants": conv.get("participants", []),
        })

    return json.dumps(conversations, ensure_ascii=False, indent=2)


@mcp.tool()
@linkedin_tool
def linkedin_send_message(recipient_id: str, message: str) -> str:
    """
    Sendet eine Nachricht an einen LinkedIn-Kontakt.

    HINWEIS: Erfordert spezielle Messaging API Berechtigung.

    Args:
        recipient_id: Person-ID des Empfängers (ohne urn:li:person: Prefix)
        message: Die Nachricht

    Returns:
        Erfolgsmeldung oder Fehler
    """
    # Eigene Person-ID abrufen
    me = api_request("me", use_rest_api=True)
    if "error" in me:
        return f"Fehler: {me['error']}"

    my_id = me.get("id")

    # Nachricht senden
    message_data = {
        "recipients": [f"urn:li:person:{recipient_id}"],
        "message": {
            "body": message
        }
    }

    result = api_request("messages", method="POST", data=message_data, use_rest_api=True)

    if "error" in result:
        if "403" in str(result.get("error", "")):
            return ("Fehler: Keine Berechtigung für Messaging API. "
                   "Beantragen Sie Zugang über LinkedIn Developer Platform.")
        return f"Fehler: {result['error']}"

    return "Nachricht erfolgreich gesendet"


# =============================================================================
# Kommentar-Tools
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_get_post_comments(post_id: str, count: int = 20) -> str:
    """
    Ruft Kommentare zu einem Post ab.

    Args:
        post_id: Die Post-ID (URN oder ID-String)
        count: Anzahl der Kommentare (max. 100)

    Returns:
        JSON-Liste der Kommentare
    """
    if not post_id.startswith("urn:"):
        post_id = f"urn:li:ugcPost:{post_id}"

    encoded_id = urllib.parse.quote(post_id, safe="")
    result = api_request(
        f"socialActions/{encoded_id}/comments?count={min(count, 100)}"
    )

    if "error" in result:
        return f"Fehler: {result['error']}"

    comments = []
    for element in result.get("elements", []):
        comments.append({
            "id": element.get("id"),
            "author": element.get("actor"),
            "message": element.get("message", {}).get("text", ""),
            "created": element.get("created", {}).get("time"),
        })

    return json.dumps(comments, ensure_ascii=False, indent=2)


# =============================================================================
# Statistik-Tools
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_get_post_stats(post_id: str) -> str:
    """
    Ruft Statistiken zu einem Post ab (Likes, Kommentare, Shares).

    Args:
        post_id: Die Post-ID

    Returns:
        JSON mit Statistiken
    """
    if not post_id.startswith("urn:"):
        post_id = f"urn:li:ugcPost:{post_id}"

    encoded_id = urllib.parse.quote(post_id, safe="")
    result = api_request(f"socialActions/{encoded_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    stats = {
        "post_id": post_id,
        "likes": result.get("likesSummary", {}).get("totalLikes", 0),
        "comments": result.get("commentsSummary", {}).get("totalFirstLevelComments", 0),
        "shares": result.get("sharesSummary", {}).get("totalShares", 0) if "sharesSummary" in result else "N/A",
    }

    return json.dumps(stats, ensure_ascii=False, indent=2)


@mcp.tool()
@linkedin_tool
def linkedin_get_company_stats(organization_id: str) -> str:
    """
    Ruft Follower-Statistiken einer Unternehmensseite ab.

    Args:
        organization_id: Die Organisations-ID

    Returns:
        JSON mit Follower-Statistiken
    """
    if not organization_id.startswith("urn:"):
        org_urn = f"urn:li:organization:{organization_id}"
    else:
        org_urn = organization_id

    org_id = org_urn.split(":")[-1]

    result = api_request(
        f"organizationalEntityFollowerStatistics?q=organizationalEntity&organizationalEntity={urllib.parse.quote(org_urn, safe='')}",
        use_rest_api=True
    )

    if "error" in result:
        return f"Fehler: {result['error']}"

    elements = result.get("elements", [])
    if not elements:
        return "Keine Statistiken verfügbar"

    stats = elements[0]
    return json.dumps({
        "organization_id": org_id,
        "totalFollowers": stats.get("followerCounts", {}).get("organicFollowerCount", 0),
        "paidFollowers": stats.get("followerCounts", {}).get("paidFollowerCount", 0),
    }, ensure_ascii=False, indent=2)


# =============================================================================
# Hilfsfunktionen
# =============================================================================

@mcp.tool()
@linkedin_tool
def linkedin_check_token() -> str:
    """
    Prüft ob der Access Token gültig ist.

    Returns:
        Token-Status und Profil-Info bei Erfolg
    """
    access_token = get_access_token()

    if not access_token:
        return "Fehler: Kein Access Token konfiguriert. Bitte über WebUI Settings → Integrations mit LinkedIn verbinden."

    # Token testen mit userinfo Endpoint (OpenID Connect)
    result = api_request("userinfo", use_rest_api=False)

    if "error" not in result and result.get("sub"):
        name = result.get("name", "")
        return f"Token gültig. Eingeloggt als: {name} (ID: {result.get('sub')})"

    # Fallback: REST API /me Endpoint
    result = api_request("me", use_rest_api=True)

    if "error" in result:
        return f"Token ungültig oder abgelaufen: {result['error']}"

    name = f"{result.get('firstName', {}).get('localized', {}).get('en_US', '')} {result.get('lastName', {}).get('localized', {}).get('en_US', '')}"

    return f"Token gültig. Eingeloggt als: {name.strip()} (ID: {result.get('id')})"


def run():
    """MCP Server starten."""
    mcp.run()


if __name__ == "__main__":
    run()
