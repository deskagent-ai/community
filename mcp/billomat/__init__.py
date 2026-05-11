#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Billomat MCP Server
===================
MCP Server für Billomat API-Zugriff.
Ermöglicht Claude das Suchen und Erstellen von Kunden und Angeboten.
"""

import json
import os
import sys
import tempfile
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, register_link
from _link_utils import (
    make_link_ref,
    LINK_TYPE_INVOICE,
    LINK_TYPE_CONTACT,
    LINK_TYPE_OFFER,
    LINK_TYPE_CONFIRMATION,
)

mcp = FastMCP("billomat")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "payments",
    "color": "#4caf50"
}

# Integration schema for WebUI Integrations Hub
INTEGRATION_SCHEMA = {
    "name": "Billomat",
    "icon": "payments",
    "color": "#4caf50",
    "config_key": "billomat",
    "auth_type": "api_key",
    "fields": [
        {
            "key": "id",
            "label": "Billomat ID",
            "type": "text",
            "required": True,
            "hint": "Deine Billomat Subdomain (z.B. 'meinefirma' aus meinefirma.billomat.net)",
        },
        {
            "key": "api_key",
            "label": "API Key",
            "type": "password",
            "required": True,
            "hint": "Billomat API Key (Einstellungen > API)",
        },
        {
            "key": "app_id",
            "label": "App ID",
            "type": "text",
            "required": False,
            "hint": "Billomat App ID (für OAuth, optional)",
        },
        {
            "key": "app_secret",
            "label": "App Secret",
            "type": "password",
            "required": False,
            "hint": "Billomat App Secret (für OAuth, optional)",
        },
    ],
    "test_tool": "billomat_search_customers",
    "setup": {
        "description": "Rechnungen und Angebote",
        "requirement": "Billomat API Key",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Billomat API-Key eintragen",
        ],
    },
}

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    # Customer queries
    "billomat_search_customers",
    "billomat_get_customer",
    # Article queries
    "billomat_get_articles",
    "billomat_get_article",
    "billomat_search_article",
    # Offer queries
    "billomat_get_recent_offers",
    "billomat_get_offer_items",
    "billomat_get_offer",
    # Confirmation queries
    "billomat_get_recent_confirmations",
    "billomat_search_confirmations",
    "billomat_get_confirmation",
    "billomat_get_confirmation_items",
    # Invoice queries
    "billomat_get_recent_invoices",
    "billomat_get_invoice",
    "billomat_get_invoice_items",
    "billomat_get_invoices_by_period",
    "billomat_search_invoices",
    "billomat_search_invoices_by_article",
    "billomat_get_open_invoices",
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    # Customer management
    "billomat_create_customer",
    # Article management
    "billomat_create_article",
    # Offers
    "billomat_create_offer",
    "billomat_add_offer_item",
    "billomat_finalize_offer",
    "billomat_create_complete_offer",
    # Confirmations
    "billomat_create_confirmation",
    "billomat_create_confirmation_from_offer",
    "billomat_add_confirmation_item",
    "billomat_finalize_confirmation",
    "billomat_create_complete_confirmation_from_offer",
    "billomat_download_confirmation_pdf",
    # Invoices
    "billomat_create_invoice",
    "billomat_add_invoice_item",
    "billomat_add_timelog_to_invoice",
    "billomat_add_article_to_invoice",
    "billomat_update_invoice_item",
    "billomat_delete_invoice_item",
    "billomat_add_invoice_items_batch",
    # Payments
    "billomat_mark_invoice_paid",
    # PDF Downloads (create files)
    "billomat_download_offer_pdf",
    "billomat_download_invoice_pdf",
}

# =============================================================================
# Caching für Performance-Optimierung
# =============================================================================

import time

# Artikel-Cache (Artikel ändern sich selten)
_article_cache = {}  # {article_number: article_data}
_article_cache_time = 0
ARTICLE_CACHE_TTL = 3600  # 1 Stunde

# Client-Cache
_client_cache = {}  # {client_id: client_name}
_client_cache_time = 0
CLIENT_CACHE_TTL = 600  # 10 Minuten


def get_article_cached(article_number: str) -> dict:
    """Holt Artikel aus Cache oder API."""
    global _article_cache, _article_cache_time

    # Cache invalidieren nach TTL
    if time.time() - _article_cache_time > ARTICLE_CACHE_TTL:
        _article_cache = {}

    if article_number not in _article_cache:
        result = api_request(f"articles?article_number={article_number}")
        articles = _normalize_list(result, "articles")
        if articles:
            _article_cache[article_number] = articles[0]
            _article_cache_time = time.time()

    return _article_cache.get(article_number)


def get_client_names_batch(client_ids: set) -> dict:
    """Holt Kundennamen für mehrere IDs (mit Cache)."""
    global _client_cache, _client_cache_time

    # Cache invalidieren nach TTL
    if time.time() - _client_cache_time > CLIENT_CACHE_TTL:
        _client_cache = {}

    result = {}
    to_fetch = []

    for cid in client_ids:
        if cid in _client_cache:
            result[cid] = _client_cache[cid]
        else:
            to_fetch.append(cid)

    # Nur nicht-gecachte IDs fetchen
    for cid in to_fetch:
        client_result = api_request(f"clients/{cid}")
        if "error" not in client_result:
            client = client_result.get("client", {})
            name = client.get("name", client.get("company", f"Kunde #{cid}"))
            _client_cache[cid] = name
            _client_cache_time = time.time()
            result[cid] = name

    return result


def _normalize_list(result: dict, entity_key: str, default=None):
    """Normalize Billomat API response to always return a list.

    Billomat API returns single items as dict, multiple items as list.
    This helper ensures consistent list handling.

    Args:
        result: API response dict
        entity_key: Key name (e.g., "articles", "clients", "invoices")
        default: Default value if key not found (default: [])

    Returns:
        List of items (empty list if not found)

    Example:
        # Single item response: {"articles": {"article": {...}}}
        # Multiple items response: {"articles": {"article": [{...}, {...}]}}
        articles = _normalize_list(result, "articles")
    """
    if default is None:
        default = []

    items = result.get(entity_key, {}).get(entity_key.rstrip('s'), default)
    return [items] if isinstance(items, dict) else items


def _build_web_link(entity_type: str, entity_id) -> str:
    """Build Billomat web link for LinkRegistry."""
    billomat_id, _, _, _ = get_config()
    return f"https://{billomat_id}.billomat.net/app/beta/{entity_type}/{entity_id}"


def _build_edit_url(entity_type: str, entity_id: int) -> str:
    """Build Billomat web UI edit URL for an entity.

    Args:
        entity_type: "offers", "invoices", "clients", etc.
        entity_id: The entity ID

    Returns:
        Full URL to the entity in Billomat web interface
    """
    billomat_id, _, _, _ = get_config()
    return f"https://{billomat_id}.billomat.net/app/beta/{entity_type}/{entity_id}"


# Mapping: doc_type -> (number_key, default_name_prefix, entity_name_de)
_DOC_TYPE_META = {
    "offers": ("offer_number", "Angebot", "Angebot"),
    "invoices": ("invoice_number", "Rechnung", "Rechnung"),
    "confirmations": ("confirmation_number", "Auftragsbestaetigung", "Auftragsbestaetigung"),
}


def _download_document_pdf(
    doc_type: str,
    doc_id: int,
    save_path: str = "",
    filename: str = ""
) -> tuple[bool, str]:
    """Download PDF for offer, invoice or confirmation.

    Args:
        doc_type: "offers", "invoices" or "confirmations"
        doc_id: Document ID
        save_path: Target folder (default: temp). Relative paths resolved to project root.
        filename: Filename without .pdf (default: document number)

    Returns:
        Tuple of (success: bool, result: str)
        - On success: (True, path_to_pdf)
        - On error: (False, error_message)
    """
    billomat_id, api_key, _, _ = get_config()

    if not billomat_id or not api_key:
        return False, "Fehler: Billomat nicht konfiguriert"

    meta = _DOC_TYPE_META.get(doc_type)
    if not meta:
        return False, f"Fehler: Unbekannter doc_type '{doc_type}'"
    number_key, default_prefix, entity_name = meta

    url = f"https://{billomat_id}.billomat.net/api/{doc_type}/{doc_id}/pdf"

    headers = {
        "X-BillomatApiKey": api_key,
        "Accept": "application/pdf"
    }

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            pdf_data = response.read()

            # Determine filename from document if not provided
            if not filename:
                doc_result = api_request(f"{doc_type}/{doc_id}")
                doc = doc_result.get(doc_type.rstrip('s'), {})
                default_name = f"{default_prefix}_{doc_id}"
                doc_number = doc.get(number_key, default_name)
                filename = doc_number.replace("/", "-").replace("\\", "-")

            # Resolve save path
            if save_path:
                save_path_obj = Path(save_path)
                if not save_path_obj.is_absolute():
                    project_root = Path(__file__).parent.parent.parent
                    temp_dir = project_root / save_path
                else:
                    temp_dir = save_path_obj
            else:
                temp_dir = Path(tempfile.gettempdir()) / "billomat_pdfs"

            temp_dir.mkdir(parents=True, exist_ok=True)

            pdf_path = temp_dir / f"{filename}.pdf"
            pdf_path.write_bytes(pdf_data)

            return True, str(pdf_path.resolve())

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"Fehler: {entity_name} #{doc_id} nicht gefunden oder noch nicht finalisiert"
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return False, f"Fehler HTTP {e.code}: {error_body[:200]}"
    except Exception as e:
        return False, f"Fehler: {str(e)}"


def get_config():
    """Lädt Billomat-Konfiguration."""
    billomat_id = os.environ.get("BILLOMAT_ID")
    api_key = os.environ.get("BILLOMAT_API_KEY")
    app_id = os.environ.get("BILLOMAT_APP_ID")
    app_secret = os.environ.get("BILLOMAT_APP_SECRET")

    if not billomat_id or not api_key:
        config = load_config()
        billomat = config.get("billomat", {})
        billomat_id = billomat.get("id")
        api_key = billomat.get("api_key")
        app_id = billomat.get("app_id")
        app_secret = billomat.get("app_secret")

    return billomat_id, api_key, app_id, app_secret


def is_configured() -> bool:
    """Prüft ob Billomat API konfiguriert und aktiviert ist.

    Wird vom System verwendet um zu entscheiden, ob dieses MCP
    geladen werden soll. Benötigt sowohl ID als auch API-Key.

    Config-Optionen in apis.json:
        enabled: false  - MCP deaktivieren (auch wenn Credentials gesetzt)
        id: "..."       - Billomat Account ID (erforderlich)
        api_key: "..."  - API-Key (erforderlich)
    """
    config = load_config().get("billomat", {})

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    billomat_id, api_key, _, _ = get_config()
    return bool(billomat_id and api_key)


def api_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Führt Billomat API-Request aus."""
    billomat_id, api_key, app_id, app_secret = get_config()

    if not billomat_id or not api_key:
        return {"error": "Billomat nicht konfiguriert"}

    url = f"https://{billomat_id}.billomat.net/api/{endpoint}"

    headers = {
        "X-BillomatApiKey": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # App-Header für höheres Rate Limit (300/15min statt 150/15min)
    if app_id and app_secret:
        headers["X-AppId"] = app_id
        headers["X-AppSecret"] = app_secret

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return {"error": f"HTTP {e.code}: {error_body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def billomat_search_customers(query: str) -> str:
    """Sucht Kunden in Billomat nach Name oder Firma."""
    encoded_query = urllib.parse.quote(query, safe='')
    result = api_request(f"clients?name={encoded_query}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    clients = _normalize_list(result, "clients")

    if not clients:
        return f"Keine Kunden gefunden für: '{query}'"

    output = [f"Gefundene Kunden ({len(clients)}):"]
    for c in clients:
        client_id = str(c.get('id', ''))
        link_ref = make_link_ref(client_id, LINK_TYPE_CONTACT)
        web_link = _build_web_link("clients", client_id)
        register_link(link_ref, web_link)
        vat_info = f", USt-IdNr: {c.get('vat_number')}" if c.get('vat_number') else ""
        output.append(f"- ID {client_id} [{link_ref}]: {c.get('name')} ({c.get('email', '-')}, {c.get('country_code', '-')}{vat_info})")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_get_customer(customer_id: int) -> str:
    """Holt Details eines Kunden aus Billomat."""
    result = api_request(f"clients/{customer_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    c = result.get("client", {})
    client_id = str(c.get('id', ''))
    link_ref = make_link_ref(client_id, LINK_TYPE_CONTACT)
    web_link = _build_web_link("clients", client_id)
    register_link(link_ref, web_link)

    # Ansprechpartner zusammenbauen
    contact_parts = []
    if c.get('first_name'):
        contact_parts.append(c.get('first_name'))
    if c.get('last_name'):
        contact_parts.append(c.get('last_name'))
    contact_person = " ".join(contact_parts) if contact_parts else "-"

    return f"""Kunde #{client_id} [{link_ref}]:
Name: {c.get('name', '-')}
Firma: {c.get('company', '-')}
Ansprechpartner: {contact_person}
E-Mail: {c.get('email', '-')}
Telefon: {c.get('phone', '-')}
Adresse: {c.get('street', '-')}, {c.get('zip', '-')} {c.get('city', '-')}
Land: {c.get('country_code', '-')}
USt-IdNr: {c.get('vat_number', '-')}
Web: {{{{LINK:{link_ref}}}}}"""


@mcp.tool()
def billomat_create_customer(
    name: str,
    email: str = "",
    company: str = "",
    first_name: str = "",
    last_name: str = "",
    street: str = "",
    zip_code: str = "",
    city: str = "",
    country_code: str = "DE",
    phone: str = "",
    vat_number: str = ""
) -> str:
    """Erstellt einen neuen Kunden in Billomat.

    Args:
        name: Display-Name (bei B2B = Firmenname, wird in Listen angezeigt)
        email: E-Mail-Adresse
        company: Firmenname (Pflicht bei B2B-Kunden!)
        first_name: Vorname des Ansprechpartners
        last_name: Nachname des Ansprechpartners
        street: Straße und Hausnummer
        zip_code: Postleitzahl
        city: Stadt
        country_code: Ländercode (DE, AT, CH, US, GB, etc.)
        phone: Telefonnummer
        vat_number: USt-IdNr / VAT ID (z.B. ATU12345678, FR12345678901)
    """
    customer_data = {"name": name}

    if email:
        customer_data["email"] = email
    if company:
        customer_data["company"] = company
    if first_name:
        customer_data["first_name"] = first_name
    if last_name:
        customer_data["last_name"] = last_name
    if street:
        customer_data["street"] = street
    if zip_code:
        customer_data["zip"] = zip_code
    if city:
        customer_data["city"] = city
    if country_code:
        customer_data["country_code"] = country_code
    if phone:
        customer_data["phone"] = phone
    if vat_number:
        customer_data["vat_number"] = vat_number

    # Locale und Tax-Rule
    customer_data["locale"] = "de_DE" if country_code in ("DE", "AT") else "en_AG"
    customer_data["tax_rule"] = "TAX" if country_code == "DE" else "NO_TAX"

    result = api_request("clients", "POST", {"client": customer_data})

    if "error" in result:
        return f"Fehler: {result['error']}"

    client_id = result.get("client", {}).get("id")
    return f"Kunde erfolgreich erstellt! ID: {client_id}"


@mcp.tool()
def billomat_update_customer(
    customer_id: int,
    name: str = "",
    email: str = "",
    company: str = "",
    first_name: str = "",
    last_name: str = "",
    street: str = "",
    zip_code: str = "",
    city: str = "",
    country_code: str = "",
    phone: str = "",
    vat_number: str = ""
) -> str:
    """Aktualisiert einen bestehenden Kunden in Billomat.

    Args:
        customer_id: Die Kunden-ID
        name: Neuer Display-Name (optional)
        email: Neue E-Mail (optional)
        company: Neue Firma (optional)
        first_name: Neuer Vorname des Ansprechpartners (optional)
        last_name: Neuer Nachname des Ansprechpartners (optional)
        street: Neue Straße (optional)
        zip_code: Neue PLZ (optional)
        city: Neue Stadt (optional)
        country_code: Neuer Ländercode (optional)
        phone: Neue Telefonnummer (optional)
        vat_number: USt-IdNr / VAT ID (optional)
    """
    customer_data = {}

    if name:
        customer_data["name"] = name
    if email:
        customer_data["email"] = email
    if company:
        customer_data["company"] = company
    if first_name:
        customer_data["first_name"] = first_name
    if last_name:
        customer_data["last_name"] = last_name
    if street:
        customer_data["street"] = street
    if zip_code:
        customer_data["zip"] = zip_code
    if city:
        customer_data["city"] = city
    if country_code:
        customer_data["country_code"] = country_code
    if phone:
        customer_data["phone"] = phone
    if vat_number:
        customer_data["vat_number"] = vat_number

    if not customer_data:
        return "Fehler: Keine Daten zum Aktualisieren angegeben"

    result = api_request(f"clients/{customer_id}", "PUT", {"client": customer_data})

    if "error" in result:
        return f"Fehler: {result['error']}"

    # Aktualisierte Daten zurückgeben
    c = result.get("client", {})
    return f"""Kunde #{customer_id} aktualisiert!
Name: {c.get('name', '-')}
Firma: {c.get('company', '-')}
E-Mail: {c.get('email', '-')}"""


@mcp.tool()
def billomat_create_offer(customer_id: int) -> str:
    """Erstellt ein neues Angebot für einen Kunden."""
    billomat_id, _, _, _ = get_config()

    result = api_request("offers", "POST", {"offer": {"client_id": customer_id}})

    if "error" in result:
        return f"Fehler: {result['error']}"

    offer = result.get("offer", {})
    offer_id = str(offer.get("id", ""))
    link_ref = make_link_ref(offer_id, LINK_TYPE_OFFER)
    web_link = _build_web_link("offers", offer_id)
    register_link(link_ref, web_link)
    edit_url = _build_edit_url("offers", int(offer_id) if offer_id else 0)

    return f"Angebot erstellt! ID: {offer_id} [{link_ref}]\nBearbeiten: {edit_url}\nWeb: {{{{LINK:{link_ref}}}}}"


@mcp.tool()
def billomat_get_recent_offers(limit: int = 5) -> str:
    """Listet die letzten Angebote."""
    result = api_request(f"offers?per_page={limit}&order_by=created&order=DESC")

    if "error" in result:
        return f"Fehler: {result['error']}"

    offers = _normalize_list(result, "offers")

    if not offers:
        return "Keine Angebote gefunden"

    output = [f"Letzte Angebote ({len(offers)}):"]
    for o in offers:
        offer_id = str(o.get('id', ''))
        link_ref = make_link_ref(offer_id, LINK_TYPE_OFFER)
        web_link = _build_web_link("offers", offer_id)
        register_link(link_ref, web_link)
        number = o.get('offer_number', '-')
        status = o.get('status', '-')
        client_id_val = o.get('client_id', '-')
        output.append(f"- #{offer_id} [{link_ref}]: {number} | Kunde-ID: {client_id_val} | {o.get('total_net', '0')}€ ({status})")
        if o.get('label'):
            output.append(f"  Label: {o.get('label')}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_search_offers(offer_number: str) -> str:
    """Sucht Angebote in Billomat nach Angebotsnummer.

    Args:
        offer_number: Die Angebotsnummer (z.B. AN2026-007)
    """
    encoded = urllib.parse.quote(offer_number, safe='')
    result = api_request(f"offers?offer_number={encoded}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    offers = _normalize_list(result, "offers")

    if not offers:
        return f"Kein Angebot mit Nummer '{offer_number}' gefunden"

    output = [f"Angebote für '{offer_number}' ({len(offers)}):"]
    for o in offers:
        offer_id = str(o.get('id', ''))
        link_ref = make_link_ref(offer_id, LINK_TYPE_OFFER)
        web_link = _build_web_link("offers", offer_id)
        register_link(link_ref, web_link)
        client_id_val = o.get('client_id', '-')
        status = o.get('status', '-')
        output.append(f"- #{offer_id} [{link_ref}]: {o.get('offer_number', '-')} | Kunde-ID: {client_id_val} | {o.get('total_net', '0')}€ ({status})")
        output.append(f"  Datum: {o.get('date', '-')}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_get_customer_offers(client_id: int, limit: int = 20) -> str:
    """Listet alle Angebote für einen bestimmten Kunden inkl. Positionen.

    Args:
        client_id: Kunden-ID aus Billomat
        limit: Maximale Anzahl Ergebnisse (Standard: 20)
    """
    result = api_request(f"offers?client_id={client_id}&per_page={limit}&order_by=created&order=DESC")

    if "error" in result:
        return f"Fehler: {result['error']}"

    offers = _normalize_list(result, "offers")

    if not offers:
        return f"Keine Angebote für Kunde #{client_id} gefunden"

    billomat_id, _, _, _ = get_config()

    output = [f"Angebote für Kunde #{client_id} ({len(offers)}):"]
    for o in offers:
        offer_id = str(o.get('id', ''))
        link_ref = make_link_ref(offer_id, LINK_TYPE_OFFER)
        web_link = _build_web_link("offers", offer_id)
        register_link(link_ref, web_link)
        number = o.get('offer_number', '-')
        total = o.get('total_net', '0')
        status = o.get('status', 'DRAFT')
        date = o.get('date', '-')

        # Items abrufen
        items_result = api_request(f"offer-items?offer_id={offer_id}")
        items = _normalize_list(items_result, "offer-items") if "error" not in items_result else []
        items_summary = ", ".join([item.get('title', '-')[:30] for item in items[:3]])
        if len(items) > 3:
            items_summary += f" (+{len(items)-3})"

        output.append(f"- #{offer_id} [{link_ref}]: {number} | {date} | {total}€ ({status})")
        output.append(f"  Positionen: {items_summary or '-'}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


def _get_products() -> dict:
    """Load predefined products from config/apis.json under billomat.products.

    Returns:
        Dict of article_code -> product_name, empty if not configured.
    """
    try:
        config = load_config()
        return config.get("billomat", {}).get("products", {})
    except Exception:
        return {}


@mcp.tool()
def billomat_get_articles() -> str:
    """Listet verfügbare Artikel/Produkte aus Billomat."""
    result = api_request("articles?per_page=50")

    if "error" in result:
        return f"Fehler: {result['error']}"

    articles = _normalize_list(result, "articles")

    if not articles:
        return "Keine Artikel gefunden"

    output = ["Verfügbare Artikel:"]
    for a in articles:
        article_num = a.get("article_number", "-")
        title = a.get("title", "-")
        price = a.get("sales_price", "0")
        output.append(f"- {article_num}: {title} ({price}€)")

    products = _get_products()
    if products:
        output.append("\n--- Häufig verwendete Produkte ---")
        for code, name in products.items():
            output.append(f"- {code}: {name}")

    return "\n".join(output)


@mcp.tool()
def billomat_get_article(article_number: str) -> str:
    """Holt Details eines Artikels aus Billomat.

    Args:
        article_number: Die Artikelnummer des Artikels

    Returns:
        Vollständige Artikeldetails inkl. Beschreibung
    """
    encoded = urllib.parse.quote(article_number, safe='')
    result = api_request(f"articles?article_number={encoded}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    articles = _normalize_list(result, "articles")

    if not articles:
        return f"Artikel '{article_number}' nicht gefunden"

    a = articles[0]

    return f"""Artikel [{a.get('article_number', '-')}]:
ID: {a.get('id')}
Titel: {a.get('title', '-')}
Beschreibung: {a.get('description', '-') or '-'}
Preis: {a.get('sales_price', '0')}€ netto
Einheit: {a.get('unit', '-')}
MwSt: {a.get('tax_rate', '19')}%
Erstellt: {a.get('created', '-')}"""


@mcp.tool()
def billomat_create_article(
    article_number: str,
    title: str,
    sales_price: float,
    description: str = "",
    unit: str = "Stück",
    tax_rate: float = 19.0
) -> str:
    """Erstellt einen neuen Artikel/Produkt in Billomat.

    Args:
        article_number: Eindeutige Artikelnummer (z.B. DESK-M, PROD-1)
        title: Titel/Name des Artikels
        sales_price: Verkaufspreis in Euro (netto)
        description: Optionale Beschreibung
        unit: Einheit (Standard: "Stück", oder "Monat", "Jahr", "Lizenz")
        tax_rate: Steuersatz in % (Standard: 19.0, oder 0.0 für steuerfreie Artikel)
    """
    article_data = {
        "article_number": article_number,
        "title": title,
        "sales_price": sales_price,
        "unit": unit,
        "tax_rate": tax_rate
    }

    if description:
        article_data["description"] = description

    result = api_request("articles", "POST", {"article": article_data})

    if "error" in result:
        return f"Fehler: {result['error']}"

    article = result.get("article", {})
    article_id = article.get("id")

    # Cache invalidieren
    global _article_cache, _article_cache_time
    _article_cache = {}
    _article_cache_time = 0

    return f"""Artikel erstellt!
- ID: {article_id}
- Artikelnummer: {article_number}
- Titel: {title}
- Preis: {sales_price}€ netto
- Einheit: {unit}
- MwSt: {tax_rate}%"""


@mcp.tool()
def billomat_update_article(
    article_number: str,
    sales_price: float = None,
    title: str = None,
    description: str = None,
    unit: str = None
) -> str:
    """Aktualisiert einen bestehenden Artikel in Billomat.

    Args:
        article_number: Artikelnummer des zu aktualisierenden Artikels (z.B. DESK-M1, DESK-Y1)
        sales_price: Neuer Verkaufspreis in Euro (netto)
        title: Neuer Titel (optional)
        description: Neue Beschreibung (optional)
        unit: Neue Einheit (optional)

    Returns:
        Bestätigung der Aktualisierung
    """
    # Zuerst Artikel-ID finden
    encoded = urllib.parse.quote(article_number, safe='')
    result = api_request(f"articles?article_number={encoded}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    articles = _normalize_list(result, "articles")

    if not articles:
        return f"Artikel '{article_number}' nicht gefunden"

    article = articles[0]
    article_id = article.get("id")

    # Update-Daten zusammenstellen (nur geänderte Felder)
    update_data = {}
    if sales_price is not None:
        update_data["sales_price"] = sales_price
    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if unit is not None:
        update_data["unit"] = unit

    if not update_data:
        return "Keine Änderungen angegeben"

    # Artikel aktualisieren
    result = api_request(f"articles/{article_id}", "PUT", {"article": update_data})

    if "error" in result:
        return f"Fehler beim Aktualisieren: {result['error']}"

    # Cache invalidieren
    global _article_cache, _article_cache_time
    _article_cache = {}
    _article_cache_time = 0

    updated = result.get("article", {})
    return f"""Artikel aktualisiert!
- Artikelnummer: {article_number}
- ID: {article_id}
- Neuer Preis: {updated.get('sales_price', sales_price)}€ netto
- Titel: {updated.get('title', article.get('title'))}"""


@mcp.tool()
def billomat_search_article(query: str) -> str:
    """Sucht Artikel nach Artikelnummer oder Titel."""
    encoded_query = urllib.parse.quote(query, safe='')
    result = api_request(f"articles?article_number={encoded_query}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    articles = _normalize_list(result, "articles")

    # Falls keine Treffer, nach Titel suchen
    if not articles:
        result = api_request(f"articles?title={query}")
        articles = _normalize_list(result, "articles")

    if not articles:
        return f"Kein Artikel gefunden für: '{query}'"

    output = [f"Gefundene Artikel ({len(articles)}):"]
    for a in articles:
        output.append(f"- ID {a.get('id')}: [{a.get('article_number')}] {a.get('title')} - {a.get('sales_price', '0')}€")

    return "\n".join(output)


@mcp.tool()
def billomat_add_offer_item(
    offer_id: int,
    article_number: str,
    quantity: int = 1,
    description: str = ""
) -> str:
    """Fügt einen Artikel zum Angebot hinzu.

    Args:
        offer_id: Die Angebots-ID
        article_number: Artikelnummer des Artikels
        quantity: Anzahl (Standard: 1)
        description: Optionale zusätzliche Beschreibung
    """
    # Zuerst Artikel-ID anhand der Artikelnummer finden
    result = api_request(f"articles?article_number={article_number}")

    if "error" in result:
        return f"Fehler beim Suchen des Artikels: {result['error']}"

    articles = _normalize_list(result, "articles")

    if not articles:
        return f"Artikel '{article_number}' nicht gefunden. Nutze billomat_get_articles() fuer verfuegbare Artikel."

    article = articles[0]
    article_id = article.get("id")

    # Angebotsposition erstellen
    item_data = {
        "offer_id": offer_id,
        "article_id": article_id,
        "quantity": quantity
    }

    if description:
        item_data["description"] = description

    result = api_request("offer-items", "POST", {"offer-item": item_data})

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    item = result.get("offer-item", {})
    edit_url = _build_edit_url("offers", offer_id)

    return f"""Artikel hinzugefügt!
- Artikel: {article.get('title')}
- Anzahl: {quantity}
- Einzelpreis: {article.get('sales_price', '0')}€
- Position-ID: {item.get('id')}

Angebot bearbeiten: {edit_url}"""


@mcp.tool()
def billomat_get_offer_items(offer_id: int) -> str:
    """Zeigt alle Positionen eines Angebots."""
    result = api_request(f"offer-items?offer_id={offer_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    items = _normalize_list(result, "offer-items")

    if not items:
        return f"Keine Positionen im Angebot #{offer_id}"

    output = [f"Positionen im Angebot #{offer_id}:"]
    total = 0
    for i in items:
        qty = float(i.get("quantity", 1))
        price = float(i.get("unit_price", 0))
        line_total = qty * price
        total += line_total
        output.append(f"- {i.get('title', '-')}: {int(qty)}x {price}€ = {line_total}€")

    output.append(f"\nSumme netto: {total}€")
    return "\n".join(output)


@mcp.tool()
def billomat_finalize_offer(offer_id: int) -> str:
    """Finalisiert ein Angebot (Status → OPEN/gesendet).

    Nach Finalisierung kann das Angebot nicht mehr bearbeitet werden
    und erhält eine offizielle Angebotsnummer.

    Args:
        offer_id: Die Angebots-ID
    """
    billomat_id, _, _, _ = get_config()

    result = api_request(f"offers/{offer_id}/complete", "PUT")

    if "error" in result:
        return f"Fehler: {result['error']}"

    # Hole aktualisierte Angebotsdaten
    offer_result = api_request(f"offers/{offer_id}")
    offer = offer_result.get("offer", {})

    offer_number = offer.get("offer_number", "-")
    status = offer.get("status", "-")
    total = offer.get("total_net", "0")

    return f"""Angebot finalisiert!
- ID: {offer_id}
- Angebotsnummer: {offer_number}
- Status: {status}
- Summe netto: {total}€
- PDF: Nutze download_offer_pdf({offer_id}) zum Herunterladen"""


@mcp.tool()
def billomat_download_offer_pdf(offer_id: int, filename: str = "") -> str:
    """Lädt das PDF eines Angebots herunter.

    Das PDF wird im temp-Verzeichnis gespeichert und kann dann
    z.B. per Outlook an eine E-Mail angehängt werden.

    Args:
        offer_id: Die Angebots-ID
        filename: Optionaler Dateiname (ohne .pdf). Standard: Angebot_{offer_id}

    Returns:
        Pfad zur heruntergeladenen PDF-Datei
    """
    success, result = _download_document_pdf("offers", offer_id, "", filename)

    if not success:
        return result

    # Format output with helpful info
    pdf_path = Path(result)
    size = pdf_path.stat().st_size
    return f"""PDF heruntergeladen!
- Datei: {pdf_path}
- Größe: {size:,} Bytes

Zum Anhängen an E-Mail:
  create_new_email_with_attachment(to, subject, body, "{pdf_path}")"""


@mcp.tool()
def billomat_get_offer(offer_id: int) -> str:
    """Holt Details eines Angebots aus Billomat.

    Args:
        offer_id: Die Angebots-ID
    """
    result = api_request(f"offers/{offer_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    o = result.get("offer", {})
    offer_id_str = str(o.get('id', offer_id))
    link_ref = make_link_ref(offer_id_str, LINK_TYPE_OFFER)
    web_link = _build_web_link("offers", offer_id_str)
    register_link(link_ref, web_link)

    status_map = {
        "DRAFT": "Entwurf",
        "OPEN": "Offen/Gesendet",
        "WON": "Gewonnen",
        "LOST": "Verloren",
        "CANCELED": "Storniert"
    }
    status = status_map.get(o.get("status", ""), o.get("status", "-"))

    edit_url = _build_edit_url("offers", offer_id)

    return f"""Angebot #{offer_id_str} [{link_ref}]:
Angebotsnummer: {o.get('offer_number', '-')}
Status: {status}
Kunde-ID: {o.get('client_id', '-')}
Datum: {o.get('date', '-')}
Gültig bis: {o.get('validity_date', '-')}
Summe netto: {o.get('total_net', '0')}€
Summe brutto: {o.get('total_gross', '0')}€
Bearbeiten: {edit_url}
Web: {{{{LINK:{link_ref}}}}}"""


# ==================== CONFIRMATION FUNCTIONS ====================
# Auftragsbestaetigungen - typischer Workflow:
#   1. Angebot existiert (Offer)
#   2. billomat_create_complete_confirmation_from_offer(offer_id) -> PDF-Pfad
#   3. PDF an Antwortmail anhaengen


@mcp.tool()
def billomat_create_confirmation(
    customer_id: int,
    intro: str = "",
    template: str = "",
    address: str = "",
    label: str = ""
) -> str:
    """Erstellt eine neue (leere) Auftragsbestaetigung fuer einen Kunden.

    Hinweis: In der Regel sollte stattdessen
    billomat_create_confirmation_from_offer(offer_id) genutzt werden,
    da Auftragsbestaetigungen fast immer aus einem Angebot entstehen.

    Args:
        customer_id: Die Kunden-ID aus Billomat
        intro: Einleitungstext
        template: Template-Name (z.B. "auftragsbestaetigung-de")
        address: Abweichende Lieferadresse
        label: Bezeichnung/Betreff
    """
    payload: dict = {"client_id": customer_id}
    if intro:
        payload["intro"] = intro
    if template:
        payload["template"] = template
    if address:
        payload["address"] = address
    if label:
        payload["label"] = label

    result = api_request("confirmations", "POST", {"confirmation": payload})

    if "error" in result:
        return f"Fehler: {result['error']}"

    confirmation = result.get("confirmation", {})
    confirmation_id = str(confirmation.get("id", ""))
    link_ref = make_link_ref(confirmation_id, LINK_TYPE_CONFIRMATION)
    web_link = _build_web_link("confirmations", confirmation_id)
    register_link(link_ref, web_link)
    edit_url = _build_edit_url("confirmations", int(confirmation_id) if confirmation_id else 0)

    return (
        f"Auftragsbestaetigung erstellt! ID: {confirmation_id} [{link_ref}]\n"
        f"Bearbeiten: {edit_url}\n"
        f"Web: {{{{LINK:{link_ref}}}}}"
    )


@mcp.tool()
def billomat_create_confirmation_from_offer(offer_id: int) -> str:
    """Erstellt eine Auftragsbestaetigung aus einem bestehenden Angebot.

    Hauptworkflow: Kunde hat Angebot akzeptiert -> aus diesem Angebot
    wird eine Auftragsbestaetigung erzeugt. Kunde, Adresse, Positionen
    und Konditionen werden aus dem Angebot uebernommen.

    Wenn der dedizierte Billomat-Endpoint nicht verfuegbar ist,
    wird die Auftragsbestaetigung manuell aus den Angebotsdaten erstellt.

    Args:
        offer_id: Die Angebots-ID aus Billomat

    Returns:
        Confirmation-Details (Status: DRAFT) - muss noch finalisiert werden
    """
    # 1. Angebot laden (fuer Daten-Fallback und Validierung)
    offer_result = api_request(f"offers/{offer_id}")
    if "error" in offer_result:
        return f"Fehler beim Laden des Angebots: {offer_result['error']}"
    offer = offer_result.get("offer", {})
    if not offer:
        return f"Fehler: Angebot #{offer_id} nicht gefunden"

    # 2. Versuche dedizierten Endpoint (POST /api/offers/{id}/confirmation)
    direct_result = api_request(f"offers/{offer_id}/confirmation", "POST")
    confirmation: dict = {}
    used_fallback = False

    if "error" not in direct_result:
        confirmation = direct_result.get("confirmation", {})

    if not confirmation:
        # 3. Fallback: Manuell aus Angebotsdaten neu anlegen
        used_fallback = True
        client_id = offer.get("client_id")
        if not client_id:
            return "Fehler: Angebot hat keine Kunden-ID"

        payload: dict = {"client_id": client_id}
        for key in ("intro", "address", "label", "template",
                    "discount_rate", "discount_date", "currency_code",
                    "supply_date", "supply_date_type", "note", "title"):
            val = offer.get(key)
            if val:
                payload[key] = val

        c_result = api_request("confirmations", "POST", {"confirmation": payload})
        if "error" in c_result:
            return f"Fehler beim Erstellen: {c_result['error']}"
        confirmation = c_result.get("confirmation", {})
        confirmation_id = confirmation.get("id")

        # 4. Angebotspositionen kopieren
        items_result = api_request(f"offer-items?offer_id={offer_id}")
        offer_items = _normalize_list(items_result, "offer-items")
        copy_errors = []
        for item in offer_items:
            new_item = {"confirmation_id": confirmation_id}
            for key in ("article_id", "unit", "quantity", "unit_price",
                        "tax_name", "tax_rate", "title", "description",
                        "total_gross", "total_net", "reduction"):
                val = item.get(key)
                if val not in (None, ""):
                    new_item[key] = val
            r = api_request("confirmation-items", "POST", {"confirmation-item": new_item})
            if "error" in r:
                copy_errors.append(item.get("title", "?") + ": " + r["error"])

        if copy_errors:
            # Confirmation existiert trotzdem - Warnungen mit zurueckgeben
            confirmation["__copy_errors"] = copy_errors

    confirmation_id = str(confirmation.get("id", ""))
    if not confirmation_id:
        return "Fehler: Konnte Confirmation-ID nicht ermitteln"

    link_ref = make_link_ref(confirmation_id, LINK_TYPE_CONFIRMATION)
    web_link = _build_web_link("confirmations", confirmation_id)
    register_link(link_ref, web_link)
    edit_url = _build_edit_url("confirmations", int(confirmation_id))

    offer_link_ref = make_link_ref(str(offer_id), LINK_TYPE_OFFER)
    register_link(offer_link_ref, _build_web_link("offers", offer_id))

    output = [
        f"Auftragsbestaetigung aus Angebot #{offer_id} [{offer_link_ref}] erstellt!",
        f"- Confirmation-ID: {confirmation_id} [{link_ref}]",
        f"- Status: {confirmation.get('status', 'DRAFT')}",
        f"- Methode: {'Fallback (manuell kopiert)' if used_fallback else 'Direkt-Endpoint'}",
        f"- Bearbeiten: {edit_url}",
        f"- Web: {{{{LINK:{link_ref}}}}}",
        "",
        f"Naechster Schritt: billomat_finalize_confirmation({confirmation_id})",
        f"oder gleich PDF: billomat_create_complete_confirmation_from_offer "
        f"(falls noch nicht genutzt)",
    ]

    copy_errors = confirmation.get("__copy_errors")
    if copy_errors:
        output.append("")
        output.append("Warnungen beim Kopieren der Positionen:")
        for err in copy_errors:
            output.append(f"  ! {err}")

    return "\n".join(output)


@mcp.tool()
def billomat_add_confirmation_item(
    confirmation_id: int,
    article_number: str,
    quantity: int = 1,
    description: str = ""
) -> str:
    """Fuegt einen Artikel zu einer Auftragsbestaetigung hinzu.

    Args:
        confirmation_id: Die Confirmation-ID
        article_number: Artikelnummer
        quantity: Anzahl (Standard: 1)
        description: Optionale zusaetzliche Beschreibung
    """
    article = get_article_cached(article_number)
    if not article:
        return (
            f"Artikel '{article_number}' nicht gefunden. "
            "Nutze billomat_get_articles() fuer verfuegbare Artikel."
        )

    item_data = {
        "confirmation_id": confirmation_id,
        "article_id": article.get("id"),
        "quantity": quantity,
    }
    if description:
        item_data["description"] = description

    result = api_request("confirmation-items", "POST", {"confirmation-item": item_data})
    if "error" in result:
        return f"Fehler beim Hinzufuegen: {result['error']}"

    item = result.get("confirmation-item", {})
    edit_url = _build_edit_url("confirmations", confirmation_id)

    return (
        f"Position hinzugefuegt!\n"
        f"- Artikel: {article.get('title')}\n"
        f"- Anzahl: {quantity}\n"
        f"- Einzelpreis: {article.get('sales_price', '0')}EUR\n"
        f"- Position-ID: {item.get('id')}\n\n"
        f"Confirmation bearbeiten: {edit_url}"
    )


@mcp.tool()
def billomat_get_confirmation_items(confirmation_id: int) -> str:
    """Zeigt alle Positionen einer Auftragsbestaetigung."""
    result = api_request(f"confirmation-items?confirmation_id={confirmation_id}")
    if "error" in result:
        return f"Fehler: {result['error']}"

    items = _normalize_list(result, "confirmation-items")
    if not items:
        return f"Keine Positionen in Auftragsbestaetigung #{confirmation_id}"

    output = [f"Positionen in Auftragsbestaetigung #{confirmation_id}:"]
    total = 0.0
    for i in items:
        qty = float(i.get("quantity", 1))
        price = float(i.get("unit_price", 0))
        line_total = qty * price
        total += line_total
        output.append(f"- {i.get('title', '-')}: {qty:g}x {price}EUR = {line_total}EUR")

    output.append(f"\nSumme netto: {total}EUR")
    return "\n".join(output)


@mcp.tool()
def billomat_finalize_confirmation(confirmation_id: int) -> str:
    """Finalisiert eine Auftragsbestaetigung (Status -> OPEN/gesendet).

    Nach Finalisierung erhaelt sie eine offizielle Nummer und das PDF
    kann heruntergeladen werden.

    Args:
        confirmation_id: Die Confirmation-ID
    """
    result = api_request(f"confirmations/{confirmation_id}/complete", "PUT")
    if "error" in result:
        return f"Fehler: {result['error']}"

    confirmation_result = api_request(f"confirmations/{confirmation_id}")
    confirmation = confirmation_result.get("confirmation", {})

    return (
        f"Auftragsbestaetigung finalisiert!\n"
        f"- ID: {confirmation_id}\n"
        f"- Nummer: {confirmation.get('confirmation_number', '-')}\n"
        f"- Status: {confirmation.get('status', '-')}\n"
        f"- Summe netto: {confirmation.get('total_net', '0')}EUR\n"
        f"- PDF: billomat_download_confirmation_pdf({confirmation_id})"
    )


@mcp.tool()
def billomat_download_confirmation_pdf(confirmation_id: int, filename: str = "") -> str:
    """Laedt das PDF einer Auftragsbestaetigung herunter.

    Das PDF wird im temp-Verzeichnis gespeichert und kann z.B. per
    create_new_email_with_attachment(...) bzw.
    create_reply_draft_with_attachment(...) an eine Mail angehaengt werden.

    Args:
        confirmation_id: Die Confirmation-ID
        filename: Optionaler Dateiname (ohne .pdf)

    Returns:
        Pfad zur heruntergeladenen PDF-Datei (absolut)
    """
    success, result = _download_document_pdf("confirmations", confirmation_id, "", filename)
    if not success:
        return result

    pdf_path = Path(result)
    size = pdf_path.stat().st_size
    return (
        f"PDF heruntergeladen!\n"
        f"- Datei: {pdf_path}\n"
        f"- Groesse: {size:,} Bytes\n\n"
        f"Zum Anhaengen an E-Mail:\n"
        f"  create_new_email_with_attachment(to, subject, body, \"{pdf_path}\")\n"
        f"  create_reply_draft_with_attachment(message_id, body, \"{pdf_path}\")"
    )


@mcp.tool()
def billomat_get_confirmation(confirmation_id: int) -> str:
    """Holt Details einer Auftragsbestaetigung aus Billomat.

    Args:
        confirmation_id: Die Confirmation-ID
    """
    result = api_request(f"confirmations/{confirmation_id}")
    if "error" in result:
        return f"Fehler: {result['error']}"

    c = result.get("confirmation", {})
    confirmation_id_str = str(c.get("id", confirmation_id))
    link_ref = make_link_ref(confirmation_id_str, LINK_TYPE_CONFIRMATION)
    web_link = _build_web_link("confirmations", confirmation_id_str)
    register_link(link_ref, web_link)

    status_map = {
        "DRAFT": "Entwurf",
        "OPEN": "Offen/Gesendet",
        "CLEARED": "Erledigt",
        "CANCELED": "Storniert",
    }
    status = status_map.get(c.get("status", ""), c.get("status", "-"))

    edit_url = _build_edit_url("confirmations", confirmation_id)

    return (
        f"Auftragsbestaetigung #{confirmation_id_str} [{link_ref}]:\n"
        f"Nummer: {c.get('confirmation_number', '-')}\n"
        f"Status: {status}\n"
        f"Kunde-ID: {c.get('client_id', '-')}\n"
        f"Datum: {c.get('date', '-')}\n"
        f"Summe netto: {c.get('total_net', '0')}EUR\n"
        f"Summe brutto: {c.get('total_gross', '0')}EUR\n"
        f"Bearbeiten: {edit_url}\n"
        f"Web: {{{{LINK:{link_ref}}}}}"
    )


@mcp.tool()
def billomat_get_recent_confirmations(limit: int = 5) -> str:
    """Listet die letzten Auftragsbestaetigungen."""
    result = api_request(f"confirmations?per_page={limit}&order_by=created&order=DESC")
    if "error" in result:
        return f"Fehler: {result['error']}"

    confirmations = _normalize_list(result, "confirmations")
    if not confirmations:
        return "Keine Auftragsbestaetigungen gefunden"

    output = [f"Letzte Auftragsbestaetigungen ({len(confirmations)}):"]
    for c in confirmations:
        cid = str(c.get("id", ""))
        link_ref = make_link_ref(cid, LINK_TYPE_CONFIRMATION)
        register_link(link_ref, _build_web_link("confirmations", cid))
        output.append(
            f"- #{cid} [{link_ref}]: {c.get('confirmation_number', '-')} | "
            f"Kunde-ID: {c.get('client_id', '-')} | "
            f"{c.get('total_net', '0')}EUR ({c.get('status', '-')})"
        )
        if c.get("label"):
            output.append(f"  Label: {c.get('label')}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_search_confirmations(confirmation_number: str) -> str:
    """Sucht Auftragsbestaetigungen nach Nummer.

    Args:
        confirmation_number: Die Nummer (z.B. AB2026-007)
    """
    encoded = urllib.parse.quote(confirmation_number, safe='')
    result = api_request(f"confirmations?confirmation_number={encoded}")
    if "error" in result:
        return f"Fehler: {result['error']}"

    confirmations = _normalize_list(result, "confirmations")
    if not confirmations:
        return f"Keine Auftragsbestaetigung mit Nummer '{confirmation_number}' gefunden"

    output = [f"Auftragsbestaetigungen fuer '{confirmation_number}' ({len(confirmations)}):"]
    for c in confirmations:
        cid = str(c.get("id", ""))
        link_ref = make_link_ref(cid, LINK_TYPE_CONFIRMATION)
        register_link(link_ref, _build_web_link("confirmations", cid))
        output.append(
            f"- #{cid} [{link_ref}]: {c.get('confirmation_number', '-')} | "
            f"Kunde-ID: {c.get('client_id', '-')} | "
            f"{c.get('total_net', '0')}EUR ({c.get('status', '-')})"
        )
        output.append(f"  Datum: {c.get('date', '-')}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_create_complete_confirmation_from_offer(
    offer_id: int,
    finalize: bool = True,
    download_pdf: bool = True
) -> str:
    """One-Shot: Auftragsbestaetigung aus Angebot + Finalisieren + PDF-Download.

    Hauptworkflow fuer Agents: Kunde akzeptiert Angebot per Mail
    -> dieser Aufruf liefert direkt den PDF-Pfad fuer den Mail-Anhang.

    Args:
        offer_id: Angebots-ID aus dem die Confirmation erstellt wird
        finalize: Confirmation direkt finalisieren (Default: True)
        download_pdf: PDF herunterladen (nur wenn finalize=True, Default: True)

    Returns:
        Confirmation-Details inkl. PDF-Pfad fuer Mail-Anhang
    """
    # 1. Confirmation aus Angebot
    create_msg = billomat_create_confirmation_from_offer(offer_id)
    if create_msg.startswith("Fehler"):
        return create_msg

    # Confirmation-ID aus dem Output parsen
    confirmation_id = None
    for line in create_msg.splitlines():
        if "Confirmation-ID:" in line:
            try:
                # Format: "- Confirmation-ID: 12345 [hash]"
                part = line.split("Confirmation-ID:")[1].strip()
                confirmation_id = int(part.split()[0])
                break
            except (ValueError, IndexError):
                pass

    if confirmation_id is None:
        return (
            "Confirmation wurde erstellt, aber ID konnte nicht ermittelt werden:\n\n"
            + create_msg
        )

    output = [create_msg, ""]

    # 2. Optional finalisieren
    if not finalize:
        return "\n".join(output)

    finalize_result = api_request(f"confirmations/{confirmation_id}/complete", "PUT")
    if "error" in finalize_result:
        output.append(f"Warnung: Finalisierung fehlgeschlagen: {finalize_result['error']}")
        return "\n".join(output)

    confirmation_data = api_request(f"confirmations/{confirmation_id}")
    confirmation = confirmation_data.get("confirmation", {})
    output.append("Finalisiert:")
    output.append(f"- Nummer: {confirmation.get('confirmation_number', '-')}")
    output.append(f"- Status: {confirmation.get('status', '-')}")
    output.append(f"- Summe netto: {confirmation.get('total_net', '0')}EUR")

    # 3. Optional PDF herunterladen
    if not download_pdf:
        output.append(f"\nPDF: billomat_download_confirmation_pdf({confirmation_id})")
        return "\n".join(output)

    success, pdf_result = _download_document_pdf("confirmations", confirmation_id)
    if not success:
        output.append(f"\nWarnung: PDF-Download fehlgeschlagen: {pdf_result}")
        return "\n".join(output)

    pdf_path = Path(pdf_result)
    output.append("")
    output.append(f"PDF bereit: {pdf_path}")
    output.append(f"Groesse: {pdf_path.stat().st_size:,} Bytes")
    output.append("")
    output.append("Zum Anhaengen an Antwortmail:")
    output.append(f"  create_reply_draft_with_attachment(message_id, body, \"{pdf_path}\")")

    return "\n".join(output)


# ==================== INVOICE FUNCTIONS ====================

@mcp.tool()
def billomat_create_invoice(
    customer_id: int,
    intro: str = "",
    template: str = "",
    address: str = "",
    label: str = ""
) -> str:
    """Erstellt eine neue Rechnung für einen Kunden.

    Args:
        customer_id: Die Kunden-ID aus Billomat
        intro: Einleitungstext (z.B. "Ihre Bestellnummer: PO-12345...")
        template: Template-Name ("rechnung-de-software" oder "rechnung-en-software")
        address: Rechnungsadresse (überschreibt Kundenadresse)
        label: Bezeichnung/Betreff der Rechnung
    """
    billomat_id, _, _, _ = get_config()

    invoice_data = {"client_id": customer_id}

    if intro:
        invoice_data["intro"] = intro
    if address:
        invoice_data["address"] = address
    if label:
        invoice_data["label"] = label

    # Template-ID ermitteln
    if template:
        templates_result = api_request("templates")
        if "error" not in templates_result:
            templates = _normalize_list(templates_result, "templates")
            for t in templates:
                if t.get("name", "").lower() == template.lower():
                    invoice_data["template_id"] = t.get("id")
                    break

    result = api_request("invoices", "POST", {"invoice": invoice_data})

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoice = result.get("invoice", {})
    invoice_id = str(invoice.get("id", ""))
    link_ref = make_link_ref(invoice_id, LINK_TYPE_INVOICE)
    web_link = _build_web_link("invoices", invoice_id)
    register_link(link_ref, web_link)
    invoice_number = invoice.get("invoice_number", "-")
    edit_url = _build_edit_url("invoices", int(invoice_id) if invoice_id else 0)

    return f"""Rechnung erstellt!
- ID: {invoice_id} [{link_ref}]
- Rechnungsnummer: {invoice_number}
- Bearbeiten: {edit_url}
- Web: {{{{LINK:{link_ref}}}}}"""


@mcp.tool()
def billomat_get_recent_invoices(limit: int = 5) -> str:
    """Listet die letzten Rechnungen."""
    billomat_id, _, _, _ = get_config()
    result = api_request(f"invoices?per_page={limit}&order_by=created&order=DESC")

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = _normalize_list(result, "invoices")

    if not invoices:
        return "Keine Rechnungen gefunden"

    # Kundennamen abrufen
    client_ids = set(inv.get("client_id") for inv in invoices if inv.get("client_id"))
    client_names = {}
    for cid in client_ids:
        client_result = api_request(f"clients/{cid}")
        if "error" not in client_result:
            client = client_result.get("client", {})
            client_names[cid] = client.get("name", client.get("company", f"Kunde #{cid}"))

    output = [f"Letzte Rechnungen ({len(invoices)}):"]
    for inv in invoices:
        inv_id = str(inv.get('id', ''))
        link_ref = make_link_ref(inv_id, LINK_TYPE_INVOICE)
        web_link = _build_web_link("invoices", inv_id)
        register_link(link_ref, web_link)
        cid = inv.get("client_id", "")
        client_name = client_names.get(cid, "-")
        status = inv.get("status", "-")
        total = inv.get("total_net", "0")
        label = inv.get("label", inv.get("invoice_number", "-"))
        output.append(f"- #{inv_id} [{link_ref}]: {label} | {client_name} | {total}€ ({status})")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_get_invoice(invoice_id: int) -> str:
    """Holt Details einer Rechnung aus Billomat.

    Args:
        invoice_id: Die Rechnungs-ID
    """
    billomat_id, _, _, _ = get_config()
    result = api_request(f"invoices/{invoice_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    inv = result.get("invoice", {})
    inv_id = str(inv.get('id', invoice_id))
    link_ref = make_link_ref(inv_id, LINK_TYPE_INVOICE)
    web_link = _build_web_link("invoices", inv_id)
    register_link(link_ref, web_link)

    status_map = {
        "DRAFT": "Entwurf",
        "OPEN": "Offen",
        "OVERDUE": "Überfällig",
        "PAID": "Bezahlt",
        "CANCELED": "Storniert"
    }
    status = status_map.get(inv.get("status", ""), inv.get("status", "-"))

    edit_url = _build_edit_url("invoices", invoice_id)

    return f"""Rechnung #{inv_id} [{link_ref}]:
Rechnungsnummer: {inv.get('invoice_number', '-')}
Status: {status}
Kunde-ID: {inv.get('client_id', '-')}
Datum: {inv.get('date', '-')}
Fällig: {inv.get('due_date', '-')}
Summe netto: {inv.get('total_net', '0')}€
Summe brutto: {inv.get('total_gross', '0')}€
Bearbeiten: {edit_url}
Web: {{{{LINK:{link_ref}}}}}"""


@mcp.tool()
def billomat_download_invoice_pdf(invoice_id: int, save_path: str = "", filename: str = "") -> str:
    """Lädt eine Rechnung als PDF herunter.

    Args:
        invoice_id: Die Rechnungs-ID aus Billomat
        save_path: Zielordner (Standard: temp-Verzeichnis). Relative Pfade wie ".temp" werden relativ zum Projekt-Root aufgelöst.
        filename: Dateiname ohne .pdf (Standard: Rechnungsnummer)

    Returns:
        Pfad zur heruntergeladenen PDF-Datei
    """
    success, result = _download_document_pdf("invoices", invoice_id, save_path, filename)
    return result


@mcp.tool()
def billomat_get_invoices_by_period(
    from_date: str,
    to_date: str,
    status: str = ""
) -> str:
    """Holt alle Rechnungen für einen bestimmten Zeitraum.

    Args:
        from_date: Startdatum im Format YYYY-MM-DD (inklusiv)
        to_date: Enddatum im Format YYYY-MM-DD (inklusiv)
        status: Optional: DRAFT, OPEN, OVERDUE, PAID, CANCELED (leer = alle)

    Returns:
        JSON-Objekt mit Rechnungen und Metadaten
    """
    import json

    params = [f"per_page=250", f"from={from_date}", f"to={to_date}"]

    if status:
        params.append(f"status={status.upper()}")

    query = "&".join(params)
    result = api_request(f"invoices?{query}")

    if "error" in result:
        return json.dumps({
            "error": result["error"],
            "query": {"from": from_date, "to": to_date, "status": status or "alle"},
            "invoices": []
        })

    invoices = _normalize_list(result, "invoices")

    if not invoices:
        return json.dumps({
            "message": f"Keine Rechnungen gefunden für Zeitraum {from_date} bis {to_date}" + (f" (Status: {status})" if status else ""),
            "query": {"from": from_date, "to": to_date, "status": status or "alle"},
            "count": 0,
            "invoices": []
        })

    # Kundennamen abrufen (mit Cache)
    client_ids = set(inv.get("client_id") for inv in invoices if inv.get("client_id"))
    client_names = get_client_names_batch(client_ids)

    # Ergebnis aufbereiten
    invoice_list = []
    total_sum = 0
    for inv in invoices:
        cid = inv.get("client_id", "")
        net = float(inv.get("total_net", 0) or 0)
        total_sum += net
        inv_id = str(inv.get("id", ""))
        link_ref = make_link_ref(inv_id, LINK_TYPE_INVOICE)
        register_link(link_ref, _build_web_link("invoices", inv_id))
        invoice_list.append({
            "id": inv_id,
            "link_ref": link_ref,
            "invoice_number": inv.get("invoice_number"),
            "client_id": cid,
            "client_name": client_names.get(cid, "-"),
            "date": inv.get("date"),
            "due_date": inv.get("due_date"),
            "status": inv.get("status"),
            "total_net": inv.get("total_net"),
            "total_gross": inv.get("total_gross")
        })

    return json.dumps({
        "query": {"from": from_date, "to": to_date, "status": status or "alle"},
        "count": len(invoice_list),
        "total_net": round(total_sum, 2),
        "invoices": invoice_list
    }, indent=2)


@mcp.tool()
def billomat_search_invoices(
    client_id: int = None,
    invoice_number: str = "",
    status: str = "",
    limit: int = 10
) -> str:
    """Sucht Rechnungen nach verschiedenen Kriterien.

    Args:
        client_id: Kunden-ID (optional)
        invoice_number: Rechnungsnummer (optional)
        status: Status-Filter: DRAFT, OPEN, OVERDUE, PAID, CANCELED (optional)
        limit: Maximale Anzahl Ergebnisse (Standard: 10)
    """
    params = [f"per_page={limit}"]

    if client_id:
        params.append(f"client_id={client_id}")
    if invoice_number:
        encoded = urllib.parse.quote(invoice_number, safe='')
        params.append(f"invoice_number={encoded}")
    if status:
        params.append(f"status={status.upper()}")

    query = "&".join(params)
    result = api_request(f"invoices?{query}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = _normalize_list(result, "invoices")

    if not invoices:
        filters = []
        if client_id:
            filters.append(f"Kunde #{client_id}")
        if invoice_number:
            filters.append(f"Nr. {invoice_number}")
        if status:
            filters.append(f"Status {status}")
        return f"Keine Rechnungen gefunden für: {', '.join(filters) or 'diese Kriterien'}"

    billomat_id, _, _, _ = get_config()

    # Kundennamen abrufen
    client_ids = set(inv.get("client_id") for inv in invoices if inv.get("client_id"))
    client_names = {}
    for cid in client_ids:
        client_result = api_request(f"clients/{cid}")
        if "error" not in client_result:
            client = client_result.get("client", {})
            client_names[cid] = client.get("name", client.get("company", f"Kunde #{cid}"))

    output = [f"Gefundene Rechnungen ({len(invoices)}):"]
    for inv in invoices:
        inv_id = str(inv.get('id', ''))
        link_ref = make_link_ref(inv_id, LINK_TYPE_INVOICE)
        web_link = _build_web_link("invoices", inv_id)
        register_link(link_ref, web_link)
        cid = inv.get("client_id", "")
        client_name = client_names.get(cid, "-")
        inv_status = inv.get("status", "-")
        total = inv.get("total_net", "0")
        inv_number = inv.get("invoice_number", "-")
        date = inv.get("date", "-")

        # Items abrufen
        items_result = api_request(f"invoice-items?invoice_id={inv_id}")
        items = _normalize_list(items_result, "invoice-items") if "error" not in items_result else []
        items_summary = ", ".join([item.get('title', '-')[:30] for item in items[:3]])
        if len(items) > 3:
            items_summary += f" (+{len(items)-3})"

        output.append(f"- #{inv_id} [{link_ref}]: {inv_number} | {date} | {client_name} | {total}€ ({inv_status})")
        output.append(f"  Positionen: {items_summary or '-'}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    return "\n".join(output)


@mcp.tool()
def billomat_add_invoice_item(
    invoice_id: int,
    title: str,
    quantity: float,
    unit_price: float,
    unit: str = "Stunden",
    description: str = ""
) -> str:
    """Fügt eine Position zur Rechnung hinzu.

    Args:
        invoice_id: Die Rechnungs-ID
        title: Titel/Bezeichnung der Position
        quantity: Anzahl/Menge
        unit_price: Einzelpreis in Euro
        unit: Einheit (z.B. "Stunden", "Stück", "Pauschal")
        description: Optionale Beschreibung
    """
    item_data = {
        "invoice_id": invoice_id,
        "title": title,
        "quantity": quantity,
        "unit_price": unit_price,
        "unit": unit
    }

    if description:
        item_data["description"] = description

    result = api_request("invoice-items", "POST", {"invoice-item": item_data})

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    item = result.get("invoice-item", {})
    line_total = quantity * unit_price

    return f"""Position hinzugefügt!
- Titel: {title}
- Menge: {quantity} {unit}
- Einzelpreis: {unit_price}€
- Gesamt: {line_total}€
- Position-ID: {item.get('id')}"""


@mcp.tool()
def billomat_add_timelog_to_invoice(
    invoice_id: int,
    date: str,
    hours: float,
    activity: str,
    hourly_rate: float = 150.0
) -> str:
    """Fügt einen Zeiteintrag als Position zur Rechnung hinzu.

    Args:
        invoice_id: Die Rechnungs-ID
        date: Datum des Eintrags (YYYY-MM-DD)
        hours: Anzahl Stunden
        activity: Beschreibung der Tätigkeit
        hourly_rate: Stundensatz in Euro (Standard: 150€)
    """
    # Formatiere Titel mit Datum
    title = f"{date}: {activity}"

    item_data = {
        "invoice_id": invoice_id,
        "title": title,
        "quantity": hours,
        "unit_price": hourly_rate,
        "unit": "Stunden"
    }

    result = api_request("invoice-items", "POST", {"invoice-item": item_data})

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    item = result.get("invoice-item", {})
    line_total = hours * hourly_rate

    return f"""Zeiteintrag hinzugefügt!
- Datum: {date}
- Tätigkeit: {activity}
- Stunden: {hours}
- Stundensatz: {hourly_rate}€
- Gesamt: {line_total}€"""


@mcp.tool()
def billomat_get_invoice_items(invoice_id: int) -> str:
    """Zeigt alle Positionen einer Rechnung."""
    result = api_request(f"invoice-items?invoice_id={invoice_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    items = _normalize_list(result, "invoice-items")

    if not items:
        return f"Keine Positionen in Rechnung #{invoice_id}"

    output = [f"Positionen in Rechnung #{invoice_id}:"]
    total = 0
    for i in items:
        qty = float(i.get("quantity", 1))
        price = float(i.get("unit_price", 0))
        unit = i.get("unit", "")
        line_total = qty * price
        total += line_total
        output.append(f"- ID {i.get('id')}: {i.get('title', '-')}: {qty} {unit} x {price}€ = {line_total}€")

    output.append(f"\nSumme netto: {total}€")
    return "\n".join(output)


@mcp.tool()
def billomat_search_invoices_by_article(
    article_number: str,
    from_date: str = "",
    to_date: str = "",
    status: str = ""
) -> str:
    """Findet alle Rechnungen die einen bestimmten Artikel enthalten.

    Sucht direkt über die Billomat invoice-items API nach article_number,
    statt alle Rechnungen einzeln abzufragen. Sehr effizient!

    Args:
        article_number: Artikel-Code (z.B. "RVP1", "CONS")
        from_date: Optional, Start-Datum (YYYY-MM-DD)
        to_date: Optional, End-Datum (YYYY-MM-DD)
        status: Optional, Rechnungsstatus-Filter (DRAFT, OPEN, PAID, CANCELED)
    """
    import json

    # Alle invoice-items mit dieser article_number holen
    params = ["per_page=250"]
    encoded = urllib.parse.quote(article_number, safe='')
    params.append(f"article_number={encoded}")
    query = "&".join(params)

    result = api_request(f"invoice-items?{query}")

    if "error" in result:
        return json.dumps({"error": result["error"], "invoices": []})

    items = _normalize_list(result, "invoice-items")

    if not items:
        return json.dumps({
            "message": f"Keine Rechnungspositionen mit Artikel '{article_number}' gefunden.",
            "count": 0,
            "invoices": []
        })

    # Invoice-IDs sammeln und Positionen gruppieren
    invoice_items_map = {}  # invoice_id -> [items]
    for item in items:
        inv_id = str(item.get("invoice_id", ""))
        if inv_id:
            if inv_id not in invoice_items_map:
                invoice_items_map[inv_id] = []
            invoice_items_map[inv_id].append(item)

    # Rechnungsdetails holen
    invoice_list = []
    client_ids = set()

    for inv_id in invoice_items_map:
        inv_result = api_request(f"invoices/{inv_id}")
        if "error" in inv_result:
            continue
        inv = inv_result.get("invoice", {})

        # Datumsfilter
        inv_date = inv.get("date", "")
        if from_date and inv_date < from_date:
            continue
        if to_date and inv_date > to_date:
            continue

        # Statusfilter
        if status and inv.get("status", "").upper() != status.upper():
            continue

        cid = inv.get("client_id", "")
        if cid:
            client_ids.add(cid)

        # Positionen für diesen Artikel
        matched_items = []
        article_total = 0
        for item in invoice_items_map[inv_id]:
            qty = float(item.get("quantity", 1) or 1)
            price = float(item.get("unit_price", 0) or 0)
            line_total = qty * price
            article_total += line_total
            matched_items.append({
                "title": item.get("title", "-"),
                "quantity": qty,
                "unit": item.get("unit", ""),
                "unit_price": price,
                "total": round(line_total, 2)
            })

        link_ref = make_link_ref(inv_id, LINK_TYPE_INVOICE)
        register_link(link_ref, _build_web_link("invoices", inv_id))

        invoice_list.append({
            "id": inv_id,
            "link_ref": link_ref,
            "invoice_number": inv.get("invoice_number"),
            "client_id": cid,
            "date": inv_date,
            "status": inv.get("status"),
            "total_net": inv.get("total_net"),
            "total_gross": inv.get("total_gross"),
            "article_items": matched_items,
            "article_total_net": round(article_total, 2)
        })

    # Kundennamen auflösen
    if client_ids:
        client_names = get_client_names_batch(client_ids)
        for inv in invoice_list:
            inv["client_name"] = client_names.get(inv.get("client_id"), "-")

    # Nach Datum sortieren (neueste zuerst)
    invoice_list.sort(key=lambda x: x.get("date", ""), reverse=True)

    total_article_sum = sum(inv.get("article_total_net", 0) for inv in invoice_list)

    return json.dumps({
        "article_number": article_number,
        "query": {
            "from": from_date or "alle",
            "to": to_date or "alle",
            "status": status or "alle"
        },
        "count": len(invoice_list),
        "total_article_net": round(total_article_sum, 2),
        "invoices": invoice_list
    }, indent=2)


@mcp.tool()
def billomat_update_invoice_item(
    item_id: int,
    unit_price: float = None,
    quantity: float = None,
    title: str = "",
    unit: str = "",
    description: str = ""
) -> str:
    """Aktualisiert eine Rechnungsposition.

    WICHTIG: Nur bei Rechnungen im DRAFT Status möglich!

    Args:
        item_id: Die Positions-ID (nicht Rechnungs-ID!)
        unit_price: Neuer Einzelpreis in Euro (optional)
        quantity: Neue Menge (optional)
        title: Neuer Titel (optional)
        unit: Neue Einheit (optional)
        description: Neue Beschreibung (optional)
    """
    item_data = {}

    if unit_price is not None:
        item_data["unit_price"] = unit_price
    if quantity is not None:
        item_data["quantity"] = quantity
    if title:
        item_data["title"] = title
    if unit:
        item_data["unit"] = unit
    if description:
        item_data["description"] = description

    if not item_data:
        return "Fehler: Keine Daten zum Aktualisieren angegeben"

    result = api_request(f"invoice-items/{item_id}", "PUT", {"invoice-item": item_data})

    if "error" in result:
        return f"Fehler: {result['error']}"

    item = result.get("invoice-item", {})
    qty = float(item.get("quantity", 1))
    price = float(item.get("unit_price", 0))
    line_total = qty * price

    return f"""Position #{item_id} aktualisiert!
- Titel: {item.get('title', '-')}
- Menge: {qty} {item.get('unit', '')}
- Einzelpreis: {price}€
- Gesamt: {line_total}€"""


@mcp.tool()
def billomat_delete_invoice_item(item_id: int) -> str:
    """Löscht eine Rechnungsposition.

    WICHTIG: Nur bei Rechnungen im DRAFT Status möglich!
    Nach dem Löschen werden die verbleibenden Positionen automatisch neu nummeriert.

    Args:
        item_id: Die Positions-ID (nicht Rechnungs-ID!)
    """
    result = api_request(f"invoice-items/{item_id}", "DELETE")

    if "error" in result:
        return f"Fehler: {result['error']}"

    return f"Position #{item_id} erfolgreich gelöscht."


@mcp.tool()
def billomat_add_article_to_invoice(
    invoice_id: int,
    article_number: str,
    quantity: int = 1,
    description: str = ""
) -> str:
    """Fügt einen Artikel zur Rechnung hinzu.

    Args:
        invoice_id: Die Rechnungs-ID
        article_number: Artikelnummer des Artikels
        quantity: Anzahl (Standard: 1)
        description: Optionale zusätzliche Beschreibung
    """
    # Zuerst Artikel-ID anhand der Artikelnummer finden
    result = api_request(f"articles?article_number={article_number}")

    if "error" in result:
        return f"Fehler beim Suchen des Artikels: {result['error']}"

    articles = _normalize_list(result, "articles")

    if not articles:
        return f"Artikel '{article_number}' nicht gefunden. Nutze billomat_get_articles() fuer verfuegbare Artikel."

    article = articles[0]
    article_id = article.get("id")

    # Rechnungsposition erstellen
    item_data = {
        "invoice_id": invoice_id,
        "article_id": article_id,
        "quantity": quantity
    }

    if description:
        item_data["description"] = description

    result = api_request("invoice-items", "POST", {"invoice-item": item_data})

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    item = result.get("invoice-item", {})
    billomat_id, _, _, _ = get_config()
    edit_url = _build_edit_url("invoices", invoice_id)

    return f"""Artikel hinzugefügt!
- Artikel: {article.get('title')}
- Anzahl: {quantity}
- Einzelpreis: {article.get('sales_price', '0')}€
- Position-ID: {item.get('id')}

Rechnung bearbeiten: {edit_url}"""


# ==================== PAYMENT FUNCTIONS ====================

@mcp.tool()
def billomat_open_invoice(invoice_id: int) -> str:
    """Öffnet eine Rechnung im Browser zur Bearbeitung.

    Args:
        invoice_id: Die Rechnungs-ID

    Returns:
        Bestätigung mit URL
    """
    import webbrowser

    url = _build_edit_url("invoices", invoice_id)
    if not url:
        return "Fehler: Billomat nicht konfiguriert"

    webbrowser.open(url)

    return f"Rechnung #{invoice_id} im Browser geöffnet:\n{url}"


@mcp.tool()
def billomat_mark_invoice_paid(invoice_id: int, payment_type: str = "BANK_TRANSFER") -> str:
    """Markiert eine Rechnung als vollständig bezahlt durch Erstellen einer Zahlung.

    WICHTIG: Diese Aktion kann nicht rückgängig gemacht werden!

    Args:
        invoice_id: Die Rechnungs-ID
        payment_type: Zahlungsart (BANK_TRANSFER, CASH, PAYPAL, CREDIT_CARD, etc.)

    Returns:
        Bestätigung der Zahlung
    """
    from datetime import date

    # Zuerst Rechnung prüfen
    invoice_result = api_request(f"invoices/{invoice_id}")
    if "error" in invoice_result:
        return f"Fehler: {invoice_result['error']}"

    inv = invoice_result.get("invoice", {})
    current_status = inv.get("status", "")
    inv_number = inv.get("invoice_number", "-")
    total_gross = float(inv.get("total_gross", "0"))

    if current_status == "PAID":
        return f"Rechnung {inv_number} ist bereits als bezahlt markiert."

    if current_status not in ("OPEN", "OVERDUE"):
        return f"Fehler: Rechnung {inv_number} hat Status '{current_status}'. Nur OPEN oder OVERDUE Rechnungen können als bezahlt markiert werden."

    # Zahlung erstellen via POST /invoice-payments
    payment_data = {
        "invoice-payment": {
            "invoice_id": invoice_id,
            "amount": total_gross,
            "date": date.today().isoformat(),
            "type": payment_type,
            "mark_invoice_as_paid": 1
        }
    }

    result = api_request("invoice-payments", "POST", payment_data)

    if "error" in result:
        return f"Fehler beim Markieren als bezahlt: {result['error']}"

    payment_id = result.get("invoice-payment", {}).get("id", "-")

    return f"""Rechnung als bezahlt markiert!
- Rechnungs-ID: {invoice_id}
- Rechnungsnummer: {inv_number}
- Betrag: {total_gross:.2f}€ brutto
- Zahlungsart: {payment_type}
- Zahlungs-ID: {payment_id}
- Neuer Status: PAID"""


# =============================================================================
# Batch-Tools für Performance-Optimierung
# =============================================================================

@mcp.tool()
def billomat_create_complete_offer(
    customer_id: int,
    items: str,
    finalize: bool = False
) -> str:
    """Erstellt Angebot mit allen Positionen in EINEM Aufruf.

    Deutlich schneller als create_offer + mehrere add_offer_item Calls.

    Args:
        customer_id: Kunden-ID
        items: JSON-Array mit Positionen:
            [
                {"article": "PROD-1", "quantity": 1},
                {"article": "SVC-1", "quantity": 2, "description": "Setup & Training"}
            ]
        finalize: Wenn True, wird Angebot direkt finalisiert

    Returns:
        Angebot-Details inkl. PDF-Download-Info bei Finalisierung
    """
    import json

    billomat_id, _, _, _ = get_config()

    try:
        item_list = json.loads(items)
    except json.JSONDecodeError as e:
        return f"Fehler: Ungültiges JSON - {str(e)}"

    # 1. Angebot erstellen
    offer_result = api_request("offers", "POST", {"offer": {"client_id": customer_id}})

    if "error" in offer_result:
        return f"Fehler beim Erstellen: {offer_result['error']}"

    offer_id = offer_result.get("offer", {}).get("id")

    if not offer_id:
        return "Fehler: Konnte Angebots-ID nicht ermitteln"

    # 2. Alle Items hinzufügen (mit Cache)
    added_items = []
    total = 0
    errors = []

    for item in item_list:
        article_number = item.get("article")
        quantity = item.get("quantity", 1)
        description = item.get("description", "")

        # Artikel aus Cache holen
        article = get_article_cached(article_number)

        if not article:
            errors.append(f"Artikel '{article_number}' nicht gefunden")
            continue

        item_data = {
            "offer_id": offer_id,
            "article_id": article["id"],
            "quantity": quantity
        }

        if description:
            item_data["description"] = description

        result = api_request("offer-items", "POST", {"offer-item": item_data})

        if "error" in result:
            errors.append(f"{article_number}: {result['error']}")
        else:
            price = float(article.get("sales_price", 0))
            line_total = price * quantity
            total += line_total
            added_items.append(f"{article_number} x{quantity}: {line_total}€")

    # 3. Optional finalisieren
    offer_number = "-"
    if finalize and added_items:
        complete_result = api_request(f"offers/{offer_id}/complete", "PUT")
        if "error" not in complete_result:
            offer_data = api_request(f"offers/{offer_id}")
            offer_number = offer_data.get("offer", {}).get("offer_number", "-")

    # Ergebnis zusammenstellen
    offer_id_str = str(offer_id)
    link_ref = make_link_ref(offer_id_str, LINK_TYPE_OFFER)
    web_link = _build_web_link("offers", offer_id_str)
    register_link(link_ref, web_link)
    edit_url = _build_edit_url("offers", offer_id)

    output = [f"Angebot erstellt!"]
    output.append(f"- ID: {offer_id} [{link_ref}]")
    if finalize:
        output.append(f"- Angebotsnummer: {offer_number}")
    output.append(f"- Status: {'Finalisiert' if finalize else 'Entwurf'}")
    output.append(f"- Positionen:")
    for item in added_items:
        output.append(f"  * {item}")
    output.append(f"- Summe netto: {total}€")
    output.append(f"- Bearbeiten: {edit_url}")
    output.append(f"- Web: {{{{LINK:{link_ref}}}}}")

    if finalize:
        output.append(f"\nPDF herunterladen: download_offer_pdf({offer_id})")

    if errors:
        output.append(f"\nWarnungen:")
        for err in errors:
            output.append(f"  ⚠ {err}")

    return "\n".join(output)


@mcp.tool()
def billomat_add_invoice_items_batch(invoice_id: int, items: str) -> str:
    """Fügt mehrere Positionen zur Rechnung in EINEM Aufruf hinzu.

    Deutlich schneller als mehrere add_invoice_item/add_timelog_to_invoice Calls.

    Args:
        invoice_id: Rechnungs-ID
        items: JSON-Array mit Positionen:
            [
                {"title": "Beratung 10.12.", "hours": 2, "rate": 150},
                {"title": "Entwicklung 11.12.", "hours": 5, "rate": 150},
                {"article": "PROD-1", "quantity": 1}
            ]

    Returns:
        Zusammenfassung aller hinzugefügten Positionen
    """
    import json

    try:
        item_list = json.loads(items)
    except json.JSONDecodeError as e:
        return f"Fehler: Ungültiges JSON - {str(e)}"

    added = []
    total = 0
    errors = []

    for item in item_list:
        if "article" in item:
            # Artikel hinzufügen (mit Cache)
            article_number = item["article"]
            quantity = item.get("quantity", 1)

            article = get_article_cached(article_number)

            if not article:
                errors.append(f"Artikel '{article_number}' nicht gefunden")
                continue

            item_data = {
                "invoice_id": invoice_id,
                "article_id": article["id"],
                "quantity": quantity
            }

            if item.get("description"):
                item_data["description"] = item["description"]

            result = api_request("invoice-items", "POST", {"invoice-item": item_data})

            if "error" in result:
                errors.append(f"{article_number}: {result['error']}")
            else:
                price = float(article.get("sales_price", 0)) * quantity
                total += price
                added.append(f"{article_number} x{quantity}: {price}€")

        else:
            # Manuelle Position (Stunden/Dienstleistung)
            title = item.get("title", "Position")
            hours = item.get("hours", item.get("quantity", 1))
            rate = item.get("rate", item.get("unit_price", 150))
            unit = item.get("unit", "Stunden")

            item_data = {
                "invoice_id": invoice_id,
                "title": title,
                "quantity": hours,
                "unit_price": rate,
                "unit": unit
            }

            if item.get("description"):
                item_data["description"] = item["description"]

            result = api_request("invoice-items", "POST", {"invoice-item": item_data})

            if "error" in result:
                errors.append(f"{title}: {result['error']}")
            else:
                line_total = hours * rate
                total += line_total
                added.append(f"{title}: {hours} {unit} x {rate}€ = {line_total}€")

    # Ergebnis zusammenstellen
    output = [f"Positionen zur Rechnung #{invoice_id} hinzugefügt:"]
    output.append("")
    for item in added:
        output.append(f"  • {item}")
    output.append("")
    output.append(f"Summe: {total}€")

    if errors:
        output.append(f"\nWarnungen:")
        for err in errors:
            output.append(f"  ⚠ {err}")

    return "\n".join(output)


@mcp.tool()
def billomat_get_open_invoices() -> str:
    """Holt alle offenen und überfälligen Rechnungen aus Billomat.

    Nutzt Client-Cache für schnellere Ausführung bei wiederholten Aufrufen.

    Returns:
        Liste aller Rechnungen mit Status OPEN oder OVERDUE
    """
    # Offene Rechnungen
    open_result = api_request("invoices?status=OPEN&per_page=100")
    overdue_result = api_request("invoices?status=OVERDUE&per_page=100")

    all_invoices = []

    # Offene sammeln
    if "error" not in open_result:
        invoices = _normalize_list(open_result, "invoices")
        for inv in invoices:
            inv["_status_display"] = "Offen"
        all_invoices.extend(invoices)

    # Überfällige sammeln
    if "error" not in overdue_result:
        invoices = _normalize_list(overdue_result, "invoices")
        for inv in invoices:
            inv["_status_display"] = "ÜBERFÄLLIG"
        all_invoices.extend(invoices)

    if not all_invoices:
        return "Keine offenen oder überfälligen Rechnungen gefunden."

    # Kundennamen mit Cache abrufen
    client_ids = set(inv.get("client_id") for inv in all_invoices if inv.get("client_id"))
    client_names = get_client_names_batch(client_ids)

    output = [f"Offene Rechnungen ({len(all_invoices)}):"]
    output.append("")

    billomat_id, _, _, _ = get_config()
    total_open = 0

    for inv in all_invoices:
        inv_id = str(inv.get("id", ""))
        link_ref = make_link_ref(inv_id, LINK_TYPE_INVOICE)
        web_link = _build_web_link("invoices", inv_id)
        register_link(link_ref, web_link)
        inv_number = inv.get("invoice_number", "-")
        client_id = inv.get("client_id", "")
        client_name = client_names.get(client_id, "-")
        total_gross = float(inv.get("total_gross", 0))
        due_date = inv.get("due_date", "-")
        status = inv.get("_status_display", inv.get("status", "-"))

        total_open += total_gross
        output.append(f"- #{inv_id} [{link_ref}]: {inv_number} | {client_name} | {total_gross:.2f}€ brutto | Fällig: {due_date} | {status}")
        output.append(f"  -> {{{{LINK:{link_ref}}}}}")

    output.append("")
    output.append(f"Gesamt offen: {total_open:.2f}€ brutto")

    return "\n".join(output)


if __name__ == "__main__":
    mcp.run()
