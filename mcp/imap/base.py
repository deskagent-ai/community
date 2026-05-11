# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP/SMTP MCP - Base Module
============================
Configuration and shared utilities for IMAP/SMTP email operations.

Supports custom IMAP flags (keywords) for advanced workflow automation.
"""

# BULLETPROOF: Add embedded Python Lib path for Nuitka builds
# Must happen before 'from email.mime...' imports
import sys as _sys
import os as _os
_mcp_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_deskagent_dir = _os.path.dirname(_mcp_dir)
_python_lib = _os.path.join(_deskagent_dir, 'python', 'Lib')
if _os.path.isdir(_python_lib) and _python_lib not in _sys.path:
    _sys.path.insert(1, _python_lib)
# ALWAYS clear cached email module - path may already be set by deskagent_main.py
# but the incomplete email module from python312.zip could still be cached
for _mod in list(_sys.modules.keys()):
    if _mod == 'email' or _mod.startswith('email.'):
        del _sys.modules[_mod]
del _mcp_dir, _deskagent_dir, _python_lib

import imaplib
import smtplib
import email
import sys
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from functools import wraps
from mcp.server.fastmcp import FastMCP

from _mcp_api import load_config, mcp_log

# Import shared email utilities
try:
    from mcp_shared.email_utils import extract_latest_message
except ImportError:
    def extract_latest_message(body, max_length=0): return body[:max_length] if max_length else body

# API timeout in seconds (prevents hangs on network issues)
API_TIMEOUT = 30

mcp = FastMCP("imap")

# Tools that return external/untrusted content (prompt injection risk)
HIGH_RISK_TOOLS = {
    "imap_search_emails",
    "imap_get_email",
    "imap_get_recent_emails",
    "imap_get_folder_emails",
    "imap_get_unread_emails",
    "imap_get_flagged_emails",
    "imap_read_pdf_attachment",
}

# Destructive tools that create, send, or delete data (irreversible operations)
# Reversible operations (move, flag) are NOT in this set
DESTRUCTIVE_TOOLS = {
    "imap_delete_email",
    "smtp_send_email",
    "smtp_send_with_attachment",
    "imap_send_reply",
}

# =============================================================================
# Configuration
# =============================================================================

def get_config():
    """Load IMAP/SMTP configuration from apis.json."""
    try:
        config = load_config()
        return config.get("imap", {})
    except Exception as e:
        mcp_log(f"[IMAP] Config load error: {e}")
    return {}


def is_configured() -> bool:
    """Check if IMAP/SMTP is configured and enabled.

    Returns True if:
    - imap section exists in apis.json
    - enabled is not explicitly False
    - required credentials are set
    """
    config = get_config()

    # Check if explicitly disabled
    if config.get("enabled") is False:
        return False

    # Check required credentials
    has_imap = bool(
        config.get("imap_host") and
        config.get("imap_user") and
        config.get("imap_password")
    )

    has_smtp = bool(
        config.get("smtp_host") and
        config.get("smtp_user") and
        config.get("smtp_password")
    )

    return has_imap and has_smtp


# =============================================================================
# IMAP Connection
# =============================================================================

_imap_connection = None

def get_imap_connection():
    """Get or create IMAP connection."""
    global _imap_connection

    config = get_config()

    # Reuse existing connection if still alive
    if _imap_connection:
        try:
            _imap_connection.noop()
            return _imap_connection
        except (imaplib.IMAP4.error, OSError, TimeoutError) as e:
            mcp_log(f"[IMAP] Connection check failed, reconnecting: {e}")
            _imap_connection = None

    # Create new connection
    try:
        imap_host = config.get("imap_host")
        imap_port = config.get("imap_port", 993)
        imap_user = config.get("imap_user")
        imap_password = config.get("imap_password")
        use_ssl = config.get("imap_ssl", True)

        if not all([imap_host, imap_user, imap_password]):
            raise ValueError("IMAP credentials not configured in apis.json")

        # Connect with SSL or plain (with timeout to prevent hangs)
        if use_ssl:
            imap = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=API_TIMEOUT)
        else:
            imap = imaplib.IMAP4(imap_host, imap_port, timeout=API_TIMEOUT)

        imap.login(imap_user, imap_password)
        mcp_log(f"[IMAP] Connected to {imap_host} as {imap_user} (timeout={API_TIMEOUT}s)")

        _imap_connection = imap
        return imap

    except Exception as e:
        mcp_log(f"[IMAP] Connection failed: {e}")
        raise


def close_imap_connection():
    """Close IMAP connection."""
    global _imap_connection
    if _imap_connection:
        try:
            _imap_connection.logout()
        except (imaplib.IMAP4.error, OSError, TimeoutError) as e:
            mcp_log(f"[IMAP] Logout failed (connection may already be closed): {e}")
        _imap_connection = None


# =============================================================================
# SMTP Connection
# =============================================================================

def get_smtp_connection():
    """Create SMTP connection (not persistent)."""
    config = get_config()

    try:
        smtp_host = config.get("smtp_host")
        smtp_port = config.get("smtp_port", 587)
        smtp_user = config.get("smtp_user")
        smtp_password = config.get("smtp_password")
        use_tls = config.get("smtp_tls", True)

        if not all([smtp_host, smtp_user, smtp_password]):
            raise ValueError("SMTP credentials not configured in apis.json")

        # Connect (with timeout to prevent hangs)
        if use_tls:
            smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=API_TIMEOUT)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=API_TIMEOUT)

        smtp.login(smtp_user, smtp_password)
        mcp_log(f"[SMTP] Connected to {smtp_host} as {smtp_user} (timeout={API_TIMEOUT}s)")

        return smtp

    except Exception as e:
        mcp_log(f"[SMTP] Connection failed: {e}")
        raise


# =============================================================================
# Helper Functions
# =============================================================================

def parse_email_message(msg_data):
    """Parse email message data into structured dict."""
    try:
        email_message = email.message_from_bytes(msg_data)

        # Extract headers
        subject = email_message.get("Subject", "")
        from_addr = email_message.get("From", "")
        to_addr = email_message.get("To", "")
        date = email_message.get("Date", "")
        message_id = email_message.get("Message-ID", "")

        # Extract body
        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
                    except (AttributeError, UnicodeDecodeError) as e:
                        mcp_log(f"[IMAP] Failed to decode multipart body: {e}")
        else:
            try:
                body = email_message.get_payload(decode=True).decode("utf-8", errors="ignore")
            except (AttributeError, UnicodeDecodeError) as e:
                mcp_log(f"[IMAP] Failed to decode body, using raw payload: {e}")
                body = str(email_message.get_payload())

        # Extract attachments
        attachments = []
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_disposition() == "attachment":
                    filename = part.get_filename()
                    if filename:
                        attachments.append(filename)

        return {
            "subject": subject,
            "from": from_addr,
            "to": to_addr,
            "date": date,
            "message_id": message_id,
            "body": body,
            "attachments": attachments,
        }

    except Exception as e:
        mcp_log(f"[IMAP] Failed to parse email: {e}")
        return None


def requires_imap(func):
    """Decorator to ensure IMAP is configured."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_configured():
            return "Error: IMAP/SMTP not configured in apis.json"
        try:
            return func(*args, **kwargs)
        except Exception as e:
            mcp_log(f"[IMAP] Tool error: {e}")
            return f"Error: {str(e)}"
    return wrapper
