#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
sevDesk MCP Server
==================
MCP Server für sevDesk API-Zugriff.
Ermöglicht Claude das Suchen und Erstellen von Kontakten, Rechnungen und Belegen.
"""

import json
import os
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config

mcp = FastMCP("sevdesk")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "receipt_long",
    "color": "#ff6f00",  # sevDesk orange
    "beta": True
}

# Integration schema for WebUI Integrations Hub
INTEGRATION_SCHEMA = {
    "name": "sevDesk",
    "icon": "receipt_long",
    "color": "#ff6f00",
    "config_key": "sevdesk",
    "auth_type": "api_key",
    "beta": True,
    "fields": [
        {
            "key": "api_token",
            "label": "API Token",
            "type": "password",
            "required": True,
            "hint": "sevDesk API Token (Einstellungen > Benutzer > API-Token)",
        },
    ],
    "test_tool": "sevdesk_get_contacts",
    "setup": {
        "description": "Buchhaltung und Rechnungen",
        "requirement": "sevDesk API Token",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "sevDesk API-Token eintragen",
        ],
    },
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    # Contact management
    "sevdesk_create_contact",
    "sevdesk_update_contact",
    # Invoices
    "sevdesk_create_invoice",
    "sevdesk_add_invoice_position",
    "sevdesk_book_invoice",
    "sevdesk_send_invoice_via_email",
    "sevdesk_reset_invoice_to_draft",
    "sevdesk_reset_invoice_to_open",
}

# High-risk tools that return external/untrusted content
# These will be sanitized by the anonymization proxy
HIGH_RISK_TOOLS = set()  # No external content tools in sevDesk

# =============================================================================
# Caching für Performance-Optimierung
# =============================================================================

# Contact-Cache
_contact_cache = {}  # {contact_id: contact_data}
_contact_cache_time = 0
CONTACT_CACHE_TTL = 600  # 10 Minuten


def get_config():
    """Lädt sevDesk-Konfiguration."""
    api_token = os.environ.get("SEVDESK_API_TOKEN")

    if not api_token:
        config = load_config()
        sevdesk = config.get("sevdesk", {})
        api_token = sevdesk.get("api_token")

    return api_token


def is_configured() -> bool:
    """Prüft ob sevDesk API konfiguriert und aktiviert ist.

    Wird vom System verwendet um zu entscheiden, ob dieses MCP
    geladen werden soll. Benötigt einen gültigen API-Token.

    Config-Optionen in apis.json:
        enabled: false  - MCP deaktivieren (auch wenn Credentials gesetzt)
        api_token: "..."  - sevDesk API-Token (erforderlich)
    """
    config = load_config().get("sevdesk", {})

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    api_token = get_config()
    return bool(api_token)


def api_request(endpoint: str, method: str = "GET", data: dict = None, params: dict = None) -> dict:
    """Führt sevDesk API-Request aus."""
    api_token = get_config()

    if not api_token:
        return {"error": "sevDesk nicht konfiguriert"}

    # URL bauen
    base_url = "https://my.sevdesk.de/api/v1"
    url = f"{base_url}/{endpoint}"

    # Query-Parameter hinzufügen
    if params:
        query_string = urllib.parse.urlencode(params)
        url = f"{url}?{query_string}"

    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "DeskAgent/1.0"
    }

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get("error", {}).get("message", error_body)
        except:
            error_msg = error_body[:200]
        return {"error": f"HTTP {e.code}: {error_msg}"}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Contact/Customer Functions
# =============================================================================

@mcp.tool()
def sevdesk_search_contacts(query: str, limit: int = 10) -> str:
    """Sucht Kontakte in sevDesk nach Name oder Kundennummer.

    Args:
        query: Suchbegriff (Name oder Kundennummer)
        limit: Maximale Anzahl Ergebnisse (Standard: 10)
    """
    params = {
        "name": query,
        "limit": limit,
        "depth": 1
    }

    result = api_request("Contact", params=params)

    if "error" in result:
        return f"Fehler: {result['error']}"

    contacts = result.get("objects", [])

    if not contacts:
        # Auch nach Kundennummer suchen
        params = {
            "customerNumber": query,
            "limit": limit,
            "depth": 1
        }
        result = api_request("Contact", params=params)
        contacts = result.get("objects", [])

    if not contacts:
        return f"Keine Kontakte gefunden für: '{query}'"

    output = [f"Gefundene Kontakte ({len(contacts)}):"]
    for c in contacts:
        contact_id = c.get('id')
        name = c.get('name', '')
        surname = c.get('surename', '')
        familyname = c.get('familyname', '')

        # Name zusammensetzen (Firma ODER Person)
        if name:
            display_name = name
        else:
            display_name = f"{surname} {familyname}".strip()

        customer_number = c.get('customerNumber', '-')
        category = c.get('category', {})
        category_name = category.get('name') if isinstance(category, dict) else str(category)

        output.append(f"- ID {contact_id}: {display_name} (Nr. {customer_number}, {category_name})")

    return "\n".join(output)


@mcp.tool()
def sevdesk_get_contact(contact_id: int) -> str:
    """Holt Details eines Kontakts aus sevDesk.

    Args:
        contact_id: Die Kontakt-ID
    """
    result = api_request(f"Contact/{contact_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    c = result.get("objects", [{}])[0]

    # Name bestimmen
    if c.get('name'):
        display_name = c.get('name')
    else:
        display_name = f"{c.get('surename', '')} {c.get('familyname', '')}".strip()

    category = c.get('category', {})
    category_name = category.get('name') if isinstance(category, dict) else str(category)

    return f"""Kontakt #{c.get('id')}:
