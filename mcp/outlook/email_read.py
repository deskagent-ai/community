# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Outlook MCP - Email Read Module
==============================
Functions for reading and searching emails.
"""

import json
import time
from datetime import datetime, timedelta

import pythoncom

from outlook.base import (
    mcp, outlook_tool, mcp_log,
    get_outlook, get_namespace, get_inbox,
    get_mail_location, EmailFinder,
    windows_search_query
)


@mcp.tool()
@outlook_tool
def outlook_get_selected_email() -> str:
    """Liest die aktuell in Outlook markierte E-Mail."""
    finder = EmailFinder()
    mail, error = finder.get_selected()
    if error:
        return error

    mailbox, folder = get_mail_location(mail)

    return f"""Postfach: {mailbox}
Ordner: {folder}
Von: {mail.SenderName} <{mail.SenderEmailAddress}>
Betreff: {mail.Subject}
Datum: {mail.ReceivedTime}

{mail.Body}"""


@mcp.tool()
@outlook_tool
def outlook_get_selected_emails() -> str:
    """Liest ALLE aktuell in Outlook markierten E-Mails (Mehrfachauswahl).

    Returns:
        JSON-Array mit allen markierten E-Mails, jede mit:
        - index: Position (1-basiert)
        - mailbox: Postfach-Name
        - folder: Ordner-Name
        - sender_name: Absender-Name
        - sender_email: Absender-E-Mail
        - subject: Betreff
        - received: Empfangsdatum
        - body: E-Mail-Text (gekürzt auf 2000 Zeichen)
        - has_attachments: True wenn Anhänge vorhanden
        - attachment_count: Anzahl der Anhänge
    """
    finder = EmailFinder()
    mails, error = finder.get_all_selected()
    if error:
        return json.dumps({"error": error}, ensure_ascii=False)

    emails = []
    for i, mail in enumerate(mails, 1):
        mailbox, folder = get_mail_location(mail)

        # Body kürzen für Performance
        body = mail.Body[:2000] if len(mail.Body) > 2000 else mail.Body

        emails.append({
            "index": i,
            "mailbox": mailbox,
            "folder": folder,
            "sender_name": mail.SenderName,
            "sender_email": mail.SenderEmailAddress,
            "subject": mail.Subject,
            "received": str(mail.ReceivedTime),
            "body": body,
            "has_attachments": mail.Attachments.Count > 0,
            "attachment_count": mail.Attachments.Count
        })

    return json.dumps({
        "count": len(emails),
        "emails": emails
    }, ensure_ascii=False, indent=2)


@mcp.tool()
@outlook_tool
def outlook_delete_selected_email() -> str:
    """Löscht die aktuell in Outlook markierte E-Mail (verschiebt in Gelöschte Elemente)."""
    finder = EmailFinder()
    mail, error = finder.get_selected()
    if error:
        return error

    subject = mail.Subject
    sender = mail.SenderName

    # Delete moves to Deleted Items folder
    mail.Delete()

    return f"E-Mail gelöscht: '{subject}' von {sender}"


@mcp.tool()
@outlook_tool
def outlook_delete_email(query: str, index: int = 0) -> str:
    """Löscht eine E-Mail aus den Suchergebnissen (verschiebt in Gelöschte Elemente).

    Args:
        query: Suchbegriff (Absender oder Betreff)
        index: Position in den Suchergebnissen (0 = erste/neueste)
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
                received = msg.ReceivedTime.strftime("%d.%m.%Y") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)

                # Delete moves to Deleted Items folder
                msg.Delete()

                return f"E-Mail gelöscht: '{subject}' von {sender} ({received})"

        return f"Keine E-Mail an Position {index} gefunden für: '{query}'"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_delete_emails_from_sender(sender: str, mailbox: str = None, dry_run: bool = True) -> str:
    """Löscht ALLE E-Mails von einem bestimmten Absender (schnelle Index-Suche).

    Verwendet AdvancedSearch für schnelle Suche über alle Ordner.
    ACHTUNG: Kann viele E-Mails auf einmal löschen!

    Args:
        sender: Absender-Name oder E-Mail-Adresse (Teilmatch)
        mailbox: Nur in dieser Mailbox suchen (optional, z.B. "info@example.com")
        dry_run: True = nur zählen ohne zu löschen (Standard: True für Sicherheit)

    Returns:
        Anzahl gelöschter/gefundener E-Mails
    """
    try:
        start_time = time.time()
        mcp_log(f"[Outlook] [delete_from_sender] Searching for sender: {sender} (dry_run={dry_run})")

        outlook = get_outlook()
        namespace = get_namespace()

        # DASL filter for sender - use fromemail which contains the email address
        # AdvancedSearch doesn't support OR operator, so we search fromemail only
        # Property name MUST be in double quotes for AdvancedSearch
        sender_escaped = sender.replace("'", "''")
        filter_dasl = f"\"urn:schemas:httpmail:fromemail\" LIKE '%{sender_escaped}%'"
        mcp_log(f"[Outlook] [delete_from_sender] Filter: {filter_dasl}")

        # Collect info and optionally delete
        deleted_count = 0
        sample_subjects = []
        total_found = 0
        searched_stores = set()

        # Search each store separately (AdvancedSearch doesn't support multiple stores)
        for store in namespace.Stores:
            try:
                store_name = store.DisplayName
                if mailbox and mailbox.lower() not in store_name.lower():
                    continue

                # Get root folder for full store search
                root_folder = store.GetRootFolder()
                store_path = root_folder.FolderPath

                # Skip duplicate stores
                if store_path in searched_stores:
                    continue
                searched_stores.add(store_path)

                scope = f"'{store_path}'"
                mcp_log(f"[Outlook] [delete_from_sender] Searching store: {scope}")

                # Start AdvancedSearch for this store
                search_tag = f"DeleteSender_{int(time.time())}_{store_name[:10]}"
                try:
                    search = outlook.AdvancedSearch(scope, filter_dasl, True, search_tag)
                except Exception as e:
                    mcp_log(f"[Outlook] [delete_from_sender] AdvancedSearch failed for {store_name}: {e}")
                    continue

                # Wait for search to complete (with IsDone fallback)
                store_timeout = 30  # Timeout per store
                wait_start = time.time()
                search_done = False
                while not search_done:
                    try:
                        search_done = search.IsDone
                    except AttributeError:
                        # IsDone not available - try accessing Results as fallback
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

                    if time.time() - wait_start > store_timeout:
                        mcp_log(f"[Outlook] [delete_from_sender] Search timeout for {store_name}")
                        break

                results = search.Results
                store_count = results.Count
                total_found += store_count
                mcp_log(f"[Outlook] [delete_from_sender] Found {store_count} in {store_name}")

                # Process results from this store
                for i in range(1, store_count + 1):
                    try:
                        msg = results.Item(i)
                        subject = msg.Subject or "(Kein Betreff)"
                        msg_sender = msg.SenderName or ""

                        # Collect samples for preview
                        if len(sample_subjects) < 5:
                            sample_subjects.append(f"  - {msg_sender}: {subject[:50]}")

                        if not dry_run:
                            msg.Delete()
                            deleted_count += 1
                        else:
                            deleted_count += 1  # Count for dry run

                    except Exception as e:
                        mcp_log(f"[Outlook] [delete_from_sender] Error processing email: {e}")
                        continue

                # Stop search for this store
                try:
                    search.Stop()
                except Exception:
                    pass

            except Exception as e:
                mcp_log(f"[Outlook] [delete_from_sender] Store error {store_name}: {e}")
                continue

        if not searched_stores:
            return f"Keine passende Mailbox gefunden für: {mailbox}" if mailbox else "Keine Mailbox gefunden"

        if total_found == 0:
            return f"Keine E-Mails von '{sender}' gefunden"

        total_time = time.time() - start_time

        if dry_run:
            preview = "\n".join(sample_subjects)
            if total_found > 5:
                preview += f"\n  ... und {total_found - 5} weitere"
            return f"DRY RUN: {total_found} E-Mails von '{sender}' gefunden ({total_time:.1f}s)\n\nBeispiele:\n{preview}\n\nZum Löschen: dry_run=False setzen"
        else:
            return f"GELÖSCHT: {deleted_count} E-Mails von '{sender}' ({total_time:.1f}s)"

    except Exception as e:
        mcp_log(f"[Outlook] [delete_from_sender] Error: {e}")
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_move_emails_from_sender(sender: str, target_folder: str, mailbox: str = None, dry_run: bool = True) -> str:
    """Verschiebt ALLE E-Mails von einem bestimmten Absender in einen Ordner (schnelle Index-Suche).

    Verwendet AdvancedSearch für schnelle Suche über alle Ordner.
    ACHTUNG: Kann viele E-Mails auf einmal verschieben!

    Args:
        sender: Absender-Name oder E-Mail-Adresse (Teilmatch)
        target_folder: Ziel-Ordner (z.B. "ToDelete", "Newsletter", "Archive")
        mailbox: Nur in dieser Mailbox suchen/verschieben (optional)
        dry_run: True = nur zählen ohne zu verschieben (Standard: True für Sicherheit)

    Returns:
        Anzahl verschobener/gefundener E-Mails
    """
    try:
        start_time = time.time()
        mcp_log(f"[Outlook] [move_from_sender] Searching for sender: {sender} -> {target_folder} (dry_run={dry_run})")

        outlook = get_outlook()
        namespace = get_namespace()

        # Find target folder first
        target = None
        target_mailbox = None

        for store in namespace.Stores:
            try:
                store_name = store.DisplayName
                if mailbox and mailbox.lower() not in store_name.lower():
                    continue

                # Search for target folder in this store
                def find_folder_recursive(folder, name, depth=0):
                    if depth > 5:
                        return None
                    try:
                        if folder.Name.lower() == name.lower():
                            return folder
                        for subfolder in folder.Folders:
                            result = find_folder_recursive(subfolder, name, depth + 1)
                            if result:
                                return result
                    except Exception:
                        pass
                    return None

                root = store.GetRootFolder()
                found = find_folder_recursive(root, target_folder)
                if found:
                    target = found
                    target_mailbox = store_name
                    break
            except Exception:
                continue

        if not target:
            return f"Ziel-Ordner '{target_folder}' nicht gefunden" + (f" in Mailbox '{mailbox}'" if mailbox else "")

        # DASL filter for sender - use fromemail which contains the email address
        # AdvancedSearch doesn't support OR operator, so we search fromemail only
        # Property name MUST be in double quotes for AdvancedSearch
        sender_escaped = sender.replace("'", "''")
        filter_dasl = f"\"urn:schemas:httpmail:fromemail\" LIKE '%{sender_escaped}%'"
        mcp_log(f"[Outlook] [move_from_sender] Filter: {filter_dasl}")

        # Collect and optionally move
        moved_count = 0
        sample_subjects = []
        errors = []
        total_found = 0
        searched_stores = set()

        # Search each store separately (AdvancedSearch doesn't support multiple stores)
        for store in namespace.Stores:
            try:
                store_name = store.DisplayName
                if mailbox and mailbox.lower() not in store_name.lower():
                    continue

                # Get root folder for full store search
                root_folder = store.GetRootFolder()
                store_path = root_folder.FolderPath

                # Skip duplicate stores
                if store_path in searched_stores:
                    continue
                searched_stores.add(store_path)

                scope = f"'{store_path}'"
                mcp_log(f"[Outlook] [move_from_sender] Searching store: {scope}")

                # Start AdvancedSearch for this store
                search_tag = f"MoveSender_{int(time.time())}_{store_name[:10]}"
                try:
                    search = outlook.AdvancedSearch(scope, filter_dasl, True, search_tag)
                except Exception as e:
                    mcp_log(f"[Outlook] [move_from_sender] AdvancedSearch failed for {store_name}: {e}")
                    continue

                # Wait for search to complete (with IsDone fallback)
                store_timeout = 30  # Timeout per store
                wait_start = time.time()
                search_done = False
                while not search_done:
                    try:
                        search_done = search.IsDone
                    except AttributeError:
                        # IsDone not available - try accessing Results as fallback
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

                    if time.time() - wait_start > store_timeout:
                        mcp_log(f"[Outlook] [move_from_sender] Search timeout for {store_name}")
                        break

                results = search.Results
                store_count = results.Count
                total_found += store_count
                mcp_log(f"[Outlook] [move_from_sender] Found {store_count} in {store_name}")

                # Process results from this store
                for i in range(1, store_count + 1):
                    try:
                        msg = results.Item(i)
                        subject = msg.Subject or "(Kein Betreff)"
                        msg_sender = msg.SenderName or ""

                        # Skip if already in target folder
                        try:
                            if msg.Parent.Name.lower() == target_folder.lower():
                                continue
                        except Exception:
                            pass

                        # Collect samples
                        if len(sample_subjects) < 5:
                            sample_subjects.append(f"  - {msg_sender}: {subject[:50]}")

                        if not dry_run:
                            msg.Move(target)
                            moved_count += 1
                        else:
                            moved_count += 1

                    except Exception as e:
                        errors.append(str(e))
                        continue

                # Stop search for this store
                try:
                    search.Stop()
                except Exception:
                    pass

            except Exception as e:
                mcp_log(f"[Outlook] [move_from_sender] Store error {store_name}: {e}")
                continue

        if not searched_stores:
            return f"Keine passende Mailbox gefunden für: {mailbox}" if mailbox else "Keine Mailbox gefunden"

        if total_found == 0:
            return f"Keine E-Mails von '{sender}' gefunden"

        total_time = time.time() - start_time

        if dry_run:
            preview = "\n".join(sample_subjects)
            if total_found > 5:
                preview += f"\n  ... und {total_found - 5} weitere"
            return f"DRY RUN: {moved_count} E-Mails von '{sender}' würden nach '{target_folder}' verschoben ({total_time:.1f}s)\n\nBeispiele:\n{preview}\n\nZum Verschieben: dry_run=False setzen"
        else:
            result_msg = f"VERSCHOBEN: {moved_count} E-Mails von '{sender}' nach '{target_folder}' ({total_time:.1f}s)"
            if errors:
                result_msg += f"\n\n{len(errors)} Fehler aufgetreten"
            return result_msg

    except Exception as e:
        mcp_log(f"[Outlook] [move_from_sender] Error: {e}")
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_unread_emails(limit: int = 5) -> str:
    """Listet ungelesene E-Mails aus dem Posteingang."""
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)

        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)

        result = []
        count = 0

        for msg in messages:
            if not msg.UnRead:
                continue
            received = msg.ReceivedTime.strftime("%d.%m.%Y %H:%M") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)
            mailbox, folder = get_mail_location(msg)
            # Flag status: 0=None, 1=Complete, 2=Followup
            flag_status = getattr(msg, 'FlagStatus', 0)
            flag_icon = {0: "", 1: "[✓]", 2: "[🚩]"}.get(flag_status, "")
            result.append(f"- [{received}] [{mailbox}/{folder}] {flag_icon} {msg.SenderName}: {msg.Subject}")
            count += 1
            if count >= limit:
                break

        if not result:
            return "Keine ungelesenen E-Mails"

        return f"Ungelesene E-Mails ({count}):\n" + "\n".join(result)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_unread_emails_json(limit: int = 20) -> str:
    """Gibt ungelesene E-Mails als JSON zurück (für Watcher/Automatisierung).

    Enthält EntryID für zuverlässige Deduplizierung.

    Args:
        limit: Max. Anzahl E-Mails (Standard: 20)

    Returns:
        JSON-Array mit E-Mail-Objekten oder Fehler-JSON
    """
    try:
        outlook = get_outlook()
        namespace = outlook.GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)

        messages = inbox.Items
        messages.Sort("[ReceivedTime]", True)

        emails = []
        count = 0

        for msg in messages:
            if not msg.UnRead:
                continue

            try:
                received = msg.ReceivedTime.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)
                mailbox, folder = get_mail_location(msg)

                # Flag status: 0=None, 1=Complete, 2=Followup
                flag_status = getattr(msg, 'FlagStatus', 0)

                email_data = {
                    "entry_id": msg.EntryID,
                    "subject": msg.Subject or "",
                    "from": msg.SenderName or "",
                    "from_email": msg.SenderEmailAddress or "",
                    "received": received,
                    "mailbox": mailbox,
                    "folder": folder,
                    "flag_status": flag_status,  # 0=None, 1=Complete, 2=Followup
                    "preview": (msg.Body or "")[:200]
                }
                emails.append(email_data)
                count += 1

                if count >= limit:
                    break
            except Exception:
                # Skip problematic messages
                continue

        return json.dumps(emails, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
@outlook_tool
def outlook_search_emails(query: str, limit: int = 50, mailbox: str = None) -> str:
    """Sucht E-Mails nach Absender oder Betreff.

    Args:
        query: Suchbegriff
        limit: Max. Anzahl Ergebnisse (Standard: 50)
        mailbox: Mailbox durchsuchen (z.B. "info@example.com"). None = Standard-Postfach.
    """
    try:
        inbox = get_inbox(mailbox)

        filter_str = (
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
        )

        messages = inbox.Items.Restrict(filter_str)
        messages.Sort("[ReceivedTime]", True)

        result = []
        for i, msg in enumerate(messages):
            if i >= limit:
                break
            received = msg.ReceivedTime.strftime("%d.%m") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)[:5]
            _, folder = get_mail_location(msg)
            result.append(f"- [{received}] [{folder}] {msg.SenderName}: {msg.Subject}")

        if not result:
            return f"Keine E-Mails gefunden für: '{query}'"

        return f"Suchergebnisse für '{query}' ({len(result)}):\n" + "\n".join(result)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_fast_search_emails(query: str, limit: int = 50, search_body: bool = True, timeout: int = 30, mailbox: str = None, all_mailboxes: bool = False) -> str:
    """Schnelle E-Mail-Suche mit Windows Search Index (wie Outlook UI).

    Durchsucht ALLE indizierten Inhalte inkl. Anhänge - genau wie die Outlook Suchleiste.
    Nutzt Windows Search Service für schnellste Suche.

    Args:
        query: Suchbegriff
        limit: Max. Anzahl Ergebnisse (Standard: 50)
        search_body: Ignoriert (Windows Search durchsucht immer alles)
        timeout: Max. Wartezeit in Sekunden (Standard: 30)
        mailbox: Ignoriert (Windows Search durchsucht alle Mailboxen)
        all_mailboxes: Ignoriert (Windows Search durchsucht immer alle)
    """
    # Try Windows Search first (fastest, searches everything including attachments)
    try:
        results = windows_search_query(query, limit)
        if results:
            formatted = []
            for r in results:
                try:
                    date_str = r["date"].strftime("%d.%m") if r["date"] else "?"
                except (AttributeError, ValueError, KeyError):
                    date_str = "?"
                # Extract mailbox/folder from path (format: /mailbox@email.com/Inbox/Subject)
                path_parts = r.get("path", "").strip("/").split("/")
                if len(path_parts) >= 2:
                    mailbox = path_parts[0]
                    folder = path_parts[1] if len(path_parts) > 1 else "?"
                    formatted.append(f"- [{date_str}] [{mailbox}/{folder}] {r['from']}: {r['subject']}")
                else:
                    formatted.append(f"- [{date_str}] {r['from']}: {r['subject']}")

            return f"Suchergebnisse für '{query}' ({len(results)}, via Windows Search):\n" + "\n".join(formatted)
    except Exception as e:
        mcp_log(f"[Outlook] [Windows Search] Failed: {e}, falling back to Outlook API")

    # Fallback to Outlook COM API
    try:
        outlook = get_outlook()
        namespace = get_namespace()

        # Escape single quotes in query
        safe_query = query.replace("'", "''")

        # Check if Instant Search is enabled on default store
        try:
            instant_search_enabled = namespace.DefaultStore.IsInstantSearchEnabled
        except Exception:
            instant_search_enabled = False

        mcp_log(f"[Outlook] [Search] IsInstantSearchEnabled: {instant_search_enabled}")

        # Build DASL filter for AdvancedSearch (NO @SQL= prefix - that's for Restrict only)
        if instant_search_enabled:
            # Use fulltextqueryinfo:any to search ALL indexed content (like Outlook UI)
            # This includes email body AND attachment content
            filter_str = f"\"urn:schemas-microsoft-com:fulltextqueryinfo:any\" ci_phrasematch '{safe_query}'"
        else:
            # Fallback to subject-only search
            filter_str = f"\"urn:schemas:httpmail:subject\" LIKE '%{safe_query}%'"

        mcp_log(f"[Outlook] [Search] Filter: {filter_str}")

        def run_advanced_search(scope_str, timeout_sec):
            """Run AdvancedSearch on a single scope and return results."""
            search_tag = f"FastSearch_{int(time.time())}_{hash(scope_str) % 10000}"
            try:
                search = outlook.AdvancedSearch(scope_str, filter_str, True, search_tag)

                start_time = time.time()
                search_done = False
                while not search_done:
                    if time.time() - start_time > timeout_sec:
                        try:
                            search.Stop()
                        except Exception:
                            pass
                        return None  # Timeout

                    try:
                        search_done = search.IsDone
                    except AttributeError:
                        time.sleep(0.5)
                        try:
                            _ = search.Results.Count
                            search_done = True
                        except Exception:
                            if time.time() - start_time > 2:
                                search_done = True
                            else:
                                time.sleep(0.1)

                    if not search_done:
                        time.sleep(0.1)

                return search.Results
            except Exception as e:
                mcp_log(f"[Outlook] [Search] AdvancedSearch failed for {scope_str}: {e}")
                return None

        result_list = []

        try:
            if all_mailboxes:
                # Search each mailbox separately (AdvancedSearch doesn't support multiple stores)
                searched_stores = set()
                per_store_timeout = max(5, timeout // 5)  # Divide timeout among stores

                for store in namespace.Stores:
                    if len(result_list) >= limit:
                        break
                    try:
                        root_folder = store.GetRootFolder()
                        store_path = root_folder.FolderPath
                        if store_path in searched_stores:
                            continue
                        searched_stores.add(store_path)

                        scope = f"'{store_path}'"
                        mcp_log(f"[Outlook] [Search] Searching: {scope}")

                        results = run_advanced_search(scope, per_store_timeout)
                        if results:
                            for i in range(min(results.Count, limit - len(result_list))):
                                msg = results.Item(i + 1)
                                try:
                                    received = msg.ReceivedTime.strftime("%d.%m") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)[:5]
                                    mailbox_name, folder = get_mail_location(msg)
                                    result_list.append(f"- [{received}] [{mailbox_name}/{folder}] {msg.SenderName}: {msg.Subject}")
                                except Exception:
                                    continue
                    except Exception as e:
                        mcp_log(f"[Outlook] [Search] Store error: {e}")
                        continue

                if not result_list:
                    # Fall through to recursive fallback
                    raise Exception("No results from AdvancedSearch on any store")

                return f"Suchergebnisse für '{query}' ({len(result_list)}, via Index, alle Postfächer):\n" + "\n".join(result_list)

            else:
                # Single mailbox search
                inbox = get_inbox(mailbox)
                try:
                    store = inbox.Store
                    root_folder = store.GetRootFolder()
                    scope = f"'{root_folder.FolderPath}'"
                except Exception:
                    scope = f"'{inbox.FolderPath}'"

                mcp_log(f"[Outlook] [Search] Scope: {scope}")
                results = run_advanced_search(scope, timeout)

                if results and results.Count > 0:
                    for i in range(min(results.Count, limit)):
                        msg = results.Item(i + 1)
                        try:
                            received = msg.ReceivedTime.strftime("%d.%m") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)[:5]
                            _, folder = get_mail_location(msg)
                            result_list.append(f"- [{received}] [{folder}] {msg.SenderName}: {msg.Subject}")
                        except Exception:
                            continue

                    if result_list:
                        return f"Suchergebnisse für '{query}' ({len(result_list)}, via Index):\n" + "\n".join(result_list)

                # Fall through to recursive fallback
                raise Exception("No results from AdvancedSearch")

        except Exception as adv_error:
            # Fallback to recursive folder search if AdvancedSearch fails
            mcp_log(f"[Outlook] [Search] AdvancedSearch failed: {adv_error}, using fallback")

            folders_searched = [0]  # Use list to allow mutation in nested function

            def search_folder_recursive(folder, query, results, limit, search_body=False):
                """Recursively search a folder and its subfolders."""
                if len(results) >= limit:
                    return
                folders_searched[0] += 1
                try:
                    # Build filter - search body requires different approach
                    if search_body:
                        # Body search with LIKE - include both text and HTML body
                        filter_str = (
                            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
                            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%' "
                            f"OR \"urn:schemas:httpmail:textdescription\" LIKE '%{query}%' "
                            f"OR \"urn:schemas:httpmail:htmldescription\" LIKE '%{query}%'"
                        )
                    else:
                        filter_str = (
                            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
                            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
                        )

                    messages = folder.Items.Restrict(filter_str)
                    msg_count = messages.Count
                    if msg_count > 0:
                        mcp_log(f"[Outlook] [Fallback] Found {msg_count} in {folder.FolderPath}")
                    for msg in messages:
                        if len(results) >= limit:
                            break
                        try:
                            received = msg.ReceivedTime.strftime("%d.%m") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)[:5]
                            mailbox_name, folder_name = get_mail_location(msg)
                            results.append({
                                "received": received,
                                "mailbox": mailbox_name,
                                "folder": folder_name,
                                "sender": msg.SenderName,
                                "subject": msg.Subject
                            })
                        except Exception:
                            continue

                    # Search subfolders
                    for subfolder in folder.Folders:
                        if len(results) >= limit:
                            break
                        search_folder_recursive(subfolder, query, results, limit, search_body)
                except Exception:
                    pass  # Skip folders that can't be accessed

            result_list = []

            if all_mailboxes:
                # Search all stores
                for store in namespace.Stores:
                    if len(result_list) >= limit:
                        break
                    try:
                        root = store.GetRootFolder()
                        search_folder_recursive(root, query, result_list, limit, search_body)
                    except Exception:
                        continue
            else:
                # Search specific mailbox
                inbox = get_inbox(mailbox)
                try:
                    root = inbox.Store.GetRootFolder()
                    search_folder_recursive(root, query, result_list, limit, search_body)
                except Exception:
                    # Last resort: just search inbox
                    search_folder_recursive(inbox, query, result_list, limit, search_body)

            if not result_list:
                scope_info = "alle Postfächer" if all_mailboxes else (mailbox or "Standard-Postfach")
                return f"Keine E-Mails gefunden für: '{query}' in {scope_info} (Fallback, rekursiv)"

            # Format results
            formatted = []
            for r in result_list:
                if all_mailboxes:
                    formatted.append(f"- [{r['received']}] [{r['mailbox']}/{r['folder']}] {r['sender']}: {r['subject']}")
                else:
                    formatted.append(f"- [{r['received']}] [{r['folder']}] {r['sender']}: {r['subject']}")

            scope_info = "alle Postfächer" if all_mailboxes else ""
            return f"Suchergebnisse für '{query}' ({len(formatted)}, Fallback rekursiv{', ' + scope_info if scope_info else ''}):\n" + "\n".join(formatted)

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_fast_get_email_content(query: str, index: int = 0, search_body: bool = True, timeout: int = 30, mailbox: str = None, all_mailboxes: bool = False) -> str:
    """Liest E-Mail-Inhalt via Windows Search (wie Outlook UI).

    Nutzt Windows Search Index für schnelle Volltextsuche inkl. Anhänge,
    dann GetItemFromID für sofortigen Zugriff auf die E-Mail.

    Args:
        query: Suchbegriff (durchsucht alles inkl. Anhänge)
        index: Position in den Ergebnissen (0 = erste/neueste)
        search_body: Ignoriert (Windows Search durchsucht immer alles)
        timeout: Ignoriert (Windows Search ist instant)
        mailbox: Ignoriert (durchsucht alle Mailboxen)
        all_mailboxes: Ignoriert (durchsucht immer alle)
    """
    try:
        # 1. Use Windows Search to find matching emails (includes decoded Entry ID)
        results = windows_search_query(query, limit=index + 10)

        if not results:
            return f"Keine E-Mail gefunden für: '{query}'"

        if index >= len(results):
            return f"Index {index} außerhalb der Ergebnisse (gefunden: {len(results)})"

        # 2. Get the email info from Windows Search result
        ws_result = results[index]
        entry_id = ws_result.get("entry_id", "")
        subject = ws_result.get("subject", "")
        path = ws_result.get("path", "")

        mcp_log(f"[Outlook] [fast_get_email_content] Found: {subject} | entry_id={entry_id[:30]}...")

        # 3. Use GetItemFromID for instant access (much faster than Restrict)
        outlook = get_outlook()
        namespace = get_namespace()

        msg = None

        # Try GetItemFromID with entry_id
        if entry_id:
            # Try without store ID first
            try:
                msg = namespace.GetItemFromID(entry_id)
                mcp_log(f"[Outlook] [fast_get_email_content] Got mail via GetItemFromID (no store)")
            except Exception:
                # Try with each store
                for store in namespace.Stores:
                    try:
                        msg = namespace.GetItemFromID(entry_id, store.StoreID)
                        mcp_log(f"[Outlook] [fast_get_email_content] Got mail via GetItemFromID (store: {store.DisplayName})")
                        break
                    except Exception:
                        continue

        # Fallback: use Restrict if GetItemFromID failed
        if not msg:
            mcp_log(f"[Outlook] [fast_get_email_content] GetItemFromID failed, using Restrict fallback")

            # Parse mailbox and folder from path
            path_parts = path.strip('/').split('/') if path else []
            ws_mailbox = path_parts[0] if len(path_parts) > 0 else None
            folder_name = path_parts[1] if len(path_parts) > 1 else "Inbox"

            # Find the folder
            target_folder = None
            for store in namespace.Stores:
                if ws_mailbox and ws_mailbox.lower() in store.DisplayName.lower():
                    try:
                        root = store.GetRootFolder()
                        for folder in root.Folders:
                            f_name = folder.Name.lower()
                            f_target = folder_name.lower()
                            if f_name == f_target:
                                target_folder = folder
                                break
                            if f_target == "inbox" and f_name in ["inbox", "posteingang"]:
                                target_folder = folder
                                break
                            if f_target == "sent items" and f_name in ["sent items", "gesendete elemente", "sent"]:
                                target_folder = folder
                                break
                        if target_folder:
                            break
                    except Exception:
                        continue

            if not target_folder:
                target_folder = namespace.GetDefaultFolder(6)

            safe_subject = subject.replace("'", "''")
            filter_str = f"@SQL=\"urn:schemas:httpmail:subject\" = '{safe_subject}'"
            items = target_folder.Items.Restrict(filter_str)
            items.Sort("[ReceivedTime]", True)

            if items.Count > 0:
                msg = items.Item(1)

        if not msg:
            return f"E-Mail nicht gefunden: '{subject}'"

        received = msg.ReceivedTime.strftime("%d.%m.%Y %H:%M") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)
        mailbox_name, folder = get_mail_location(msg)

        # Include attachment info
        attachment_info = ""
        if msg.Attachments.Count > 0:
            att_list = []
            for i in range(msg.Attachments.Count):
                att = msg.Attachments.Item(i + 1)
                att_list.append(f"  [{i}] {att.FileName}")
            attachment_info = f"\nAnhänge ({msg.Attachments.Count}):\n" + "\n".join(att_list)

        return f"""Postfach: {mailbox_name}
Ordner: {folder}
Entry-ID: {msg.EntryID}
Von: {msg.SenderName} <{msg.SenderEmailAddress}>
Betreff: {msg.Subject}
Datum: {received}{attachment_info}

{msg.Body}"""

    except Exception as e:
        mcp_log(f"[Outlook] [fast_get_email_content] Error: {e}")
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_email_content(query: str, index: int = 0, mailbox: str = None) -> str:
    """Liest den vollständigen Inhalt einer E-Mail aus den Suchergebnissen.

    Args:
        query: Suchbegriff (Absender oder Betreff)
        index: Position in den Suchergebnissen (0 = erste/neueste)
        mailbox: Mailbox durchsuchen (z.B. "info@example.com"). None = Standard-Postfach.
    """
    try:
        inbox = get_inbox(mailbox)

        filter_str = (
            f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{query}%' "
            f"OR \"urn:schemas:httpmail:sendername\" LIKE '%{query}%'"
        )

        messages = inbox.Items.Restrict(filter_str)
        messages.Sort("[ReceivedTime]", True)

        for i, msg in enumerate(messages):
            if i == index:
                received = msg.ReceivedTime.strftime("%d.%m.%Y %H:%M") if hasattr(msg.ReceivedTime, 'strftime') else str(msg.ReceivedTime)
                mailbox, folder = get_mail_location(msg)
                return f"""Postfach: {mailbox}
Ordner: {folder}
Von: {msg.SenderName} <{msg.SenderEmailAddress}>
Betreff: {msg.Subject}
Datum: {received}

{msg.Body}"""

        return f"Keine E-Mail an Position {index} gefunden für: '{query}'"

    except Exception as e:
        return f"Fehler: {str(e)}"


