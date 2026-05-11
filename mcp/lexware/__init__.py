#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Lexware/lexoffice MCP Server
============================
MCP Server für Lexware Office (lexoffice) API-Zugriff.
Ermöglicht Claude das Suchen und Erstellen von Kontakten, Angeboten und Rechnungen.

API-Dokumentation: https://developers.lexware.io/docs/
Base URL: https://api.lexoffice.io
Rate Limit: 2 requests/second
"""

import json
import os
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from mcp.server.fastmcp import FastMCP


def _format_voucher_date(d: date = None) -> str:
    """Format date for Lexware API (RFC 3339 with timezone).

    Lexware API requires format: yyyy-MM-ddTHH:mm:ss.SSSXXX
    Example: 2026-01-01T00:00:00.000+01:00
    """
    if d is None:
        d = date.today()
    # Create datetime at midnight with CET timezone (+01:00)
    cet = timezone(timedelta(hours=1))
    dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, cet)
    # Format as RFC 3339 with milliseconds and proper timezone (+HH:MM)
    tz = dt.strftime("%z")  # Returns +0100
    tz_formatted = f"{tz[:3]}:{tz[3:]}"  # Convert to +01:00
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000") + tz_formatted

from _mcp_api import load_config, mcp_log

mcp = FastMCP("lexware")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "receipt_long",
    "color": "#8bc34a",
    "beta": True
}

# Integration schema for Settings UI
INTEGRATION_SCHEMA = {
    "name": "Lexware Office",
    "icon": "receipt_long",
    "color": "#8bc34a",
    "config_key": "lexware",
    "auth_type": "api_key",
    "beta": True,
    "fields": [
        {
            "key": "api_key",
            "label": "API Key",
            "type": "password",
            "required": True,
            "hint": "Lexware Office API Key (developers.lexware.io)",
        },
    ],
    "test_tool": "lexware_get_articles",
    "setup": {
        "description": "Buchhaltung und Rechnungen",
        "requirement": "Lexware API Key",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "Lexware API-Key eintragen",
        ],
    },
}

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    # Contact queries
    "lexware_search_contacts",
    "lexware_get_contact",
    # Article queries
    "lexware_get_articles",
    "lexware_get_article",
    "lexware_search_articles",
    # Invoice queries
    "lexware_get_invoice",
    "lexware_get_recent_invoices",
    "lexware_get_open_invoices",
    "lexware_get_payments",
    # Quotation queries
    "lexware_get_quotation",
    "lexware_get_recent_quotations",
    # Credit note queries
    "lexware_get_credit_note",
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    # Contact management
    "lexware_create_contact",
    "lexware_update_contact",
    # Invoices
    "lexware_create_invoice",
    "lexware_add_invoice_item",
    "lexware_finalize_invoice",
    # Quotations
    "lexware_create_quotation",
    "lexware_add_quotation_item",
    # Credit notes
    "lexware_create_credit_note",
    # PDF Downloads (create files)
    "lexware_download_invoice_pdf",
    "lexware_download_quotation_pdf",
}

# =============================================================================
# API Configuration
# =============================================================================

API_BASE_URL = "https://api.lexoffice.io/v1"

# Rate limiting (2 req/sec)
_last_request_time = 0
MIN_REQUEST_INTERVAL = 0.5  # 500ms between requests

# API Logging
_api_log_enabled = None  # Lazy-loaded from config


def _log_api(message: str):
    """Log API-Kommunikation wenn aktiviert."""
    global _api_log_enabled
    if _api_log_enabled is None:
        config = load_config()
        _api_log_enabled = config.get("lexware", {}).get("log_api", False)

    if _api_log_enabled:
        mcp_log(f"[Lexware] {message}")


def get_config():
    """Lädt Lexware-Konfiguration."""
    api_key = os.environ.get("LEXWARE_API_KEY")

    if not api_key:
        config = load_config()
        lexware = config.get("lexware", {})
        api_key = lexware.get("api_key")

    return api_key


def is_configured() -> bool:
    """Prüft ob Lexware API konfiguriert und aktiviert ist.

    Wird vom System verwendet um zu entscheiden, ob dieses MCP
    geladen werden soll.

    Config-Optionen in apis.json:
        enabled: false  - MCP deaktivieren (auch wenn api_key gesetzt)
        api_key: "..."  - API-Key (erforderlich)
    """
    config = load_config().get("lexware", {})

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    return bool(get_config())


def api_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Führt Lexware API-Request aus mit Rate-Limiting und optionalem Logging."""
    global _last_request_time

    api_key = get_config()

    if not api_key:
        return {"error": "Lexware nicht konfiguriert. API-Key in apis.json unter 'lexware.api_key' setzen."}

    # Rate limiting
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    url = f"{API_BASE_URL}/{endpoint}"

    # Log request
    _log_api(f">>> {method} {endpoint}")
    if data:
        data_str = json.dumps(data, ensure_ascii=False)
        if len(data_str) > 500:
            _log_api(f"    Body: {data_str[:500]}...")
        else:
            _log_api(f"    Body: {data_str}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        _last_request_time = time.time()
        with urllib.request.urlopen(req, timeout=30) as response:
            response_text = response.read().decode("utf-8")
            # Log response
            _log_api(f"<<< {response.status} OK ({len(response_text)} bytes)")
            if response_text:
                result = json.loads(response_text)
                # Log summary of result
                if isinstance(result, dict):
                    if "content" in result and isinstance(result["content"], list):
                        _log_api(f"    Result: {len(result['content'])} items")
                    elif "id" in result:
                        _log_api(f"    Result: id={result['id']}")
                return result
            return {"success": True}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        # Log error
        _log_api(f"<<< {e.code} ERROR")
        _log_api(f"    Error body: {error_body[:500]}")
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("message", error_body[:200])
        except (json.JSONDecodeError, KeyError):
            error_msg = error_body[:200]
        return {"error": f"HTTP {e.code}: {error_msg}"}
    except Exception as e:
        return {"error": str(e)}


def download_document(endpoint: str, save_path: str = "", filename: str = "") -> tuple[bool, str]:
    """Download PDF document from Lexware."""
    api_key = get_config()

    if not api_key:
        return False, "Fehler: Lexware nicht konfiguriert"

    url = f"{API_BASE_URL}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/pdf"
    }

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            pdf_data = response.read()

            # Resolve save path
            if save_path:
                save_path_obj = Path(save_path)
                if not save_path_obj.is_absolute():
                    project_root = Path(__file__).parent.parent.parent
                    temp_dir = project_root / save_path
                else:
                    temp_dir = save_path_obj
            else:
                temp_dir = Path(tempfile.gettempdir()) / "lexware_pdfs"

            temp_dir.mkdir(parents=True, exist_ok=True)

            pdf_path = temp_dir / f"{filename}.pdf"
            pdf_path.write_bytes(pdf_data)

            return True, str(pdf_path.resolve())

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"Fehler: Dokument nicht gefunden oder noch nicht finalisiert"
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return False, f"Fehler HTTP {e.code}: {error_body[:200]}"
    except Exception as e:
        return False, f"Fehler: {str(e)}"