Name: {display_name}
Kundennummer: {c.get('customerNumber', '-')}
Kategorie: {category_name}
E-Mail: {c.get('email', '-')}
Telefon: {c.get('phone', '-')}
Beschreibung: {c.get('description', '-')}"""


@mcp.tool()
def sevdesk_create_contact(
    name: str = "",
    surname: str = "",
    familyname: str = "",
    customer_number: str = "",
    email: str = "",
    phone: str = "",
    description: str = "",
    category_id: int = 3
) -> str:
    """Erstellt einen neuen Kontakt in sevDesk.

    Args:
        name: Firmenname (für Organisationen)
        surname: Vorname (für Personen)
        familyname: Nachname (für Personen)
        customer_number: Kundennummer (optional, wird auto-generiert wenn leer)
        email: E-Mail-Adresse
        phone: Telefonnummer
        description: Beschreibung/Notizen
        category_id: Kategorie (3=Kunde, 14=Interessent, Standard: 3)
    """
    # Kontaktdaten zusammenstellen
    contact_data = {
        "category": {
            "id": category_id,
            "objectName": "Category"
        }
    }

    # Firma ODER Person
    if name:
        contact_data["name"] = name
    else:
        if not surname or not familyname:
            return "Fehler: Entweder 'name' (Firma) ODER 'surname' + 'familyname' (Person) erforderlich"
        contact_data["surename"] = surname
        contact_data["familyname"] = familyname

    if customer_number:
        contact_data["customerNumber"] = customer_number
    if email:
        contact_data["email"] = email
    if phone:
        contact_data["phone"] = phone
    if description:
        contact_data["description"] = description

    result = api_request("Contact", "POST", contact_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    contact = result.get("objects", [{}])[0]
    contact_id = contact.get("id")
    customer_num = contact.get("customerNumber", "-")

    return f"Kontakt erfolgreich erstellt! ID: {contact_id}, Kundennummer: {customer_num}"


@mcp.tool()
def sevdesk_update_contact(
    contact_id: int,
    name: str = "",
    surname: str = "",
    familyname: str = "",
    email: str = "",
    phone: str = "",
    description: str = ""
) -> str:
    """Aktualisiert einen bestehenden Kontakt in sevDesk.

    Args:
        contact_id: Die Kontakt-ID
        name: Neuer Firmenname (optional)
        surname: Neuer Vorname (optional)
        familyname: Neuer Nachname (optional)
        email: Neue E-Mail (optional)
        phone: Neue Telefonnummer (optional)
        description: Neue Beschreibung (optional)
    """
    contact_data = {}

    if name:
        contact_data["name"] = name
    if surname:
        contact_data["surename"] = surname
    if familyname:
        contact_data["familyname"] = familyname
    if email:
        contact_data["email"] = email
    if phone:
        contact_data["phone"] = phone
    if description:
        contact_data["description"] = description

    if not contact_data:
        return "Fehler: Keine Daten zum Aktualisieren angegeben"

    result = api_request(f"Contact/{contact_id}", "PUT", contact_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    c = result.get("objects", [{}])[0]

    # Name bestimmen
    if c.get('name'):
        display_name = c.get('name')
    else:
        display_name = f"{c.get('surename', '')} {c.get('familyname', '')}".strip()

    return f"""Kontakt #{contact_id} aktualisiert!
