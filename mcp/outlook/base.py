# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP - Base Module
========================
Shared utilities, decorators, and helper classes for Outlook MCP.
"""

import json
import re
import time
import threading
from datetime import datetime, timedelta
from functools import wraps
from mcp.server.fastmcp import FastMCP

# Windows COM imports
import pythoncom
import win32com.client

# Import system logger and email utilities
try:
    from _mcp_api import mcp_log
    from email_utils import render_email_footer, append_footer_to_html
    from mcp_shared.email_utils import extract_latest_message
except ImportError:
    def mcp_log(msg): print(msg)  # Fallback to print
    def render_email_footer(lang="de"): return ""  # Fallback
    def append_footer_to_html(html, lang="de"): return html  # Fallback
    def extract_latest_message(body, max_length=0): return body[:max_length] if max_length else body  # Fallback


# Create the shared MCP instance
mcp = FastMCP("outlook")

# Tools that return external/untrusted content (prompt injection risk)
# These will be wrapped with sanitization by the anonymization proxy
HIGH_RISK_TOOLS = {
    # Email tools
    "outlook_get_selected_email",
    "outlook_get_selected_emails",
    "outlook_get_email_content",
    "outlook_get_recent_emails",
    "outlook_get_folder_emails",
    "outlook_get_flagged_emails",
    "outlook_get_unread_emails",
    "outlook_search_emails",
    "outlook_fast_search_emails",
    "outlook_fast_get_email_content",
    "outlook_read_pdf_attachment",
    "outlook_read_pdf_attachment_by_id",
    # Calendar tools (contain attendee names)
    "outlook_get_today_events",
    "outlook_get_upcoming_events",
    "outlook_get_calendar_event_details",
    "outlook_check_availability",
}

# Destructive tools that create, send, or delete data (irreversible operations)
# Reversible operations (move, flag, categorize) are NOT in this set
DESTRUCTIVE_TOOLS = {
    # Email creation/modification
    "outlook_create_reply_draft",
    "outlook_create_reply_draft_with_attachment",
    "outlook_update_draft",
    "outlook_create_new_email",
    "outlook_create_new_email_with_attachment",
    # Email deletion
    "outlook_delete_selected_email",
    "outlook_delete_email",
    "outlook_delete_emails_from_sender",
    # Email sending
    "outlook_send_reply",
    # Calendar
    "outlook_create_appointment",
    "outlook_create_meeting",
    "outlook_create_teams_meeting",
}

# Read-only tools that only retrieve data without modifications
# Used by tool_mode: "read_only" to allow only safe operations
READ_ONLY_TOOLS = {
    # Email reading
    "outlook_get_selected_email",
    "outlook_get_selected_emails",
    "outlook_get_email_content",
    "outlook_get_recent_emails",
    "outlook_get_folder_emails",
    "outlook_get_flagged_emails",
    "outlook_get_unread_emails",
    "outlook_get_unread_emails_json",
    "outlook_search_emails",
    "outlook_fast_search_emails",
    "outlook_fast_get_email_content",
    # Attachments (read-only access)
    "outlook_get_email_attachments",
    "outlook_get_email_attachments_by_id",
    "outlook_read_pdf_attachment",
    "outlook_read_pdf_attachment_by_id",
    "outlook_save_email_attachment",
    "outlook_save_attachment_by_entry_id",
    # Calendar reading
    "outlook_get_today_events",
    "outlook_get_upcoming_events",
    "outlook_get_calendar_event_details",
    "outlook_check_availability",
    # Folder/category listing
    "outlook_list_mail_folders",
    "outlook_get_categories",
    "outlook_get_emails_by_category",
    # Debug/info
    "outlook_debug_info",
}

# Cache for folder list (structure rarely changes)
_folder_cache = {"data": None, "timestamp": 0}
FOLDER_CACHE_TTL = 300  # 5 minutes

# Thread-local storage for COM objects (COM objects are thread-local in Windows)
_thread_local = threading.local()

# Cache for COM availability check
_com_check_result = {"checked": False, "available": False, "error": None}


def check_outlook_com_available() -> tuple[bool, str | None]:
    """Check if classic Outlook with COM support is available.

    The new Outlook (One Outlook) does not support COM automation.
    This function detects which version is installed.

    Returns:
        tuple: (is_available, error_message)
            - (True, None) if classic Outlook with COM is available
            - (False, "error message") if not available with explanation
    """
    global _com_check_result

    # Return cached result if already checked
    if _com_check_result["checked"]:
        return _com_check_result["available"], _com_check_result["error"]

    try:
        # Try to create Outlook COM object
        pythoncom.CoInitialize()
        outlook = win32com.client.Dispatch("Outlook.Application")

        # Verify we can access the namespace (confirms full COM functionality)
        namespace = outlook.GetNamespace("MAPI")

        # Check if this is the new Outlook by looking for specific indicators
        # New Outlook may fail on certain COM operations that classic supports
        try:
            # This operation works in classic Outlook but may fail in new Outlook
            _ = namespace.GetDefaultFolder(6)  # Inbox
            _com_check_result = {"checked": True, "available": True, "error": None}
            mcp_log("[Outlook] COM check: Classic Outlook detected, COM available")
            return True, None
        except Exception as e:
            error_msg = (
                f"Outlook COM eingeschränkt: {e}\n\n"
                "Dies kann bedeuten, dass das neue Outlook (One Outlook) installiert ist.\n"
                "Das neue Outlook unterstützt keine COM-Automatisierung.\n\n"
                "Lösung: Verwende stattdessen den 'msgraph' MCP-Server für Office 365/Microsoft Graph API.\n"
                "Konfiguration: config/backends.json → Microsoft Graph Credentials eintragen"
            )
            _com_check_result = {"checked": True, "available": False, "error": error_msg}
            mcp_log(f"[Outlook] COM check failed: {error_msg}")
            return False, error_msg

    except pythoncom.com_error as e:
        # COM error - Outlook not installed or not registered
        error_code = e.hresult if hasattr(e, 'hresult') else 'unknown'
        error_msg = (
            f"Outlook COM nicht verfügbar (Error: {error_code}).\n\n"
            "Mögliche Ursachen:\n"
            "1. Outlook ist nicht installiert\n"
            "2. Das neue Outlook (One Outlook) ist installiert - dieses unterstützt kein COM\n"
            "3. Outlook ist nicht korrekt registriert\n\n"
            "Lösung für neues Outlook: Verwende den 'msgraph' MCP-Server statt 'outlook'.\n"
            "Konfiguration: config/backends.json → Microsoft Graph Credentials eintragen"
        )
        _com_check_result = {"checked": True, "available": False, "error": error_msg}
        mcp_log(f"[Outlook] COM not available: {error_msg}")
        return False, error_msg

    except Exception as e:
        # Generic error
        error_msg = (
            f"Outlook COM Fehler: {e}\n\n"
            "Falls das neue Outlook (One Outlook) installiert ist:\n"
            "Verwende stattdessen den 'msgraph' MCP-Server für Microsoft Graph API."
        )
        _com_check_result = {"checked": True, "available": False, "error": error_msg}
        mcp_log(f"[Outlook] COM error: {error_msg}")
        return False, error_msg


def outlook_tool(func):
    """Decorator for consistent error handling in Outlook tools.

    Wraps tool functions with try/except to catch and format errors consistently.
    This eliminates the need for repetitive error handling in each function.

    Usage:
        @mcp.tool()
        @outlook_tool
        def my_tool():
            # Function logic - errors will be caught automatically
            # No need for try/except wrapper
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Log unexpected errors for debugging
            import traceback
            mcp_log(f"[Outlook] [{func.__name__}] Error: {e}")
            mcp_log(f"[Outlook] [{func.__name__}] Traceback: {traceback.format_exc()}")
            return f"Fehler: {str(e)}"
    return wrapper


