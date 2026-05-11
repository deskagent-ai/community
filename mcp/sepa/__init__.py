#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
SEPA MCP Server
===============
MCP Server für SEPA XML Dateien (pain.001.001.03 - Credit Transfer).
Ermöglicht das Erstellen von SEPA-Überweisungsdateien für Bank-Upload.
"""

# BULLETPROOF: Add embedded Python Lib path for Nuitka builds
import sys as _sys
import os as _os
_mcp_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_deskagent_dir = _os.path.dirname(_mcp_dir)
_python_lib = _os.path.join(_deskagent_dir, 'python', 'Lib')
if _os.path.isdir(_python_lib) and _python_lib not in _sys.path:
    _sys.path.insert(1, _python_lib)
# ALWAYS clear cached xml module (may be cached from python312.zip)
for _mod in list(_sys.modules.keys()):
    if _mod == 'xml' or _mod.startswith('xml.'):
        del _sys.modules[_mod]
del _mcp_dir, _deskagent_dir, _python_lib

import json
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

from mcp.server.fastmcp import FastMCP

# DeskAgent MCP API (provides config, paths, logging via HTTP)
from _mcp_api import get_exports_dir, get_config_dir, mcp_log

mcp = FastMCP("sepa")

# Tool metadata for dynamic icon/color in WebUI
TOOL_METADATA = {
    "icon": "account_balance",
    "color": "#3f51b5"
}

# Integration schema for Settings UI
# Note: SEPA uses banking.json for multi-account config, not apis.json
INTEGRATION_SCHEMA = {
    "name": "SEPA Banking",
    "icon": "account_balance",
    "color": "#3f51b5",
    "config_key": "banking",
    "config_file": "banking.json",
    "auth_type": "custom",
    "fields": [
        {
            "key": "name",
            "label": "Kontoinhaber",
            "type": "text",
            "required": True,
            "hint": "Name des Kontoinhabers (wie bei der Bank)",
        },
        {
            "key": "iban",
            "label": "IBAN",
            "type": "text",
            "required": True,
            "hint": "IBAN des Bankkontos (z.B. DE89370400440532013000)",
        },
        {
            "key": "bic",
            "label": "BIC",
            "type": "text",
            "required": False,
            "hint": "BIC/SWIFT-Code (optional seit SEPA 2.0)",
        },
    ],
    "test_tool": "sepa_get_accounts",
    "setup": {
        "description": "SEPA XML Dateien erstellen",
        "requirement": "Bankkonten nicht konfiguriert",
        "setup_steps": [
            "In <code>config/banking.json</code> Bankkonten eintragen",
            "Format: Name, IBAN, BIC, Currency (EUR)",
        ],
    },
}

# Read-only tools that only retrieve data (for tool_mode: "read_only")
READ_ONLY_TOOLS = {
    "sepa_validate_iban",
    "sepa_get_accounts",
    "sepa_lookup_recipient_iban",
    "sepa_get_details",
    "sepa_list_files",
    "sepa_read_camt052_zip",
    "sepa_read_camt052_xml",
    "sepa_get_camt_credits",
}

# Destructive tools that modify, create, or delete data
# These will be simulated in dry-run mode instead of executed
DESTRUCTIVE_TOOLS = {
    "sepa_create_transfer",
    "sepa_create_batch",
    "sepa_append",
    "sepa_clear_files",
}

# =============================================================================
# Configuration
# =============================================================================

def get_accounts() -> dict:
    """Lädt alle SEPA-Konten aus banking.json."""
    banking_file = get_config_dir() / "banking.json"
    if banking_file.exists():
        try:
            with open(banking_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            mcp_log(f"[SEPA] Error loading banking.json: {e}")
    return {}


def get_config(account: str = None) -> dict:
    """
    Lädt SEPA-Konfiguration für ein bestimmtes Konto aus banking.json.

    Args:
        account: Kontoname (z.B. "company", "private").
                 None = Default-Konto verwenden.
    """
    sepa_config = get_accounts()

    # Bestimme welches Konto verwendet werden soll
    if account is None:
        account = sepa_config.get("default", "")

    account_config = sepa_config.get(account, {})

    if not account_config:
        return {
            "error": f"Konto '{account}' nicht gefunden. Verfügbar: {list_accounts()}"
        }

    return {
        "account": account,
        "initiator_name": account_config.get("name", ""),
        "initiator_iban": account_config.get("iban", ""),
        "initiator_bic": account_config.get("bic", ""),
        "default_currency": account_config.get("currency", "EUR"),
        "charge_bearer": account_config.get("charge_bearer", "SLEV"),
    }


def list_accounts() -> list:
    """Gibt eine Liste der verfügbaren Konten zurück."""
    sepa_config = get_accounts()
    return [k for k in sepa_config.keys() if k != "default"]


def is_configured() -> bool:
    """Prüft ob SEPA konfiguriert und aktiviert ist."""
    # SEPA uses banking.json, check if at least one account exists
    accounts = get_accounts()

    # Check enabled flag in first account or global
    for key, value in accounts.items():
        if key == "default":
            continue
        if isinstance(value, dict):
            if value.get("enabled") is False:
                continue
            # Found at least one enabled account with IBAN
            if value.get("iban"):
                return True

    return False

# =============================================================================
# IBAN Validation
# =============================================================================

IBAN_LENGTHS = {
    'DE': 22, 'AT': 20, 'CH': 21, 'FR': 27, 'IT': 27, 'ES': 24,
    'NL': 18, 'BE': 16, 'LU': 20, 'PT': 25, 'IE': 22, 'FI': 18,
    'DK': 18, 'SE': 24, 'NO': 15, 'PL': 28, 'CZ': 24, 'SK': 24,
    'HU': 28, 'GB': 22, 'GR': 27, 'SI': 19, 'HR': 21, 'RO': 24,
    'BG': 22, 'EE': 20, 'LV': 21, 'LT': 20, 'MT': 31, 'CY': 28,
}

def validate_iban(iban: str) -> tuple[bool, str]:
    """
    Validiert eine IBAN nach ISO 13616.
    Returns: (is_valid, error_message)
    """
    # Remove spaces and convert to uppercase
    iban = iban.replace(" ", "").upper()

    # Check format
    if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]+$', iban):
        return False, "Ungültiges IBAN-Format"

    country = iban[:2]

    # Check country and length
    if country not in IBAN_LENGTHS:
        return False, f"Unbekanntes Land: {country}"

    expected_length = IBAN_LENGTHS[country]
    if len(iban) != expected_length:
        return False, f"Falsche Länge für {country}: erwartet {expected_length}, erhalten {len(iban)}"

    # Checksum validation (mod 97)
    # Move first 4 chars to end, convert letters to numbers
    rearranged = iban[4:] + iban[:4]
    numeric = ""
    for char in rearranged:
        if char.isalpha():
            numeric += str(ord(char) - 55)  # A=10, B=11, etc.
        else:
            numeric += char

    if int(numeric) % 97 != 1:
        return False, "Ungültige Prüfsumme"

    return True, "IBAN ist gültig"


def format_iban(iban: str) -> str:
    """Formatiert IBAN ohne Leerzeichen."""
    return iban.replace(" ", "").upper()

# =============================================================================
# SEPA XML Generation (pain.001.001.03)
# =============================================================================

NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"

def create_element(parent, tag, text=None, **attrs):
    """Erstellt ein XML-Element mit optionalem Text und Attributen."""
    elem = ET.SubElement(parent, tag)
    if text is not None:
        elem.text = str(text)
    for key, value in attrs.items():
        elem.set(key, value)
    return elem

def generate_message_id():
    """Generiert eine eindeutige Message-ID."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:8].upper()
    return f"SEPA-{timestamp}-{unique}"