Name: {display_name}
E-Mail: {c.get('email', '-')}"""


@mcp.tool()
def sevdesk_get_next_customer_number() -> str:
    """Holt die nächste verfügbare Kundennummer."""
    result = api_request("Contact/Factory/getNextCustomerNumber")

    if "error" in result:
        return f"Fehler: {result['error']}"

    next_number = result.get("objects", "-")
    return f"Nächste Kundennummer: {next_number}"


# =============================================================================
# Invoice Functions
# =============================================================================

@mcp.tool()
def sevdesk_search_invoices(
    contact_id: int = None,
    invoice_number: str = "",
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 10
) -> str:
    """Sucht Rechnungen nach verschiedenen Kriterien.

    Args:
        contact_id: Kontakt-ID (optional)
        invoice_number: Rechnungsnummer (optional)
        status: Status-Filter: 100=Draft, 200=Open, 1000=Paid (optional)
        start_date: Start-Datum (YYYY-MM-DD)
        end_date: End-Datum (YYYY-MM-DD)
        limit: Maximale Anzahl Ergebnisse (Standard: 10)
    """
    params = {"limit": limit}

    if contact_id:
        params["contact[id]"] = contact_id
    if invoice_number:
        params["invoiceNumber"] = invoice_number
    if status:
        params["status"] = status
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date

    result = api_request("Invoice", params=params)

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = result.get("objects", [])

    if not invoices:
        return "Keine Rechnungen gefunden"

    # Status-Map
    status_map = {
        "100": "Entwurf",
        "200": "Offen",
        "1000": "Bezahlt"
    }

    output = [f"Gefundene Rechnungen ({len(invoices)}):"]
    for inv in invoices:
        inv_id = inv.get('id')
        inv_number = inv.get('invoiceNumber', '-')
        contact = inv.get('contact', {})
        contact_name = contact.get('name', '-') if isinstance(contact, dict) else '-'
        inv_status = inv.get('status', '-')
        status_text = status_map.get(str(inv_status), str(inv_status))
        total = inv.get('sumGross', '0')

        output.append(f"- #{inv_id}: {inv_number} | {contact_name} | {total}€ ({status_text})")

    return "\n".join(output)


@mcp.tool()
def sevdesk_get_recent_invoices(limit: int = 5) -> str:
    """Listet die letzten Rechnungen.

    Args:
        limit: Maximale Anzahl (Standard: 5)
    """
    params = {
        "limit": limit,
        "orderBy": "id",
        "order": "DESC"
    }

    result = api_request("Invoice", params=params)

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = result.get("objects", [])

    if not invoices:
        return "Keine Rechnungen gefunden"

    status_map = {
        "100": "Entwurf",
        "200": "Offen",
        "1000": "Bezahlt"
    }

    output = [f"Letzte Rechnungen ({len(invoices)}):"]
    for inv in invoices:
        inv_id = inv.get('id')
        inv_number = inv.get('invoiceNumber', '-')
        contact = inv.get('contact', {})
        contact_name = contact.get('name', '-') if isinstance(contact, dict) else '-'
        inv_status = inv.get('status', '-')
        status_text = status_map.get(str(inv_status), str(inv_status))
        total = inv.get('sumGross', '0')

        output.append(f"- #{inv_id}: {inv_number} | {contact_name} | {total}€ ({status_text})")

    return "\n".join(output)


@mcp.tool()
def sevdesk_get_invoice(invoice_id: int) -> str:
    """Holt Details einer Rechnung aus sevDesk.

    Args:
        invoice_id: Die Rechnungs-ID
    """
    result = api_request(f"Invoice/{invoice_id}")

    if "error" in result:
        return f"Fehler: {result['error']}"

    inv = result.get("objects", [{}])[0]

    status_map = {
        "100": "Entwurf",
        "200": "Offen",
        "1000": "Bezahlt"
    }

    contact = inv.get('contact', {})
    contact_name = contact.get('name', '-') if isinstance(contact, dict) else '-'
    inv_status = inv.get('status', '-')
    status_text = status_map.get(str(inv_status), str(inv_status))

    return f"""Rechnung #{invoice_id}:
Rechnungsnummer: {inv.get('invoiceNumber', '-')}
Status: {status_text}
Kunde: {contact_name}
Datum: {inv.get('invoiceDate', '-')}
Fällig: {inv.get('deliveryDate', '-')}
Summe netto: {inv.get('sumNet', '0')}€
Summe brutto: {inv.get('sumGross', '0')}€
Währung: {inv.get('currency', '-')}"""


@mcp.tool()
def sevdesk_create_invoice(
    contact_id: int,
    invoice_date: str = "",
    delivery_date: str = "",
    status: int = 100,
    currency: str = "EUR"
) -> str:
    """Erstellt eine neue Rechnung für einen Kontakt.

    Args:
        contact_id: Die Kontakt-ID
        invoice_date: Rechnungsdatum (YYYY-MM-DD, Standard: heute)
        delivery_date: Lieferdatum (YYYY-MM-DD, optional)
        status: Status (100=Entwurf, 200=Offen, Standard: 100)
        currency: Währung (Standard: EUR)
    """
    # Standard-Datum
    if not invoice_date:
        invoice_date = date.today().isoformat()

    invoice_data = {
        "invoiceDate": invoice_date,
        "status": status,
        "currency": currency,
        "contact": {
            "id": contact_id,
            "objectName": "Contact"
        },
        "contactPerson": {
            "id": 0,
            "objectName": "SevUser"
        },
        "invoiceType": "RE",
        "taxType": "default",
        "taxSet": None,
        "invoicePosSave": [],
        "invoicePosDelete": None
    }

    if delivery_date:
        invoice_data["deliveryDate"] = delivery_date

    result = api_request("Invoice/Factory/saveInvoice", "POST", invoice_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoice = result.get("objects", {}).get("invoice", {})
    invoice_id = invoice.get("id")
    invoice_number = invoice.get("invoiceNumber", "-")

    return f"""Rechnung erstellt!
- ID: {invoice_id}
- Rechnungsnummer: {invoice_number}
- Status: Entwurf"""


@mcp.tool()
def sevdesk_add_invoice_position(
    invoice_id: int,
    name: str,
    quantity: float,
    price: float,
    tax_rate: float = 19.0,
    unity_id: int = 1,
    unity_name: str = "Stück"
) -> str:
    """Fügt eine Position zur Rechnung hinzu (nur im Entwurfs-Status möglich).

    Args:
        invoice_id: Die Rechnungs-ID
        name: Bezeichnung der Position
        quantity: Anzahl/Menge
        price: Einzelpreis in Euro
        tax_rate: Steuersatz (0.0, 7.0, 19.0, Standard: 19.0)
        unity_id: Einheiten-ID (1=Stück, 2=Stunde, Standard: 1)
        unity_name: Einheiten-Name (Standard: Stück)
    """
    # Hole aktuelle Rechnung
    invoice_result = api_request(f"Invoice/{invoice_id}")

    if "error" in invoice_result:
        return f"Fehler: {invoice_result['error']}"

    invoice = invoice_result.get("objects", [{}])[0]

    # Prüfe Status
    if invoice.get("status") != 100:
        return "Fehler: Positionen können nur zu Rechnungen im Entwurfs-Status (100) hinzugefügt werden"

    # Position erstellen
    position_data = {
        "name": name,
        "quantity": quantity,
        "price": price,
        "taxRate": tax_rate,
        "unity": {
            "id": unity_id,
            "objectName": "Unity",
            "translationCode": unity_name
        }
    }

    # Update mit neuer Position
    update_data = {
        "invoicePosSave": [position_data],
        "invoicePosDelete": None
    }

    result = api_request(f"Invoice/{invoice_id}", "PUT", update_data)

    if "error" in result:
        return f"Fehler beim Hinzufügen: {result['error']}"

    line_total = quantity * price
    tax_amount = line_total * (tax_rate / 100)

    return f"""Position hinzugefügt!