def get_outlook():
    """Initialisiert Outlook COM-Objekt (thread-safe, per-thread cached).

    COM objects in Windows are thread-local - they cannot be shared across threads.
    This function ensures each thread gets its own COM connection to Outlook.
    """
    # Check if this thread has been initialized
    if not getattr(_thread_local, 'initialized', False):
        pythoncom.CoInitialize()
        _thread_local.initialized = True
        _thread_local.outlook = None
        _thread_local.namespace = None

    # Get or create Outlook COM object for this thread
    if _thread_local.outlook is None:
        try:
            _thread_local.outlook = win32com.client.Dispatch("Outlook.Application")
        except Exception:
            # Reset and retry on error (COM object may be stale)
            _thread_local.outlook = None
            _thread_local.namespace = None
            pythoncom.CoInitialize()
            _thread_local.outlook = win32com.client.Dispatch("Outlook.Application")

    return _thread_local.outlook


def get_namespace():
    """Get cached MAPI namespace (per-thread)."""
    if not getattr(_thread_local, 'namespace', None):
        _thread_local.namespace = get_outlook().GetNamespace("MAPI")
    return _thread_local.namespace


class EmailFinder:
    """
    Consolidated helper for finding emails in Outlook.

    Eliminates duplicate code patterns for:
    - Getting selected email from Outlook UI
    - Searching emails by query
    - Getting email by EntryID

    Usage:
        finder = EmailFinder()

        # Get selected email
        mail, error = finder.get_selected()
        if error:
            return error

        # Search for email
        mail, error = finder.search("invoice", index=0)
        if error:
            return error

        # Get by selection OR search
        mail, error = finder.get_mail(query="invoice", selection_index=1)
    """

    def __init__(self):
        self.outlook = get_outlook()
        self.namespace = self.outlook.GetNamespace("MAPI")

    def get_selected(self, selection_index: int = 1) -> tuple:
        """
        Get selected email from Outlook's active explorer.

        Args:
            selection_index: Which email in multi-selection (1-based, default: 1)

        Returns:
            tuple: (mail_object, error_message)
                   If successful: (mail, None)
                   If error: (None, "Error message")
        """
        explorer = self.outlook.ActiveExplorer()

        if not explorer:
            return None, "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return None, "Fehler: Keine E-Mail ausgewählt"

        if selection_index > selection.Count:
            return None, f"Fehler: Nur {selection.Count} E-Mail(s) markiert, Index {selection_index} ungültig"

        return selection.Item(selection_index), None

    def get_all_selected(self) -> tuple:
        """
        Get all selected emails from Outlook's active explorer.

        Returns:
            tuple: (list_of_mails, error_message)
                   If successful: ([mail1, mail2, ...], None)
                   If error: (None, "Error message")
        """
        explorer = self.outlook.ActiveExplorer()

        if not explorer:
            return None, "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return None, "Fehler: Keine E-Mail ausgewählt"

        mails = []
        for i in range(1, selection.Count + 1):
            mails.append(selection.Item(i))

        return mails, None

    def search(self, query: str, folder=None, index: int = 0, limit: int = 50) -> tuple:
        """
        Search for email by query string.

        Args:
            query: Search term (matches subject or sender)
            folder: Outlook folder to search (None = default inbox)
            index: Which result to return (0 = first/newest)
            limit: Maximum results to consider

        Returns:
            tuple: (mail_object, error_message)
                   If successful: (mail, None)
                   If error: (None, "Error message")
        """
        if folder is None:
            folder = self.namespace.GetDefaultFolder(6)  # Inbox

        filter_str = (
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
        )

        messages = folder.Items.Restrict(filter_str)
        messages.Sort("[ReceivedTime]", True)

        if messages.Count == 0:
            return None, f"Keine E-Mail mit '{query}' gefunden"

        if index >= messages.Count:
            return None, f"Index {index} außerhalb des Bereichs (max: {messages.Count - 1})"

        return messages.Item(index + 1), None

    def search_all(self, query: str, folder=None, limit: int = 50) -> tuple:
        """
        Search for all matching emails.

        Args:
            query: Search term (matches subject or sender)
            folder: Outlook folder to search (None = default inbox)
            limit: Maximum results to return

        Returns:
            tuple: (list_of_mails, error_message)
                   If successful: ([mail1, mail2, ...], None)
                   If error: (None, "Error message")
        """
        if folder is None:
            folder = self.namespace.GetDefaultFolder(6)  # Inbox

        filter_str = (
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
        )

        messages = folder.Items.Restrict(filter_str)
        messages.Sort("[ReceivedTime]", True)

        if messages.Count == 0:
            return None, f"Keine E-Mail mit '{query}' gefunden"

        mails = []
        for i in range(1, min(messages.Count + 1, limit + 1)):
            mails.append(messages.Item(i))

        return mails, None

    def get_by_id(self, entry_id: str) -> tuple:
        """
        Get email by EntryID.

        Args:
            entry_id: Outlook EntryID

        Returns:
            tuple: (mail_object, error_message)
                   If successful: (mail, None)
                   If error: (None, "Error message")
        """
        try:
            mail = self.namespace.GetItemFromID(entry_id)
            return mail, None
        except Exception as e:
            return None, f"Fehler: E-Mail mit ID nicht gefunden: {e}"

    def get_mail(self, query: str = None, index: int = 0, selection_index: int = 1) -> tuple:
        """
        Get email by selection OR search - the most common pattern.

        If query is None, uses selected email from Outlook UI.
        If query is provided, searches for email.

        Args:
            query: Search term (None = use selected email)
            index: Index in search results (0 = newest)
            selection_index: Which email in multi-selection (1-based)

        Returns:
            tuple: (mail_object, error_message)
                   If successful: (mail, None)
                   If error: (None, "Error message")
        """
        if query is None:
            return self.get_selected(selection_index)
        else:
            return self.search(query, index=index)


