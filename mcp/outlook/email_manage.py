# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP - Email Manage Module
=================================
Functions for managing emails: flag, move, batch operations.
"""

import json
import time
import pythoncom
from datetime import datetime, timedelta

from outlook.base import (
    mcp, outlook_tool, mcp_log,
    get_outlook, get_namespace, get_folder_cache, FOLDER_CACHE_TTL,
    get_mail_location
)


# =============================================================================
# Helper Functions
# =============================================================================

def _find_folder_recursive(folder, name: str):
    """Recursively search for folder by name (case-insensitive)."""
    if folder.Name.lower() == name.lower():
        return folder
    try:
        for subfolder in folder.Folders:
            result = _find_folder_recursive(subfolder, name)
            if result:
                return result
    except Exception:
        pass
    return None


def _get_mail_store_name(msg) -> str:
    """Get the store/mailbox name that contains this email.

    Args:
        msg: Outlook MailItem object

    Returns:
        Store display name (e.g., "info@example.com") or None
    """
    try:
        # Navigate: msg.Parent (folder) → Store → DisplayName
        parent_folder = msg.Parent
        if parent_folder:
            store = parent_folder.Store
            if store:
                return store.DisplayName
    except Exception:
        pass
    return None


def _get_or_create_folder(namespace, folder_name: str, mailbox: str = None):
    """Get folder by name, create under Inbox if not found.

    For demo/standard delivery: Ensures folders like ToDelete, ToOffer, ToPay
    are automatically created if they don't exist.

    Args:
        namespace: Outlook MAPI namespace
        folder_name: Name of folder (e.g., "ToDelete", "ToOffer", "ToPay")
        mailbox: Optional mailbox name (default: search all, create in default)

    Returns:
        Folder object (existing or newly created)
    """
    # 1. Search in specific mailbox if provided
    if mailbox:
        mailbox_lower = mailbox.lower()
        for store in namespace.Folders:
            if store.Name.lower() == mailbox_lower:
                folder = _find_folder_recursive(store, folder_name)
                if folder:
                    return folder
                # Not found in mailbox → create there
                try:
                    inbox = store.Folders["Inbox"] if "Inbox" in [f.Name for f in store.Folders] else store.Folders["Posteingang"]
                    new_folder = inbox.Folders.Add(folder_name)
                    mcp_log(f"[Outlook] Created folder '{folder_name}' in {mailbox}")
                    return new_folder
                except Exception as e:
                    mcp_log(f"[Outlook] Failed to create folder in {mailbox}: {e}")
                    return None
        return None  # Mailbox not found

    # 2. Search all mailboxes
    for store in namespace.Folders:
        folder = _find_folder_recursive(store, folder_name)
        if folder:
            return folder

    # 3. Not found → Create under default Inbox
    try:
        inbox = namespace.GetDefaultFolder(6)  # olFolderInbox
        new_folder = inbox.Folders.Add(folder_name)
        mcp_log(f"[Outlook] Created folder '{folder_name}' under Inbox")
        return new_folder
    except Exception as e:
        mcp_log(f"[Outlook] Failed to create folder: {e}")
        return None


# =============================================================================
# Tool Functions
# =============================================================================

@mcp.tool()
@outlook_tool
def outlook_flag_selected_email(flag_type: str = "followup", selection_index: int = None) -> str:
    """Markiert die ausgewählte E-Mail mit einem Flag.

    Args:
        flag_type: Art des Flags - "followup" (Standard), "complete", oder "clear"
        selection_index: Index der E-Mail bei Mehrfachauswahl (1-basiert).
                        None = alle markierten E-Mails flaggen.
    """
    try:
        outlook = get_outlook()
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        # Bestimme welche E-Mails geflaggt werden sollen
        if selection_index is not None:
            # Einzelne E-Mail flaggen
            if selection_index < 1 or selection_index > selection.Count:
                return f"Fehler: Index {selection_index} ungültig (1-{selection.Count})"
            indices = [selection_index]
        else:
            # Alle markierten E-Mails flaggen
            indices = list(range(1, selection.Count + 1))

        results = []
        for idx in indices:
            mail = selection.Item(idx)
            subject = mail.Subject

            # Flag constants: 0=olNoFlag, 1=olFlagComplete, 2=olFlagMarked
            if flag_type.lower() == "clear":
                mail.FlagStatus = 0
                mail.Save()
                results.append(f"Flag entfernt: '{subject}'")
            elif flag_type.lower() == "complete":
                mail.FlagStatus = 1
                mail.Save()
                results.append(f"Als erledigt markiert: '{subject}'")
            else:  # followup
                mail.FlagStatus = 2
                mail.FlagRequest = "Follow up"
                mail.Save()
                results.append(f"Follow-up Flag gesetzt: '{subject}'")

        if len(results) == 1:
            return results[0]
        return f"{len(results)} E-Mails geflaggt:\n" + "\n".join(results)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_flag_email(query: str, index: int = 0, flag_type: str = "followup") -> str:
    """Markiert eine E-Mail aus den Suchergebnissen mit einem Flag.

    Args:
        query: Suchbegriff (Absender oder Betreff)
        index: Position in den Suchergebnissen (0 = erste/neueste)
        flag_type: Art des Flags - "followup" (Standard), "complete", oder "clear"
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)

        filter_str = (
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
        )

        messages = inbox.Items.Restrict(filter_str)
        messages.Sort("[ReceivedTime]", True)

        for i, msg in enumerate(messages):
            if i == index:
                subject = msg.Subject
                sender = msg.SenderName

                if flag_type.lower() == "clear":
                    msg.FlagStatus = 0
                    msg.Save()
                    return f"Flag entfernt: '{subject}' von {sender}"
                elif flag_type.lower() == "complete":
                    msg.FlagStatus = 1
                    msg.Save()
                    return f"Als erledigt markiert: '{subject}' von {sender}"
                else:  # followup
                    msg.FlagStatus = 2
                    msg.FlagRequest = "Follow up"
                    msg.Save()
                    return f"Follow-up Flag gesetzt: '{subject}' von {sender}"

        return f"Keine E-Mail an Position {index} gefunden für: '{query}'"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_list_mail_folders() -> str:
    """Listet alle verfügbaren E-Mail-Ordner auf."""
    folder_cache = get_folder_cache()

    # Return cached result if still valid
    if folder_cache["data"] and (time.time() - folder_cache["timestamp"]) < FOLDER_CACHE_TTL:
        return folder_cache["data"]

    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")

        def get_folders(folder, prefix="", depth=0):
            result = []
            if depth > 3:  # Limit recursion depth
                return result
            try:
                result.append(f"{prefix}{folder.Name}")
                for subfolder in folder.Folders:
                    result.extend(get_folders(subfolder, prefix + "  ", depth + 1))
            except Exception:
                pass
            return result

        all_folders = []
        for store in namespace.Folders:
            all_folders.extend(get_folders(store))

        result = "E-Mail-Ordner:\n" + "\n".join(all_folders)

        # Cache the result
        folder_cache["data"] = result
        folder_cache["timestamp"] = time.time()

        return result

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_move_selected_email(folder_name: str, mailbox: str = None) -> str:
    """Verschiebt die ausgewählte E-Mail in einen anderen Ordner.

    Args:
        folder_name: Name des Zielordners (z.B. "Archiv", "ToDelete", "ToOffer")
                     Ordner wird automatisch erstellt wenn nicht vorhanden.
        mailbox: Optional: Ziel-Mailbox für Cross-Mailbox-Move.
                 Standard: E-Mail bleibt in ihrer Mailbox.
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        mail = selection.Item(1)
        subject = mail.Subject

        # Default: Stay in same mailbox as the email (no cross-mailbox move)
        target_mailbox = mailbox if mailbox else _get_mail_store_name(mail)

        # Get or create target folder in the appropriate mailbox
        target_folder = _get_or_create_folder(namespace, folder_name, target_mailbox)

        if not target_folder:
            return f"Ordner '{folder_name}' konnte nicht gefunden oder erstellt werden."

        mail.Move(target_folder)
        return f"E-Mail verschoben: '{subject}' → {folder_name}"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_move_email(query: str, folder_name: str, index: int = 0, mailbox: str = None) -> str:
    """Verschiebt eine E-Mail aus den Suchergebnissen in einen anderen Ordner.

    Args:
        query: Suchbegriff (Absender oder Betreff)
        folder_name: Name des Zielordners (z.B. "Archiv", "ToDelete", "ToOffer")
                     Ordner wird automatisch erstellt wenn nicht vorhanden.
        index: Position in den Suchergebnissen (0 = erste/neueste)
        mailbox: Optional: Ziel-Mailbox für Cross-Mailbox-Move.
                 Standard: E-Mail bleibt in ihrer Mailbox.
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)

        # Find email first
        filter_str = (
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
        )

        messages = inbox.Items.Restrict(filter_str)
        messages.Sort("[ReceivedTime]", True)

        for i, msg in enumerate(messages):
            if i == index:
                subject = msg.Subject
                sender = msg.SenderName

                # Default: Stay in same mailbox as the email (no cross-mailbox move)
                target_mailbox = mailbox if mailbox else _get_mail_store_name(msg)

                # Get or create target folder in the appropriate mailbox
                target_folder = _get_or_create_folder(namespace, folder_name, target_mailbox)

                if not target_folder:
                    return f"Ordner '{folder_name}' konnte nicht gefunden oder erstellt werden."

                msg.Move(target_folder)
                return f"E-Mail verschoben: '{subject}' von {sender} → {folder_name}"

        return f"Keine E-Mail an Position {index} gefunden für: '{query}'"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_flagged_emails(limit: int = 20, include_completed: bool = True, dedupe_threads: bool = True) -> str:
    """Holt geflaggte und erledigte E-Mails aus ALLEN Ordnern.

    Iteriert durch alle Mailboxen und deren Ordner (robust, ohne AdvancedSearch).
    Gibt JSON zurück mit entry_id für batch_email_actions().

    Args:
        limit: Max. Anzahl E-Mails (Standard: 20)
        include_completed: Auch erledigte (flag_status=1) zurückgeben (Standard: True)
        dedupe_threads: Nur neueste E-Mail pro Thread anzeigen (Standard: True)

    Returns:
        JSON mit {"flagged": [...], "completed": [...]}
    """
    try:
        start_time = time.time()
        mcp_log(f"[Outlook] [get_flagged_emails] Starting folder iteration (limit={limit}, include_completed={include_completed})")

        namespace = get_namespace()

        # System folders to skip
        SKIP_FOLDERS = {
            "deleted items", "gelöschte elemente",
            "junk", "junk-e-mail", "spam",
            "sent", "sent items", "gesendete elemente", "gesendet",
            "drafts", "entwürfe",
            "outbox", "postausgang",
            "contacts", "kontakte",
            "calendar", "kalender",
            "tasks", "aufgaben",
            "notes", "notizen",
            "journal",
            "synchronisierungsprobleme", "sync issues",
            "rss-feeds", "rss feeds",
            "conversation history",
            "yammer root",
        }

        flagged_raw = []
        completed_raw = []
        seen_entry_ids = set()
        folders_checked = 0
        scan_limit = limit * 3  # Collect more than needed for deduplication

        def process_folder(folder, store_name: str):
            """Process a single folder for flagged emails."""
            nonlocal folders_checked

            folder_name = folder.Name.lower()

            # Skip system folders
            if folder_name in SKIP_FOLDERS:
                return

            # Skip folders starting with special chars
            if folder_name.startswith('{') or folder_name.startswith('_'):
                return

            folders_checked += 1

            try:
                items = folder.Items
                item_count = items.Count

                if item_count == 0:
                    return

                # Check recent items for flags (last 200 per folder max)
                check_count = min(item_count, 200)

                for i in range(1, check_count + 1):
                    if len(flagged_raw) >= scan_limit and len(completed_raw) >= scan_limit:
                        return  # We have enough

                    try:
                        msg = items.Item(i)

                        # Only process mail items
                        if msg.Class != 43:  # olMail = 43
                            continue

                        flag_status = getattr(msg, 'FlagStatus', 0)

                        # Skip unflagged (0 = olNoFlag)
                        if flag_status == 0:
                            continue

                        entry_id = msg.EntryID
                        if entry_id in seen_entry_ids:
                            continue
                        seen_entry_ids.add(entry_id)

                        # Get received time
                        try:
                            received = msg.ReceivedTime.strftime("%Y-%m-%dT%H:%M:%S")
                        except Exception:
                            received = ""

                        # Get conversation ID for deduplication
                        conversation_id = ""
                        try:
                            conversation_id = msg.ConversationID
                        except Exception:
                            pass

                        email_data = {
                            "entry_id": entry_id,
                            "subject": msg.Subject or "",
                            "sender": msg.SenderName or "",
                            "sender_email": getattr(msg, 'SenderEmailAddress', "") or "",
                            "received": received,
                            "mailbox": store_name,
                            "folder": folder.Name,
                            "flag_status": flag_status,
                            "conversation_id": conversation_id
                        }

                        if flag_status == 1:  # olFlagComplete
                            if include_completed and len(completed_raw) < scan_limit:
                                completed_raw.append(email_data)
                        elif flag_status == 2:  # olFlagMarked
                            if len(flagged_raw) < scan_limit:
                                flagged_raw.append(email_data)

                    except Exception:
                        continue

            except Exception as e:
                mcp_log(f"[Outlook] [get_flagged_emails] Error in folder {folder.Name}: {e}")

        def process_folders_recursive(folder, store_name: str, depth: int = 0):
            """Recursively process folder and subfolders."""
            if depth > 5:  # Limit recursion depth
                return

            process_folder(folder, store_name)

            try:
                for subfolder in folder.Folders:
                    if len(flagged_raw) >= scan_limit and len(completed_raw) >= scan_limit:
                        return
                    process_folders_recursive(subfolder, store_name, depth + 1)
            except Exception:
                pass

        # Iterate through all stores
        for store in namespace.Stores:
            if len(flagged_raw) >= scan_limit and len(completed_raw) >= scan_limit:
                break

            try:
                store_name = store.DisplayName
                root = store.GetRootFolder()

                # Process all folders in this store
                for folder in root.Folders:
                    if len(flagged_raw) >= scan_limit and len(completed_raw) >= scan_limit:
                        break
                    process_folders_recursive(folder, store_name)

            except Exception as e:
                mcp_log(f"[Outlook] [get_flagged_emails] Error in store {store.DisplayName}: {e}")
                continue

        total_time = time.time() - start_time
        mcp_log(f"[Outlook] [get_flagged_emails] Checked {folders_checked} folders in {total_time:.2f}s - found {len(flagged_raw)} flagged, {len(completed_raw)} completed")

        def dedupe_by_thread(emails):
            """Keep only the newest email per conversation thread."""
            if not dedupe_threads:
                return emails[:limit]

            threads = {}
            for email in sorted(emails, key=lambda x: x['received'], reverse=True):
                conv_id = email.get('conversation_id') or email['entry_id']
                if conv_id not in threads:
                    threads[conv_id] = email

            result = list(threads.values())
            result.sort(key=lambda x: x['received'], reverse=True)
            return result[:limit]

        flagged = dedupe_by_thread(flagged_raw)
        completed = dedupe_by_thread(completed_raw)

        return json.dumps({
            "flagged": flagged,
            "completed": completed
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[Outlook] [get_flagged_emails] Error: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
@outlook_tool
def outlook_get_folder_emails(folder_name: str, limit: int = 50, mailbox: str = None) -> str:
    """Holt ALLE E-Mails aus einem bestimmten Ordner.

    Für Arbeitsqueues wie ToOffer, ToPay, DoneInvoices.
    Gibt JSON zurück mit entry_id für batch_email_actions().

    Args:
        folder_name: Name des Ordners (z.B. "ToOffer", "ToPay")
        limit: Max. Anzahl E-Mails (Standard: 50)
        mailbox: Nur in dieser Mailbox suchen (optional)

    Returns:
        JSON-Array mit E-Mails
    """
    try:
        namespace = get_namespace()

        def find_folder_recursive(folder, name):
            if folder.Name.lower() == name.lower():
                return folder
            try:
                for subfolder in folder.Folders:
                    result = find_folder_recursive(subfolder, name)
                    if result:
                        return result
            except Exception:
                pass
            return None

        target_folder = None
        store_name = ""

        if mailbox:
            # Search only in specified mailbox
            for store in namespace.Folders:
                if store.Name.lower() == mailbox.lower():
                    target_folder = find_folder_recursive(store, folder_name)
                    store_name = store.Name
                    break
        else:
            # Search all mailboxes
            for store in namespace.Folders:
                target_folder = find_folder_recursive(store, folder_name)
                if target_folder:
                    store_name = store.Name
                    break

        if not target_folder:
            return json.dumps({"error": f"Ordner '{folder_name}' nicht gefunden"}, ensure_ascii=False)

        messages = target_folder.Items
        messages.Sort("[ReceivedTime]", True)

        emails = []
        count = 0

        for msg in messages:
            if count >= limit:
                break

            try:
                received = msg.ReceivedTime.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)

                # Body preview (300 chars)
                body = msg.Body or ""
                body_preview = body[:300].replace('\r\n', ' ').replace('\n', ' ').strip()

                emails.append({
                    "entry_id": msg.EntryID,
                    "subject": msg.Subject or "",
                    "sender": msg.SenderName or "",
                    "sender_email": msg.SenderEmailAddress or "",
                    "received": received,
                    "mailbox": store_name,
                    "folder": folder_name,
                    "flag_status": getattr(msg, 'FlagStatus', 0),
                    "has_attachments": msg.Attachments.Count > 0,
                    "body_preview": body_preview
                })
                count += 1

            except Exception:
                continue

        return json.dumps(emails, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# =============================================================================
# Category Functions
# =============================================================================

@mcp.tool()
@outlook_tool
def outlook_get_categories() -> str:
    """Listet alle verfügbaren Outlook-Kategorien auf.

    Returns:
        JSON mit Kategorien (Name, Farbe)
    """
    try:
        namespace = get_namespace()

        categories = []
        for cat in namespace.Categories:
            # Color mapping (Outlook OlCategoryColor enum)
            color_map = {
                0: "None", 1: "Red", 2: "Orange", 3: "Peach",
                4: "Yellow", 5: "Green", 6: "Teal", 7: "Olive",
                8: "Blue", 9: "Purple", 10: "Maroon", 11: "Steel",
                12: "DarkSteel", 13: "Gray", 14: "DarkGray", 15: "Black",
                16: "DarkRed", 17: "DarkOrange", 18: "DarkPeach",
                19: "DarkYellow", 20: "DarkGreen", 21: "DarkTeal",
                22: "DarkOlive", 23: "DarkBlue", 24: "DarkPurple", 25: "DarkMaroon"
            }
            color = color_map.get(cat.Color, "Unknown")

            categories.append({
                "name": cat.Name,
                "color": color,
                "color_id": cat.Color
            })

        return json.dumps({
            "categories": categories,
            "count": len(categories)
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
@outlook_tool
def outlook_set_selected_email_category(category: str, selection_index: int = None) -> str:
    """Setzt eine Kategorie für die ausgewählte E-Mail.

    Args:
        category: Name der Kategorie (z.B. "DeskAgent", "Wichtig")
        selection_index: Bei Mehrfachauswahl: welche E-Mail (1-basiert, None = alle)

    Returns:
        Bestätigung oder Fehler
    """
    try:
        outlook = get_outlook()
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        # Bestimme welche E-Mails bearbeitet werden
        if selection_index is not None:
            if selection_index < 1 or selection_index > selection.Count:
                return f"Fehler: Index {selection_index} ungültig (1-{selection.Count})"
            indices = [selection_index]
        else:
            indices = list(range(1, selection.Count + 1))

        results = []
        for idx in indices:
            mail = selection.Item(idx)
            subject = mail.Subject

            # Kategorien sind komma-getrennt - bestehende behalten, neue hinzufügen
            existing = mail.Categories or ""
            existing_list = [c.strip() for c in existing.split(",") if c.strip()]

            if category not in existing_list:
                existing_list.append(category)
                mail.Categories = ", ".join(existing_list)
                mail.Save()
                results.append(f"Kategorie '{category}' gesetzt: '{subject}'")
            else:
                results.append(f"Kategorie '{category}' bereits vorhanden: '{subject}'")

        if len(results) == 1:
            return results[0]
        return f"{len(results)} E-Mails bearbeitet:\n" + "\n".join(results)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_clear_selected_email_category(category: str = None, selection_index: int = None) -> str:
    """Entfernt eine Kategorie von der ausgewählten E-Mail.

    Args:
        category: Name der Kategorie (None = alle Kategorien entfernen)
        selection_index: Bei Mehrfachauswahl: welche E-Mail (1-basiert, None = alle)

    Returns:
        Bestätigung oder Fehler
    """
    try:
        outlook = get_outlook()
        explorer = outlook.ActiveExplorer()

        if not explorer:
            return "Fehler: Kein Outlook-Fenster aktiv"

        selection = explorer.Selection
        if selection.Count == 0:
            return "Fehler: Keine E-Mail ausgewählt"

        if selection_index is not None:
            if selection_index < 1 or selection_index > selection.Count:
                return f"Fehler: Index {selection_index} ungültig (1-{selection.Count})"
            indices = [selection_index]
        else:
            indices = list(range(1, selection.Count + 1))

        results = []
        for idx in indices:
            mail = selection.Item(idx)
            subject = mail.Subject

            if category is None:
                # Alle Kategorien entfernen
                mail.Categories = ""
                mail.Save()
                results.append(f"Alle Kategorien entfernt: '{subject}'")
            else:
                # Nur bestimmte Kategorie entfernen
                existing = mail.Categories or ""
                existing_list = [c.strip() for c in existing.split(",") if c.strip()]

                if category in existing_list:
                    existing_list.remove(category)
                    mail.Categories = ", ".join(existing_list)
                    mail.Save()
                    results.append(f"Kategorie '{category}' entfernt: '{subject}'")
                else:
                    results.append(f"Kategorie '{category}' nicht vorhanden: '{subject}'")

        if len(results) == 1:
            return results[0]
        return f"{len(results)} E-Mails bearbeitet:\n" + "\n".join(results)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_emails_by_category(category: str, limit: int = 50, mailbox: str = None) -> str:
    """Holt E-Mails mit einer bestimmten Kategorie aus ALLEN Ordnern.

    Verwendet AdvancedSearch für schnelle Suche.

    Args:
        category: Name der Kategorie (z.B. "DeskAgent")
        limit: Max. Anzahl E-Mails (Standard: 50)
        mailbox: Nur in dieser Mailbox suchen (optional)

    Returns:
        JSON-Array mit E-Mails
    """
    try:
        start_time = time.time()
        mcp_log(f"[Outlook] [get_emails_by_category] Searching for category '{category}'")

        outlook = get_outlook()
        namespace = get_namespace()

        # Build scope
        scopes = []
        for store in namespace.Stores:
            try:
                if mailbox and store.DisplayName.lower() != mailbox.lower():
                    continue
                inbox = store.GetDefaultFolder(6)
                scopes.append(f"'{inbox.FolderPath}'")
            except Exception:
                continue

        if not scopes:
            return json.dumps({"error": "No mailboxes found"}, ensure_ascii=False)

        scope = ",".join(scopes)

        # DASL filter for category
        # Categories property: http://schemas.microsoft.com/mapi/string/{00020329-0000-0000-C000-000000000046}/Keywords
        filter_dasl = f'"urn:schemas-microsoft-com:office:office#Keywords" LIKE \'%{category}%\''

        search_tag = f"CategorySearch_{int(time.time())}"
        search = outlook.AdvancedSearch(scope, filter_dasl, True, search_tag)

        # Wait for completion
        timeout = 30
        wait_start = time.time()
        search_done = False
        while not search_done:
            try:
                search_done = search.IsDone
            except AttributeError:
                time.sleep(0.3)
                try:
                    _ = search.Results.Count
                    search_done = True
                except Exception:
                    if time.time() - wait_start > 2:
                        search_done = True
                    else:
                        time.sleep(0.1)
                        continue

            if not search_done:
                pythoncom.PumpWaitingMessages()
                time.sleep(0.05)

            if time.time() - wait_start > timeout:
                break

        results = search.Results
        result_count = results.Count
        mcp_log(f"[Outlook] [get_emails_by_category] Found {result_count} items in {time.time() - start_time:.2f}s")

        emails = []
        for i in range(1, min(result_count + 1, limit + 1)):
            try:
                msg = results.Item(i)

                # Get folder info
                try:
                    parent = msg.Parent
                    folder_name = parent.Name
                    folder_path = parent.FolderPath
                    store_name = folder_path.split("\\")[1] if "\\" in folder_path else "Unknown"
                except Exception:
                    folder_name = "Unknown"
                    store_name = "Unknown"

                received = msg.ReceivedTime.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)

                emails.append({
                    "entry_id": msg.EntryID,
                    "subject": msg.Subject or "",
                    "sender": msg.SenderName or "",
                    "sender_email": msg.SenderEmailAddress or "",
                    "received": received,
                    "mailbox": store_name,
                    "folder": folder_name,
                    "categories": msg.Categories or "",
                    "has_attachments": msg.Attachments.Count > 0
                })

            except Exception:
                continue

        try:
            search.Stop()
        except Exception:
            pass

        return json.dumps({
            "category": category,
            "count": len(emails),
            "emails": emails
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        mcp_log(f"[Outlook] [get_emails_by_category] Error: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# =============================================================================
# Batch Operations
# =============================================================================

@mcp.tool()
@outlook_tool
def outlook_batch_email_actions(actions: str) -> str:
    """Führt mehrere E-Mail-Aktionen in einem Aufruf aus.

    Effizienter als einzelne Aufrufe - nutzt EntryID für direkten Zugriff.

    Args:
        actions: JSON-Array mit Aktionen:
            [
                {"action": "move", "entry_id": "...", "folder": "ToDelete"},
                {"action": "move", "entry_id": "...", "folder": "Invoices", "mailbox": "info@..."},
                {"action": "flag", "entry_id": "...", "flag_type": "followup"}
            ]

    Returns:
        JSON mit Ergebnis:
        {
            "success": 8,
            "failed": 0,
            "results": [
                {"entry_id": "AAA...", "status": "ok", "action": "moved to ToDelete"},
                ...
            ]
        }
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")

        action_list = json.loads(actions)

        results = []
        success = 0
        failed = 0

        # Cache für Ordner (einmal suchen/erstellen, mehrfach verwenden)
        folder_cache = {}

        def get_folder(name, mailbox=None):
            """Get or create folder by name, optionally in specific mailbox."""
            cache_key = f"{mailbox or 'any'}:{name}"
            if cache_key in folder_cache:
                return folder_cache[cache_key]

            # Use shared helper function (auto-creates if missing)
            folder = _get_or_create_folder(namespace, name, mailbox)
            if folder:
                folder_cache[cache_key] = folder
            return folder

        for action in action_list:
            entry_id = action.get("entry_id")
            action_type = action.get("action")

            if not entry_id:
                results.append({"entry_id": entry_id, "status": "error", "error": "Missing entry_id"})
                failed += 1
                continue

            try:
                # E-Mail per EntryID holen (schneller als Query)
                msg = namespace.GetItemFromID(entry_id)
                subject = msg.Subject[:50] if msg.Subject else ""

                if action_type == "move":
                    folder_name = action.get("folder")
                    explicit_mailbox = action.get("mailbox")  # Optional: explicit target mailbox for cross-mailbox move

                    # Default: Stay in same mailbox as the email (no cross-mailbox move)
                    if explicit_mailbox:
                        target_mailbox = explicit_mailbox
                    else:
                        target_mailbox = _get_mail_store_name(msg)

                    folder = get_folder(folder_name, target_mailbox)
                    if folder:
                        msg.Move(folder)
                        target_desc = f"{folder_name}" + (f" ({explicit_mailbox})" if explicit_mailbox else "")
                        results.append({
                            "entry_id": entry_id,
                            "status": "ok",
                            "action": f"moved to {target_desc}",
                            "subject": subject
                        })
                        success += 1
                    else:
                        error_msg = f"Folder '{folder_name}'" + (f" in mailbox '{target_mailbox}'" if target_mailbox else "") + " could not be found or created"
                        results.append({
                            "entry_id": entry_id,
                            "status": "error",
                            "error": error_msg
                        })
                        failed += 1

                elif action_type == "flag":
                    flag_type = action.get("flag_type", "followup")
                    flag_map = {"clear": 0, "complete": 1, "followup": 2}
                    msg.FlagStatus = flag_map.get(flag_type, 2)
                    if flag_type == "followup":
                        msg.FlagRequest = "Follow up"
                    msg.Save()
                    results.append({
                        "entry_id": entry_id,
                        "status": "ok",
                        "action": f"flagged as {flag_type}",
                        "subject": subject
                    })
                    success += 1

                elif action_type == "delete":
                    results.append({"entry_id": entry_id, "status": "error", "error": "delete not supported in batch - use outlook_delete_email instead"})
                    failed += 1
                    continue

                else:
                    results.append({
                        "entry_id": entry_id,
                        "status": "error",
                        "error": f"Unknown action: {action_type}"
                    })
                    failed += 1

            except Exception as e:
                results.append({
                    "entry_id": entry_id,
                    "status": "error",
                    "error": str(e)
                })
                failed += 1

        return json.dumps({
            "success": success,
            "failed": failed,
            "total": len(action_list),
            "results": results
        }, ensure_ascii=False, indent=2)

    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {str(e)}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