def generate_payment_id():
    """Generiert eine eindeutige Payment-ID."""
    return f"PMT-{uuid.uuid4().hex[:12].upper()}"

def generate_sepa_xml(payments: list, config: dict, execution_date: str = None) -> str:
    """
    Generiert eine SEPA XML Datei (pain.001.001.03).

    Args:
        payments: Liste von Payment-Dicts mit:
            - creditor_name: Name des Empfängers
            - creditor_iban: IBAN des Empfängers
            - creditor_bic: BIC des Empfängers (optional)
            - amount: Betrag in EUR
            - reference: Verwendungszweck
        config: Konfiguration mit Initiator-Daten
        execution_date: Ausführungsdatum (YYYY-MM-DD), None für sofort

    Returns:
        XML-String
    """
    if not payments:
        raise ValueError("Keine Zahlungen angegeben")

    # Calculate totals
    total_amount = sum(float(p.get("amount", 0)) for p in payments)
    nb_of_txs = len(payments)

    # Execution date
    if execution_date:
        exec_date = execution_date
    else:
        exec_date = datetime.now().strftime("%Y-%m-%d")

    # Create root
    root = ET.Element("Document", xmlns=NAMESPACE)
    cstmr_cdt_trf_initn = ET.SubElement(root, "CstmrCdtTrfInitn")

    # --- Group Header ---
    grp_hdr = create_element(cstmr_cdt_trf_initn, "GrpHdr")
    create_element(grp_hdr, "MsgId", generate_message_id())
    create_element(grp_hdr, "CreDtTm", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    create_element(grp_hdr, "NbOfTxs", nb_of_txs)
    create_element(grp_hdr, "CtrlSum", f"{total_amount:.2f}")

    # Initiating Party
    initg_pty = create_element(grp_hdr, "InitgPty")
    create_element(initg_pty, "Nm", config.get("initiator_name", "Unknown"))

    # --- Payment Information ---
    pmt_inf = create_element(cstmr_cdt_trf_initn, "PmtInf")
    create_element(pmt_inf, "PmtInfId", generate_payment_id())
    create_element(pmt_inf, "PmtMtd", "TRF")  # Transfer
    create_element(pmt_inf, "NbOfTxs", nb_of_txs)
    create_element(pmt_inf, "CtrlSum", f"{total_amount:.2f}")

    # Payment Type Information
    pmt_tp_inf = create_element(pmt_inf, "PmtTpInf")
    svc_lvl = create_element(pmt_tp_inf, "SvcLvl")
    create_element(svc_lvl, "Cd", "SEPA")

    # Requested Execution Date
    create_element(pmt_inf, "ReqdExctnDt", exec_date)

    # Debtor (Auftraggeber)
    dbtr = create_element(pmt_inf, "Dbtr")
    create_element(dbtr, "Nm", config.get("initiator_name", "Unknown"))

    # Debtor Account
    dbtr_acct = create_element(pmt_inf, "DbtrAcct")
    dbtr_id = create_element(dbtr_acct, "Id")
    create_element(dbtr_id, "IBAN", format_iban(config.get("initiator_iban", "")))

    # Debtor Agent (Bank)
    dbtr_agt = create_element(pmt_inf, "DbtrAgt")
    fin_instn_id = create_element(dbtr_agt, "FinInstnId")
    if config.get("initiator_bic"):
        create_element(fin_instn_id, "BIC", config.get("initiator_bic"))
    else:
        create_element(fin_instn_id, "Othr")  # BIC optional seit SEPA 2.0

    # Charge Bearer
    create_element(pmt_inf, "ChrgBr", config.get("charge_bearer", "SLEV"))

    # --- Credit Transfer Transactions ---
    for idx, payment in enumerate(payments, 1):
        cdt_trf_tx_inf = create_element(pmt_inf, "CdtTrfTxInf")

        # Payment ID
        pmt_id = create_element(cdt_trf_tx_inf, "PmtId")
        create_element(pmt_id, "EndToEndId", payment.get("end_to_end_id", f"E2E-{idx:04d}"))

        # Amount
        amt = create_element(cdt_trf_tx_inf, "Amt")
        create_element(amt, "InstdAmt", f"{float(payment['amount']):.2f}", Ccy=config.get("default_currency", "EUR"))

        # Creditor Agent (optional)
        if payment.get("creditor_bic"):
            cdtr_agt = create_element(cdt_trf_tx_inf, "CdtrAgt")
            fin_instn_id = create_element(cdtr_agt, "FinInstnId")
            create_element(fin_instn_id, "BIC", payment["creditor_bic"])

        # Creditor (Empfänger)
        cdtr = create_element(cdt_trf_tx_inf, "Cdtr")
        create_element(cdtr, "Nm", payment.get("creditor_name", "Unknown"))

        # Creditor Account
        cdtr_acct = create_element(cdt_trf_tx_inf, "CdtrAcct")
        cdtr_id = create_element(cdtr_acct, "Id")
        create_element(cdtr_id, "IBAN", format_iban(payment.get("creditor_iban", "")))

        # Remittance Information (Verwendungszweck)
        if payment.get("reference"):
            rmt_inf = create_element(cdt_trf_tx_inf, "RmtInf")
            # Unstructured reference (max 140 chars)
            reference = payment["reference"][:140]
            create_element(rmt_inf, "Ustrd", reference)

    # Pretty print XML
    xml_string = ET.tostring(root, encoding='unicode')
    dom = minidom.parseString(xml_string)
    return dom.toprettyxml(indent="  ", encoding=None)

# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
def sepa_validate_iban(iban: str) -> str:
    """
    Validiert eine IBAN-Nummer.

    Args:
        iban: Die zu prüfende IBAN (mit oder ohne Leerzeichen)

    Returns:
        Validierungsergebnis
    """
    is_valid, message = validate_iban(iban)
    formatted = format_iban(iban)
    country = formatted[:2] if len(formatted) >= 2 else "??"

    return json.dumps({
        "valid": is_valid,
        "message": message,
        "iban_formatted": formatted,
        "country": country
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def sepa_create_transfer(
    creditor_name: str,
    creditor_iban: str,
    amount: float,
    reference: str,
    creditor_bic: str = None,
    execution_date: str = None,
    account: str = None,
    filename: str = None
) -> str:
    """
    Erstellt eine einzelne SEPA-Überweisung als XML-Datei.

    Args:
        creditor_name: Name des Empfängers
        creditor_iban: IBAN des Empfängers
        amount: Betrag in EUR
        reference: Verwendungszweck (max. 140 Zeichen)
        creditor_bic: BIC des Empfängers (optional seit SEPA 2.0)
        execution_date: Ausführungsdatum YYYY-MM-DD (optional, Standard: heute)
        account: Absender-Konto (z.B. "company" oder "private", Standard: default aus config)
        filename: Dateiname ohne Erweiterung (optional, z.B. "sepa-company-20251231")

    Returns:
        Pfad zur erstellten XML-Datei
    """
    # Validate IBAN
    is_valid, message = validate_iban(creditor_iban)
    if not is_valid:
        return json.dumps({"error": f"Ungültige Empfänger-IBAN: {message}"}, ensure_ascii=False)

    config = get_config(account)

    # Check for config error
    if "error" in config:
        return json.dumps(config, ensure_ascii=False)

    # Validate initiator config
    if not config.get("initiator_iban"):
        return json.dumps({
            "error": f"Keine IBAN für Konto '{config.get('account')}' konfiguriert. Bitte in banking.json setzen."
        }, ensure_ascii=False)

    is_valid, message = validate_iban(config["initiator_iban"])
    if not is_valid:
        return json.dumps({"error": f"Ungültige Absender-IBAN: {message}"}, ensure_ascii=False)

    # Create payment
    payment = {
        "creditor_name": creditor_name,
        "creditor_iban": creditor_iban,
        "creditor_bic": creditor_bic,
        "amount": amount,
        "reference": reference,
        "end_to_end_id": f"TRF-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    }

    try:
        xml_content = generate_sepa_xml([payment], config, execution_date)

        # Save to temp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if filename:
            # Sanitize filename
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "-_")
            file = f"{safe_filename}.xml"
        else:
            file = f"sepa_transfer_{timestamp}.xml"
        filepath = get_exports_dir() / file

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(xml_content)

        return json.dumps({
            "success": True,
            "file": str(filepath),
            "filename": filename,
            "account": config.get("account"),
            "initiator": config.get("initiator_name"),
            "payments": 1,
            "total_amount": f"{amount:.2f} EUR",
            "creditor": creditor_name,
            "execution_date": execution_date or datetime.now().strftime("%Y-%m-%d")
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sepa_create_batch(
    payments: str,
    execution_date: str = None,
    filename: str = None,
    account: str = None
) -> str:
    """
    Erstellt eine SEPA-Batch-Datei mit mehreren Überweisungen.

    Args:
        payments: JSON-Array von Zahlungen, jede mit:
            - creditor_name: Name des Empfängers
            - creditor_iban: IBAN des Empfängers
            - amount: Betrag in EUR
            - reference: Verwendungszweck
            - creditor_bic: (optional) BIC des Empfängers
        execution_date: Ausführungsdatum YYYY-MM-DD (optional)
        filename: Dateiname ohne Erweiterung (optional)
        account: Absender-Konto (z.B. "company" oder "private", Standard: default aus config)

    Returns:
        Pfad zur erstellten XML-Datei

    Example:
        payments = '[{"creditor_name": "Max Mustermann", "creditor_iban": "DE89370400440532013000", "amount": 100.50, "reference": "Rechnung 123"}]'
    """
    try:
        payment_list = json.loads(payments)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Ungültiges JSON: {e}"}, ensure_ascii=False)

    if not payment_list:
        return json.dumps({"error": "Keine Zahlungen angegeben"}, ensure_ascii=False)

    config = get_config(account)

    # Check for config error
    if "error" in config:
        return json.dumps(config, ensure_ascii=False)

    # Validate initiator config
    if not config.get("initiator_iban"):
        return json.dumps({
            "error": f"Keine IBAN für Konto '{config.get('account')}' konfiguriert. Bitte in banking.json setzen."
        }, ensure_ascii=False)

    # Validate all IBANs
    errors = []
    for idx, payment in enumerate(payment_list, 1):
        if "creditor_iban" not in payment:
            errors.append(f"Zahlung {idx}: Keine IBAN angegeben")
            continue
        is_valid, message = validate_iban(payment["creditor_iban"])
        if not is_valid:
            errors.append(f"Zahlung {idx} ({payment.get('creditor_name', 'Unbekannt')}): {message}")

    if errors:
        return json.dumps({"error": "IBAN-Validierungsfehler", "details": errors}, ensure_ascii=False, indent=2)

    # Add end-to-end IDs
    for idx, payment in enumerate(payment_list, 1):
        if "end_to_end_id" not in payment:
            payment["end_to_end_id"] = f"BATCH-{datetime.now().strftime('%Y%m%d')}-{idx:04d}"

    try:
        xml_content = generate_sepa_xml(payment_list, config, execution_date)

        # Save to temp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if filename:
            safe_filename = re.sub(r'[^\w\-]', '_', filename)
            file = f"{safe_filename}.xml"
        else:
            file = f"sepa_batch_{timestamp}.xml"

        filepath = get_exports_dir() / file

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(xml_content)

        total_amount = sum(float(p.get("amount", 0)) for p in payment_list)

        return json.dumps({
            "success": True,
            "file": str(filepath),
            "filename": file,
            "account": config.get("account"),
            "initiator": config.get("initiator_name"),
            "payments": len(payment_list),
            "total_amount": f"{total_amount:.2f} EUR",
            "execution_date": execution_date or datetime.now().strftime("%Y-%m-%d"),
            "creditors": [p.get("creditor_name", "Unknown") for p in payment_list]
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sepa_get_accounts() -> str:
    """
    Zeigt alle verfügbaren SEPA-Konten an.

    Returns:
        Liste der Konten mit maskierten IBANs
    """
    sepa_config = get_accounts()
    default_account = sepa_config.get("default", "")
    accounts = []

    for name, data in sepa_config.items():
        if name == "default":
            continue

        iban = data.get("iban", "")
        if len(iban) > 8:
            masked_iban = iban[:4] + "****" + iban[-4:]
        else:
            masked_iban = "Nicht konfiguriert"

        accounts.append({
            "account": name,
            "name": data.get("name", "Unbekannt"),
            "iban": masked_iban,
            "bic": data.get("bic", ""),
            "is_default": name == default_account
        })

    return json.dumps({
        "accounts": accounts,
        "default": default_account,
        "config_hint": "Konfiguration in config/banking.json anpassen"
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def sepa_lookup_recipient_iban(name: str) -> str:
    """
    Sucht die IBAN eines Empfängers in banking.json.

    Matched gegen das 'name' Feld aller Konten:
    - Exakter Match (case-insensitive)
    - Teilmatch auf Vorname (z.B. "Max" findet "Max Mustermann")
    - Teilmatch auf Nachname (z.B. "Mustermann" findet "Max Mustermann")

    Args:
        name: Name des Empfaengers (z.B. "Max", "Max Mustermann", "Mustermann")

    Returns:
        IBAN und Kontodaten wenn gefunden, sonst Fehlermeldung
    """
    sepa_config = get_accounts()
    search_name = name.strip().lower()

    matches = []

    for account_key, data in sepa_config.items():
        if account_key == "default":
            continue

        account_name = data.get("name", "").lower()
        iban = data.get("iban", "")

        if not account_name or not iban:
            continue

        # Exact match
        if search_name == account_name:
            matches.append({
                "account": account_key,
                "name": data.get("name"),
                "iban": iban,
                "bic": data.get("bic", ""),
                "match_type": "exact"
            })
            continue

        # Partial match (Vorname oder Nachname)
        name_parts = account_name.split()
        if any(search_name == part for part in name_parts):
            matches.append({
                "account": account_key,
                "name": data.get("name"),
                "iban": iban,
                "bic": data.get("bic", ""),
                "match_type": "partial"
            })
            continue

        # Contains match
        if search_name in account_name or account_name in search_name:
            matches.append({
                "account": account_key,
                "name": data.get("name"),
                "iban": iban,
                "bic": data.get("bic", ""),
                "match_type": "contains"
            })

    if not matches:
        return json.dumps({
            "found": False,
            "error": f"Kein Konto gefunden für '{name}'",
            "hint": "IBAN muss manuell angegeben werden"
        }, ensure_ascii=False)

    if len(matches) == 1:
        match = matches[0]
        return json.dumps({
            "found": True,
            "account": match["account"],
            "name": match["name"],
            "iban": match["iban"],
            "bic": match["bic"]
        }, ensure_ascii=False)

    # Multiple matches - return all
    return json.dumps({
        "found": True,
        "multiple": True,
        "matches": matches,
        "hint": "Mehrere Treffer - bitte genauer spezifizieren"
    }, ensure_ascii=False)


@mcp.tool()
def sepa_clear_files() -> str:
    """
    Löscht alle SEPA-XML-Dateien im sepa/ Ordner.

    Verwenden vor dem Erstellen einer neuen SEPA-Session.

    Returns:
        Anzahl der gelöschten Dateien
    """
    sepa_dir = get_exports_dir()
    deleted = []

    for f in sepa_dir.glob("*.xml"):
        try:
            f.unlink()
            deleted.append(f.name)
        except Exception as e:
            pass  # Ignore errors

    if deleted:
        return json.dumps({
            "success": True,
            "deleted": deleted,
            "count": len(deleted),
            "message": f"{len(deleted)} SEPA-Datei(en) gelöscht"
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "success": True,
            "deleted": [],
            "count": 0,
            "message": "Keine SEPA-Dateien vorhanden"
        }, ensure_ascii=False)


# =============================================================================
# Append to existing SEPA file
# =============================================================================

def parse_sepa_xml(filepath: Path) -> tuple[list, dict]:
    """
    Parst eine existierende SEPA XML Datei.

    Returns:
        (payments, metadata) - Liste der Zahlungen und Metadaten
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Namespace handling
    ns = {"pain": NAMESPACE}

    payments = []
    metadata = {}

    # Find all CdtTrfTxInf elements (individual payments)
    for tx in root.findall(".//pain:CdtTrfTxInf", ns):
        payment = {}

        # Creditor name
        cdtr_nm = tx.find(".//pain:Cdtr/pain:Nm", ns)
        if cdtr_nm is not None:
            payment["creditor_name"] = cdtr_nm.text

        # Creditor IBAN
        cdtr_iban = tx.find(".//pain:CdtrAcct/pain:Id/pain:IBAN", ns)
        if cdtr_iban is not None:
            payment["creditor_iban"] = cdtr_iban.text

        # Amount
        amt = tx.find(".//pain:Amt/pain:InstdAmt", ns)
        if amt is not None:
            payment["amount"] = float(amt.text)

        # Reference
        ustrd = tx.find(".//pain:RmtInf/pain:Ustrd", ns)
        if ustrd is not None:
            payment["reference"] = ustrd.text

        # End-to-end ID
        e2e = tx.find(".//pain:PmtId/pain:EndToEndId", ns)
        if e2e is not None:
            payment["end_to_end_id"] = e2e.text

        # BIC (optional)
        bic = tx.find(".//pain:CdtrAgt/pain:FinInstnId/pain:BIC", ns)
        if bic is not None:
            payment["creditor_bic"] = bic.text

        if payment.get("creditor_name") and payment.get("amount"):
            payments.append(payment)

    # Get execution date
    exec_date = root.find(".//pain:ReqdExctnDt", ns)
    if exec_date is not None:
        metadata["execution_date"] = exec_date.text

    return payments, metadata


@mcp.tool()
def sepa_get_details(filename: str = None) -> str:
    """
    Zeigt alle Überweisungen einer SEPA-Datei mit vollständigen Details.

    Args:
        filename: Name der SEPA-Datei (optional, bei leer: neueste Datei)

    Returns:
        Vollständige Übersicht mit Von, Von-IBAN, Nach, Nach-IBAN, Referenz, Betrag
    """
    sepa_dir = get_exports_dir()

    # Find file
    if filename:
        filepath = sepa_dir / filename
        if not filepath.exists():
            return json.dumps({"error": f"Datei nicht gefunden: {filename}"}, ensure_ascii=False)
    else:
        # Get newest file
        files = list(sepa_dir.glob("*.xml"))
        if not files:
            return json.dumps({"error": "Keine SEPA-Dateien vorhanden"}, ensure_ascii=False)
        filepath = max(files, key=lambda f: f.stat().st_mtime)

    try:
        payments, metadata = parse_sepa_xml(filepath)

        # Get debtor info from XML
        tree = ET.parse(filepath)
        root = tree.getroot()
        ns = {"pain": NAMESPACE}

        debtor_name = ""
        debtor_iban = ""

        dbtr_nm = root.find(".//pain:Dbtr/pain:Nm", ns)
        if dbtr_nm is not None:
            debtor_name = dbtr_nm.text

        dbtr_iban = root.find(".//pain:DbtrAcct/pain:Id/pain:IBAN", ns)
        if dbtr_iban is not None:
            debtor_iban = dbtr_iban.text

        # Build result
        total = sum(p.get("amount", 0) for p in payments)

        result = {
            "filename": filepath.name,
            "debtor": {
                "name": debtor_name,
                "iban": debtor_iban
            },
            "execution_date": metadata.get("execution_date", ""),
            "payments": payments,
            "total_count": len(payments),
            "total_amount": round(total, 2)
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sepa_list_files() -> str:
    """
    Listet alle SEPA XML Dateien im sepa/ Ordner auf.

    Returns:
        Liste der Dateien mit Metadaten (Anzahl Zahlungen, Summe)
    """
    sepa_dir = get_exports_dir()
    files = []

    for filepath in sorted(sepa_dir.glob("*.xml"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            payments, metadata = parse_sepa_xml(filepath)
            total_amount = sum(p.get("amount", 0) for p in payments)

            files.append({
                "filename": filepath.name,
                "path": str(filepath),
                "payments": len(payments),
                "total_amount": f"{total_amount:.2f} EUR",
                "execution_date": metadata.get("execution_date", ""),
                "modified": datetime.fromtimestamp(filepath.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        except Exception as e:
            files.append({
                "filename": filepath.name,
                "path": str(filepath),
                "error": str(e)
            })

    return json.dumps({
        "files": files,
        "folder": str(sepa_dir),
        "count": len(files)
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def sepa_append(
    filename: str,
    payments: str,
    account: str = None
) -> str:
    """
    Fügt Zahlungen zu einer bestehenden SEPA-Datei hinzu.

    Args:
        filename: Name der existierenden SEPA-Datei (im sepa/ Ordner)
        payments: JSON-Array von neuen Zahlungen (wie bei sepa_create_batch)
        account: Absender-Konto (muss mit Original übereinstimmen)

    Returns:
        Pfad zur aktualisierten XML-Datei

    Example:
        payments = '[{"creditor_name": "Max Mustermann", "creditor_iban": "DE89...", "amount": 100.50, "reference": "Gehalt"}]'
    """
    sepa_dir = get_exports_dir()
    filepath = sepa_dir / filename

    if not filepath.exists():
        return json.dumps({"error": f"Datei nicht gefunden: {filename}"}, ensure_ascii=False)

    # Parse new payments
    try:
        new_payments = json.loads(payments)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Ungültiges JSON: {e}"}, ensure_ascii=False)

    if not new_payments:
        return json.dumps({"error": "Keine neuen Zahlungen angegeben"}, ensure_ascii=False)

    # Parse existing file
    try:
        existing_payments, metadata = parse_sepa_xml(filepath)
    except Exception as e:
        return json.dumps({"error": f"Fehler beim Parsen der Datei: {e}"}, ensure_ascii=False)

    # Get config
    config = get_config(account)
    if "error" in config:
        return json.dumps(config, ensure_ascii=False)

    # Validate new IBANs
    errors = []
    for idx, payment in enumerate(new_payments, 1):
        if "creditor_iban" not in payment:
            errors.append(f"Zahlung {idx}: Keine IBAN angegeben")
            continue
        is_valid, message = validate_iban(payment["creditor_iban"])
        if not is_valid:
            errors.append(f"Zahlung {idx} ({payment.get('creditor_name', 'Unbekannt')}): {message}")

    if errors:
        return json.dumps({"error": "IBAN-Validierungsfehler", "details": errors}, ensure_ascii=False, indent=2)

    # Add end-to-end IDs to new payments
    start_idx = len(existing_payments) + 1
    for idx, payment in enumerate(new_payments, start_idx):
        if "end_to_end_id" not in payment:
            payment["end_to_end_id"] = f"APPEND-{datetime.now().strftime('%Y%m%d')}-{idx:04d}"

    # Combine payments
    all_payments = existing_payments + new_payments

    # Generate new XML
    try:
        execution_date = metadata.get("execution_date")
        xml_content = generate_sepa_xml(all_payments, config, execution_date)

        # Overwrite file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(xml_content)

        old_total = sum(p.get("amount", 0) for p in existing_payments)
        new_total = sum(p.get("amount", 0) for p in new_payments)
        total_amount = old_total + new_total

        return json.dumps({
            "success": True,
            "file": str(filepath),
            "filename": filename,
            "existing_payments": len(existing_payments),
            "added_payments": len(new_payments),
            "total_payments": len(all_payments),
            "added_amount": f"{new_total:.2f} EUR",
            "total_amount": f"{total_amount:.2f} EUR",
            "new_creditors": [p.get("creditor_name", "Unknown") for p in new_payments]
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# =============================================================================
# CAMT.052 Parsing (Bank Account Report)
# =============================================================================

# CAMT.052 Namespace (ISO 20022)
CAMT052_NAMESPACES = [
    "urn:iso:std:iso:20022:tech:xsd:camt.052.001.02",
    "urn:iso:std:iso:20022:tech:xsd:camt.052.001.08",
    "urn:iso:std:iso:20022:tech:xsd:camt.052.001.10",
]


def detect_camt_namespace(root: ET.Element) -> str:
    """Erkennt die verwendete CAMT-Namespace aus dem Root-Element."""
    # Check xmlns attribute
    ns = root.attrib.get("xmlns", "")
    if ns:
        return ns

    # Check tag prefix
    tag = root.tag
    if "{" in tag:
        return tag.split("}")[0][1:]

    return ""


def parse_camt052_entry(entry: ET.Element, ns: dict) -> dict:
    """Parst einen einzelnen Buchungseintrag (Ntry) aus CAMT.052."""
    result = {}

    # Booking Date
    booking_date = entry.find(".//camt:BookgDt/camt:Dt", ns)
    if booking_date is not None:
        result["booking_date"] = booking_date.text

    # Value Date
    value_date = entry.find(".//camt:ValDt/camt:Dt", ns)
    if value_date is not None:
        result["value_date"] = value_date.text

    # Amount
    amt = entry.find(".//camt:Amt", ns)
    if amt is not None:
        result["amount"] = float(amt.text)
        result["currency"] = amt.attrib.get("Ccy", "EUR")

    # Credit/Debit Indicator (CRDT = Eingang, DBIT = Ausgang)
    cdi = entry.find(".//camt:CdtDbtInd", ns)
    if cdi is not None:
        result["type"] = "credit" if cdi.text == "CRDT" else "debit"

    # Status
    status = entry.find(".//camt:Sts", ns)
    if status is not None:
        result["status"] = status.text  # BOOK = gebucht, PDNG = pending

    # Bank Transaction Code
    btc = entry.find(".//camt:BkTxCd/camt:Domn/camt:Cd", ns)
    if btc is not None:
        result["bank_tx_code"] = btc.text

    # Transaction Details (kann mehrere geben)
    tx_details = entry.find(".//camt:NtryDtls/camt:TxDtls", ns)
    if tx_details is not None:
        # Counterparty (Debtor for credits, Creditor for debits)
        # Bei Zahlungseingang: Debtor = Wer hat gezahlt
        # Bei Zahlungsausgang: Creditor = Wer hat bekommen
        debtor = tx_details.find(".//camt:RltdPties/camt:Dbtr/camt:Nm", ns)
        if debtor is not None:
            result["debtor_name"] = debtor.text

        debtor_iban = tx_details.find(".//camt:RltdPties/camt:DbtrAcct/camt:Id/camt:IBAN", ns)
        if debtor_iban is not None:
            result["debtor_iban"] = debtor_iban.text

        creditor = tx_details.find(".//camt:RltdPties/camt:Cdtr/camt:Nm", ns)
        if creditor is not None:
            result["creditor_name"] = creditor.text

        creditor_iban = tx_details.find(".//camt:RltdPties/camt:CdtrAcct/camt:Id/camt:IBAN", ns)
        if creditor_iban is not None:
            result["creditor_iban"] = creditor_iban.text

        # Reference/Purpose (Verwendungszweck)
        ustrd = tx_details.find(".//camt:RmtInf/camt:Ustrd", ns)
        if ustrd is not None:
            result["reference"] = ustrd.text

        # End-to-End ID
        e2e = tx_details.find(".//camt:Refs/camt:EndToEndId", ns)
        if e2e is not None and e2e.text != "NOTPROVIDED":
            result["end_to_end_id"] = e2e.text

    return result


def parse_camt052_xml(xml_content: str) -> dict:
    """Parst CAMT.052 XML-Inhalt und extrahiert Transaktionen."""
    root = ET.fromstring(xml_content)

    # Detect namespace
    detected_ns = detect_camt_namespace(root)
    ns = {"camt": detected_ns} if detected_ns else {}

    result = {
        "namespace": detected_ns,
        "account": {},
        "balances": [],
        "transactions": [],
        "summary": {}
    }

    # Find Report element (BkToCstmrAcctRpt -> Rpt)
    report = root.find(".//camt:Rpt", ns) if ns else root.find(".//{*}Rpt")
    if report is None:
        # Try without namespace
        report = root.find(".//Rpt")

    if report is None:
        return {"error": "Kein Report-Element gefunden", "namespace": detected_ns}

    # Account Info
    acct = report.find(".//camt:Acct", ns) if ns else report.find(".//{*}Acct")
    if acct is not None:
        iban = acct.find(".//camt:Id/camt:IBAN", ns) if ns else acct.find(".//{*}IBAN")
        if iban is not None:
            result["account"]["iban"] = iban.text

        owner = acct.find(".//camt:Ownr/camt:Nm", ns) if ns else acct.find(".//{*}Ownr/{*}Nm")
        if owner is not None:
            result["account"]["owner"] = owner.text

    # Balances
    for bal in (report.findall(".//camt:Bal", ns) if ns else report.findall(".//{*}Bal")):
        balance = {}

        bal_type = bal.find(".//camt:Tp/camt:CdOrPrtry/camt:Cd", ns) if ns else bal.find(".//{*}Cd")
        if bal_type is not None:
            balance["type"] = bal_type.text  # OPBD = Opening, CLBD = Closing, etc.

        amt = bal.find(".//camt:Amt", ns) if ns else bal.find(".//{*}Amt")
        if amt is not None:
            balance["amount"] = float(amt.text)
            balance["currency"] = amt.attrib.get("Ccy", "EUR")

        cdi = bal.find(".//camt:CdtDbtInd", ns) if ns else bal.find(".//{*}CdtDbtInd")
        if cdi is not None:
            balance["indicator"] = cdi.text

        if balance:
            result["balances"].append(balance)

    # Transactions (Ntry = Entry)
    entries = report.findall(".//camt:Ntry", ns) if ns else report.findall(".//{*}Ntry")
    for entry in entries:
        tx = parse_camt052_entry(entry, ns) if ns else {}
        if not ns:
            # Fallback parsing without namespace
            tx = {}
            for child in entry.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "Dt" and "booking_date" not in tx:
                    tx["booking_date"] = child.text
                elif tag == "Amt":
                    tx["amount"] = float(child.text)
                    tx["currency"] = child.attrib.get("Ccy", "EUR")
                elif tag == "CdtDbtInd":
                    tx["type"] = "credit" if child.text == "CRDT" else "debit"
                elif tag == "Ustrd":
                    tx["reference"] = child.text

        if tx:
            result["transactions"].append(tx)

    # Summary
    credits = [t for t in result["transactions"] if t.get("type") == "credit"]
    debits = [t for t in result["transactions"] if t.get("type") == "debit"]

    result["summary"] = {
        "total_transactions": len(result["transactions"]),
        "credits": len(credits),
        "debits": len(debits),
        "total_credits": round(sum(t.get("amount", 0) for t in credits), 2),
        "total_debits": round(sum(t.get("amount", 0) for t in debits), 2)
    }

    return result


@mcp.tool()
def sepa_read_camt052_zip(zip_path: str) -> str:
    """
    Liest CAMT.052 Kontoauszüge aus einer ZIP-Datei.

    CAMT.052 ist das ISO 20022 Format für Intraday-Kontoauszüge.
    Banken liefern diese oft als ZIP mit XML-Dateien.

    Args:
        zip_path: Pfad zur ZIP-Datei mit CAMT.052 XML-Dateien

    Returns:
        JSON mit allen Transaktionen, Salden und Zusammenfassung
    """
    zip_file = Path(zip_path)

    if not zip_file.exists():
        return json.dumps({"error": f"Datei nicht gefunden: {zip_path}"}, ensure_ascii=False)

    if not zip_file.suffix.lower() == ".zip":
        return json.dumps({"error": "Keine ZIP-Datei"}, ensure_ascii=False)

    try:
        result = {
            "zip_file": zip_file.name,
            "reports": [],
            "all_transactions": [],
            "summary": {}
        }

        with zipfile.ZipFile(zip_file, 'r') as zf:
            xml_files = [f for f in zf.namelist() if f.lower().endswith('.xml')]

            if not xml_files:
                return json.dumps({"error": "Keine XML-Dateien in der ZIP gefunden"}, ensure_ascii=False)

            for xml_name in xml_files:
                try:
                    with zf.open(xml_name) as xml_file:
                        content = xml_file.read().decode('utf-8')
                        report = parse_camt052_xml(content)
                        report["filename"] = xml_name

                        result["reports"].append(report)

                        # Collect all transactions
                        for tx in report.get("transactions", []):
                            tx["source_file"] = xml_name
                            result["all_transactions"].append(tx)

                except Exception as e:
                    result["reports"].append({
                        "filename": xml_name,
                        "error": str(e)
                    })

        # Overall summary
        all_tx = result["all_transactions"]
        credits = [t for t in all_tx if t.get("type") == "credit"]
        debits = [t for t in all_tx if t.get("type") == "debit"]

        result["summary"] = {
            "files_processed": len(xml_files),
            "total_transactions": len(all_tx),
            "credits": {
                "count": len(credits),
                "total": round(sum(t.get("amount", 0) for t in credits), 2)
            },
            "debits": {
                "count": len(debits),
                "total": round(sum(t.get("amount", 0) for t in debits), 2)
            }
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except zipfile.BadZipFile:
        return json.dumps({"error": "Ungültige ZIP-Datei"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sepa_read_camt052_xml(xml_path: str) -> str:
    """
    Liest eine einzelne CAMT.052 XML-Datei.

    Args:
        xml_path: Pfad zur CAMT.052 XML-Datei

    Returns:
        JSON mit Transaktionen, Salden und Zusammenfassung
    """
    xml_file = Path(xml_path)

    if not xml_file.exists():
        return json.dumps({"error": f"Datei nicht gefunden: {xml_path}"}, ensure_ascii=False)

    try:
        with open(xml_file, 'r', encoding='utf-8') as f:
            content = f.read()

        result = parse_camt052_xml(content)
        result["filename"] = xml_file.name

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sepa_get_camt_credits(zip_path: str, min_amount: float = 0) -> str:
    """
    Extrahiert nur Zahlungseingänge (Credits) aus CAMT.052.

    Nützlich für den Abgleich mit offenen Rechnungen.

    Args:
        zip_path: Pfad zur ZIP-Datei mit CAMT.052 XML-Dateien
        min_amount: Mindestbetrag filtern (Standard: 0 = alle)

    Returns:
        JSON mit allen Zahlungseingängen (Debitor, IBAN, Betrag, Referenz)
    """
    # First read the ZIP
    raw_result = sepa_read_camt052_zip(zip_path)
    data = json.loads(raw_result)

    if "error" in data:
        return raw_result

    # Filter credits
    credits = []
    for tx in data.get("all_transactions", []):
        if tx.get("type") != "credit":
            continue

        amount = tx.get("amount", 0)
        if amount < min_amount:
            continue

        credit = {
            "date": tx.get("booking_date") or tx.get("value_date"),
            "amount": amount,
            "currency": tx.get("currency", "EUR"),
            "debtor_name": tx.get("debtor_name", ""),
            "debtor_iban": tx.get("debtor_iban", ""),
            "reference": tx.get("reference", ""),
            "end_to_end_id": tx.get("end_to_end_id", "")
        }
        credits.append(credit)

    # Sort by date descending
    credits.sort(key=lambda x: x.get("date", ""), reverse=True)

    return json.dumps({
        "credits": credits,
        "count": len(credits),
        "total": round(sum(c.get("amount", 0) for c in credits), 2),
        "source": data.get("zip_file", "")
    }, ensure_ascii=False, indent=2)


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    mcp.run()