def get_inbox(mailbox: str = None):
    """Holt den Inbox-Ordner, optional für eine bestimmte Mailbox.

    Args:
        mailbox: Name der Mailbox (z.B. "info@example.com").
                 None = Standard-Posteingang.

    Returns:
        Outlook Folder Objekt für den Posteingang
    """
    outlook = get_outlook()
    namespace = outlook.GetNamespace("MAPI")

    if mailbox is None:
        return namespace.GetDefaultFolder(6)  # Default Inbox

    # Suche die spezifische Mailbox
    mailbox_lower = mailbox.lower()
    for store in namespace.Folders:
        if store.Name.lower() == mailbox_lower:
            # Finde den Inbox-Ordner in dieser Mailbox
            for folder in store.Folders:
                folder_name = folder.Name.lower()
                if folder_name in ["inbox", "posteingang"]:
                    return folder
            # Fallback: Versuche "Inbox" direkt
            try:
                return store.Folders["Inbox"]
            except (KeyError, AttributeError):
                pass
            try:
                return store.Folders["Posteingang"]
            except (KeyError, AttributeError):
                pass

    raise Exception(f"Mailbox '{mailbox}' nicht gefunden. Nutze list_mail_folders() für verfügbare Mailboxen.")


def markdown_to_html(text: str, include_footer: bool = False, lang: str = "de") -> str:
    """Konvertiert einfaches Markdown zu HTML für Outlook mit Calibri 11pt.

    Args:
        text: Markdown text to convert
        include_footer: Whether to include the DeskAgent footer (default: False, only if explicitly requested)
        lang: Language code for footer template selection ("de", "en")

    Returns:
        HTML string with optional footer
    """
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    text = text.replace('\n\n', '</p><p>')
    text = text.replace('\n', '<br>')

    html = f'<div style="font-family: Calibri, sans-serif; font-size: 11pt;"><p>{text}</p></div>'

    # Add footer if enabled
    if include_footer:
        footer = render_email_footer(lang)
        if footer:
            html += footer

    return html


