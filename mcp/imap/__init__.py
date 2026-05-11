# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP/SMTP MCP Server
====================
MCP server for IMAP/SMTP email operations with custom flags support.

Provides email operations using standard IMAP/SMTP protocols:
- IMAP: Search, read, flags (including custom keywords)
- SMTP: Send emails with attachments
- Management: Move, copy, delete, folder operations

Configuration in apis.json:
    "imap": {
        "enabled": true,
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "imap_user": "user@example.com",
        "imap_password": "password",
        "imap_ssl": true,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "user@example.com",
        "smtp_password": "password",
        "smtp_tls": true
    }

Features:
    - Full IMAP search with standard criteria
    - Custom IMAP flags (keywords) for workflow automation
    - SMTP with HTML, attachments, CC/BCC
    - Email threading with In-Reply-To/References
    - Folder management (create, delete, rename)
"""

from imap.base import (
    mcp,
    HIGH_RISK_TOOLS,
    DESTRUCTIVE_TOOLS,
    is_configured,
    get_imap_connection,
    get_smtp_connection,
    close_imap_connection,
)

# Import all tool modules to register them with FastMCP
from imap import imap_email as email
from imap import flags
from imap import smtp
from imap import manage
from imap import attachments

# Metadata for UI display
TOOL_METADATA = {
    "icon": "mail",
    "color": "#00A4EF"  # Blue (generic email color)
}

# Integration schema for dynamic UI configuration
INTEGRATION_SCHEMA = {
    "name": "IMAP/SMTP",
    "icon": "mail",
    "color": "#00A4EF",
    "config_key": "imap",
    "auth_type": "credentials",
    "description": "Standard IMAP/SMTP E-Mail-Zugang mit Custom Flags Support.",
    "fields": [
        # IMAP Settings
        {
            "key": "imap_host",
            "label": "IMAP Server",
            "type": "text",
            "required": True,
            "hint": "z.B. imap.gmail.com, imap.mail.me.com"
        },
        {
            "key": "imap_port",
            "label": "IMAP Port",
            "type": "number",
            "required": False,
            "hint": "Standard: 993 (SSL)"
        },
        {
            "key": "imap_user",
            "label": "IMAP Benutzer",
            "type": "text",
            "required": True,
            "hint": "E-Mail-Adresse"
        },
        {
            "key": "imap_password",
            "label": "IMAP Passwort",
            "type": "password",
            "required": True,
            "hint": "App-Passwort empfohlen"
        },
        # SMTP Settings
        {
            "key": "smtp_host",
            "label": "SMTP Server",
            "type": "text",
            "required": True,
            "hint": "z.B. smtp.gmail.com, smtp.mail.me.com"
        },
        {
            "key": "smtp_port",
            "label": "SMTP Port",
            "type": "number",
            "required": False,
            "hint": "Standard: 587 (TLS) oder 465 (SSL)"
        },
        {
            "key": "smtp_user",
            "label": "SMTP Benutzer",
            "type": "text",
            "required": False,
            "hint": "Falls abweichend von IMAP"
        },
        {
            "key": "smtp_password",
            "label": "SMTP Passwort",
            "type": "password",
            "required": False,
            "hint": "Falls abweichend von IMAP"
        },
    ],
    # Note: No test_tool - connection tested implicitly via imap_get_recent_emails
    "setup": {
        "description": "E-Mail via IMAP/SMTP",
        "requirement": "IMAP/SMTP Server Credentials",
        "setup_steps": [
            '<a href="#" onclick="event.preventDefault(); this.closest(\'.confirm-overlay\').remove(); '
            'openSettings(); setTimeout(() => switchSettingsTab(\'integrations\'), 100);" '
            'style="color: var(--accent-primary); text-decoration: underline;">'
            'Einstellungen \u2192 Integrationen</a> \u00f6ffnen',
            "IMAP/SMTP Server-Daten eintragen",
        ],
    },
}

__all__ = [
    'mcp',
    'HIGH_RISK_TOOLS',
    'DESTRUCTIVE_TOOLS',
    'is_configured',
    'get_imap_connection',
    'get_smtp_connection',
    'close_imap_connection',
    'TOOL_METADATA',
    'INTEGRATION_SCHEMA',
]