- Name: {name}
- Menge: {quantity} {unity_name}
- Einzelpreis: {price}€
- MwSt: {tax_rate}%
- Netto: {line_total}€
- MwSt-Betrag: {tax_amount:.2f}€
- Brutto: {line_total + tax_amount:.2f}€"""


@mcp.tool()
def sevdesk_get_open_invoices() -> str:
    """Holt alle offenen Rechnungen aus sevDesk (Status 200)."""
    params = {
        "status": 200,
        "limit": 100
    }

    result = api_request("Invoice", params=params)

    if "error" in result:
        return f"Fehler: {result['error']}"

    invoices = result.get("objects", [])

    if not invoices:
        return "Keine offenen Rechnungen gefunden."

    output = [f"Offene Rechnungen ({len(invoices)}):"]
    output.append("")

    total_open = 0
    for inv in invoices:
        inv_id = inv.get("id")
        inv_number = inv.get("invoiceNumber", "-")
        contact = inv.get('contact', {})
        contact_name = contact.get('name', '-') if isinstance(contact, dict) else '-'
        total_gross = float(inv.get("sumGross", 0))
        due_date = inv.get("deliveryDate", "-")

        total_open += total_gross
        output.append(f"- #{inv_id}: {inv_number} | {contact_name} | {total_gross:.2f}€ brutto | Fällig: {due_date}")

    output.append("")
    output.append(f"Gesamt offen: {total_open:.2f}€ brutto")

    return "\n".join(output)


@mcp.tool()
def sevdesk_book_invoice(invoice_id: int, amount: float, date_str: str = "", type_str: str = "N") -> str:
    """Bucht eine Rechnung als (teilweise) bezahlt.

    Args:
        invoice_id: Die Rechnungs-ID
        amount: Gezahlter Betrag
        date_str: Zahlungsdatum (YYYY-MM-DD, Standard: heute)
        type_str: Zahlungsart (N=Bar, B=Bank, Standard: N)
    """
    if not date_str:
        date_str = date.today().isoformat()

    # Hole Rechnung
    invoice_result = api_request(f"Invoice/{invoice_id}")

    if "error" in invoice_result:
        return f"Fehler: {invoice_result['error']}"

    invoice = invoice_result.get("objects", [{}])[0]
    inv_number = invoice.get("invoiceNumber", "-")
    total_gross = float(invoice.get("sumGross", 0))

    # Buchung erstellen
    booking_data = {
        "amount": amount,
        "date": date_str,
        "type": type_str,
        "checkAccount": {
            "id": 1,
            "objectName": "CheckAccount"
        }
    }

    result = api_request(f"Invoice/{invoice_id}/bookAmount", "POST", booking_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    remaining = total_gross - amount
    status = "Bezahlt" if remaining <= 0 else f"Teilzahlung ({remaining:.2f}€ offen)"

    return f"""Rechnung gebucht!
- Rechnungsnummer: {inv_number}
- Gezahlter Betrag: {amount:.2f}€
- Gesamt: {total_gross:.2f}€
- Status: {status}"""


@mcp.tool()
def sevdesk_send_invoice_via_email(
    invoice_id: int,
    to_email: str,
    subject: str = "",
    body: str = ""
) -> str:
    """Versendet eine Rechnung per E-Mail.

    Args:
        invoice_id: Die Rechnungs-ID
        to_email: Empfänger E-Mail-Adresse
        subject: Betreff (optional)
        body: E-Mail-Text (optional)
    """
    email_data = {
        "toEmail": to_email
    }

    if subject:
        email_data["subject"] = subject
    if body:
        email_data["body"] = body

    result = api_request(f"Invoice/{invoice_id}/sendViaEmail", "POST", email_data)

    if "error" in result:
        return f"Fehler: {result['error']}"

    return f"Rechnung #{invoice_id} erfolgreich per E-Mail an {to_email} versendet."


@mcp.tool()
def sevdesk_reset_invoice_to_draft(invoice_id: int) -> str:
    """Setzt eine Rechnung zurück in den Entwurfs-Status.

    Args:
        invoice_id: Die Rechnungs-ID
    """
    result = api_request(f"Invoice/{invoice_id}/resetToDraft", "POST")

    if "error" in result:
        return f"Fehler: {result['error']}"

    return f"Rechnung #{invoice_id} wurde zurück in den Entwurfs-Status gesetzt."


@mcp.tool()
def sevdesk_reset_invoice_to_open(invoice_id: int) -> str:
    """Setzt eine Rechnung zurück in den Offen-Status.

    Args:
        invoice_id: Die Rechnungs-ID
    """
    result = api_request(f"Invoice/{invoice_id}/resetToOpen", "POST")

    if "error" in result:
        return f"Fehler: {result['error']}"

    return f"Rechnung #{invoice_id} wurde zurück in den Offen-Status gesetzt."


if __name__ == "__main__":
    mcp.run()