def get_mail_location(msg) -> tuple:
    """Ermittelt Postfach und Ordner einer E-Mail.

    Returns:
        tuple: (mailbox_name, folder_name)
    """
    folder_name = "Unbekannt"
    mailbox_name = "Unbekannt"

    try:
        # Get the folder containing this message
        folder = msg.Parent
        if folder:
            folder_name = folder.Name

            # Get the Store (mailbox/account) directly from the folder
            try:
                store = folder.Store
                if store:
                    mailbox_name = store.DisplayName
            except AttributeError:
                # Fallback: try to get it from the folder path
                try:
                    folder_path = folder.FolderPath
                    if folder_path:
                        # FolderPath format: \\mailbox@email.com\Inbox\Subfolder
                        parts = folder_path.strip("\\").split("\\")
                        if parts:
                            mailbox_name = parts[0]
                except AttributeError:
                    pass
    except AttributeError:
        pass

    return (mailbox_name, folder_name)


def get_folder_cache():
    """Get the folder cache for list_mail_folders."""
    return _folder_cache


# Windows Search helper functions
HANGUL_BASE = 0xAC00  # Unicode Hangul Syllables start (가)


def decode_mapi_entry_id(encoded_string: str) -> str:
    """Decode Hangul-encoded Entry ID from MAPI URL.

    Windows Search stores Entry IDs encoded as Hangul characters (U+AC00 - U+D7AF).
    Each Hangul character represents one byte of the Entry ID.
    """
    entry_id_bytes = []
    for char in encoded_string:
        code_point = ord(char)
        # Check if it's a Hangul character
        if 0xAC00 <= code_point <= 0xD7AF:
            byte_value = code_point - HANGUL_BASE
            entry_id_bytes.append(byte_value)
    # Return as hex string (Outlook EntryID format)
    return ''.join(f'{b:02X}' for b in entry_id_bytes)


