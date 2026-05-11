# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
IMAP MCP - Email Module
=======================
Email search, read, and folder operations.
"""

import json
from datetime import datetime, timedelta
from imap.base import mcp, requires_imap, get_imap_connection, parse_email_message
from _mcp_api import mcp_log


@mcp.tool()
@requires_imap
def imap_list_folders() -> str:
    """List all IMAP folders/mailboxes.

    Returns:
        List of available folders with their hierarchy
    """
    imap = get_imap_connection()

    try:
        status, folders = imap.list()

        if status != 'OK':
            return "Error: Failed to list folders"

        folder_list = []
        for folder_data in folders:
            # Parse folder name from LIST response
            # Format: (\\HasNoChildren) "/" "INBOX"
            parts = folder_data.decode().split('"')
            if len(parts) >= 3:
                folder_name = parts[-2]
                folder_list.append(folder_name)

        if not folder_list:
            return "No folders found"

        return "\n".join([f"- {folder}" for folder in folder_list])

    except Exception as e:
        mcp_log(f"[IMAP] List folders error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_search_emails(
    folder: str = "INBOX",
    search_criteria: str = "ALL",
    limit: int = 50
) -> str:
    """Search emails in IMAP folder.

    Args:
        folder: IMAP folder name (default: INBOX)
        search_criteria: IMAP search criteria. Examples:
                        - "ALL" - All messages
                        - "UNSEEN" - Unread messages
                        - "SEEN" - Read messages
                        - "FLAGGED" - Flagged messages
                        - "UNFLAGGED" - Unflagged messages
                        - "FROM sender@example.com" - From specific sender
                        - "TO recipient@example.com" - To specific recipient
                        - "SUBJECT keyword" - Subject contains keyword
                        - "BODY keyword" - Body contains keyword
                        - "SINCE 1-Jan-2025" - Since date
                        - "BEFORE 31-Dec-2025" - Before date
                        - "KEYWORD MyCustomFlag" - Has custom flag
                        - Combine: "(FROM example.com UNSEEN)"
        limit: Maximum results (default: 50)

    Returns:
        JSON array of matching emails with UID, subject, from, date
    """
    imap = get_imap_connection()

    try:
        # Select folder
        status, _ = imap.select(folder, readonly=True)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Search emails
        status, message_ids = imap.search(None, search_criteria)
        if status != 'OK':
            return f"Error: Search failed with criteria: {search_criteria}"

        # Get UIDs
        uids = message_ids[0].split()
        if not uids:
            return f"No emails found matching: {search_criteria}"

        # Reverse to get newest first, apply limit
        uids = uids[::-1][:limit]

        # Fetch email headers and flags
        emails = []
        for uid in uids:
            try:
                status, msg_data = imap.fetch(uid, '(RFC822.HEADER FLAGS)')
                if status == 'OK':
                    parsed = parse_email_message(msg_data[0][1])
                    if parsed:
                        # Extract flags from response
                        flags_str = ""
                        for item in msg_data:
                            if isinstance(item, tuple) and len(item) > 0:
                                item_str = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                                if 'FLAGS' in item_str:
                                    import re
                                    flags_match = re.search(r'FLAGS \(([^)]*)\)', item_str)
                                    if flags_match:
                                        flags_str = flags_match.group(1)

                        # Determine flag_status (similar to Graph API format)
                        flag_status = "notFlagged"
                        if "\\Flagged" in flags_str:
                            flag_status = "flagged"
                        if "Complete" in flags_str or "\\Completed" in flags_str:
                            flag_status = "complete"

                        emails.append({
                            "uid": uid.decode(),
                            "subject": parsed["subject"],
                            "from": parsed["from"],
                            "to": parsed["to"],
                            "date": parsed["date"],
                            "flag_status": flag_status,
                            "flags": flags_str
                        })
            except Exception as e:
                mcp_log(f"[IMAP] Failed to fetch UID {uid}: {e}")
                continue

        if not emails:
            return "No emails could be retrieved"

        return json.dumps(emails, indent=2, ensure_ascii=False)

    except Exception as e:
        mcp_log(f"[IMAP] Search error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_get_folder_emails(folder: str, limit: int = 50) -> str:
    """Get all emails from a specific IMAP folder.

    Use this for work queues like ToPay, ToOffer, DoneInvoices.
    Returns JSON with uid, flag_status for filtering.

    Args:
        folder: IMAP folder name (e.g., "ToPay", "INBOX", "ToOffer")
        limit: Maximum results (default: 50)

    Returns:
        JSON with folder name, count, and emails array.
        Each email has: uid, subject, from, to, date, flag_status, has_attachments
    """
    imap = get_imap_connection()

    try:
        # Select folder
        status, data = imap.select(folder, readonly=True)
        if status != 'OK':
            return json.dumps({
                "error": f"Folder '{folder}' not found",
                "folder": folder,
                "count": 0,
                "emails": []
            }, indent=2)

        # Search all emails in folder
        status, message_ids = imap.search(None, "ALL")
        if status != 'OK':
            return json.dumps({
                "error": "Search failed",
                "folder": folder,
                "count": 0,
                "emails": []
            }, indent=2)

        # Get UIDs
        uids = message_ids[0].split()
        if not uids:
            return json.dumps({
                "folder": folder,
                "count": 0,
                "emails": []
            }, indent=2)

        # Reverse to get newest first, apply limit
        uids = uids[::-1][:limit]

        # Fetch email headers, flags, and structure
        import re
        emails = []
        for uid in uids:
            try:
                status, msg_data = imap.fetch(uid, '(RFC822.HEADER FLAGS BODYSTRUCTURE)')
                if status == 'OK':
                    parsed = parse_email_message(msg_data[0][1])
                    if parsed:
                        # Extract flags from response
                        flags_str = ""
                        has_attachments = False
                        for item in msg_data:
                            if isinstance(item, tuple) and len(item) > 0:
                                item_str = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                                if 'FLAGS' in item_str:
                                    flags_match = re.search(r'FLAGS \(([^)]*)\)', item_str)
                                    if flags_match:
                                        flags_str = flags_match.group(1)
                                # Check for attachments in BODYSTRUCTURE
                                if 'BODYSTRUCTURE' in item_str and ('attachment' in item_str.lower() or 'application/pdf' in item_str.lower()):
                                    has_attachments = True

                        # Determine flag_status (matching Graph API format)
                        flag_status = "notFlagged"
                        if "\\Flagged" in flags_str:
                            flag_status = "flagged"
                        if "Complete" in flags_str or "\\Completed" in flags_str:
                            flag_status = "complete"

                        emails.append({
                            "uid": uid.decode(),
                            "id": uid.decode(),  # Alias for compatibility
                            "subject": parsed["subject"],
                            "sender_name": parsed["from"],
                            "sender_email": parsed.get("from_email", ""),
                            "received": parsed["date"][:10] if parsed["date"] else "",
                            "flag_status": flag_status,
                            "has_attachments": has_attachments,
                            "flags": flags_str
                        })
            except Exception as e:
                mcp_log(f"[IMAP] Failed to fetch UID {uid}: {e}")
                continue

        return json.dumps({
            "folder": folder,
            "count": len(emails),
            "emails": emails
        }, indent=2, ensure_ascii=False)

    except Exception as e:
        mcp_log(f"[IMAP] Get folder emails error: {e}")
        return json.dumps({
            "error": str(e),
            "folder": folder,
            "count": 0,
            "emails": []
        }, indent=2)


@mcp.tool()
@requires_imap
def imap_get_email(uid: str, folder: str = "INBOX") -> str:
    """Get full content of an IMAP email message.

    Args:
        uid: Message UID (from search results)
        folder: IMAP folder name (default: INBOX)

    Returns:
        Full email content with headers and body
    """
    imap = get_imap_connection()

    try:
        # Select folder
        status, _ = imap.select(folder, readonly=True)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Fetch full message
        status, msg_data = imap.fetch(uid, '(RFC822)')
        if status != 'OK':
            return f"Error: Failed to fetch email UID {uid}"

        parsed = parse_email_message(msg_data[0][1])
        if not parsed:
            return f"Error: Failed to parse email UID {uid}"

        # Format output
        output = []
        output.append(f"Subject: {parsed['subject']}")
        output.append(f"From: {parsed['from']}")
        output.append(f"To: {parsed['to']}")
        output.append(f"Date: {parsed['date']}")
        if parsed['message_id']:
            output.append(f"Message-ID: {parsed['message_id']}")

        if parsed['attachments']:
            output.append(f"\nAttachments: {', '.join(parsed['attachments'])}")

        output.append(f"\n--- Body ---\n{parsed['body']}")

        return "\n".join(output)

    except Exception as e:
        mcp_log(f"[IMAP] Get email error: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
@requires_imap
def imap_get_recent_emails(
    folder: str = "INBOX",
    days: int = 7,
    limit: int = 50,
    only_unseen: bool = False
) -> str:
    """Get recent emails from the last N days.

    Args:
        folder: IMAP folder name (default: INBOX)
        days: Number of days to look back (default: 7)
        limit: Maximum results (default: 50)
        only_unseen: Only return unread emails (default: False)

    Returns:
        JSON array of recent emails with UID, subject, from, date
    """
    # Calculate date for SINCE criteria
    since_date = datetime.now() - timedelta(days=days)
    date_str = since_date.strftime("%d-%b-%Y")

    # Build search criteria
    criteria = f"SINCE {date_str}"
    if only_unseen:
        criteria = f"({criteria} UNSEEN)"

    return imap_search_emails(folder=folder, search_criteria=criteria, limit=limit)


@mcp.tool()
@requires_imap
def imap_get_unread_emails(folder: str = "INBOX", limit: int = 50) -> str:
    """Get all unread emails from folder.

    Args:
        folder: IMAP folder name (default: INBOX)
        limit: Maximum results (default: 50)

    Returns:
        JSON array of unread emails
    """
    return imap_search_emails(folder=folder, search_criteria="UNSEEN", limit=limit)


@mcp.tool()
@requires_imap
def imap_get_flagged_emails(folder: str = "INBOX", limit: int = 50) -> str:
    """Get all flagged emails from folder.

    Args:
        folder: IMAP folder name (default: INBOX)
        limit: Maximum results (default: 50)

    Returns:
        JSON array of flagged emails
    """
    return imap_search_emails(folder=folder, search_criteria="FLAGGED", limit=limit)


@mcp.tool()
@requires_imap
def imap_mark_read(uid: str, folder: str = "INBOX", is_read: bool = True) -> str:
    """Mark an email as read or unread.

    Convenience wrapper for setting/removing the \\Seen flag.

    Args:
        uid: Message UID
        folder: IMAP folder name (default: INBOX)
        is_read: True to mark as read, False to mark as unread (default: True)

    Returns:
        Success message or error

    Example:
        imap_mark_read("123")           # Mark as read
        imap_mark_read("123", is_read=False)  # Mark as unread
    """
    imap = get_imap_connection()

    try:
        # Select folder (writable)
        status, _ = imap.select(folder)
        if status != 'OK':
            return f"Error: Folder '{folder}' not found"

        # Set or remove \\Seen flag
        if is_read:
            status, _ = imap.store(uid, '+FLAGS', '\\Seen')
            action = "read"
        else:
            status, _ = imap.store(uid, '-FLAGS', '\\Seen')
            action = "unread"

        if status != 'OK':
            return f"Error: Failed to mark email UID {uid} as {action}"

        mcp_log(f"[IMAP] Marked email UID {uid} as {action} in {folder}")
        return f"Success: Email UID {uid} marked as {action}"

    except Exception as e:
        mcp_log(f"[IMAP] Mark read error: {e}")
        return f"Error: {str(e)}"