# =============================================================================
# Contact Functions (Kunden/Lieferanten)
# =============================================================================

def _extract_contact_emails(contact: dict) -> list[str]:
    """Extract all email addresses from a contact."""
    emails = []
    email_addresses = contact.get("emailAddresses", {})
    for key in ["business", "private", "office"]:
        addr_list = email_addresses.get(key, [])
        if isinstance(addr_list, list):
            emails.extend([e.lower() for e in addr_list if e])
    return emails


def _format_contact_result(contacts: list) -> str:
    """Format contacts for output."""
    output = [f"Gefundene Kontakte ({len(contacts)}):"]
    for c in contacts:
        contact_id = c.get("id", "-")
        # Get name from company or person
        company = c.get("company", {})
        person = c.get("person", {})
        if company:
            name = company.get("name", "-")
        elif person:
            name = f"{person.get('firstName', '')} {person.get('lastName', '')}".strip() or "-"
        else:
            name = "-"

        roles = c.get("roles", {})
        role_str = "Kunde" if roles.get("customer") else "Lieferant" if roles.get("vendor") else "-"

        # Get email from emailAddresses
        emails = _extract_contact_emails(c)
        email = emails[0] if emails else "-"

        output.append(f"- ID {contact_id}: {name} ({role_str}) - {email}")
    return "\n".join(output)


