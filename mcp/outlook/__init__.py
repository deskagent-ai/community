# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP Server
==================
MCP Server für lokalen Outlook-Zugriff via COM.
Ermöglicht Claude das Lesen und Schreiben von E-Mails und Kalender.

This package is split into modules for better maintainability:
- base.py: Shared utilities, decorators, helper classes
- email_read.py: Reading and searching emails
- email_write.py: Creating and replying to emails
- email_manage.py: Flag, move, delete, batch operations
- calendar.py: Calendar operations
- attachments.py: Attachment handling
"""

# Import the shared MCP instance and tool sets from base
from outlook.base import mcp, HIGH_RISK_TOOLS, DESTRUCTIVE_TOOLS, READ_ONLY_TOOLS, check_outlook_com_available
from outlook import email_read
from outlook import email_write
from outlook import email_manage
from outlook import outlook_calendar as calendar
from outlook import attachments
from _mcp_api import load_config

# Integration schema for dynamic UI configuration
INTEGRATION_SCHEMA = {
    "name": "Microsoft Outlook",
    "icon": "mail",
    "color": "#0078D4",
    "config_key": None,  # No config needed - local COM
    "auth_type": "none",
    "description": "Lokales Outlook via COM-Schnittstelle. Outlook muss installiert sein (klassisches Outlook, nicht 'New Outlook').",
    "setup": {
        "description": "Lokaler Outlook-Zugriff via COM",
        "requirement": "Klassisches Microsoft Outlook (Desktop-Version)",
        "alternative": "msgraph (für Office 365 / neues Outlook)",
        "setup_steps": [
            "Microsoft Outlook (Desktop) installieren",
            "Outlook mindestens einmal starten und Konto einrichten",
        ],
    },
}

# Export the main entry points
__all__ = ['mcp', 'HIGH_RISK_TOOLS', 'DESTRUCTIVE_TOOLS', 'READ_ONLY_TOOLS', 'is_configured', 'check_outlook_com_available', 'INTEGRATION_SCHEMA']


# Cache for is_configured result (avoid repeated logging)
_is_configured_logged = False


def is_configured() -> bool:
    """Prüft ob Outlook verfügbar ist.

    Outlook ist ein lokaler COM-Dienst und benötigt keine API-Konfiguration.
    Prüft ob klassisches Outlook mit COM-Unterstützung installiert ist.
    Das neue Outlook (One Outlook) unterstützt kein COM - dafür msgraph verwenden.

    Kann über outlook.enabled deaktiviert werden.
    """
    global _is_configured_logged

    config = load_config()
    mcp_config = config.get("outlook", {})

    if mcp_config.get("enabled") is False:
        return False

    # Check if COM is available (classic Outlook vs new Outlook)
    com_available, error_msg = check_outlook_com_available()
    if not com_available:
        # Log the error only once for visibility
        if not _is_configured_logged:
            from _mcp_api import mcp_log
            mcp_log(f"[Outlook] COM not available: {error_msg}")
            _is_configured_logged = True
        return False

    return True


def run():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    run()