@mcp.tool()
def outlook_debug_info(reload_calendar: bool = False) -> str:
    """Debug-Tool: Zeigt Modul-Versionen, Outlook-Version und COM-Status.

    Args:
        reload_calendar: Wenn True, wird das calendar Modul neu geladen

    Returns:
        Debug-Informationen über geladene Module und Outlook-Verfügbarkeit
    """
    import importlib
    info = []
    info.append("=== Outlook MCP Debug Info ===")

    # Check Outlook COM availability
    info.append("\n--- Outlook COM Status ---")
    com_available, error_msg = check_outlook_com_available()
    if com_available:
        info.append("✓ Klassisches Outlook mit COM-Unterstützung erkannt")
        try:
            outlook = get_outlook()
            version = outlook.Version
            info.append(f"  Outlook Version: {version}")

            # Get account info
            namespace = outlook.GetNamespace("MAPI")
            accounts = []
            for account in namespace.Accounts:
                accounts.append(account.DisplayName)
            if accounts:
                info.append(f"  Accounts: {', '.join(accounts)}")
        except Exception as e:
            info.append(f"  (Detailabfrage fehlgeschlagen: {e})")
    else:
        info.append("✗ Outlook COM nicht verfügbar")
        info.append(f"\n{error_msg}")

    # Check calendar module version
    info.append("\n--- Module Status ---")
    try:
        from outlook import outlook_calendar as cal_module
        cal_version = getattr(cal_module, '_CALENDAR_MODULE_VERSION', 'unknown')
        info.append(f"Calendar Module Version: {cal_version}")

        if reload_calendar:
            info.append("\n--- Reloading calendar module ---")
            importlib.reload(cal_module)
            new_version = getattr(cal_module, '_CALENDAR_MODULE_VERSION', 'unknown')
            info.append(f"New Calendar Module Version: {new_version}")
    except Exception as e:
        info.append(f"Calendar Module: ERROR - {e}")

    # Show current time for reference
    info.append(f"\nServer Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return "\n".join(info)


def windows_search_query(query: str, limit: int = 50) -> list:
    """Query Windows Search index for Outlook emails (uses same index as Outlook UI search).

    Returns list of dicts with email metadata and Entry ID from the search index.
    """
    pythoncom.CoInitialize()
    try:
        # Create ADO connection to Windows Search
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")

        # Escape query for SQL - escape both single quotes and double quotes
        safe_query = query.replace("'", "''").replace('"', '""')

        # SQL query against Windows Search SystemIndex
        # CONTAINS with double quotes for exact phrase matching
        # System.Kind = 'email' filters to Outlook items
        sql = f"""
            SELECT TOP {limit}
                System.ItemName,
                System.ItemUrl,
                System.ItemPathDisplay,
                System.Kind,
                System.Message.FromName,
                System.Message.FromAddress,
                System.Message.DateReceived,
                System.Subject,
                System.Search.Rank
            FROM SystemIndex
            WHERE System.Kind = 'email'
            AND CONTAINS(*, '"{safe_query}"')
            ORDER BY System.Search.Rank DESC
        """

        mcp_log(f"[Outlook] [Windows Search] CONTAINS search for: {query}")

        rs = win32com.client.Dispatch("ADODB.Recordset")
        rs.Open(sql, conn)

        results = []
        while not rs.EOF:
            try:
                # Extract fields from result set (ADO may return tuples for multi-value props)
                item_path = rs.Fields("System.ItemPathDisplay").Value or ""
                item_url = rs.Fields("System.ItemUrl").Value or ""
                from_name = rs.Fields("System.Message.FromName").Value or ""
                from_addr = rs.Fields("System.Message.FromAddress").Value or ""

                # Handle ADO multi-value fields (come as tuples)
                if isinstance(from_name, tuple):
                    from_name = from_name[0] if from_name else ""
                if isinstance(from_addr, tuple):
                    from_addr = from_addr[0] if from_addr else ""
                if isinstance(item_path, tuple):
                    item_path = item_path[0] if item_path else ""

                # Build from field: prefer "Name <address>" format
                from_field = from_name
                if from_addr and from_addr != from_name:
                    from_field = f"{from_name} <{from_addr}>" if from_name else from_addr

                subject = rs.Fields("System.Subject").Value or ""
                if isinstance(subject, tuple):
                    subject = subject[0] if subject else ""

                # Decode Entry ID from MAPI URL (last part after the folder is Hangul-encoded Entry ID)
                entry_id = ""
                if item_url:
                    url_parts = item_url.rstrip('/').split('/')
                    if url_parts:
                        encoded_id = url_parts[-1]
                        # Remove attachment parameter if present
                        if '?at=' in encoded_id:
                            encoded_id = encoded_id.split('?at=')[0]
                        entry_id = decode_mapi_entry_id(encoded_id)

                item = {
                    "name": rs.Fields("System.ItemName").Value or "",
                    "url": item_url,
                    "from": from_field,
                    "date": rs.Fields("System.Message.DateReceived").Value,
                    "subject": subject,
                    "path": item_path,
                    "entry_id": entry_id,
                    "rank": rs.Fields("System.Search.Rank").Value or 0
                }
                results.append(item)
                mcp_log(f"[Outlook] [Windows Search] Result: {subject[:50]}... | entry_id={entry_id[:30]}...")
            except Exception as e:
                mcp_log(f"[Outlook] [Windows Search] Row error: {e}")
            rs.MoveNext()

        rs.Close()
        conn.Close()

        mcp_log(f"[Outlook] [Windows Search] Found {len(results)} results")
        return results

    except Exception as e:
        mcp_log(f"[Outlook] [Windows Search] Error: {e}")
        return []
    finally:
        pythoncom.CoUninitialize()