@mcp.tool()
def lexware_search_contacts(query: str, role: str = "") -> str:
    """Sucht Kontakte in Lexware nach Firmenname, Personenname oder E-Mail.

    Args:
        query: Suchbegriff (Firmenname, Personenname oder E-Mail)
        role: Optional: "customer" oder "vendor" zum Filtern

    Hinweis: Suche nach Firmennamen liefert die besten Ergebnisse.
    Bei E-Mail-Suche werden alle Kontakte geladen und lokal gefiltert.
    """
    query_lower = query.lower().strip()

    # If query looks like an email, search all contacts and filter locally
    if "@" in query:
        # Load all contacts (paginated)
        params = ["size=250"]  # Max page size
        if role:
            params.append(f"role={role}")

        result = api_request(f"contacts?{'&'.join(params)}")

        if "error" in result:
            return f"Fehler: {result['error']}"

        all_contacts = result.get("content", [])

        # Filter by email
        matching = []
        for c in all_contacts:
            contact_emails = _extract_contact_emails(c)
            if query_lower in contact_emails:
                matching.append(c)

        if not matching:
            return f"Keine Kontakte gefunden mit E-Mail: '{query}'"

        return _format_contact_result(matching)

    # Standard search by name (works for company and person names)
    params = [f"name={urllib.parse.quote(query, safe='')}"]
    if role:
        params.append(f"role={role}")

    result = api_request(f"contacts?{'&'.join(params)}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    contacts = result.get("content", [])

    if not contacts:
        return f"Keine Kontakte gefunden für: '{query}'"

    return _format_contact_result(contacts)


@mcp.tool()
def lexware_get_contact(contact_id: str) -> str:
    """Holt Details eines Kontakts aus Lexware.

    Args:
        contact_id: Die Kontakt-UUID
    """
    result = api_request(f"contacts/{contact_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    c = result

    # Extract company or person info
    company = c.get("company", {})
    person = c.get("person", {})

    if company:
        name = company.get("name", "-")
        contact_person = company.get("contactPersons", [{}])[0] if company.get("contactPersons") else {}
        contact_name = f"{contact_person.get('firstName', '')} {contact_person.get('lastName', '')}".strip()
    else:
        name = f"{person.get('firstName', '')} {person.get('lastName', '')}".strip() or "-"
        contact_name = ""

    # Extract address
    addresses = c.get("addresses", {})
    billing = addresses.get("billing", [{}])[0] if addresses.get("billing") else {}
    address_parts = [billing.get("street", ""), f"{billing.get('zip', '')} {billing.get('city', '')}"]
    address = ", ".join(p for p in address_parts if p.strip())

    # Extract email
    emails = c.get("emailAddresses", {})
    email_list = emails.get("business", emails.get("private", []))
    email = email_list[0] if email_list else "-"

    # Extract phone
    phones = c.get("phoneNumbers", {})
    phone_list = phones.get("business", phones.get("mobile", []))
    phone = phone_list[0] if phone_list else "-"

    # Roles
    roles = c.get("roles", {})
    role_str = []
    if roles.get("customer"):
        role_str.append("Kunde")
    if roles.get("vendor"):
        role_str.append("Lieferant")

    output = f"""Kontakt #{contact_id}:
Name: {name}"""

    if contact_name:
        output += f"\nAnsprechpartner: {contact_name}"

    output += f"""
E-Mail: {email}
Telefon: {phone}
Adresse: {address or '-'}
Land: {billing.get('countryCode', '-')}
Rolle: {', '.join(role_str) or '-'}
Kundennummer: {c.get('roles', {}).get('customer', {}).get('number', '-') if isinstance(c.get('roles', {}).get('customer'), dict) else '-'}"""

    return output


@mcp.tool()
def lexware_create_contact(
    name: str,
    email: str = "",
    company: str = "",
    street: str = "",
    zip_code: str = "",
    city: str = "",
    country_code: str = "DE",
    phone: str = "",
    is_customer: bool = True,
    is_vendor: bool = False
) -> str:
    """Erstellt einen neuen Kontakt in Lexware.

    Args:
        name: Name (Person oder Firma)
        email: E-Mail-Adresse
        company: Firmenname (wenn leer, wird als Person angelegt)
        street: Straße und Hausnummer
        zip_code: Postleitzahl
        city: Stadt
        country_code: Ländercode (DE, AT, CH, etc.)
        phone: Telefonnummer
        is_customer: Als Kunde anlegen (Standard: True)
        is_vendor: Als Lieferant anlegen (Standard: False)
    """
    contact_data = {
        "version": 0,
        "roles": {}
    }

    # Set roles
    if is_customer:
        contact_data["roles"]["customer"] = {}
    if is_vendor:
        contact_data["roles"]["vendor"] = {}

    # Company or Person
    # Note: Lexware uses firstName/lastName split. Billomat uses a single "name" field.
    # Split on first space only - lastName can have multiple parts (e.g., "Degli Esposti")
    if company:
        name_parts = name.split(" ", 1) if name else []
        contact_data["company"] = {
            "name": company,
            "contactPersons": [{
                "firstName": name_parts[0] if name_parts else "",
                "lastName": name_parts[1] if len(name_parts) > 1 else ""
            }] if name else []
        }
    else:
        name_parts = name.split(" ", 1)
        contact_data["person"] = {
            "firstName": name_parts[0] if name_parts else "",
            "lastName": name_parts[1] if len(name_parts) > 1 else ""
        }

    # Address
    if street or zip_code or city:
        contact_data["addresses"] = {
            "billing": [{
                "street": street,
                "zip": zip_code,
                "city": city,
                "countryCode": country_code
            }]
        }

    # Email
    if email:
        contact_data["emailAddresses"] = {
            "business": [email]
        }

    # Phone
    if phone:
        contact_data["phoneNumbers"] = {
            "business": [phone]
        }

    result = api_request("contacts", "POST", contact_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    contact_id = result.get("id", "-")
    return f"Kontakt erfolgreich erstellt! ID: {contact_id}"


@mcp.tool()
def lexware_update_contact(
    contact_id: str,
    name: str = "",
    email: str = "",
    street: str = "",
    zip_code: str = "",
    city: str = "",
    country_code: str = "",
    phone: str = ""
) -> str:
    """Aktualisiert einen bestehenden Kontakt in Lexware.

    Args:
        contact_id: Die Kontakt-UUID
        name: Neuer Name (optional)
        email: Neue E-Mail (optional)
        street: Neue Straße (optional)
        zip_code: Neue PLZ (optional)
        city: Neue Stadt (optional)
        country_code: Neuer Ländercode (optional)
        phone: Neue Telefonnummer (optional)
    """
    # First get current contact to preserve version
    current = api_request(f"contacts/{contact_id}")
    if "error" in current:
        return f"Fehler beim Laden: {current['error']}"

    # Update fields
    if name:
        if current.get("company"):
            current["company"]["name"] = name
        elif current.get("person"):
            name_parts = name.split(" ", 1)
            current["person"]["firstName"] = name_parts[0]
            current["person"]["lastName"] = name_parts[1] if len(name_parts) > 1 else ""

    if email:
        if "emailAddresses" not in current:
            current["emailAddresses"] = {}
        current["emailAddresses"]["business"] = [email]

    if phone:
        if "phoneNumbers" not in current:
            current["phoneNumbers"] = {}
        current["phoneNumbers"]["business"] = [phone]

    if street or zip_code or city or country_code:
        if "addresses" not in current:
            current["addresses"] = {"billing": [{}]}
        if not current["addresses"].get("billing"):
            current["addresses"]["billing"] = [{}]

        billing = current["addresses"]["billing"][0]
        if street:
            billing["street"] = street
        if zip_code:
            billing["zip"] = zip_code
        if city:
            billing["city"] = city
        if country_code:
            billing["countryCode"] = country_code

    result = api_request(f"contacts/{contact_id}", "PUT", current)

    if "error" in result:
        return f"Fehler: {result['error']}"

    return f"Kontakt #{contact_id} erfolgreich aktualisiert!"


# =============================================================================
# Article Functions (Artikel/Produkte)
# =============================================================================

@mcp.tool()
def lexware_get_articles() -> str:
    """Listet alle Artikel/Produkte aus Lexware."""
    result = api_request("articles?size=100")

    if "error" in result:
        return f"Fehler: {result['error']}"

    articles = result.get("content", [])

    if not articles:
        return "Keine Artikel gefunden"

    output = ["Verfügbare Artikel:"]
    for a in articles:
        article_id = a.get("id", "-")
        title = a.get("title", "-")
        article_num = a.get("articleNumber", "-")
        price = a.get("price", {}).get("netPrice", "0")
        unit = a.get("unitName", "Stück")
        output.append(f"- {article_num}: {title} ({price}€/{unit}) [ID: {article_id}]")

    return "\n".join(output)


@mcp.tool()
def lexware_get_article(article_id: str) -> str:
    """Holt Details eines Artikels.

    Args:
        article_id: Die Artikel-UUID
    """
    result = api_request(f"articles/{article_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    a = result

    return f"""Artikel #{article_id}:
Artikelnummer: {a.get('articleNumber', '-')}
Titel: {a.get('title', '-')}
Beschreibung: {a.get('description', '-')}
Typ: {a.get('type', '-')}
Einheit: {a.get('unitName', '-')}
Preis netto: {a.get('price', {}).get('netPrice', '0')}€
MwSt: {a.get('price', {}).get('taxRate', '0')}%"""


@mcp.tool()
def lexware_search_articles(query: str) -> str:
    """Sucht Artikel nach Titel oder Artikelnummer.

    Args:
        query: Suchbegriff
    """
    # Lexware doesn't have search, so we filter manually
    result = api_request("articles?size=250")

    if "error" in result:
        return f"Fehler: {result['error']}"

    articles = result.get("content", [])
    query_lower = query.lower()

    matched = [a for a in articles if
               query_lower in a.get("title", "").lower() or
               query_lower in a.get("articleNumber", "").lower()]

    if not matched:
        return f"Kein Artikel gefunden für: '{query}'"

    output = [f"Gefundene Artikel ({len(matched)}):"]
    for a in matched:
        article_id = a.get("id", "-")
        title = a.get("title", "-")
        article_num = a.get("articleNumber", "-")
        price = a.get("price", {}).get("netPrice", "0")
        output.append(f"- {article_num}: {title} ({price}€) [ID: {article_id}]")

    return "\n".join(output)


# =============================================================================
# Invoice Functions (Rechnungen)
# =============================================================================

@mcp.tool()
def lexware_create_invoice(
    contact_id: str,
    title: str = "",
    introduction: str = "",
    finalize: bool = False
) -> str:
    """Erstellt eine neue Rechnung für einen Kontakt.

    Args:
        contact_id: Die Kontakt-UUID
        title: Titel/Bezeichnung der Rechnung
        introduction: Einleitungstext
        finalize: Wenn True, wird Rechnung direkt finalisiert (Standard: False = Entwurf)
    """
    invoice_data = {
        "voucherDate": _format_voucher_date(),
        "address": {
            "contactId": contact_id
        },
        "lineItems": [],
        "totalPrice": {
            "currency": "EUR"
        },
        "taxConditions": {
            "taxType": "net"
        },
        "shippingConditions": {
            "shippingType": "none"
        }
    }

    if title:
        # Lexware API limits title to 25 characters
        invoice_data["title"] = title[:25]
    if introduction:
        invoice_data["introduction"] = introduction

    endpoint = "invoices"
    if finalize:
        endpoint += "?finalize=true"

    result = api_request(endpoint, "POST", invoice_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoice_id = result.get("id", "-")
    status = "Finalisiert" if finalize else "Entwurf"

    return f"""Rechnung erstellt!
- ID: {invoice_id}
- Status: {status}

Positionen hinzufügen mit: lexware_add_invoice_item("{invoice_id}", ...)"""


@mcp.tool()
def lexware_get_invoice(invoice_id: str) -> str:
    """Holt Details einer Rechnung aus Lexware.

    Args:
        invoice_id: Die Rechnungs-UUID
    """
    result = api_request(f"invoices/{invoice_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    inv = result

    # Status mapping
    status_map = {
        "draft": "Entwurf",
        "open": "Offen",
        "paid": "Bezahlt",
        "voided": "Storniert",
        "paidoff": "Abgeschrieben",
        "uncollectible": "Uneinbringlich"
    }
    status = status_map.get(inv.get("voucherStatus", ""), inv.get("voucherStatus", "-"))

    # Total
    total = inv.get("totalPrice", {})
    total_net = total.get("totalNetAmount", "0")
    total_gross = total.get("totalGrossAmount", "0")

    # Contact name
    address = inv.get("address", {})
    contact_name = address.get("name", "-")

    return f"""Rechnung #{invoice_id}:
Rechnungsnummer: {inv.get('voucherNumber', '-')}
Status: {status}
Kunde: {contact_name}
Datum: {inv.get('voucherDate', '-')}
Fällig: {inv.get('dueDate', '-')}
Summe netto: {total_net}€
Summe brutto: {total_gross}€"""


@mcp.tool()
def lexware_get_recent_invoices(limit: int = 10) -> str:
    """Listet die letzten Rechnungen.

    Args:
        limit: Maximale Anzahl (Standard: 10)
    """
    result = api_request(f"voucherlist?voucherType=invoice&size={limit}&sort=voucherDate,desc")

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = result.get("content", [])

    if not invoices:
        return "Keine Rechnungen gefunden"

    output = [f"Letzte Rechnungen ({len(invoices)}):"]
    for inv in invoices:
        inv_id = inv.get('id', '-')
        inv_number = inv.get('voucherNumber', '-')
        contact_name = inv.get('contactName', '-')
        status = inv.get('voucherStatus', '-')
        total_gross = inv.get('totalAmount', '0')
        voucher_date = inv.get('voucherDate', '-')

        output.append(f"- {inv_number}: {contact_name} | {total_gross}€ | {status} | {voucher_date} [ID: {inv_id}]")

    return "\n".join(output)


@mcp.tool()
def lexware_add_invoice_item(
    invoice_id: str,
    title: str,
    quantity: float,
    unit_price: float,
    unit: str = "Stunde",
    description: str = "",
    tax_rate: float = 19.0
) -> str:
    """Fügt eine Position zur Rechnung hinzu.

    WICHTIG: Nur bei Rechnungen im Entwurf-Status möglich!

    Args:
        invoice_id: Die Rechnungs-UUID
        title: Titel/Bezeichnung der Position
        quantity: Menge
        unit_price: Einzelpreis netto in Euro
        unit: Einheit (z.B. "Stunde", "Stück", "Pauschal")
        description: Optionale Beschreibung
        tax_rate: MwSt-Satz in Prozent (Standard: 19%)
    """
    # First get current invoice
    current = api_request(f"invoices/{invoice_id}")
    if "error" in current:
        return f"Fehler beim Laden: {current['error']}"

    if current.get("voucherStatus") != "draft":
        return f"Fehler: Rechnung ist nicht im Entwurf-Status (aktuell: {current.get('voucherStatus')})"

    # Add line item
    line_items = current.get("lineItems", [])
    new_item = {
        "type": "custom",
        "name": title,
        "quantity": quantity,
        "unitName": unit,
        "unitPrice": {
            "currency": "EUR",
            "netAmount": unit_price,
            "taxRatePercentage": tax_rate
        }
    }

    if description:
        new_item["description"] = description

    line_items.append(new_item)
    current["lineItems"] = line_items

    result = api_request(f"invoices/{invoice_id}", "PUT", current)

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    line_total = quantity * unit_price

    return f"""Position hinzugefügt!
- Titel: {title}
- Menge: {quantity} {unit}
- Einzelpreis: {unit_price}€
- Gesamt netto: {line_total}€"""


@mcp.tool()
def lexware_finalize_invoice(invoice_id: str) -> str:
    """Finalisiert eine Rechnung (Status: Entwurf → Offen).

    WICHTIG: Nach Finalisierung kann die Rechnung nicht mehr bearbeitet werden!

    Args:
        invoice_id: Die Rechnungs-UUID
    """
    # Get current invoice
    current = api_request(f"invoices/{invoice_id}")
    if "error" in current:
        return f"Fehler beim Laden: {current['error']}"

    if current.get("voucherStatus") != "draft":
        return f"Fehler: Rechnung ist nicht im Entwurf-Status (aktuell: {current.get('voucherStatus')})"

    # Update via PUT with finalize flag - need to recreate the invoice
    # Lexware requires POST to /invoices?finalize=true with full data

    # First, we need to mark it as finalized
    # Actually, Lexware doesn't support direct finalization via PUT
    # We need to check the actual API - for now return helpful message

    return f"""Hinweis: Rechnung #{invoice_id} kann über die Lexware Web-Oberfläche finalisiert werden.

Alternativ: Rechnung mit finalize=True direkt erstellen:
lexware_create_invoice(contact_id, finalize=True)

Um das PDF einer finalisierten Rechnung herunterzuladen:
lexware_download_invoice_pdf("{invoice_id}")"""


@mcp.tool()
def lexware_download_invoice_pdf(invoice_id: str, save_path: str = "", filename: str = "") -> str:
    """Lädt eine Rechnung als PDF herunter.

    Args:
        invoice_id: Die Rechnungs-UUID
        save_path: Zielordner (Standard: temp-Verzeichnis)
        filename: Dateiname ohne .pdf (Standard: Rechnungsnummer)
    """
    # Get invoice info for filename
    if not filename:
        inv = api_request(f"invoices/{invoice_id}")
        if "error" not in inv:
            inv_number = inv.get("voucherNumber", invoice_id)
            filename = f"Rechnung_{inv_number}".replace("/", "-").replace("\\", "-")
        else:
            filename = f"Rechnung_{invoice_id[:8]}"

    # Render document first
    render_result = api_request(f"invoices/{invoice_id}/document")
    if "error" in render_result:
        return f"Fehler beim Rendern: {render_result['error']}"

    # Download the file
    success, result = download_document(f"invoices/{invoice_id}/document", save_path, filename)

    if not success:
        return result

    pdf_path = Path(result)
    size = pdf_path.stat().st_size

    return f"""PDF heruntergeladen!
- Datei: {pdf_path}
- Größe: {size:,} Bytes"""


# =============================================================================
# Quotation/Offer Functions (Angebote)
# =============================================================================

@mcp.tool()
def lexware_create_quotation(
    contact_id: str,
    title: str = "",
    introduction: str = "",
    validity_days: int = 14
) -> str:
    """Erstellt ein neues Angebot für einen Kontakt.

    Args:
        contact_id: Die Kontakt-UUID
        title: Titel/Bezeichnung des Angebots
        introduction: Einleitungstext
        validity_days: Gültigkeitsdauer in Tagen (Standard: 14)
    """
    expiration_date = date.today() + timedelta(days=validity_days)

    quotation_data = {
        "voucherDate": _format_voucher_date(),
        "expirationDate": _format_voucher_date(expiration_date),
        "address": {
            "contactId": contact_id
        },
        "lineItems": [],
        "totalPrice": {
            "currency": "EUR"
        },
        "taxConditions": {
            "taxType": "net"
        }
    }

    if title:
        # Lexware API limits title to 25 characters
        quotation_data["title"] = title[:25]
    if introduction:
        quotation_data["introduction"] = introduction

    result = api_request("quotations", "POST", quotation_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    quotation_id = result.get("id", "-")

    return f"""Angebot erstellt!
- ID: {quotation_id}
- Gültig bis: {expiration}

Positionen hinzufügen mit: lexware_add_quotation_item("{quotation_id}", ...)"""


@mcp.tool()
def lexware_get_quotation(quotation_id: str) -> str:
    """Holt Details eines Angebots aus Lexware.

    Args:
        quotation_id: Die Angebots-UUID
    """
    result = api_request(f"quotations/{quotation_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    q = result

    # Status mapping
    status_map = {
        "draft": "Entwurf",
        "open": "Offen",
        "accepted": "Angenommen",
        "rejected": "Abgelehnt"
    }
    status = status_map.get(q.get("voucherStatus", ""), q.get("voucherStatus", "-"))

    # Total
    total = q.get("totalPrice", {})
    total_net = total.get("totalNetAmount", "0")
    total_gross = total.get("totalGrossAmount", "0")

    # Contact name
    address = q.get("address", {})
    contact_name = address.get("name", "-")

    return f"""Angebot #{quotation_id}:
Angebotsnummer: {q.get('voucherNumber', '-')}
Status: {status}
Kunde: {contact_name}
Datum: {q.get('voucherDate', '-')}
Gültig bis: {q.get('expirationDate', '-')}
Summe netto: {total_net}€
Summe brutto: {total_gross}€"""


@mcp.tool()
def lexware_get_recent_quotations(limit: int = 10) -> str:
    """Listet die letzten Angebote.

    Args:
        limit: Maximale Anzahl (Standard: 10)
    """
    result = api_request(f"voucherlist?voucherType=quotation&size={limit}&sort=voucherDate,desc")

    if "error" in result:
        return f"Fehler: {result['error']}"

    quotations = result.get("content", [])

    if not quotations:
        return "Keine Angebote gefunden"

    output = [f"Letzte Angebote ({len(quotations)}):"]
    for q in quotations:
        q_id = q.get('id', '-')
        q_number = q.get('voucherNumber', '-')
        contact_name = q.get('contactName', '-')
        status = q.get('voucherStatus', '-')
        total_gross = q.get('totalAmount', '0')

        output.append(f"- {q_number}: {contact_name} | {total_gross}€ | {status} [ID: {q_id}]")

    return "\n".join(output)


@mcp.tool()
def lexware_add_quotation_item(
    quotation_id: str,
    title: str,
    quantity: float,
    unit_price: float,
    unit: str = "Stück",
    description: str = "",
    tax_rate: float = 19.0
) -> str:
    """Fügt eine Position zum Angebot hinzu.

    Args:
        quotation_id: Die Angebots-UUID
        title: Titel/Bezeichnung der Position
        quantity: Menge
        unit_price: Einzelpreis netto in Euro
        unit: Einheit (z.B. "Stück", "Stunde", "Pauschal")
        description: Optionale Beschreibung
        tax_rate: MwSt-Satz in Prozent (Standard: 19%)
    """
    # First get current quotation
    current = api_request(f"quotations/{quotation_id}")
    if "error" in current:
        return f"Fehler beim Laden: {current['error']}"

    # Add line item
    line_items = current.get("lineItems", [])
    new_item = {
        "type": "custom",
        "name": title,
        "quantity": quantity,
        "unitName": unit,
        "unitPrice": {
            "currency": "EUR",
            "netAmount": unit_price,
            "taxRatePercentage": tax_rate
        }
    }

    if description:
        new_item["description"] = description

    line_items.append(new_item)
    current["lineItems"] = line_items

    result = api_request(f"quotations/{quotation_id}", "PUT", current)

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    line_total = quantity * unit_price

    return f"""Position hinzugefügt!
- Titel: {title}
- Menge: {quantity} {unit}
- Einzelpreis: {unit_price}€
- Gesamt netto: {line_total}€"""


@mcp.tool()
def lexware_download_quotation_pdf(quotation_id: str, save_path: str = "", filename: str = "") -> str:
    """Lädt ein Angebot als PDF herunter.

    Args:
        quotation_id: Die Angebots-UUID
        save_path: Zielordner (Standard: temp-Verzeichnis)
        filename: Dateiname ohne .pdf (Standard: Angebotsnummer)
    """
    # Get quotation info for filename
    if not filename:
        q = api_request(f"quotations/{quotation_id}")
        if "error" not in q:
            q_number = q.get("voucherNumber", quotation_id)
            filename = f"Angebot_{q_number}".replace("/", "-").replace("\\", "-")
        else:
            filename = f"Angebot_{quotation_id[:8]}"

    # Render and download
    render_result = api_request(f"quotations/{quotation_id}/document")
    if "error" in render_result:
        return f"Fehler beim Rendern: {render_result['error']}"

    success, result = download_document(f"quotations/{quotation_id}/document", save_path, filename)

    if not success:
        return result

    pdf_path = Path(result)
    size = pdf_path.stat().st_size

    return f"""PDF heruntergeladen!
- Datei: {pdf_path}
- Größe: {size:,} Bytes"""


# =============================================================================
# Payment Functions (Zahlungen)
# =============================================================================

@mcp.tool()
def lexware_get_open_invoices() -> str:
    """Holt alle offenen (unbezahlten) Rechnungen aus Lexware."""
    result = api_request("voucherlist?voucherType=invoice&voucherStatus=open&size=100")

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = result.get("content", [])

    if not invoices:
        return "Keine offenen Rechnungen gefunden."

    output = [f"Offene Rechnungen ({len(invoices)}):"]
    output.append("")

    total_open = 0
    for inv in invoices:
        inv_id = inv.get('id', '-')
        inv_number = inv.get('voucherNumber', '-')
        contact_name = inv.get('contactName', '-')
        total_gross = float(inv.get('totalAmount', 0))
        due_date = inv.get('dueDate', '-')
        overdue = "(ÜBERFÄLLIG)" if inv.get('isOverdue') else ""

        total_open += total_gross
        output.append(f"- {inv_number}: {contact_name} | {total_gross:.2f}€ | Fällig: {due_date} {overdue}")
        output.append(f"  ID: {inv_id}")

    output.append("")
    output.append(f"Gesamt offen: {total_open:.2f}€")

    return "\n".join(output)


@mcp.tool()
def lexware_get_payments(voucher_id: str) -> str:
    """Holt Zahlungsinformationen zu einem Beleg.

    Args:
        voucher_id: Die Beleg-UUID (Rechnung, Gutschrift, etc.)
    """
    result = api_request(f"payments/{voucher_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    payments = result.get("paymentItems", [])

    if not payments:
        return f"Keine Zahlungen für Beleg #{voucher_id} gefunden."

    output = [f"Zahlungen für Beleg #{voucher_id}:"]
    total_paid = 0

    for p in payments:
        amount = float(p.get("paymentAmount", {}).get("amount", 0))
        payment_date = p.get("paymentDate", "-")
        payment_type = p.get("paymentType", "-")
        total_paid += amount

        output.append(f"- {payment_date}: {amount:.2f}€ ({payment_type})")

    output.append("")
    output.append(f"Gesamt bezahlt: {total_paid:.2f}€")

    return "\n".join(output)


# =============================================================================
# Credit Note Functions (Gutschriften)
# =============================================================================

@mcp.tool()
def lexware_create_credit_note(
    contact_id: str,
    title: str = "",
    introduction: str = "",
    invoice_id: str = "",
    finalize: bool = False
) -> str:
    """Erstellt eine neue Gutschrift.

    Args:
        contact_id: Die Kontakt-UUID
        title: Titel/Bezeichnung der Gutschrift
        introduction: Einleitungstext
        invoice_id: Optional: Bezugnehmende Rechnung (für Gutschrift zu Rechnung)
        finalize: Wenn True, wird Gutschrift direkt finalisiert
    """
    credit_note_data = {
        "voucherDate": _format_voucher_date(),
        "address": {
            "contactId": contact_id
        },
        "lineItems": [],
        "totalPrice": {
            "currency": "EUR"
        },
        "taxConditions": {
            "taxType": "net"
        }
    }

    if title:
        # Lexware API limits title to 25 characters
        credit_note_data["title"] = title[:25]
    if introduction:
        credit_note_data["introduction"] = introduction

    endpoint = "credit-notes"
    params = []
    if invoice_id:
        params.append(f"precedingSalesVoucherId={invoice_id}")
    if finalize:
        params.append("finalize=true")

    if params:
        endpoint += "?" + "&".join(params)

    result = api_request(endpoint, "POST", credit_note_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    cn_id = result.get("id", "-")
    status = "Finalisiert" if finalize else "Entwurf"

    output = f"""Gutschrift erstellt!
- ID: {cn_id}
- Status: {status}"""

    if invoice_id:
        output += f"\n- Bezug zu Rechnung: {invoice_id}"

    return output


@mcp.tool()
def lexware_get_credit_note(credit_note_id: str) -> str:
    """Holt Details einer Gutschrift aus Lexware.

    Args:
        credit_note_id: Die Gutschrift-UUID
    """
    result = api_request(f"credit-notes/{credit_note_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    cn = result

    # Status mapping
    status_map = {
        "draft": "Entwurf",
        "open": "Offen",
        "paid": "Bezahlt",
        "voided": "Storniert"
    }
    status = status_map.get(cn.get("voucherStatus", ""), cn.get("voucherStatus", "-"))

    # Total
    total = cn.get("totalPrice", {})
    total_net = total.get("totalNetAmount", "0")
    total_gross = total.get("totalGrossAmount", "0")

    # Contact name
    address = cn.get("address", {})
    contact_name = address.get("name", "-")

    return f"""Gutschrift #{credit_note_id}:
Gutschriftnummer: {cn.get('voucherNumber', '-')}
Status: {status}
Kunde: {contact_name}
Datum: {cn.get('voucherDate', '-')}
Summe netto: {total_net}€
Summe brutto: {total_gross}€"""


if __name__ == "__main__":
    mcp.run()