@mcp.tool()
@outlook_tool
def outlook_get_recent_emails(
    days: int = 7,
    exclude_folders: list = None,
    exclude_flagged: bool = False,
    date_from: str = None,
    date_to: str = None,
    sender: str = None
) -> str:
    """Holt die neuesten E-Mails aus ALLEN Postfächern (nur Inbox).

    Gibt JSON zurück mit entry_id für batch_email_actions().
    Für Unterordner wie ToOffer/ToPay nutze get_folder_emails() separat.

    Args:
        days: Zeitraum in Tagen (Standard: 7 = letzte Woche). Wird ignoriert wenn date_from gesetzt.
        exclude_folders: Ordnernamen die ausgeschlossen werden (z.B. ["ToDelete", "Done"])
        exclude_flagged: Wenn True, geflaggte E-Mails ausschließen (flag_status != 0)
        date_from: Start-Datum (Format: YYYY-MM-DD oder DD.MM.YYYY). Überschreibt 'days'.
        date_to: End-Datum (Format: YYYY-MM-DD oder DD.MM.YYYY). Standard: heute.
        sender: Optional: Nur E-Mails von diesem Absender (Name oder E-Mail-Adresse, case-insensitive)

    Returns:
        JSON-Array mit E-Mails, jede mit entry_id für batch_email_actions()
    """
    def parse_date(date_str: str) -> datetime:
        """Parse date string in various formats."""
        if not date_str:
            return None
        # Try ISO format first (YYYY-MM-DD)
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass
        # Try German format (DD.MM.YYYY)
        try:
            return datetime.strptime(date_str, "%d.%m.%Y")
        except ValueError:
            pass
        # Try short German format (DD.MM.YY)
        try:
            return datetime.strptime(date_str, "%d.%m.%y")
        except ValueError:
            pass
        raise ValueError(f"Ungültiges Datumsformat: {date_str}. Verwende YYYY-MM-DD oder DD.MM.YYYY")

    try:
        namespace = get_namespace()

        # Determine date range
        if date_from:
            cutoff = parse_date(date_from)
            # Set to start of day
            cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff = datetime.now() - timedelta(days=days)

        end_date = None
        if date_to:
            end_date = parse_date(date_to)
            # Set to end of day
            end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Normalize sender filter
        sender_filter = sender.lower().strip() if sender else None

        # Normalize exclude_folders to lowercase for comparison
        excluded = [f.lower() for f in (exclude_folders or [])]

        emails = []
        seen_entry_ids = set()

        # Scan all stores
        for store in namespace.Stores:
            try:
                inbox = store.GetDefaultFolder(6)  # olFolderInbox
                store_name = store.DisplayName

                messages = inbox.Items
                messages.Sort("[ReceivedTime]", True)

                for msg in messages:
                    try:
                        # Check if email is within time range
                        received_time = msg.ReceivedTime
                        if hasattr(received_time, 'replace'):
                            # Remove timezone info for comparison
                            received_time = received_time.replace(tzinfo=None)

                        # Check start date (cutoff)
                        if received_time < cutoff:
                            break  # Sorted by date desc, so no more recent emails

                        # Check end date (if specified)
                        if end_date and received_time > end_date:
                            continue  # Skip emails after end_date, continue to find older ones

                        entry_id = msg.EntryID
                        if entry_id in seen_entry_ids:
                            continue

                        # Skip emails from excluded folders
                        if excluded:
                            try:
                                parent_folder = msg.Parent.Name.lower()
                                if parent_folder in excluded:
                                    continue
                            except AttributeError:
                                pass

                        # Skip flagged emails if requested (flag_status: 0=none, 1=complete, 2=flagged)
                        if exclude_flagged:
                            flag_status = getattr(msg, 'FlagStatus', 0)
                            if flag_status != 0:
                                continue

                        # Filter by sender if specified
                        if sender_filter:
                            msg_sender = (msg.SenderName or "").lower()
                            msg_sender_email = (msg.SenderEmailAddress or "").lower()
                            if sender_filter not in msg_sender and sender_filter not in msg_sender_email:
                                continue

                        seen_entry_ids.add(entry_id)
                        received = received_time.strftime("%Y-%m-%dT%H:%M:%S")

                        # Body - full text or preview
                        body = msg.Body or ""
                        body_preview = body[:300].replace('\r\n', ' ').replace('\n', ' ').strip()

                        email_data = {
                            "entry_id": entry_id,
                            "subject": msg.Subject or "",
                            "sender": msg.SenderName or "",
                            "sender_email": msg.SenderEmailAddress or "",
                            "received": received,
                            "mailbox": store_name,
                            "folder": "Inbox",
                            "flag_status": getattr(msg, 'FlagStatus', 0),
                            "body_preview": body_preview,
                            "body": body[:2000]  # Full body up to 2000 chars
                        }
                        emails.append(email_data)

                    except Exception:
                        continue

            except Exception:
                continue

        # Sort by received time (newest first)
        emails.sort(key=lambda x: x['received'], reverse=True)

        return json.dumps(emails, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
